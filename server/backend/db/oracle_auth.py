from __future__ import annotations

import logging

import oracledb

from backend.config import OracleAuthConfig

log = logging.getLogger(__name__)

# Fetch CLOB values as plain Python strings.
oracledb.defaults.fetch_lobs = False


class OracleAuthDatabase:
    engine = "oracle"
    _thick_client_ready = False

    def __init__(self, config: OracleAuthConfig):
        self.config = config
        self._pool = None

    @property
    def is_configured(self) -> bool:
        return self.config.is_configured

    def _get_pool(self):
        if self._pool is not None:
            return self._pool

        if not self.is_configured:
            raise RuntimeError(
                "Oracle auth DB is not configured. Set ORACLE_USER, ORACLE_PASSWORD, and ORACLE_DSN."
            )

        if self.config.thick_mode and not OracleAuthDatabase._thick_client_ready:
            oracledb.init_oracle_client(lib_dir=self.config.lib_dir or None)
            OracleAuthDatabase._thick_client_ready = True

        kwargs: dict = {
            "user": self.config.user,
            "password": self.config.password,
            "dsn": self.config.dsn,
            "min": self.config.pool_min,
            "max": self.config.pool_max,
            "increment": 1,
        }

        if self.config.wallet_dir:
            if self.config.thick_mode:
                kwargs["config_dir"] = self.config.wallet_dir
            else:
                kwargs["wallet_location"] = self.config.wallet_dir
        if self.config.wallet_password:
            kwargs["wallet_password"] = self.config.wallet_password

        self._pool = oracledb.create_pool(**kwargs)
        return self._pool

    def get_connection(self):
        return self._get_pool().acquire()

    def keep_alive(self) -> None:
        if not self.is_configured:
            return

        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT 1 FROM DUAL")
                cursor.fetchone()
            finally:
                cursor.close()
        finally:
            conn.close()

    def _exec_ddl(self, cursor, sql: str) -> None:
        try:
            cursor.execute(sql)
        except oracledb.DatabaseError as exc:
            (err,) = exc.args
            if err.code != 955:
                raise

    def init_schema(self) -> None:
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            try:
                self._exec_ddl(
                    cursor,
                    """
                    CREATE TABLE roles (
                        id NUMBER PRIMARY KEY,
                        name VARCHAR2(100 CHAR) NOT NULL,
                        description VARCHAR2(500 CHAR)
                    )
                    """,
                )
                self._exec_ddl(cursor, "CREATE UNIQUE INDEX uq_roles_name ON roles (UPPER(name))")

                for role_id, role_name, role_desc in [
                    (1, "user", "Regular authenticated user"),
                    (2, "admin", "Administrator with no restrictions"),
                ]:
                    try:
                        cursor.execute(
                            "INSERT INTO roles (id, name, description) VALUES (:1, :2, :3)",
                            (role_id, role_name, role_desc),
                        )
                    except oracledb.IntegrityError:
                        pass

                self._exec_ddl(
                    cursor,
                    """
                    CREATE TABLE users (
                        id                 NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                        email              VARCHAR2(255 CHAR) NOT NULL,
                        name               VARCHAR2(255 CHAR),
                        username           VARCHAR2(255 CHAR),
                        avatar             VARCHAR2(1000 CHAR),
                        role_id            NUMBER DEFAULT 1 NOT NULL REFERENCES roles(id),
                        two_factor_enabled NUMBER(1,0) DEFAULT 0 NOT NULL,
                        login_ip_log       CLOB,
                        theme              VARCHAR2(20 CHAR) DEFAULT 'light' NOT NULL,
                        created_at         VARCHAR2(30 CHAR) DEFAULT
                            TO_CHAR(SYSTIMESTAMP AT TIME ZONE 'UTC',
                                    'YYYY-MM-DD"T"HH24:MI:SS"Z"') NOT NULL
                    )
                    """,
                )
                self._exec_ddl(cursor, "CREATE UNIQUE INDEX uq_users_email ON users (UPPER(email))")

                self._exec_ddl(
                    cursor,
                    """
                    CREATE TABLE users_sensitive (
                        user_id              NUMBER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                        password_hash        VARCHAR2(200 CHAR) DEFAULT '' NOT NULL,
                        two_factor_secret    VARCHAR2(64 CHAR),
                        two_factor_confirmed NUMBER(1,0) DEFAULT 0 NOT NULL,
                        session_id           VARCHAR2(64 CHAR),
                        last_login_ip        VARCHAR2(50 CHAR),
                        last_login_at        VARCHAR2(30 CHAR),
                        current_token        CLOB
                    )
                    """,
                )

                self._exec_ddl(
                    cursor,
                    """
                    CREATE TABLE user_progress (
                        id                     NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                        user_id                NUMBER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        course_id              NUMBER NOT NULL,
                        topic_index            NUMBER NOT NULL,
                        completed              NUMBER(1,0) DEFAULT 0 NOT NULL,
                        last_visited_at        VARCHAR2(30 CHAR) DEFAULT
                            TO_CHAR(SYSTIMESTAMP AT TIME ZONE 'UTC',
                                    'YYYY-MM-DD"T"HH24:MI:SS"Z"') NOT NULL,
                        last_visited_course_at VARCHAR2(30 CHAR) DEFAULT
                            TO_CHAR(SYSTIMESTAMP AT TIME ZONE 'UTC',
                                    'YYYY-MM-DD"T"HH24:MI:SS"Z"') NOT NULL
                    )
                    """,
                )
                self._exec_ddl(
                    cursor,
                    "CREATE UNIQUE INDEX uq_user_progress ON user_progress (user_id, course_id, topic_index)",
                )

                conn.commit()
            finally:
                cursor.close()
        finally:
            conn.close()

        log.info("Oracle auth DB ready (dsn=%s)", self.config.dsn)

    def is_integrity_error(self, exc: Exception) -> bool:
        return isinstance(exc, oracledb.IntegrityError)
