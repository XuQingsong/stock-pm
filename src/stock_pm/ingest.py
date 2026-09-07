from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

from .database import Database


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest an IBKR plugin payload")
    parser.add_argument("payload", help="UTF-8 JSON file path, or - to read stdin")
    parser.add_argument(
        "--base64",
        action="store_true",
        help="Treat payload as base64-encoded UTF-8 JSON (useful for small batches)",
    )
    args = parser.parse_args()

    if args.base64:
        payload = json.loads(base64.b64decode(args.payload).decode("utf-8"))
    elif args.payload == "-":
        chunks: list[str] = []
        for line in sys.stdin:
            if line.rstrip("\r\n") == "__END__":
                break
            chunks.append(line)
        payload = json.loads("".join(chunks))
    else:
        payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    database = Database()
    try:
        database.initialize()
        counts = database.ingest(payload)
        print(json.dumps(counts, ensure_ascii=False))
    finally:
        database.close()


if __name__ == "__main__":
    main()
