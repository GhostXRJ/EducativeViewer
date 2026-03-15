from __future__ import annotations

import base64
import io
import re
import time
import uuid

import bcrypt
import jwt as pyjwt
import pyotp
import segno
from flask import Blueprint, abort, jsonify, request

from backend.auth_service import AuthService
from backend.db.manager import DBManager
from backend.db.sql_helpers import execute, fetch_one_dict, rollback_quietly

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def create_auth_blueprint(auth_service: AuthService, db_manager: DBManager) -> Blueprint:
    bp = Blueprint("auth_api", __name__, url_prefix="/api/auth")

    @bp.route("/signup", methods=["POST"])
    def auth_signup():
        data = request.get_json(force=True, silent=True) or {}
        email = str(data.get("email", "")).strip().lower()
        password = auth_service.decrypt_password(str(data.get("password", "")))
        invite = str(data.get("inviteCode", "")).strip()
        name = str(data.get("name", "")).strip() or None

        if not email or not EMAIL_RE.match(email):
            abort(400, description="Invalid email address")
        if len(password) < 8 or len(password) > 72:
            abort(400, description="Password must be 8-72 characters")

        if auth_service.invite_codes and invite not in auth_service.invite_codes:
            abort(403, description="Invalid invite code")
        if not invite:
            abort(400, description="Invite code is required")

        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
        totp_secret = pyotp.random_base32()

        conn = db_manager.get_auth_connection()
        try:
            try:
                user_id = db_manager.insert_user(conn, email=email, name=name)
                execute(
                    conn,
                    "INSERT INTO users_sensitive (user_id, password_hash, two_factor_secret) "
                    "VALUES (:user_id, :pw_hash, :totp_secret)",
                    {
                        "user_id": user_id,
                        "pw_hash": pw_hash,
                        "totp_secret": totp_secret,
                    },
                )
                conn.commit()
            except Exception as exc:
                rollback_quietly(conn)
                if db_manager.auth_backend.is_integrity_error(exc):
                    abort(409, description="An account with that email already exists")
                raise

            user = auth_service.fetch_user_by_id(conn, user_id)
        finally:
            conn.close()

        if not user:
            abort(500, description="Failed to load account after signup")

        partial = auth_service.make_partial_token(int(user["id"]))
        return (
            jsonify(
                {
                    "token": partial,
                    "requiresTwoFactor": True,
                    "message": "Account created. Set up two-factor authentication to continue.",
                }
            ),
            201,
        )

    @bp.route("/login", methods=["POST"])
    def auth_login():
        data = request.get_json(force=True, silent=True) or {}
        email = str(data.get("email", "")).strip().lower()
        raw_pw = str(data.get("password", ""))

        if not email or not raw_pw:
            abort(400, description="Email and password are required")

        password = auth_service.decrypt_password(raw_pw)

        conn = db_manager.get_auth_connection()
        try:
            user = auth_service.fetch_user_by_email(conn, email)
        finally:
            conn.close()

        dummy_hash = b"$2b$12$" + b"x" * 53
        stored_hash = user["password_hash"].encode() if (user and user.get("password_hash")) else dummy_hash
        password_ok = bcrypt.checkpw(password.encode(), stored_hash)

        if not user or not password_ok:
            abort(401, description="Invalid email or password")

        if user.get("two_factor_secret") and not user.get("two_factor_confirmed"):
            return (
                jsonify(
                    {
                        "token": auth_service.make_partial_token(int(user["id"])),
                        "requiresTwoFactorSetup": True,
                        "message": (
                            "Your account setup is incomplete. Please complete "
                            "two-factor authentication to continue."
                        ),
                    }
                ),
                200,
            )

        if user.get("two_factor_enabled") and user.get("two_factor_confirmed"):
            return (
                jsonify(
                    {
                        "token": auth_service.make_partial_token(int(user["id"])),
                        "requiresTwoFactor": True,
                    }
                ),
                200,
            )

        new_session_id = str(uuid.uuid4())
        client_ip = auth_service.get_client_ip()

        conn2 = db_manager.get_auth_connection()
        try:
            auth_service.check_ip_restriction(conn2, user, client_ip)
            user["session_id"] = new_session_id
            token = auth_service.make_full_token(user)
            execute(
                conn2,
                "UPDATE users_sensitive SET session_id = :session_id, last_login_ip = :ip, "
                "last_login_at = :login_at, current_token = :token WHERE user_id = :user_id",
                {
                    "session_id": new_session_id,
                    "ip": client_ip,
                    "login_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "token": token,
                    "user_id": user["id"],
                },
            )
            conn2.commit()
        finally:
            conn2.close()

        return jsonify({"token": token, "user": auth_service.user_public(user)}), 200

    @bp.route("/me", methods=["GET"])
    def auth_me():
        user, _ = auth_service.resolve_user(require_full=True)
        if not user:
            abort(401, description="Not authenticated")

        conn = db_manager.get_auth_connection()
        try:
            return jsonify(auth_service.user_public(user, conn=conn)), 200
        finally:
            conn.close()

    @bp.route("/logout", methods=["POST"])
    def auth_logout():
        user, _ = auth_service.resolve_user(require_full=False)
        if user:
            conn = db_manager.get_auth_connection()
            try:
                execute(
                    conn,
                    "UPDATE users_sensitive SET session_id = NULL, current_token = NULL "
                    "WHERE user_id = :user_id",
                    {"user_id": user["id"]},
                )
                conn.commit()
            except Exception:
                pass
            finally:
                conn.close()

        return jsonify({"message": "Logged out"}), 200

    @bp.route("/change-password", methods=["POST"])
    def auth_change_password():
        user, _ = auth_service.resolve_user(require_full=True)
        if not user:
            abort(401, description="Not authenticated")

        body = request.get_json(force=True, silent=True) or {}
        current_password = auth_service.decrypt_password(str(body.get("current_password", "")).strip())
        new_password = auth_service.decrypt_password(str(body.get("new_password", "")))

        if not current_password or not new_password:
            abort(400, description="current_password and new_password are required")
        if len(new_password) < 8 or len(new_password) > 72:
            abort(400, description="New password must be 8-72 characters")

        conn = db_manager.get_auth_connection()
        try:
            row = fetch_one_dict(
                conn,
                "SELECT password_hash FROM users_sensitive WHERE user_id = :user_id",
                {"user_id": user["id"]},
            )
        finally:
            conn.close()

        if not row or not row.get("password_hash"):
            abort(400, description="No password set for this account")

        stored_hash_raw = row["password_hash"]
        stored_hash = stored_hash_raw.encode() if isinstance(stored_hash_raw, str) else stored_hash_raw

        if not bcrypt.checkpw(current_password.encode(), stored_hash):
            abort(400, description="Current password is incorrect")

        pw_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt(rounds=12)).decode()

        conn = db_manager.get_auth_connection()
        try:
            execute(
                conn,
                "UPDATE users_sensitive SET password_hash = :pw_hash WHERE user_id = :user_id",
                {"pw_hash": pw_hash, "user_id": user["id"]},
            )
            conn.commit()
        finally:
            conn.close()

        return jsonify({"message": "Password updated successfully"}), 200

    @bp.route("/2fa/setup", methods=["GET"])
    def auth_2fa_setup():
        user, _ = auth_service.resolve_user(require_full=False)
        if not user:
            abort(401, description="Not authenticated")

        totp_secret = user.get("two_factor_secret")
        if not totp_secret:
            totp_secret = pyotp.random_base32()
            conn = db_manager.get_auth_connection()
            try:
                execute(
                    conn,
                    "UPDATE users_sensitive SET two_factor_secret = :secret WHERE user_id = :user_id",
                    {"secret": totp_secret, "user_id": user["id"]},
                )
                conn.commit()
            finally:
                conn.close()

        uri = pyotp.totp.TOTP(totp_secret).provisioning_uri(
            name=user["email"],
            issuer_name=auth_service.config.totp_issuer,
        )
        buf = io.BytesIO()
        segno.make_qr(uri).save(buf, kind="svg", scale=5, dark="#1e1b4b", light="#ffffff")
        qr_data_url = "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()

        return jsonify({"qrCodeUrl": qr_data_url, "secret": totp_secret}), 200

    @bp.route("/theme", methods=["PUT"])
    def auth_set_theme():
        user, _ = auth_service.resolve_user(require_full=True)
        if not user:
            abort(401, description="Not authenticated")

        body = request.get_json(force=True, silent=True) or {}
        theme = str(body.get("theme", "")).strip()
        if theme not in ("light", "dark"):
            abort(400, description="theme must be 'light' or 'dark'")

        conn = db_manager.get_auth_connection()
        try:
            execute(
                conn,
                "UPDATE users SET theme = :theme WHERE id = :user_id",
                {"theme": theme, "user_id": user["id"]},
            )
            conn.commit()
        finally:
            conn.close()

        return jsonify({"theme": theme}), 200

    @bp.route("/progress/topic", methods=["POST"])
    def auth_progress_topic():
        user, _ = auth_service.resolve_user(require_full=True)
        if not user:
            abort(401, description="Not authenticated")

        body = request.get_json(force=True, silent=True) or {}
        course_id = body.get("course_id")
        topic_index = body.get("topic_index")
        completed = bool(body.get("completed", False))

        if course_id is None or topic_index is None:
            abort(400, description="course_id and topic_index are required")

        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        conn = db_manager.get_auth_connection()
        try:
            db_manager.upsert_user_progress(
                conn,
                user_id=int(user["id"]),
                course_id=int(course_id),
                topic_index=int(topic_index),
                completed=completed,
                now_iso=now_iso,
            )
            conn.commit()
        finally:
            conn.close()

        return jsonify({"ok": True}), 200

    @bp.route("/progress/course", methods=["DELETE"])
    def auth_reset_course_progress():
        user, _ = auth_service.resolve_user(require_full=True)
        if not user:
            abort(401, description="Not authenticated")

        data = request.get_json(force=True, silent=True) or {}
        course_id = data.get("course_id")
        if course_id is None:
            abort(400, description="course_id is required")

        conn = db_manager.get_auth_connection()
        try:
            execute(
                conn,
                "DELETE FROM user_progress WHERE user_id = :user_id AND course_id = :course_id",
                {"user_id": user["id"], "course_id": int(course_id)},
            )
            conn.commit()
        finally:
            conn.close()

        return jsonify({"ok": True, "message": "Course progress has been reset"}), 200

    @bp.route("/signup/rollback", methods=["POST"])
    def auth_signup_rollback():
        user, _ = auth_service.resolve_user(require_full=False)
        if not user:
            resp = jsonify({"message": "No partial session found"})
            resp.delete_cookie("ev_token", path="/", samesite="Lax")
            resp.delete_cookie("ev_session", path="/", samesite="Lax")
            return resp, 200

        if user.get("two_factor_confirmed"):
            abort(403, description="Account is already fully set up; rollback not allowed")

        conn = db_manager.get_auth_connection()
        try:
            execute(
                conn,
                """
                DELETE FROM users WHERE id = :user_id
                  AND NOT EXISTS (
                    SELECT 1 FROM users_sensitive
                    WHERE user_id = :user_id AND two_factor_confirmed = 1
                  )
                """,
                {"user_id": user["id"]},
            )
            conn.commit()
        finally:
            conn.close()

        resp = jsonify({"message": "Partial signup rolled back successfully"})
        resp.delete_cookie("ev_token", path="/", samesite="Lax")
        resp.delete_cookie("ev_session", path="/", samesite="Lax")
        return resp, 200

    @bp.route("/2fa/enable", methods=["POST"])
    def auth_2fa_enable():
        user, _ = auth_service.resolve_user(require_full=False)
        if not user:
            abort(401, description="Not authenticated")

        body = request.get_json(force=True, silent=True) or {}
        code = str(body.get("code", "")).strip()

        if not user.get("two_factor_secret"):
            abort(400, description="2FA setup not started. Call GET /auth/2fa/setup first.")
        if not pyotp.TOTP(user["two_factor_secret"]).verify(code, valid_window=1):
            abort(400, description="Invalid authenticator code")

        new_session_id = str(uuid.uuid4())
        client_ip = auth_service.get_client_ip()

        conn = db_manager.get_auth_connection()
        try:
            execute(
                conn,
                "UPDATE users SET two_factor_enabled = 1 WHERE id = :user_id",
                {"user_id": user["id"]},
            )

            user = auth_service.fetch_user_by_id(conn, int(user["id"]))
            if not user:
                abort(401, description="Not authenticated")

            auth_service.check_ip_restriction(conn, user, client_ip)
            user["session_id"] = new_session_id
            token = auth_service.make_full_token(user)

            execute(
                conn,
                "UPDATE users_sensitive SET two_factor_confirmed = 1, "
                "session_id = :session_id, last_login_ip = :ip, "
                "last_login_at = :login_at, current_token = :token "
                "WHERE user_id = :user_id",
                {
                    "session_id": new_session_id,
                    "ip": client_ip,
                    "login_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "token": token,
                    "user_id": user["id"],
                },
            )
            conn.commit()

            user = auth_service.fetch_user_by_id(conn, int(user["id"]))
        finally:
            conn.close()

        if not user:
            abort(500, description="Failed to load account after 2FA enable")

        return jsonify({"token": token, "user": auth_service.user_public(user)}), 200

    @bp.route("/2fa/verify", methods=["POST"])
    def auth_2fa_verify():
        user, _ = auth_service.resolve_user(require_full=False)
        if not user:
            abort(401, description="Not authenticated")

        body = request.get_json(force=True, silent=True) or {}
        code = str(body.get("code", "")).strip()

        if not user.get("two_factor_secret") or not user.get("two_factor_confirmed"):
            abort(400, description="2FA is not configured for this account")
        if not pyotp.TOTP(user["two_factor_secret"]).verify(code, valid_window=1):
            abort(401, description="Invalid authenticator code")

        new_session_id = str(uuid.uuid4())
        client_ip = auth_service.get_client_ip()

        conn = db_manager.get_auth_connection()
        try:
            auth_service.check_ip_restriction(conn, user, client_ip)
            user["session_id"] = new_session_id
            token = auth_service.make_full_token(user)

            execute(
                conn,
                "UPDATE users_sensitive SET session_id = :session_id, last_login_ip = :ip, "
                "last_login_at = :login_at, current_token = :token WHERE user_id = :user_id",
                {
                    "session_id": new_session_id,
                    "ip": client_ip,
                    "login_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "token": token,
                    "user_id": user["id"],
                },
            )
            conn.commit()
        finally:
            conn.close()

        return jsonify({"token": token, "user": auth_service.user_public(user)}), 200

    @bp.route("/forgot-password/request", methods=["POST"])
    def auth_forgot_password_request():
        data = request.get_json(force=True, silent=True) or {}
        email = str(data.get("email", "")).strip().lower()

        if not email or not EMAIL_RE.match(email):
            abort(400, description="Invalid email address")

        conn = db_manager.get_auth_connection()
        try:
            user = auth_service.fetch_user_by_email(conn, email)
        finally:
            conn.close()

        if user and user.get("two_factor_secret") and not user.get("two_factor_confirmed"):
            abort(
                400,
                description=(
                    "This account has incomplete two-factor authentication setup. "
                    "Password reset is not available. Please create a new account or contact support."
                ),
            )

        if not user or not user.get("two_factor_confirmed") or not user.get("two_factor_secret"):
            abort(
                400,
                description=(
                    "No account with a verified authenticator was found for that email. "
                    "If you set up 2FA during sign-up, try again or contact support."
                ),
            )

        now = int(time.time())
        token = pyjwt.encode(
            {
                "id": user["id"],
                "scope": "pw_reset_pending",
                "iat": now,
                "exp": now + 600,
            },
            auth_service.config.jwt_secret,
            algorithm="HS256",
        )
        return jsonify({"token": token, "requiresTwoFactor": True}), 200

    @bp.route("/forgot-password/verify", methods=["POST"])
    def auth_forgot_password_verify():
        token_raw = auth_service.bearer_token()
        if not token_raw:
            abort(401, description="Reset session token required")

        payload = auth_service.decode_token(token_raw)
        if not payload or payload.get("scope") != "pw_reset_pending":
            abort(401, description="Invalid or expired password-reset session")

        body = request.get_json(force=True, silent=True) or {}
        code = str(body.get("code", "")).strip()

        if len(code) != 6 or not code.isdigit():
            abort(400, description="Enter the 6-digit code from your authenticator app")

        conn = db_manager.get_auth_connection()
        try:
            user = auth_service.fetch_user_by_id(conn, int(payload["id"]))
        finally:
            conn.close()

        if not user or not user.get("two_factor_secret"):
            abort(401, description="Invalid reset session")

        if not pyotp.TOTP(user["two_factor_secret"]).verify(code, valid_window=1):
            abort(400, description="Invalid authenticator code")

        now = int(time.time())
        confirmed_token = pyjwt.encode(
            {
                "id": user["id"],
                "scope": "pw_reset_confirmed",
                "iat": now,
                "exp": now + 300,
            },
            auth_service.config.jwt_secret,
            algorithm="HS256",
        )
        return jsonify({"token": confirmed_token}), 200

    @bp.route("/forgot-password/reset", methods=["POST"])
    def auth_forgot_password_reset():
        token_raw = auth_service.bearer_token()
        if not token_raw:
            abort(401, description="Reset session token required")

        payload = auth_service.decode_token(token_raw)
        if not payload or payload.get("scope") != "pw_reset_confirmed":
            abort(401, description="Invalid or expired password-reset session")

        body = request.get_json(force=True, silent=True) or {}
        password = auth_service.decrypt_password(str(body.get("password", "")))

        if len(password) < 8 or len(password) > 72:
            abort(400, description="Password must be 8-72 characters")

        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()

        conn = db_manager.get_auth_connection()
        try:
            execute(
                conn,
                "UPDATE users_sensitive "
                "SET password_hash = :pw_hash, session_id = NULL, current_token = NULL "
                "WHERE user_id = :user_id",
                {"pw_hash": pw_hash, "user_id": int(payload["id"])},
            )
            conn.commit()
        finally:
            conn.close()

        return jsonify({"message": "Password updated. Please sign in with your new password."}), 200

    return bp
