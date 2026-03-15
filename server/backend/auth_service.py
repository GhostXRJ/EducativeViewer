from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

import jwt as pyjwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from flask import abort, request

from backend.config import AppConfig
from backend.db.manager import DBManager
from backend.db.sql_helpers import execute, fetch_all_dict, fetch_one_dict

log = logging.getLogger(__name__)


_USER_JOIN = """
    SELECT u.id, u.email, u.name, u.username, u.avatar,
           r.name AS role,
           u.role_id, u.two_factor_enabled, u.login_ip_log, u.theme, u.created_at,
           s.password_hash, s.two_factor_secret, s.two_factor_confirmed,
           s.session_id, s.last_login_ip, s.last_login_at, s.current_token
    FROM users u
    LEFT JOIN roles r ON r.id = u.role_id
    LEFT JOIN users_sensitive s ON s.user_id = u.id
"""


class AuthService:
    def __init__(self, config: AppConfig, db_manager: DBManager):
        self.config = config
        self.db_manager = db_manager

        self._rsa_private_key = None
        self._rsa_public_key = None
        self._rsa_public_pem = ""
        self._rsa_private_pem_export = ""

        self._init_rsa_keys()

    @property
    def invite_codes(self) -> set[str]:
        return self.config.invite_codes

    def _init_rsa_keys(self) -> None:
        if self.config.rsa_private_key:
            self._rsa_private_key = serialization.load_pem_private_key(
                self.config.rsa_private_key.encode(),
                password=None,
            )
            log.info("RSA private key loaded from RSA_PRIVATE_KEY env var")
        else:
            self._rsa_private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            generated_pem = self._rsa_private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            ).decode().replace("\n", "\\n")
            log.warning(
                "RSA_PRIVATE_KEY not set; generated ephemeral key. Add this to server/.env:\n"
                "RSA_PRIVATE_KEY=%s",
                generated_pem,
            )

        self._rsa_public_key = self._rsa_private_key.public_key()
        self._rsa_public_pem = self._rsa_public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()
        self._rsa_private_pem_export = self._rsa_private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()

        pub_oneliner = self._rsa_public_pem.replace("\n", "\\n")
        priv_oneliner = self._rsa_private_pem_export.replace("\n", "\\n")

        print("\n" + "=" * 70)
        print("  RSA KEY PAIR; copy both lines into your .env files")
        print("=" * 70)
        print("  [server/.env]")
        print("  RSA_PRIVATE_KEY=" + priv_oneliner)
        print()
        print("  [client/.env.local]")
        print("  NEXT_PUBLIC_RSA_PUBLIC_KEY=" + pub_oneliner)
        print("=" * 70 + "\n")

    def decrypt_password(self, ciphertext_b64: str) -> str:
        if not ciphertext_b64:
            abort(400, description="Password field is required")

        try:
            ciphertext = base64.b64decode(ciphertext_b64)
            plaintext = self._rsa_private_key.decrypt(
                ciphertext,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None,
                ),
            )
            return plaintext.decode("utf-8")
        except Exception:
            abort(400, description="Invalid or malformed password encryption")

    def make_full_token(self, user: dict[str, Any]) -> str:
        now = int(time.time())
        payload = {
            "id": user["id"],
            "email": user["email"],
            "name": user.get("name"),
            "username": user.get("username"),
            "avatar": user.get("avatar"),
            "role": user.get("role", "user"),
            "theme": user.get("theme", "light"),
            "twoFactorEnabled": bool(user.get("two_factor_enabled")),
            "createdAt": user.get("created_at"),
            "sessionId": user.get("session_id"),
            "iat": now,
            "exp": now + self.config.jwt_expires_days * 86400,
        }
        return pyjwt.encode(payload, self.config.jwt_secret, algorithm="HS256")

    def make_partial_token(self, user_id: int) -> str:
        now = int(time.time())
        payload = {
            "id": user_id,
            "partial": True,
            "iat": now,
            "exp": now + 600,
        }
        return pyjwt.encode(payload, self.config.jwt_secret, algorithm="HS256")

    def decode_token(self, token: str) -> dict[str, Any] | None:
        try:
            return pyjwt.decode(token, self.config.jwt_secret, algorithms=["HS256"])
        except pyjwt.PyJWTError:
            return None

    @staticmethod
    def bearer_token() -> str | None:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]
        return None

    def fetch_user_by_id(self, conn: Any, user_id: int) -> dict[str, Any] | None:
        return fetch_one_dict(conn, _USER_JOIN + "WHERE u.id = :user_id", {"user_id": user_id})

    def fetch_user_by_email(self, conn: Any, email: str) -> dict[str, Any] | None:
        return fetch_one_dict(
            conn,
            _USER_JOIN + "WHERE UPPER(u.email) = UPPER(:email)",
            {"email": email},
        )

    @staticmethod
    def get_client_ip() -> str | None:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.remote_addr

    def check_ip_restriction(self, conn: Any, user: dict[str, Any], client_ip: str | None) -> None:
        if user.get("role", "user") == "admin":
            return

        today = time.strftime("%Y-%m-%d", time.gmtime())
        try:
            ip_log = json.loads(user.get("login_ip_log") or "{}")
        except (json.JSONDecodeError, TypeError):
            ip_log = {}

        if ip_log.get("date") != today:
            ip_log = {"date": today, "ips": []}

        ips = list(ip_log.get("ips", []))
        if client_ip and client_ip not in ips:
            if len(ips) >= 2:
                abort(
                    403,
                    description=(
                        "Login restricted: you have already signed in from 2 different IP addresses "
                        "today. Try again tomorrow or log in from an IP you have used today."
                    ),
                )
            ips.append(client_ip)

        ip_log["ips"] = ips
        execute(
            conn,
            "UPDATE users SET login_ip_log = :ip_log WHERE id = :user_id",
            {"ip_log": json.dumps(ip_log), "user_id": user["id"]},
        )

    def resolve_user(self, require_full: bool = True) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        token = self.bearer_token()
        if not token:
            return None, None

        payload = self.decode_token(token)
        if not payload:
            return None, None

        if require_full and payload.get("partial"):
            return None, payload

        conn = self.db_manager.get_auth_connection()
        try:
            user = self.fetch_user_by_id(conn, int(payload["id"]))
        finally:
            conn.close()

        if not user:
            return None, payload

        if not payload.get("partial"):
            if payload.get("sessionId") != user.get("session_id"):
                abort(401, description="Session superseded by a newer login. Please sign in again.")

        return user, payload

    def get_compact_progress(self, conn: Any, user_id: int) -> dict[str, Any]:
        rows = fetch_all_dict(
            conn,
            """
            SELECT course_id, topic_index, completed, last_visited_course_at
            FROM user_progress
            WHERE user_id = :user_id
            ORDER BY last_visited_course_at DESC, course_id
            """,
            {"user_id": user_id},
        )

        course_order: list[int] = []
        seen_courses: set[int] = set()
        completed: dict[str, list[int]] = {}

        for row in rows:
            course_id = int(row["course_id"])
            if course_id not in seen_courses:
                seen_courses.add(course_id)
                course_order.append(course_id)

            if row.get("completed"):
                completed.setdefault(str(course_id), []).append(int(row["topic_index"]))

        return {"course_order": course_order, "completed": completed}

    def user_public(self, user: dict[str, Any], conn: Any | None = None) -> dict[str, Any]:
        data = {
            "id": user["id"],
            "email": user["email"],
            "name": user.get("name"),
            "username": user.get("username"),
            "avatar": user.get("avatar"),
            "role": user.get("role", "user"),
            "theme": user.get("theme", "light"),
            "twoFactorEnabled": bool(user.get("two_factor_enabled")),
            "createdAt": user.get("created_at"),
        }
        if conn is not None:
            data["progress"] = self.get_compact_progress(conn, int(user["id"]))
        return data
