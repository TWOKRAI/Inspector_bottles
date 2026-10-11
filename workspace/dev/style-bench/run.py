"""Стенд стиля ответов: вариант A (как сейчас) против B (+ хук-напоминание STE-80).

Каждый вызов — отдельная сессия `claude -p`, поэтому стенд не тратит контекст
текущей сессии. Результаты дописываются в results.jsonl; повторный запуск
пропускает готовые прогоны (можно прерывать и продолжать).

Примеры:
    python workspace/dev/style-bench/run.py --dry-run
    python workspace/dev/style-bench/run.py --mode single --reps 3
    python workspace/dev/style-bench/run.py --mode chain --reps 2
    python workspace/dev/style-bench/run.py --report-only
"""

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess  # nosec B404 - вызов claude CLI с фиксированным списком аргументов
import sys
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
RESULTS = HERE / "results.jsonl"  # переопределяется --results
# Вариант -> файл напоминания; A — без хука.
REMINDERS = {"B": "reminder.md", "C": "reminder_c.md", "D": "reminder_d.md"}
HOOK_LOG = HERE / "hook_fired.log"

# Признаки стиля, которые режет Terse. Для русского вывода.
FIRST_PERSON = re.compile(
    r"\b(я|мне|меня|мной|мой|моя|моё|мои|сейчас (?:посмотрю|проверю|сделаю|найду))\b",
    re.IGNORECASE,
)
CLOSER = re.compile(
    r"(если хотите|если нужно|могу (?:также|ещё|сделать|показать|подготовить)|хотите,|дайте знать|скажите, если)",
    re.IGNORECASE,
)
BOLD_LEAD_IN = re.compile(r"^\s*(?:[-*]\s+)?\*\*[^*\n]+\*\*\s*[:—-]", re.MULTILINE)
WORD = re.compile(r"\w+")


def hook_settings(reminder: str) -> str:
    python = Path(sys.executable).as_posix()
    inject = (HERE / "inject.py").as_posix()
    settings = {
        "hooks": {
            "UserPromptSubmit": [{"hooks": [{"type": "command", "command": f'"{python}" "{inject}" {reminder}'}]}]
        }
    }
    return json.dumps(settings)


def hook_fire_count() -> int:
    if not HOOK_LOG.exists():
        return 0
    return len(HOOK_LOG.read_text(encoding="utf-8").splitlines())


def build_command(args, variant: str, session_flag: list[str]) -> list[str]:
    claude = shutil.which("claude")
    if claude is None:
        sys.exit("claude не найден в PATH")
    cmd = [
        claude,
        "-p",
        "--output-format",
        "json",
        "--model",
        args.model,
        "--max-budget-usd",
        str(args.budget),
        # Без MCP: одинаково для A и B, дешевле и быстрее старт.
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        # Только чтение: стенд не должен менять рабочее дерево.
        "--allowedTools",
        "Read,Grep,Glob",
        "--disallowedTools",
        "Edit,Write,NotebookEdit,Bash",
        *session_flag,
    ]
    if variant in REMINDERS:
        cmd += ["--settings", hook_settings(REMINDERS[variant])]
    return cmd


def call_claude(args, variant: str, prompt: str, session_flag: list[str]) -> dict:
    env = dict(os.environ, PYTHONUTF8="1")
    env.pop("CLAUDECODE", None)
    fires_before = hook_fire_count()
    started = time.time()
    proc = subprocess.run(  # nosec B603 - команда собирается из своих констант, без shell
        build_command(args, variant, session_flag),
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=REPO_ROOT,
        env=env,
        timeout=args.timeout,
    )
    fires = hook_fire_count() - fires_before
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print(f"  ! не JSON (код {proc.returncode}): {proc.stderr[-300:]}", file=sys.stderr)
        return {"error": proc.stderr[-2000:] or proc.stdout[-2000:], "hook_fires": fires}
    usage = data.get("usage") or {}
    return {
        "text": data.get("result") or "",
        "is_error": bool(data.get("is_error")),
        "cost_usd": data.get("total_cost_usd"),
        "output_tokens": usage.get("output_tokens"),
        # Владелец на подписке: меряем токены, доллары — справочно.
        "input_tokens": usage.get("input_tokens"),
        "cache_read_tokens": usage.get("cache_read_input_tokens"),
        "cache_creation_tokens": usage.get("cache_creation_input_tokens"),
        "num_turns": data.get("num_turns"),
        "duration_s": round(time.time() - started, 1),
        "session_id": data.get("session_id"),
        "hook_fires": fires,
    }


