from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


DEFAULT_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def mount_frontend(app: FastAPI, directory: Path = DEFAULT_FRONTEND_DIST) -> bool:
    """Serve the production frontend when a Vite build is available."""
    if not directory.is_dir():
        return False

    app.mount(
        "/",
        StaticFiles(directory=str(directory), html=True),
        name="frontend",
    )
    return True
