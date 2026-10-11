"""Слепые пакеты для оценки качества режима single.

На каждый промпт — один файл с вопросом и 6 ответами под случайными метками.
Ключ «метка -> вариант/повтор» пишется в judge_key.json — оценщикам его не показывают.
"""

import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main(out_dir: Path, results_name: str, key_name: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    prompts = {p["id"]: p["text"] for p in json.loads((HERE / "prompts.json").read_text(encoding="utf-8"))["single"]}
    rows = [json.loads(line) for line in (HERE / results_name).read_text(encoding="utf-8").splitlines()]
    rng = random.Random(20261011)  # nosec B311 - детерминированная перемешка для слепой оценки, не криптография
    key = {}
    for item, question in prompts.items():
        answers = [r for r in rows if r["mode"] == "single" and r["item"] == item and not r.get("is_error")]
        rng.shuffle(answers)
        labels = [f"{item.upper()}-{chr(ord('K') + i)}" for i in range(len(answers))]
        parts = [f"# Вопрос {item}", "", question, ""]
        for label, row in zip(labels, answers):
            key[label] = {"variant": row["variant"], "rep": row["rep"]}
            parts += [f"## Ответ {label}", "", row["text"].strip(), ""]
        (out_dir / f"{item}.md").write_text("\n".join(parts), encoding="utf-8")
    (HERE / key_name).write_text(json.dumps(key, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"пакетов: {len(prompts)}, ответов: {len(key)} -> {out_dir}")


if __name__ == "__main__":
    # аргументы: папка пакетов [файл результатов] [файл ключа]
    args = sys.argv[1:] + ["results.jsonl", "judge_key.json"][len(sys.argv) - 2 :]
    main(Path(args[0]), args[1], args[2])
