"""開発時にファイル変更を監視してUvicornサーバーを自動再起動するランチャー。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional

import uvicorn
import logging

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent


def _collect_reload_dirs() -> Iterable[str]:
    """監視対象ディレクトリのリストを生成。"""

    candidates = [
        PROJECT_ROOT / "apps",
        PROJECT_ROOT / "packages",
    ]
    return [str(path) for path in candidates if path.exists()]


def _resolve_env_file() -> Optional[str]:
    """環境変数で指定されたenvファイル、もしくはデフォルトパスを返す。"""

    env_path = os.environ.get("SERVER_ENV_FILE")
    if env_path:
        return str(Path(env_path).expanduser().resolve())

    default_env = BASE_DIR / ".env"
    if default_env.exists():
        return str(default_env)

    return None


def main() -> None:
    log_level = os.environ.get("UVICORN_LOG_LEVEL", os.environ.get("LOG_LEVEL", "info")).lower()
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))

    kwargs = {
        "app": "apps.server.main:app",
        "host": os.environ.get("UVICORN_HOST", "127.0.0.1"),
        "port": int(os.environ.get("UVICORN_PORT", "8000")),
        "reload": True,
        "reload_dirs": list(_collect_reload_dirs()),
        "log_level": log_level,
    }

    env_file = _resolve_env_file()
    if env_file:
        kwargs["env_file"] = env_file

    uvicorn.run(**kwargs)


if __name__ == "__main__":
    main()