def is_failed(row: dict) -> bool:
    return "error" in row or bool(row.get("is_error"))


def load_done() -> dict[tuple, dict]:
    """Ключ прогона -> строка результата; упавшие прогоны не считаются сделанными."""
    done = {}
    if RESULTS.exists():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if not is_failed(row):
                done[(row["mode"], row["variant"], row["item"], row["rep"], row["turn"])] = row
    return done


def append(row: dict) -> None:
    with RESULTS.open("a", encoding="utf-8") as out:
        out.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_single(args, prompts, done) -> None:
    for rep in range(1, args.reps + 1):
        for item in prompts["single"]:
            if args.only and item["id"] not in args.only:
                continue
            for variant in args.variants:
                key = ("single", variant, item["id"], rep, 1)
                if key in done:
                    continue
                print(f"single {variant} {item['id']} rep{rep}", flush=True)
                if args.dry_run:
                    continue
                result = call_claude(args, variant, item["text"], ["--no-session-persistence"])
                append({"mode": "single", "variant": variant, "item": item["id"], "rep": rep, "turn": 1, **result})


def run_chain(args, prompts, done) -> None:
    turns = len(prompts["chain"])
    for rep in range(1, args.reps + 1):
        for variant in args.variants:
            done_turns = [t for t in range(1, turns + 1) if ("chain", variant, "chain", rep, t) in done]
            if len(done_turns) == turns:
                continue
            # Недоделанная цепочка продолжается в той же сессии, иначе дрейф по ходам не сравним.
            if done_turns:
                last = max(done_turns)
                session_id = done[("chain", variant, "chain", rep, last)]["session_id"]
            else:
                last = 0
                session_id = str(uuid.uuid4())
            for turn, text in enumerate(prompts["chain"], start=1):
                if turn <= last:
                    continue
                print(f"chain {variant} rep{rep} turn{turn}", flush=True)
                if args.dry_run:
                    continue
                flag = ["--session-id", session_id] if turn == 1 else ["--resume", session_id]
                result = call_claude(args, variant, text, flag)
                append({"mode": "chain", "variant": variant, "item": "chain", "rep": rep, "turn": turn, **result})
                if is_failed(result):
                    print("  ! цепочка прервана", file=sys.stderr)
                    break


def metrics(text: str) -> dict:
    words = len(WORD.findall(text))
    last_paragraph = text.strip().split("\n\n")[-1] if text.strip() else ""
    per_k = 1000 / words if words else 0
    return {
        "words": words,
        "first_person_per_k": len(FIRST_PERSON.findall(text)) * per_k,
        "dashes_per_k": text.count("—") * per_k,
        "bold_lead_ins": len(BOLD_LEAD_IN.findall(text)),
        "closer": bool(CLOSER.search(last_paragraph)),
    }


def mean_sd(values: list[float]) -> str:
    values = [v for v in values if v is not None]
    if not values:
        return "—"
    if len(values) == 1:
        return f"{values[0]:.0f} (n=1)"
    return f"{statistics.mean(values):.0f} ± {statistics.stdev(values):.0f}"


