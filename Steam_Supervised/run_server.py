from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn


BASE_DIR = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Start the Steam Price Monitor app with the correct app directory."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    uvicorn_kwargs = {
        "app": "steam_price_monitor.main:app",
        "host": args.host,
        "port": args.port,
        "reload": args.reload,
        "app_dir": str(BASE_DIR),
    }
    if args.reload:
        uvicorn_kwargs["reload_dirs"] = [str(BASE_DIR)]
    uvicorn.run(**uvicorn_kwargs)


if __name__ == "__main__":
    main()
