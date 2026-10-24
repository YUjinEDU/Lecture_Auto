from __future__ import annotations

import argparse
import sys

from lecture_auto.web.settings import REPO_ROOT, settings_from_env

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> None:
    ap = argparse.ArgumentParser(description="Lecture Auto 스튜디오 (web UI)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8800)
    args = ap.parse_args()

    import uvicorn

    from lecture_auto.web.app import create_app

    uvicorn.run(create_app(settings_from_env()), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
