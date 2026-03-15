from __future__ import annotations

import logging

from flask import Flask, jsonify, request

from backend.auth_service import AuthService
from backend.config import AppConfig, load_config
from backend.db.manager import DBManager
from backend.routes.auth import create_auth_blueprint
from backend.routes.courses import create_courses_blueprint

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def create_app(
    config: AppConfig | None = None,
    *,
    initialize_db: bool = True,
    start_background_jobs: bool = False,
) -> Flask:
    cfg = config or load_config()

    app = Flask(__name__)
    db_manager = DBManager(cfg)
    auth_service = AuthService(cfg, db_manager)

    app.extensions["app_config"] = cfg
    app.extensions["db_manager"] = db_manager
    app.extensions["auth_service"] = auth_service

    @app.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
        log.info("%s %s -> %s", request.method, request.full_path.rstrip("?"), response.status_code)
        return response

    @app.route("/api/<path:_path>", methods=["OPTIONS"])
    def handle_preflight(_path: str):
        return "", 204

    @app.errorhandler(400)
    @app.errorhandler(401)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(409)
    @app.errorhandler(500)
    def json_error(error):
        return jsonify({"error": getattr(error, "description", str(error))}), error.code

    app.register_blueprint(create_courses_blueprint(auth_service, db_manager))
    app.register_blueprint(create_auth_blueprint(auth_service, db_manager))

    if initialize_db:
        db_manager.init_auth_db()

    if start_background_jobs:
        db_manager.start_keepalive_scheduler(app)

    return app
