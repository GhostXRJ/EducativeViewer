from __future__ import annotations

import logging
import os

from waitress import serve

from backend.app_factory import create_app
from backend.config import load_config

log = logging.getLogger(__name__)

config = load_config()
debug_mode = config.flask_debug
should_start_background_jobs = (not debug_mode or os.environ.get("WERKZEUG_RUN_MAIN") == "true")

app = create_app(
    config=config,
    initialize_db=True,
    start_background_jobs=should_start_background_jobs,
)

if __name__ == "__main__":
    if debug_mode:
        app.run(host="0.0.0.0", port=config.flask_port, debug=True)
    else:
        log.info("Starting production server via waitress on 0.0.0.0:%d", config.flask_port)
        serve(app, host="0.0.0.0", port=config.flask_port, threads=4)
