"""Потолок Атласа на rel1 ДО прогона: что дают ``atlas ref/map`` при идеальных id и при id из текста вопроса.

Цели — ``atlas_targets.json`` рядом (``ideal``: id, которые знает только автор эталона, с ``--all``/``--full``;
``realistic``: имена из текста вопроса или самая естественная догадка, срез по умолчанию). Атлас здесь НЕ источник
эталона: его адреса сравниваются с ``truth.json`` (паросочетание ±допуск, ``relset.score_set``).

    python scripts/nav_bench/questions/rel1_truth/atlas_ceiling.py --atlas-root <клон с scripts/atlas и кэшем> \
        [--python <python>] [--only A1 B1] [--show]

Платных вызовов нет; каждый вызов atlas ~1,3 с на тёплом кэше.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3]))
from scripts.nav_bench import bench, relset  # noqa: E402


def run_atlas(atlas_root: Path, python: str, sha: str, exclude: list[str], argv: list[str]) -> tuple[int, str, str]:
    cmd = [python, str(atlas_root / "scripts" / "atlas"), *argv, "--ref", sha, "--root", str(atlas_root)]
    if argv[0] == "ref":
        cmd += ["--format", "passport"]
    for e in exclude:
        cmd += ["--exclude", e]
    done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=atlas_root)
    return done.returncode, done.stdout, done.stderr


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--atlas-root", type=Path, required=True)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--show", action="store_true", help="печатать вывод atlas")
    args = ap.parse_args(argv)
    qset = json.loads((HERE.parent / "rel1.json").read_text(encoding="utf-8"))
    targets = json.loads((HERE / "atlas_targets.json").read_text(encoding="utf-8"))
    for q in qset["questions"]:
        qid = q["id"]
        if args.only and qid not in args.only:
            continue
        for mode in ("ideal", "realistic"):
            locs: list[str] = []
            notes = []
            spent = 0.0
            for one in targets[qid][mode]:
                started = time.monotonic()
                code, out, err = run_atlas(args.atlas_root, args.python, qset["repo_sha"], qset["exclude"], one)
                spent += time.monotonic() - started
                if code != 0:
                    notes.append(f"`{' '.join(one)}`: код {code}: {(err.strip().splitlines() or [''])[-1][:90]}")
                if args.show:
                    print(out)
                locs += [f"{p}:{n}" if n is not None else p for p, n in bench.text_addresses(out)]
            row = relset.score_set(q["expected"], locs)
            print(
                f"{qid} {mode}: вызовов {len(targets[qid][mode])}, адресов в выводе {len(set(locs))}, "
                f"верных {row['tp']}/{len(q['expected'])}, recall {row['recall']:.2f}, {spent:.1f} с"
                + (f"; {'; '.join(notes)}" if notes else "")
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
