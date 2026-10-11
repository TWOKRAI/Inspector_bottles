"""Раскрытие слепой оценки: scores.tsv (метка, верность, полнота, польза) + judge_key.json."""

import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AXES = ("верность", "полнота", "польза")


def main(scores_path: Path, key_name: str) -> None:
    key = json.loads((HERE / key_name).read_text(encoding="utf-8"))
    data = []
    for line in scores_path.read_text(encoding="utf-8").splitlines():
        label, *values = line.split("\t")
        scores = [float(v) for v in values]
        data.append({"q": label.split("-")[0].lower(), **key[label], "scores": scores, "sum": sum(scores)})

    print("| Вариант | n | " + " | ".join(AXES) + " | сумма из 15 |")
    print("|---|---|---|---|---|---|")
    variants = sorted({d["variant"] for d in data})
    for variant in variants:
        rows = [d for d in data if d["variant"] == variant]
        axes = [statistics.mean(d["scores"][i] for d in rows) for i in range(3)]
        total = statistics.mean(d["sum"] for d in rows)
        print(f"| {variant} | {len(rows)} | " + " | ".join(f"{a:.2f}" for a in axes) + f" | {total:.2f} |")

    print("\n| Вопрос | " + " | ".join(f"сумма {v}" for v in variants) + " | лучший ответ |")
    print("|---" * (len(variants) + 2) + "|")
    for q in sorted({d["q"] for d in data}):
        part = [d for d in data if d["q"] == q]
        cells = [statistics.mean(d["sum"] for d in part if d["variant"] == v) for v in variants]
        best = max(d["sum"] for d in part)
        winners = ",".join(f"{d['variant']}{d['rep']}" for d in part if d["sum"] == best)
        print(f"| {q} | " + " | ".join(f"{c:.1f}" for c in cells) + f" | {winners} |")


if __name__ == "__main__":
    main(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "judge_key.json")
