from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class OracleAuthConfig:
    user: str
    password: str
    dsn: str
    wallet_dir: str
    wallet_password: str
    pool_min: int
    pool_max: int
    thick_mode: bool
    lib_dir: str

    @property
    def is_configured(self) -> bool:
        return bool(self.user and self.password and self.dsn)


@dataclass(frozen=True)
class SqliteCourseShard:
    start_id: int
    end_id: int
    db_path: str


@dataclass(frozen=True)
class AppConfig:
    flask_port: int
    flask_debug: bool
    db_keepalive_enabled: bool
    db_keepalive_interval_minutes: int

    auth_db_engine: str
    auth_sqlite_db_path: str
    oracle_auth: OracleAuthConfig

    course_db_engine: str
    course_sqlite_default_db_path: str
    course_sqlite_shards: tuple[SqliteCourseShard, ...]

    jwt_secret: str
    jwt_expires_days: int
    totp_issuer: str
    invite_codes: set[str]

    rsa_private_key: str


def load_env_file(env_path: Path | None = None) -> None:
    """Load key=value pairs from server/.env if present.

    python-dotenv is optional. If unavailable, the parser below handles the
    simple key=value format used by this project.
    """
    candidate = env_path or (Path(__file__).resolve().parents[1] / ".env")
    try:
        from dotenv import load_dotenv

        load_dotenv(candidate)
        return
    except ImportError:
        pass

    if not candidate.exists():
        return

    with candidate.open("r", encoding="utf-8") as env_file:
        for line in env_file:
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            key, _, value = raw.partition("=")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            os.environ.setdefault(key.strip(), value)


def _parse_csv_codes(raw_codes: str) -> set[str]:
    return {code.strip() for code in raw_codes.split(",") if code.strip()}


def _parse_sqlite_shards(raw: str) -> tuple[SqliteCourseShard, ...]:
    """Parse shard configuration from COURSE_SQLITE_SHARDS_JSON.

    Expected JSON format:
    [
      {"start_id": 1, "end_id": 999, "db_path": "/path/to/shard_a.db"},
      {"start_id": 1000, "end_id": 1999, "db_path": "/path/to/shard_b.db"}
    ]
    """
    raw = (raw or "").strip()
    if not raw:
        return ()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("COURSE_SQLITE_SHARDS_JSON must be valid JSON") from exc

    if not isinstance(parsed, list):
        raise ValueError("COURSE_SQLITE_SHARDS_JSON must be a JSON array")

    shards: list[SqliteCourseShard] = []
    for item in parsed:
        if not isinstance(item, dict):
            raise ValueError("Each shard entry must be a JSON object")

        start_id = int(item.get("start_id"))
        end_id = int(item.get("end_id"))
        db_path = str(item.get("db_path", "")).strip()

        if start_id > end_id:
            raise ValueError(f"Invalid shard range: {start_id}>{end_id}")
        if not db_path:
            raise ValueError("Each shard entry must include a non-empty db_path")

        shards.append(SqliteCourseShard(start_id=start_id, end_id=end_id, db_path=db_path))

    shards.sort(key=lambda shard: shard.start_id)
    for prev, curr in zip(shards, shards[1:]):
        if curr.start_id <= prev.end_id:
            raise ValueError(
                "Overlapping shard ranges found in COURSE_SQLITE_SHARDS_JSON: "
                f"[{prev.start_id}, {prev.end_id}] overlaps [{curr.start_id}, {curr.end_id}]"
            )

    return tuple(shards)


def load_config() -> AppConfig:
    load_env_file()

    legacy_db_path = os.environ.get("DB_PATH", r"/path/to/educative_scraper.db")
    raw_shards = os.environ.get("COURSE_SQLITE_SHARDS_JSON", "")

    shards: tuple[SqliteCourseShard, ...]
    try:
        shards = _parse_sqlite_shards(raw_shards)
    except ValueError as exc:
        log.warning("Invalid shard config ignored: %s", exc)
        shards = ()

    oracle_auth = OracleAuthConfig(
        user=os.environ.get("ORACLE_USER", ""),
        password=os.environ.get("ORACLE_PASSWORD", ""),
        dsn=os.environ.get("ORACLE_DSN", ""),
        wallet_dir=os.environ.get("ORACLE_WALLET_DIR", "").strip(),
        wallet_password=os.environ.get("ORACLE_WALLET_PASSWORD", "").strip(),
        pool_min=int(os.environ.get("ORACLE_POOL_MIN", "1")),
        pool_max=int(os.environ.get("ORACLE_POOL_MAX", "5")),
        thick_mode=os.environ.get("ORACLE_THICK_MODE", "0") == "1",
        lib_dir=os.environ.get("ORACLE_LIB_DIR", "").strip(),
    )

    return AppConfig(
        flask_port=int(os.environ.get("FLASK_PORT", "5000")),
        flask_debug=os.environ.get("FLASK_DEBUG", "0") == "1",
        db_keepalive_enabled=os.environ.get("DB_KEEPALIVE_ENABLED", "1") == "1",
        db_keepalive_interval_minutes=max(1, int(os.environ.get("DB_KEEPALIVE_INTERVAL_MINUTES", "10"))),

        auth_db_engine=os.environ.get("AUTH_DB_ENGINE", "oracle").strip().lower(),
        auth_sqlite_db_path=os.environ.get("AUTH_SQLITE_DB_PATH", str(Path(__file__).resolve().parents[1] / "auth.sqlite3")),
        oracle_auth=oracle_auth,

        course_db_engine=os.environ.get("COURSE_DB_ENGINE", "sqlite").strip().lower(),
        course_sqlite_default_db_path=os.environ.get("COURSE_SQLITE_DB_PATH", os.environ.get("COURSE_DB_PATH", legacy_db_path)),
        course_sqlite_shards=shards,

        jwt_secret=os.environ.get("JWT_SECRET", "changeme-dev-secret"),
        jwt_expires_days=int(os.environ.get("JWT_EXPIRES_DAYS", "7")),
        totp_issuer=os.environ.get("TOTP_ISSUER", "EduViewer"),
        invite_codes=_parse_csv_codes(os.environ.get("INVITE_CODES", "")),

        rsa_private_key=os.environ.get("RSA_PRIVATE_KEY", "").replace("\\n", "\n").strip(),
    )
