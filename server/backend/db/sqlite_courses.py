from __future__ import annotations

import logging
import sqlite3
from typing import Sequence

from backend.config import SqliteCourseShard

log = logging.getLogger(__name__)


class SQLiteCourseDatabase:
    """SQLite adapter for course/topic read APIs.

    A default DB path handles the current single-file setup. Optional shards can
    override the DB path for specific course ID ranges.
    """

    engine = "sqlite"

    def __init__(self, default_db_path: str, shards: Sequence[SqliteCourseShard] = ()):
        self.default_db_path = default_db_path
        self.shards = tuple(sorted(shards, key=lambda shard: shard.start_id))

        if self.shards:
            ranges = ", ".join(
                f"[{shard.start_id}-{shard.end_id}] -> {shard.db_path}" for shard in self.shards
            )
            log.info("Course DB sharding enabled: %s", ranges)
        else:
            log.info("Course DB sharding disabled; using single DB: %s", self.default_db_path)

    def resolve_db_path(self, course_id: int | None = None) -> str:
        if course_id is None:
            return self.default_db_path

        for shard in self.shards:
            if shard.start_id <= course_id <= shard.end_id:
                return shard.db_path

        return self.default_db_path

    def get_connection(self, course_id: int | None = None) -> sqlite3.Connection:
        db_path = self.resolve_db_path(course_id)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn
