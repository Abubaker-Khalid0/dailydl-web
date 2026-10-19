"""Private JSON-lines protocol for a killable extraction/download process."""

import json
import sys

from .engine import execute, public_error


def emit(message):
    print(json.dumps(message, ensure_ascii=True), flush=True)


def main():
    try:
        request = json.loads(sys.stdin.readline())
        result = execute(request, emit)
        emit({"type": "result", "result": result})
    except Exception as error:
        emit({"type": "error", "error": public_error(error)})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
