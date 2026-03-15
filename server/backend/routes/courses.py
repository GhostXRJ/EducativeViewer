from __future__ import annotations

import json
from typing import Any

from flask import Blueprint, abort, jsonify, request

from backend.auth_service import AuthService
from backend.db.manager import DBManager


def _rows_to_list(rows: list[Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _require(payload: dict[str, Any], *keys: str) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        abort(400, description=f"Missing required field(s): {', '.join(missing)}")


def create_courses_blueprint(auth_service: AuthService, db_manager: DBManager) -> Blueprint:
    bp = Blueprint("courses_api", __name__, url_prefix="/api")

    @bp.route("/courses", methods=["GET"])
    def get_all_courses():
        user, _ = auth_service.resolve_user(require_full=True)
        if not user:
            abort(401, description="Authentication required")

        conn = db_manager.get_course_connection()
        try:
            rows = conn.execute(
                "SELECT id, slug, title, type FROM courses ORDER BY id"
            ).fetchall()
            return jsonify(_rows_to_list(rows))
        finally:
            conn.close()

    @bp.route("/course-details", methods=["POST"])
    def get_course_data():
        user, _ = auth_service.resolve_user(require_full=True)
        if not user:
            abort(401, description="Authentication required")

        payload = request.get_json(force=True, silent=True) or {}
        _require(payload, "course_id")
        course_id = int(payload["course_id"])

        conn = db_manager.get_course_connection(course_id)
        try:
            row = conn.execute(
                "SELECT id, slug, title, type, toc_json FROM courses WHERE id = ?",
                (course_id,),
            ).fetchone()

            if not row:
                abort(404, description=f"Course id={course_id} not found")

            data = dict(row)
            data["toc"] = json.loads(data.pop("toc_json") or "[]")
            return jsonify(data)
        finally:
            conn.close()

    @bp.route("/topic-details", methods=["POST"])
    def get_topic_data():
        user, _ = auth_service.resolve_user(require_full=True)
        if not user:
            abort(401, description="Authentication required")

        payload = request.get_json(force=True, silent=True) or {}
        _require(payload, "course_id", "topic_index")

        course_id = int(payload["course_id"])
        topic_index = int(payload["topic_index"])

        conn = db_manager.get_course_connection(course_id)
        try:
            topic = conn.execute(
                """
                SELECT topic_name, topic_slug, topic_url, api_url, status
                FROM topics
                WHERE course_id = ? AND topic_index = ?
                """,
                (course_id, topic_index),
            ).fetchone()

            if not topic:
                abort(
                    404,
                    description=(
                        f"Topic course_id={course_id} topic_index={topic_index} not found"
                    ),
                )

            component_rows = conn.execute(
                """
                SELECT component_index, type, content_json
                FROM components
                WHERE course_id = ? AND topic_index = ?
                ORDER BY component_index
                """,
                (course_id, topic_index),
            ).fetchall()

            components = [
                {
                    "index": row["component_index"],
                    "type": row["type"],
                    "content": json.loads(row["content_json"] or "{}"),
                }
                for row in component_rows
            ]

            return jsonify(
                {
                    "course_id": course_id,
                    "topic_index": topic_index,
                    "topic_name": topic["topic_name"],
                    "topic_slug": topic["topic_slug"],
                    "topic_url": topic["topic_url"],
                    "api_url": topic["api_url"],
                    "status": topic["status"],
                    "components": components,
                }
            )
        finally:
            conn.close()

    @bp.route("/test_components", methods=["GET"])
    def get_test_components():
        user, _ = auth_service.resolve_user(require_full=True)
        if not user:
            abort(401, description="Authentication required")

        conn = db_manager.get_course_connection()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS test_components (
                    component_id INTEGER PRIMARY KEY,
                    component_type TEXT,
                    content_json TEXT,
                    topic_url TEXT
                )
                """
            )
            conn.commit()

            rows = conn.execute(
                "SELECT component_id, component_type, content_json, topic_url "
                "FROM test_components ORDER BY component_id"
            ).fetchall()
            return jsonify(_rows_to_list(rows))
        finally:
            conn.close()

    return bp
