"""Сверка эталона rel1 с ``git grep`` и счёт «разумного grep» для таблицы потолка.

Для каждого вопроса — шаблон(ы) ``grep`` из ``spec.json`` (поле ``grep``: то, что разумный агент ввёл бы первым,
зная имя из текста вопроса или найдя его одним шагом). Вывод:
  * каждая прод-строка вне тестов с отметкой ``[T]`` (есть в эталоне, точная строка) / ``[ ]`` (нет) — список для
    ручной сверки: каждую ``[ ]`` человек читает и решает по правилам включения (``truth.py``);
  * эталонные записи, которых grep не нашёл (``ПРОПУСК grep``);
  * итог: строк всего (как увидит агент: тесты, документы, комментарии), из них верных (паросочетание ±3, как у
    оценки), ложных, recall.

    python scripts/nav_bench/questions/rel1_truth/crosscheck.py --root . [--only A1 B1]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3]))
from scripts.nav_bench import relset  # noqa: E402
from scripts.nav_bench.questions.rel1_truth.truth import is_test  # noqa: E402


def grep(root: Path, sha: str, pattern: str, exclude: list[str], where: str = ".") -> list[tuple[str, int, str]]:
    cmd = ["git", "-C", str(root), "grep", "-n", "-I", "-E", "-e", pattern, sha, "--", where]
    cmd += [f":(exclude){e}" for e in exclude]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    rows = []
    for row in out.splitlines():
        parts = row.split(":", 3)
        if len(parts) == 4 and parts[2].isdigit():
            rows.append((parts[1], int(parts[2]), parts[3].strip()[:110]))
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--quiet", action="store_true", help="только итоги")
    args = ap.parse_args(argv)
    spec = json.loads((HERE / "spec.json").read_text(encoding="utf-8"))
    truth = json.loads((HERE / "truth.json").read_text(encoding="utf-8"))
    for qid, q in spec["questions"].items():
        if args.only and qid not in args.only:
            continue
        entries = truth["questions"][qid]["entries"]
        keys = {(e["path"], e["line"]) for e in entries}
        files = {e["path"] for e in entries}
        hits: list[tuple[str, int, str]] = []
        for pattern in q.get("grep", []):
            hits += grep(args.root, spec["repo_sha"], pattern, spec["exclude"], q.get("grep_path", "."))
        hits = list(dict.fromkeys(hits))
        print(f"## {qid}: grep {q.get('grep')} — строк {len(hits)}")
        if not args.quiet:
            for path, line, text in hits:
                if is_test(path) or not path.endswith(".py"):
                    continue
                mark = "T" if (path, line) in keys or (path, None) in keys else " "
                print(f"  [{mark}] {path}:{line}  {text}")
        locs = [f"{p}:{n}" for p, n, _ in hits]
        row = relset.score_set(entries, locs)
        found = {(entries[j]["path"], entries[j]["line"]) for _, j in relset.match(entries, locs)}
        for e in entries:
            if (e["path"], e["line"]) not in found:
                print(f"  ПРОПУСК grep: {e['path']}:{e['line']} {e['symbol']}")
        test_rows = sum(is_test(p) for p, _, _ in hits)
        doc_rows = sum(not p.endswith(".py") for p, _, _ in hits)
        print(
            f"  итог {qid}: эталон {len(entries)} (файлов {len(files)}); строк grep {len(hits)} "
            f"(тесты {test_rows}, не .py {doc_rows}); верных {row['tp']}, ложных {row['fp']}, "
            f"recall {row['recall']:.2f}, precision {row['precision'] or 0:.2f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
