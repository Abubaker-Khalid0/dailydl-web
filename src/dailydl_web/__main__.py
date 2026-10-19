import argparse

from waitress import serve

from .app import create_app


def main():
    parser = argparse.ArgumentParser(
        description="DailyDL Web — local Dailymotion downloads"
    )
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    app = create_app()
    print(f"DailyDL Web: http://127.0.0.1:{args.port}", flush=True)
    try:
        serve(app, host="127.0.0.1", port=args.port, threads=6)
    finally:
        app.extensions["jobs"].close()


if __name__ == "__main__":
    main()
