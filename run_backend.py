"""Launcher that chdir's into backend/ (so .env, SQLite file, and relative
data/report paths resolve correctly) before starting uvicorn."""

import os
import sys

BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
os.chdir(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

import uvicorn  # noqa: E402

if __name__ == "__main__":
    # Cloud Run injects PORT (and expects the container to bind 0.0.0.0) -
    # default to the local-dev values (127.0.0.1:8000) when unset.
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("app.main:app", host=host, port=port, reload=False)
