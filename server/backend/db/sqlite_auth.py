from __future__ import annotations

import logging
import sqlite3

log = logging.getLogger(__name__)


class SQLiteAuthDatabase:
    engine = "sqlite"

    def __init__(self, db_path: str):
        self.db_path = db_path

    @property
    def is_configured(self) -> bool:
        return bool(self.db_path)

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def keep_alive(self) -> None:
        conn = self.get_connection()
        try:
            conn.execute("SELECT 1")
        finally:
            conn.close()

    def init_schema(self) -> None:
        conn = self.get_connection()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS roles (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT
                )
                """
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_roles_name ON roles (name COLLATE NOCASE)"
            )

            conn.execute(
                "INSERT OR IGNORE INTO roles (id, name, description) VALUES (1, 'user', 'Regular authenticated user')"
            )
            conn.execute(
                "INSERT OR IGNORE INTO roles (id, name, description) VALUES (2, 'admin', 'Administrator with no restrictions')"
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL,
                    name TEXT,
                    username TEXT,
                    avatar TEXT,
                    role_id INTEGER NOT NULL DEFAULT 1 REFERENCES roles(id),
                    two_factor_enabled INTEGER NOT NULL DEFAULT 0,
                    login_ip_log TEXT,
                    theme TEXT NOT NULL DEFAULT 'light',
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                )
                """
            )
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email ON users (email COLLATE NOCASE)"
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users_sensitive (
                    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    password_hash TEXT NOT NULL DEFAULT '',
                    two_factor_secret TEXT,
                    two_factor_confirmed INTEGER NOT NULL DEFAULT 0,
                    session_id TEXT,
                    last_login_ip TEXT,
                    last_login_at TEXT,
                    current_token TEXT
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_progress (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    course_id INTEGER NOT NULL,
                    topic_index INTEGER NOT NULL,
                    completed INTEGER NOT NULL DEFAULT 0,
                    last_visited_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                    last_visited_course_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_user_progress
                ON user_progress (user_id, course_id, topic_index)
                """
            )

            conn.commit()
        finally:
            conn.close()

        log.info("SQLite auth DB ready (path=%s)", self.db_path)

    def is_integrity_error(self, exc: Exception) -> bool:
        return isinstance(exc, sqlite3.IntegrityError)
