from __future__ import annotations

import os
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn


def data_directory() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "mrbot-payroll"


def main() -> None:
    database = data_directory() / "payroll.db"
    database.parent.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PAYROLL_DATABASE_URL", f"sqlite:///{database.as_posix()}")
    os.environ.setdefault("PAYROLL_ENVIRONMENT", "local")

    url = "http://127.0.0.1:8000"
    threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
