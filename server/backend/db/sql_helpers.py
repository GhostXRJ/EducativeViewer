from __future__ import annotations

from typing import Any


def execute(conn: Any, sql: str, params: dict[str, Any] | tuple[Any, ...] | None = None) -> int:
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params or {})
        return int(getattr(cursor, "rowcount", -1))
    finally:
        cursor.close()


def fetch_one(conn: Any, sql: str, params: dict[str, Any] | tuple[Any, ...] | None = None) -> tuple[Any, list[str]]:
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params or {})
        row = cursor.fetchone()
        columns = [col[0].lower() for col in (cursor.description or [])]
        return row, columns
    finally:
        cursor.close()


def fetch_all(conn: Any, sql: str, params: dict[str, Any] | tuple[Any, ...] | None = None) -> tuple[list[Any], list[str]]:
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params or {})
        rows = cursor.fetchall()
        columns = [col[0].lower() for col in (cursor.description or [])]
        return rows, columns
    finally:
        cursor.close()


def fetch_one_dict(conn: Any, sql: str, params: dict[str, Any] | tuple[Any, ...] | None = None) -> dict[str, Any] | None:
    row, columns = fetch_one(conn, sql, params)
    if row is None:
        return None
    return {col: row[idx] for idx, col in enumerate(columns)}


def fetch_all_dict(conn: Any, sql: str, params: dict[str, Any] | tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
    rows, columns = fetch_all(conn, sql, params)
    return [{col: row[idx] for idx, col in enumerate(columns)} for row in rows]


def rollback_quietly(conn: Any) -> None:
    try:
        conn.rollback()
    except Exception:
        pass