def report() -> None:
    if not RESULTS.exists():
        sys.exit("results.jsonl пуст — сначала запустить прогоны")
    rows = [json.loads(line) for line in RESULTS.read_text(encoding="utf-8").splitlines()]
    good = [r for r in rows if not is_failed(r)]
    for r in good:
        r.update(metrics(r["text"]))
    lines = [f"# Стенд стиля: {RESULTS.name}", ""]
    errors = len(rows) - len(good)
    lines.append(f"Прогонов: {len(rows)}, ошибок: {errors}.")
    bad_hook = [
        r
        for r in good
        if (r["variant"] in REMINDERS and r["hook_fires"] < 1) or (r["variant"] == "A" and r["hook_fires"] > 0)
    ]
    lines.append(f"Нарушений проверки хука (хук не сработал или сработал в A): {len(bad_hook)}.")
    lines.append("")
    for mode in ("single", "chain"):
        part = [r for r in good if r["mode"] == mode]
        if not part:
            continue
        lines += [
            f"## {mode}",
            "",
            "| Вариант | n | Слова | Output-токены на ответ | Output-токены всего "
            "| 1-е лицо /1k | Тире /1k | Bold lead-in | Доля с закрывашкой |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for variant in sorted({r["variant"] for r in part}):
            vr = [r for r in part if r["variant"] == variant]
            lines.append(
                f"| {variant} | {len(vr)} | {mean_sd([r['words'] for r in vr])} "
                f"| {mean_sd([r['output_tokens'] for r in vr])} "
                f"| {sum(r['output_tokens'] or 0 for r in vr)} "
                f"| {statistics.mean(r['first_person_per_k'] for r in vr):.1f} "
                f"| {statistics.mean(r['dashes_per_k'] for r in vr):.1f} "
                f"| {statistics.mean(r['bold_lead_ins'] for r in vr):.1f} "
                f"| {sum(r['closer'] for r in vr) / len(vr):.0%} |"
            )
        lines.append("")
        if mode == "single":
            variants = sorted({r["variant"] for r in part})
            lines += [
                "Слова по промптам (среднее ± sd):",
                "",
                "| Промпт | " + " | ".join(variants) + " |",
                "|---" * (len(variants) + 1) + "|",
            ]
            for item in sorted({r["item"] for r in part}):
                cells = [
                    mean_sd([r["words"] for r in part if r["item"] == item and r["variant"] == v]) for v in variants
                ]
                lines.append(f"| {item} | " + " | ".join(cells) + " |")
        else:
            variants = sorted({r["variant"] for r in part})
            lines += [
                "Дрейф — слова по номеру хода (среднее по повторам):",
                "",
                "| Ход | " + " | ".join(variants) + " |",
                "|---" * (len(variants) + 1) + "|",
            ]
            for turn in sorted({r["turn"] for r in part}):
                cells = [
                    mean_sd([r["words"] for r in part if r["turn"] == turn and r["variant"] == v]) for v in variants
                ]
                lines.append(f"| {turn} | " + " | ".join(cells) + " |")
        lines.append("")
    (HERE / f"report{RESULTS.stem.removeprefix('results')}.md").write_text("\n".join(lines), encoding="utf-8")

    answers = ["# Ответы для ручной оценки точности", ""]
    for r in sorted(good, key=lambda r: (r["mode"], r["item"], r["turn"], r["rep"], r["variant"])):
        answers += [
            f"## {r['mode']} / {r['item']} / ход {r['turn']} / rep{r['rep']} / {r['variant']} ({r['words']} слов)",
            "",
            r["text"],
            "",
        ]
    (HERE / f"answers{RESULTS.stem.removeprefix('results')}.md").write_text("\n".join(answers), encoding="utf-8")
    print("\n".join(lines))
    suffix = RESULTS.stem.removeprefix("results")
    print(f"\nОтчёт: {HERE / f'report{suffix}.md'}\nОтветы: {HERE / f'answers{suffix}.md'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["single", "chain"], default="single")
    parser.add_argument("--variants", default="A,B", type=lambda s: s.split(","))
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--only", type=lambda s: s.split(","), help="id промптов single, через запятую")
    parser.add_argument("--model", default="claude-opus-5-5")
    parser.add_argument("--results", default="results.jsonl", help="файл результатов в папке стенда")
    parser.add_argument("--budget", type=float, default=1.0, help="лимит $ на один вызов")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--dry-run", action="store_true", help="только показать план вызовов")
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    global RESULTS
    RESULTS = HERE / args.results

    if not args.report_only:
        prompts = json.loads((HERE / "prompts.json").read_text(encoding="utf-8"))
        done = load_done()
        (run_single if args.mode == "single" else run_chain)(args, prompts, done)
        if args.dry_run:
            return
    report()


if __name__ == "__main__":
    main()
