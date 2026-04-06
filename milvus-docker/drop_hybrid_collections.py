"""
Удаляет коллекции claude-context с префиксом hybrid_code_chunks_ на локальном Milvus.
Нужен при ошибке load: sparse_vector / битая схема после смены версии Milvus.

Запуск из корня репозитория (с активированным venv, где установлен pymilvus):
  python milvus-docker/drop_hybrid_collections.py
  python milvus-docker/drop_hybrid_collections.py --list-only
"""
from __future__ import annotations

import argparse
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Drop claude-context hybrid_* collections in Milvus")
    parser.add_argument("--host", default="localhost", help="Milvus gRPC host")
    parser.add_argument("--port", default="19530", help="Milvus gRPC port")
    parser.add_argument(
        "--prefix",
        default="hybrid_code_chunks_",
        help="Drop all collections whose name starts with this prefix",
    )
    parser.add_argument("--list-only", action="store_true", help="Only print collection names, do not drop")
    args = parser.parse_args()

    try:
        from pymilvus import connections, utility
    except ImportError:
        print("Install pymilvus in this environment (see project venv / Inspector_bottles setup).", file=sys.stderr)
        return 1

    connections.connect("default", host=args.host, port=str(args.port))
    names = utility.list_collections()
    targets = [n for n in names if n.startswith(args.prefix)]

    if not targets:
        print("No collections match prefix:", repr(args.prefix))
        print("All collections:", names)
        return 0

    print("Matching:", targets)
    if args.list_only:
        return 0

    for name in targets:
        utility.drop_collection(name)
        print("Dropped:", name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
