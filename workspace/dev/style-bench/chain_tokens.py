"""Токены цепочек по сохранённым транскриптам сессий (~/.claude/projects/...).

Ход = промпт пользователя и все API-вызовы до следующего промпта.
Вход = input + cache_read + cache_creation; повторы одного message.id не считаются.
"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECTS = Path.home() / ".claude" / "projects"


def session_turns(path: Path) -> list[dict]:
    turns: list[dict] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        message = entry.get("message") or {}
        if entry.get("type") == "user" and isinstance(message.get("content"), str):
            turns.append({"input": 0, "cache_read": 0, "cache_creation": 0, "output": 0, "calls": 0})
            continue
        usage = message.get("usage")
        if entry.get("type") != "assistant" or not usage or not turns or message.get("id") in seen:
            continue
        seen.add(message.get("id"))
        turn = turns[-1]
        turn["input"] += usage.get("input_tokens", 0)
        turn["cache_read"] += usage.get("cache_read_input_tokens", 0)
        turn["cache_creation"] += usage.get("cache_creation_input_tokens", 0)
        turn["output"] += usage.get("output_tokens", 0)
        turn["calls"] += 1
    return turns


def main() -> None:
    rows = [json.loads(line) for line in (HERE / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    sessions = sorted({(r["variant"], r["rep"], r["session_id"]) for r in rows if r["mode"] == "chain"})
    print("| Цепочка | Ход | Вход всего | из них cache_read | Output | API-вызовов |")
    print("|---|---|---|---|---|---|")
    totals: dict[str, list[int]] = {}
    for variant, rep, session_id in sessions:
        path = next(PROJECTS.glob(f"*/{session_id}.jsonl"))
        for number, turn in enumerate(session_turns(path), start=1):
            full_input = turn["input"] + turn["cache_read"] + turn["cache_creation"]
            print(
                f"| {variant}{rep} | {number} | {full_input} | {turn['cache_read']} "
                f"| {turn['output']} | {turn['calls']} |"
            )
            # Ход 8 у A2 упал — в сумму идут только ходы 1–7, общие для всех цепочек.
            if number <= 7:
                totals.setdefault(variant, [0, 0])
                totals[variant][0] += full_input
                totals[variant][1] += turn["output"]
    print()
    for variant, (full_input, output) in sorted(totals.items()):
        print(f"{variant}, ходы 1–7, 2 цепочки: вход {full_input}, output {output}")


if __name__ == "__main__":
    main()
