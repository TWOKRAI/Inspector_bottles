"""nav_bench — как быстро ИИ-агент находит нужное ``файл:строка`` и понимает архитектуру при заданном условии.

    python scripts/nav_bench/bench.py run --questions Q.json --condition C.json --repeats 3 [--dry-run] [--yes]
    python scripts/nav_bench/bench.py floor --questions Q.json --condition C.json [--dry-run] [--yes]
    python scripts/nav_bench/bench.py score --run data/nav_bench/<файл>.json [--baseline B.json]
    python scripts/nav_bench/bench.py compare A.json B.json
    python scripts/nav_bench/bench.py verify-set --questions Q.json

Один повтор = одна headless-сессия ``claude -p``, которая отвечает на ВСЕ вопросы набора. Сессия идёт в ЧИСТОЙ КОПИИ
репозитория (``git archive <repo_sha>`` без путей ``exclude`` набора), чтобы эталон не лежал рядом с кодом.
Реальный запуск стоит денег: без ``--yes`` он не стартует; без ``max_budget_usd`` — только с ``--no-budget``.
``--dry-run`` ничего не запускает. Подробности и формат наборов — README.md рядом.
"""

from __future__ import annotations

import argparse
import datetime
import fnmatch
import hashlib
import json
import shlex
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TextIO

try:
    from . import score
except ImportError:  # запуск как скрипта: python scripts/nav_bench/bench.py
    import score  # type: ignore[no-redef]

PKG_DIR = Path(__file__).resolve().parent

# --- Флаги claude: единственное место, где они перечислены ------------------------------------
# Сверено с `claude --help` (v2.1.289): -p, --output-format, --model, --allowedTools, --disallowedTools,
# --tools (встроенные инструменты), --mcp-config, --strict-mcp-config, --append-system-prompt,
# --max-budget-usd, --no-session-persistence, --verbose.
# `--max-turns` в этой версии в --help НЕТ, поэтому не передаётся: max_turns условия проверяется
# после прогона по num_turns (поле over_max_turns), жёсткий стоп-кран — max_budget_usd.
CLAUDE_BIN = "claude"
DEFAULT_OUTPUT_FORMAT = "stream-json"  # json не отдаёт число вызовов инструментов; stream-json требует --verbose
SESSION_TIMEOUT_S = 1800
MCP_PREFIX = "mcp__"

CONDITION_DEFAULTS: dict[str, Any] = {
    "allowed_tools": [],
    "disallowed_tools": [],
    "context_files": [],
    "prompt_prefix": "",
    "max_turns": None,
    "max_budget_usd": None,
    "expected_tokens": 0,
    "thresholds": {},
    "output_format": DEFAULT_OUTPUT_FORMAT,
    "audit_reads": False,  # True: Read разрешён только на context_files, любое другое чтение — нарушение
    "mcp_config": None,  # шаблон MCP-конфига (от nav_bench); {python} {repo_root} {run_root}
    "requires": [],  # предпроверки: "qex-index", "graphify-graph"
}

PROMPT_TEMPLATE = """\
You are answering navigation questions about the codebase in the current directory.
For each question find the place in the code that answers it: a repository-relative path and a line number.
{context_block}
Questions:
{questions_block}

Answer format: exactly one JSON object per question, one object per line, nothing else around it:
{{"id": "<question id>", "answer": "<short answer>", "locations": ["dir/file.py:123"], "confidence": "sure"}}
Rules:
- answer: the facts the question asks for, in your own words (names, counts, the mechanism), not only an address.
- locations: posix paths relative to the repository root, each "path:line", the line pointing at the answering code.
  Give the minimum number of addresses the question needs; extra addresses count against you.
- confidence: "sure" only if you opened that place yourself; "unsure" for a guess;
  "unknown" if you found nothing (then locations is []).
- A wrong address marked "sure" is worse than "unsure" or "unknown".
- Stop as soon as you have given one object for every question.
"""

FLOOR_PROMPT = (
    "Do not use any tools. Reply with exactly one JSON object and nothing else: "
    '{"id": "F0", "answer": "ready", "locations": [], "confidence": "unknown"}\n'
)
FLOOR_QUESTION = {"id": "F0", "question": "(floor: no question)", "expected": [], "scored": False}
FLOOR_THRESHOLDS = {"hits_min": 0, "false_max": 99}


# --- Загрузка и проверка наборов ----------------------------------------------------------------
def load_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _check_expected(path: Path, qid: str, question: dict[str, Any]) -> None:
    for item in question.get("expected") or []:
        line = item.get("line")
        if not item.get("path") or not (line is None or isinstance(line, int)):
            raise ValueError(f"{path}: {qid}: expected нужен path и line (int или null): {item!r}")
        if not isinstance(item.get("tolerance", 0), int):
            raise ValueError(f"{path}: {qid}: tolerance должен быть int: {item!r}")
    for fact in question.get("expected_facts") or []:
        options = fact.get("any_of") if isinstance(fact, dict) else None
        if not options or not all(isinstance(option, str) and option for option in options):
            raise ValueError(f"{path}: {qid}: у факта нужен непустой any_of из строк: {fact!r}")
    for key in ("require", "facts_require"):
        if question.get(key, "any" if key == "require" else "all") not in score.REQUIRES:
            raise ValueError(f"{path}: {qid}: {key} должно быть all или any: {question[key]!r}")


def load_questions(path: Path) -> dict[str, Any]:
    data = load_json(path)
    for field in ("name", "repo_sha", "questions"):
        if field not in data:
            raise ValueError(f"{path}: нет поля {field!r}")
    if not data["questions"]:
        raise ValueError(f"{path}: пустой набор вопросов")
    data.setdefault("exclude", [])
    data.setdefault("thresholds", {})
    seen: set[str] = set()
    for question in data["questions"]:
        qid = question.get("id")
        if not qid or not question.get("question"):
            raise ValueError(f"{path}: у вопроса нет id или текста: {question!r}")
        if qid in seen:
            raise ValueError(f"{path}: повтор id {qid!r}")
        seen.add(qid)
        if not question.get("expected") and not question.get("expected_facts"):
            raise ValueError(f"{path}: у {qid} нет ни expected, ни expected_facts")
        _check_expected(path, qid, question)
    return data


def load_condition(path: Path) -> dict[str, Any]:
    data = load_json(path)
    for field in ("name", "model"):
        if field not in data:
            raise ValueError(f"{path}: нет поля {field!r}")
    return {**CONDITION_DEFAULTS, **data}


def effective_thresholds(qset: dict[str, Any], condition: dict[str, Any]) -> dict[str, Any]:
    """Пороги: умолчания score < условие < набор."""
    return {**condition["thresholds"], **qset["thresholds"]}


# --- Чистая копия репозитория -----------------------------------------------------------------
def clean_copy_path(qset: dict[str, Any], condition: dict[str, Any], temp_base: Path | None = None) -> Path:
    """``%TEMP%/nav_bench/<sha>-<hash>``; hash = exclude набора + context_files условия (иначе копия
    от условия с картой осталась бы видна условию без карты)."""
    key = json.dumps({"exclude": sorted(qset["exclude"]), "context": sorted(condition["context_files"])})
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    base = Path(temp_base) if temp_base else Path(tempfile.gettempdir())
    return base / "nav_bench" / f"{qset['repo_sha']}-{digest}"


def _rmtree_force(path: Path) -> None:
    """Удаляет каталог, снимая read-only (Windows: файлы из git archive и .git-объекты)."""

    def _onexc(func: Callable[..., Any], target: str, _exc: BaseException) -> None:
        Path(target).chmod(stat.S_IWRITE)
        func(target)

    shutil.rmtree(path, onexc=_onexc)


def _extract_archive(repo_root: Path, sha: str, dest: Path, err: TextIO) -> None:
    proc = subprocess.Popen(
        ["git", "-C", str(repo_root), "archive", "--format=tar", sha], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    assert proc.stdout is not None and proc.stderr is not None
    skipped = 0
    with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
        for member in tar:
            try:
                tar.extract(member, dest, filter="fully_trusted")
            except (OSError, tarfile.TarError):
                skipped += 1  # симлинк без прав на Windows и т.п.
    stderr = proc.stderr.read().decode("utf-8", errors="replace")
    if proc.wait() != 0:
        raise RuntimeError(f"git archive {sha} не удался: {stderr.strip()}")
    if skipped:
        print(f"предупреждение: при распаковке пропущено элементов: {skipped} (симлинки?)", file=err)


def prepare_clean_copy(
    qset: dict[str, Any],
    condition: dict[str, Any],
    repo_root: Path,
    temp_base: Path | None = None,
    err: TextIO | None = None,
) -> Path:
    """Распаковывает ``git archive <repo_sha>`` без ``exclude`` и докладывает ``context_files`` условия.

    Каталог собирается во временном соседе и переименовывается: недоделанная копия не переиспользуется.
    Уже существующая копия с тем же sha+hash берётся как есть. В копии нет .git.
    """
    err = err or sys.stderr
    repo_root = Path(repo_root)
    dest = clean_copy_path(qset, condition, temp_base)
    if dest.exists():
        return dest
    tmp = dest.with_name(dest.name + ".tmp")
    if tmp.exists():
        _rmtree_force(tmp)
    tmp.mkdir(parents=True)
    try:
        _extract_archive(repo_root, qset["repo_sha"], tmp, err)
        for rel in qset["exclude"]:
            target = tmp / rel
            if target.is_dir():
                _rmtree_force(target)
            elif target.exists():
                target.chmod(stat.S_IWRITE)
                target.unlink()
        missing = [rel for rel in condition["context_files"] if not (repo_root / rel).is_file()]
        if missing:
            raise FileNotFoundError(f"context_files условия нет в репозитории {repo_root}: {missing}")
        for rel in condition["context_files"]:
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(repo_root / rel, tmp / rel)
        tmp.rename(dest)
    except BaseException:
        if tmp.exists():
            _rmtree_force(tmp)
        raise
    return dest


# --- git: проверки эталона -----------------------------------------------------------------------
def git_show(root: Path, sha: str, path: str) -> str | None:
    """Текст файла на ``sha`` или ``None``, если файла там нет."""
    out = subprocess.run(
        ["git", "-C", str(root), "show", f"{sha}:{path}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return out.stdout if out.returncode == 0 else None


def git_dirty(root: Path, paths: list[str]) -> list[str]:
    """Строки ``git status --porcelain -- <paths>``: эталонные файлы с незакоммиченными правками."""
    if not paths:
        return []
    out = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--", *paths],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return [line for line in out.stdout.splitlines() if line.strip()]


def expected_paths(qset: dict[str, Any]) -> list[str]:
    paths = {item["path"] for q in qset["questions"] for item in (q.get("expected") or [])}
    paths |= {item["path"] for q in qset["questions"] for item in (q.get("evidence") or [])}
    return sorted(paths)


def verify_set(
    qset: dict[str, Any], root: Path, show_fn: Callable[[Path, str, str], str | None] = git_show
) -> tuple[list[str], int]:
    """Сверка набора с кодом на ``repo_sha``: список проблем и число проверенных записей.

    expected: файл существует; если заданы ``line`` и ``symbol`` — символ (последняя часть после точки) встречается
    в строках ``line ± tolerance``. evidence (``{"path", "contains"}``): файл существует и содержит строку.
    """
    problems: list[str] = []
    checked = 0
    cache: dict[str, str | None] = {}

    def text_of(path: str) -> str | None:
        if path not in cache:
            cache[path] = show_fn(root, qset["repo_sha"], path)
        return cache[path]

    for question in qset["questions"]:
        qid = question["id"]
        for item in question.get("expected") or []:
            checked += 1
            text = text_of(item["path"])
            if text is None:
                problems.append(f"{qid}: файла {item['path']} нет на {qset['repo_sha']}")
                continue
            line, symbol = item.get("line"), item.get("symbol")
            if line is None or not symbol:
                continue
            tol = int(item.get("tolerance", score.TOLERANCE_LINES))
            lines = text.splitlines()
            window = lines[max(0, line - 1 - tol) : line + tol]
            needle = str(symbol).split(".")[-1]
            if not any(needle in row for row in window):
                problems.append(f"{qid}: символ {needle!r} не найден в {item['path']}:{line} ±{tol}")
        for item in question.get("evidence") or []:
            checked += 1
            text = text_of(item["path"])
            if text is None:
                problems.append(f"{qid}: evidence: файла {item['path']} нет на {qset['repo_sha']}")
            elif item["contains"] not in text:
                problems.append(f"{qid}: evidence: в {item['path']} нет строки {item['contains']!r}")
    return problems, checked


# --- MCP-конфиг и предпроверки -------------------------------------------------------------------
def _subst(obj: Any, mapping: dict[str, str]) -> Any:
    if isinstance(obj, str):
        for key, value in mapping.items():
            obj = obj.replace("{" + key + "}", value)
        return obj
    if isinstance(obj, list):
        return [_subst(item, mapping) for item in obj]
    if isinstance(obj, dict):
        return {key: _subst(value, mapping) for key, value in obj.items()}
    return obj


def mcp_config_dest(run_root: Path, condition: dict[str, Any]) -> Path:
    """Куда кладётся готовый MCP-конфиг: рядом с копией, не внутри (агент его не видит)."""
    return run_root.with_name(f"{run_root.name}.mcp-{condition['name']}.json")


def render_mcp_config(condition: dict[str, Any], repo_root: Path, run_root: Path) -> Path | None:
    if not condition["mcp_config"]:
        return None
    template = Path(condition["mcp_config"])
    if not template.is_absolute():
        template = PKG_DIR / template
    mapping = {"python": sys.executable, "repo_root": str(Path(repo_root).resolve()), "run_root": str(run_root)}
    dest = mcp_config_dest(run_root, condition)
    dest.write_text(json.dumps(_subst(load_json(template), mapping), indent=2), encoding="utf-8")
    return dest


def _norm_root(path: str) -> str:
    return path.removeprefix("\\\\?\\").replace("\\", "/").rstrip("/").casefold()


def check_requires(condition: dict[str, Any], run_root: Path, qex_home: Path | None = None) -> list[str]:
    """Проблемы предпроверки (пустой список — можно запускать). Индексы не строятся: только точная команда."""
    problems: list[str] = []
    for need in condition["requires"]:
        if need == "qex-index":
            projects = Path(qex_home) if qex_home else Path.home() / ".qex" / "projects"
            roots = set()
            for info in projects.glob("*/project_info.json"):
                try:
                    roots.add(_norm_root(str(load_json(info).get("project_path", ""))))
                except (OSError, ValueError):
                    continue
            if _norm_root(str(Path(run_root).resolve())) not in roots:
                problems.append(
                    f"нет qex-индекса для {run_root}. Построить (лид, основной чекаут, нужен `ollama serve`): "
                    f'mcp__qex__index_codebase(path="{run_root}", force=true)'
                )
        elif need == "graphify-graph":
            graph = Path(run_root) / "graphify-out" / "graph.json"
            if not graph.is_file():
                problems.append(
                    f"нет графа graphify для {run_root} (ждём {graph}). Построить (лид): "
                    f"в каталоге {run_root} выполнить /graphify . --update"
                )
        else:
            problems.append(f"неизвестное требование условия: {need!r}")
    return problems


# --- Промпт и команда ----------------------------------------------------------------------------
def build_prompt(questions: list[dict[str, Any]], condition: dict[str, Any], floor: bool = False) -> str:
    if floor:
        return FLOOR_PROMPT
    context_files = condition["context_files"]
    context_block = ""
    if context_files:
        listing = "\n".join(f"- {path}" for path in context_files)
        context_block = f"\nReference files available to you (paths from the repository root):\n{listing}\n"
    questions_block = "\n".join(f"{q['id']}: {q['question']}" for q in questions)
    return PROMPT_TEMPLATE.format(context_block=context_block, questions_block=questions_block)


def builtin_tools(allowed_tools: list[str]) -> list[str]:
    """Встроенные инструменты из allowed_tools (без MCP и шаблонов в скобках) — для ``--tools``."""
    names = [item.split("(")[0] for item in allowed_tools if not item.startswith(MCP_PREFIX)]
    return list(dict.fromkeys(names))


def build_command(
    condition: dict[str, Any],
    claude_bin: str = CLAUDE_BIN,
    *,
    mcp_config: Path | str | None = None,
    run_root: Path | str | None = None,
) -> list[str]:
    """Командная строка одной сессии. Сам промпт идёт через stdin (длина, кавычки)."""
    output_format = condition["output_format"]
    cmd = [claude_bin, "-p", "--output-format", output_format]
    if output_format == "stream-json":
        cmd.append("--verbose")
    cmd += ["--model", condition["model"], "--no-session-persistence"]
    if condition["allowed_tools"]:
        cmd += ["--tools", ",".join(builtin_tools(condition["allowed_tools"]))]
        cmd += ["--allowedTools", ",".join(condition["allowed_tools"])]
    if condition["disallowed_tools"]:
        cmd += ["--disallowedTools", ",".join(condition["disallowed_tools"])]
    if mcp_config is not None:
        cmd += ["--mcp-config", str(mcp_config)]
    cmd.append("--strict-mcp-config")  # только серверы из --mcp-config; без него — никаких MCP
    if condition["max_budget_usd"] is not None:
        cmd += ["--max-budget-usd", str(condition["max_budget_usd"])]
    if condition["prompt_prefix"]:
        prefix = condition["prompt_prefix"].replace("{run_root}", str(run_root or "."))
        cmd += ["--append-system-prompt", prefix]
    return cmd


def cost_line(repeats: int, condition: dict[str, Any]) -> str:
    total = repeats * int(condition["expected_tokens"])
    return (
        f"Оценка стоимости: {repeats} x {condition['expected_tokens']} = {total} токенов (ориентир из условия, не счёт)"
    )


def budget_line(repeats: int, condition: dict[str, Any]) -> str:
    usd = condition["max_budget_usd"]
    if usd is None:
        return "Потолок бюджета: НЕ ЗАДАН (max_budget_usd нет — расход не ограничен)"
    return f"Потолок бюджета: {repeats} x {usd} = {repeats * usd:g} USD (max_budget_usd на повтор)"


# --- Запуск сессии -------------------------------------------------------------------------------
@dataclass
class SessionResult:
    stdout: str
    returncode: int
    wall_s: float
    stderr: str = ""


type Runner = Callable[[list[str], str, Path], SessionResult]


def subprocess_runner(cmd: list[str], prompt: str, cwd: Path) -> SessionResult:
    """Боевой запуск: ``claude`` с промптом на stdin в каталоге ``cwd``."""
    exe = shutil.which(cmd[0]) or cmd[0]
    started = time.monotonic()
    try:
        proc = subprocess.run(
            [exe, *cmd[1:]],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            timeout=SESSION_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return SessionResult("", -1, time.monotonic() - started, f"timeout {SESSION_TIMEOUT_S}s")
    except OSError as exc:
        return SessionResult("", -1, time.monotonic() - started, f"не удалось запустить {exe}: {exc}")
    return SessionResult(proc.stdout, proc.returncode, time.monotonic() - started, proc.stderr)


def _load_events(stdout: str) -> list[dict[str, Any]]:
    """Весь вывод — один JSON (объект или массив) либо JSONL событий; битые строки пропускаются."""
    try:
        data = json.loads(stdout)
        items = data if isinstance(data, list) else [data]
        return [item for item in items if isinstance(item, dict)]
    except ValueError:
        pass
    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def _sum_usage(usage: Any, keys: tuple[str, ...]) -> int | None:
    if not isinstance(usage, dict):
        return None
    return sum(int(usage.get(key) or 0) for key in keys)


def parse_session_output(stdout: str) -> dict[str, Any]:
    """Достаёт из вывода claude счётчики и финальный текст.

    Имена полей — по документации (событие type=result: subtype, num_turns, duration_ms, result, is_error,
    total_cost_usd, usage{input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens};
    события type=assistant: message.content[] с блоками tool_use, message.usage). НЕ ПРОВЕРЕНО ЖИВЫМ ПРОГОНОМ.

    Метрики токенов (определение — здесь, одно место):
      final_context_tokens — размер контекста на последнем шаге: input + cache_creation + cache_read из usage
                             последнего assistant-события (без output); ``None``, если usage там нет;
      cumulative_tokens    — input + output + cache_creation из usage итогового события (без cache_read);
      cache_read_tokens    — cache_read из usage итогового события.
    """
    events = _load_events(stdout)
    result = next((e for e in reversed(events) if e.get("type") == "result"), None)
    assistant = [e for e in events if e.get("type") == "assistant"]
    blocks = [
        block
        for event in assistant
        for block in ((event.get("message") or {}).get("content") or [])
        if isinstance(block, dict)
    ]
    tool_uses = []
    for block in blocks:
        if block.get("type") == "tool_use":
            args = block.get("input") or {}
            target = args.get("file_path") or args.get("path") or args.get("pattern") or args.get("command")
            tool_uses.append({"name": block.get("name"), "target": target})

    assistant_text = "\n".join(b["text"] for b in blocks if b.get("type") == "text" and isinstance(b.get("text"), str))
    final_text = result["result"] if result is not None and isinstance(result.get("result"), str) else assistant_text

    last_usage = next(
        (
            (e.get("message") or {}).get("usage")
            for e in reversed(assistant)
            if isinstance((e.get("message") or {}).get("usage"), dict)
        ),
        None,
    )
    usage = (result or {}).get("usage")
    duration_ms = (result or {}).get("duration_ms")
    return {
        "turns": (result or {}).get("num_turns"),
        "tool_calls": len(tool_uses) if assistant else None,
        "tool_uses": tool_uses,
        "final_context_tokens": _sum_usage(
            last_usage, ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        ),
        "cumulative_tokens": _sum_usage(usage, ("input_tokens", "output_tokens", "cache_creation_input_tokens")),
        "cache_read_tokens": _sum_usage(usage, ("cache_read_input_tokens",)),
        "duration_s": duration_ms / 1000 if isinstance(duration_ms, (int, float)) else None,
        "cost_usd": (result or {}).get("total_cost_usd"),
        "subtype": (result or {}).get("subtype"),
        "is_error": True if result is None else bool(result.get("is_error")),
        "final_text": final_text,
        "assistant_text": assistant_text,
    }


def _tool_allowed(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(name.casefold(), pattern.split("(")[0].casefold()) for pattern in patterns)


def audit_violations(
    tool_uses: list[dict[str, Any]],
    allowed_tools: list[str],
    context_files: list[str],
    prefixes: tuple[str, ...],
    audit_reads: bool = False,
) -> list[str]:
    """Аудит по списку разрешённого: любой tool_use вне ``allowed_tools`` — нарушение; при ``audit_reads`` и любое
    чтение вне ``context_files``. Имена и пути сравниваются без учёта регистра, пути — в posix-виде."""
    allowed_paths = {score.normalize_path(path).casefold() for path in context_files}
    bad = []
    for use in tool_uses:
        name, target = str(use.get("name") or ""), use.get("target") or ""
        if allowed_tools and not _tool_allowed(name, allowed_tools):
            bad.append(f"{name}:{target}")
        elif audit_reads and name.casefold() == "read":
            if score.normalize_path(target, prefixes).casefold() not in allowed_paths:
                bad.append(f"Read:{target}")
    return bad


# --- Сборка записи прогона -----------------------------------------------------------------------
def _answer_text(parsed: dict[str, Any], question_count: int) -> str:
    """Текст для оценки: ``result``; если в нём ответов меньше, чем вопросов, — текст всех assistant-блоков
    плюс ``result`` последним (при конфликте id побеждает ``result``)."""
    if len(score.parse_answers(parsed["final_text"])) >= question_count:
        return parsed["final_text"]
    return parsed["assistant_text"] + "\n" + parsed["final_text"]


def _repeat_record(
    index: int,
    session: SessionResult,
    questions: list[dict[str, Any]],
    condition: dict[str, Any],
    prefixes: tuple[str, ...],
) -> dict[str, Any]:
    parsed = parse_session_output(session.stdout)
    text = _answer_text(parsed, len(questions))
    scored = score.score_run(questions, text, prefixes)
    turns = parsed["turns"]
    max_turns = condition["max_turns"]
    violations = audit_violations(
        parsed["tool_uses"], condition["allowed_tools"], condition["context_files"], prefixes, condition["audit_reads"]
    )
    error = ""
    if session.returncode != 0 or parsed["is_error"]:
        error = (
            parsed["subtype"] if parsed["subtype"] else (session.stderr.strip()[-500:] or f"код {session.returncode}")
        )
        if parsed["subtype"] is None and session.stderr.strip():
            error = session.stderr.strip()[-500:]
    return {
        "index": index,
        "returncode": session.returncode,
        "subtype": parsed["subtype"],
        "error": error,
        "turns": turns,
        "tool_calls": parsed["tool_calls"],
        "final_context_tokens": parsed["final_context_tokens"],
        "cumulative_tokens": parsed["cumulative_tokens"],
        "cache_read_tokens": parsed["cache_read_tokens"],
        "wall_s": parsed["duration_s"] if parsed["duration_s"] is not None else round(session.wall_s, 1),
        "cost_usd": parsed["cost_usd"],
        "over_max_turns": bool(max_turns and turns is not None and turns > max_turns),
        "violations": violations,
        "tool_uses": parsed["tool_uses"],
        "final_text": text,
        "score": scored,
    }


def summarize_record(record: dict[str, Any]) -> None:
    """Пересчитывает сводку и вердикт по повторам записи (``aggregate`` + ``verdict`` из score)."""
    runs = [
        {
            "hits": rep["score"]["hits"],
            "false": rep["score"]["false"],
            "facts_hit": rep["score"]["facts_hit"] if rep["score"]["facts_scored"] else None,
            "tool_calls": rep["tool_calls"],
            "final_context_tokens": rep["final_context_tokens"],
            "cumulative_tokens": rep["cumulative_tokens"],
            "cache_read_tokens": rep["cache_read_tokens"],
            "wall_s": rep["wall_s"],
        }
        for rep in record["repeats"]
    ]
    record["aggregate"] = score.aggregate(runs)
    baseline = (record.get("baseline") or {}).get("aggregate")
    tainted = any(rep["violations"] for rep in record["repeats"])
    thresholds = record.get("thresholds", record["condition_def"]["thresholds"])
    record["verdict"] = score.verdict(record["aggregate"], thresholds, baseline=baseline, tainted=tainted)


def load_baseline(path: Path | str | None) -> dict[str, Any] | None:
    """Базовая запись для относительных порогов: ``{"path", "aggregate"}`` или ``None``."""
    if not path:
        return None
    return {"path": str(path), "aggregate": load_json(Path(path))["aggregate"]}


def rescore_record(
    record: dict[str, Any], questions: list[dict[str, Any]], baseline_path: Path | None = None
) -> dict[str, Any]:
    """Оценка заново по сохранённому тексту (эталон поправили — повторять сессии не надо)."""
    prefixes = (record["root"],)
    for rep in record["repeats"]:
        rep["score"] = score.score_run(questions, rep["final_text"], prefixes)
    record["questions"] = questions
    if baseline_path:
        record["baseline"] = load_baseline(baseline_path)
    summarize_record(record)
    return record


# --- Вывод ---------------------------------------------------------------------------------------
def _fmt(value: Any) -> str:
    if value is None:
        return "н/д"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def render_markdown(record: dict[str, Any]) -> str:
    agg, ver = record["aggregate"], record["verdict"]
    lines = [
        f"## nav_bench: {record['set']} / {record['condition']} ({record['date']})",
        "",
        f"repo_sha набора `{record['repo_sha']}`, прогон в чистой копии `{record.get('root', 'н/д')}`, "
        f"модель `{record['model']}`",
        "",
        "| # | hits | false | факты | hits (все) | вызовы | контекст | накоп. | cache read | сек | ходы | статус "
        "| заметки |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for rep in record["repeats"]:
        notes = []
        if rep["error"]:
            notes.append(f"ошибка сессии: {rep['error'][:60]}")
        if rep["over_max_turns"]:
            notes.append("ходов больше max_turns")
        if rep["violations"]:
            notes.append(f"нарушений доступа: {len(rep['violations'])}")
        sc = rep["score"]
        lines.append(
            f"| {rep['index']} | {sc['hits']}/{sc['scored']} | {sc['false']} | {sc['facts_hit']}/{sc['facts_scored']} "
            f"| {sc['total_hits']}/{sc['total']} | {_fmt(rep['tool_calls'])} | {_fmt(rep['final_context_tokens'])} "
            f"| {_fmt(rep['cumulative_tokens'])} | {_fmt(rep['cache_read_tokens'])} | {_fmt(rep['wall_s'])} "
            f"| {_fmt(rep['turns'])} | {_fmt(rep['subtype'])} | {'; '.join(notes)} |"
        )
    for stat_name in ("min", "median", "max"):
        lines.append(
            f"| **{stat_name}** | {_fmt(agg['hits'][stat_name])} | {_fmt(agg['false'][stat_name])} "
            f"| {_fmt(agg['facts_hit'][stat_name])} | | {_fmt(agg['tool_calls'][stat_name])} "
            f"| {_fmt(agg['final_context_tokens'][stat_name])} | {_fmt(agg['cumulative_tokens'][stat_name])} "
            f"| {_fmt(agg['cache_read_tokens'][stat_name])} | {_fmt(agg['wall_s'][stat_name])} | | | |"
        )
    lines += ["", f"**Вердикт: {ver['band']}**"]
    if ver["band"] == "TAINTED":
        bad = [v for rep in record["repeats"] for v in rep["violations"]]
        lines.append(f"- нарушения доступа ({len(bad)}), прогон недействителен: " + "; ".join(bad[:5]))
    for name, check in ver["checks"].items():
        mark = {True: "ok", False: "НЕТ", None: "не измерено"}[check["ok"]]
        lines.append(f"- {name}: {_fmt(check['value'])} (порог {_fmt(check['limit'])}) — {mark}")
    lines += ["", "| вопрос | оценивается | " + " | ".join(f"#{rep['index']}" for rep in record["repeats"]) + " |"]
    lines.append("|---|---|" + "---|" * len(record["repeats"]))
    for pos, question in enumerate(record["questions"]):
        cells = []
        for rep in record["repeats"]:
            row = rep["score"]["per_question"][pos]
            cells.append(row["verdict"] + (f" / факты: {row['facts']}" if row["facts"] else ""))
        lines.append(
            f"| {question['id']} | {'да' if question.get('scored', True) else 'нет'} | " + " | ".join(cells) + " |"
        )
    return "\n".join(lines) + "\n"


def render_compare(a: dict[str, Any], b: dict[str, Any]) -> str:
    def row(label: str, getter: Callable[[dict[str, Any]], Any]) -> str:
        return f"| {label} | {_fmt(getter(a))} | {_fmt(getter(b))} |"

    lines = [
        f"| | A: {a['set']} / {a['condition']} | B: {b['set']} / {b['condition']} |",
        "|---|---|---|",
        row("повторов", lambda r: r["aggregate"]["repeats"]),
        row("hits min", lambda r: r["aggregate"]["hits"]["min"]),
        row("hits median", lambda r: r["aggregate"]["hits"]["median"]),
        row("hits max", lambda r: r["aggregate"]["hits"]["max"]),
        row("факты median", lambda r: r["aggregate"]["facts_hit"]["median"]),
        row("false max", lambda r: r["aggregate"]["false"]["max"]),
        row("вызовы median", lambda r: r["aggregate"]["tool_calls"]["median"]),
        row("контекст median", lambda r: r["aggregate"]["final_context_tokens"]["median"]),
        row("накопленные median", lambda r: r["aggregate"]["cumulative_tokens"]["median"]),
        row("сек median", lambda r: r["aggregate"]["wall_s"]["median"]),
        row("вердикт", lambda r: r["verdict"]["band"]),
    ]
    ids = [q["id"] for q in a["questions"]]
    if ids != [q["id"] for q in b["questions"]]:
        lines.append("\nВНИМАНИЕ: наборы вопросов разные, построчное сравнение вопросов пропущено.")
        return "\n".join(lines) + "\n"
    lines += ["", "| вопрос | hit у A | hit у B |", "|---|---|---|"]
    for pos, qid in enumerate(ids):
        counts = []
        for rec in (a, b):
            hits = sum(rep["score"]["per_question"][pos]["verdict"] == "hit" for rep in rec["repeats"])
            counts.append(f"{hits}/{len(rec['repeats'])}")
        lines.append(f"| {qid} | {counts[0]} | {counts[1]} |")
    return "\n".join(lines) + "\n"


# --- Команды -------------------------------------------------------------------------------------
def _unique_path(directory: Path, stem: str) -> Path:
    path = directory / f"{stem}.json"
    number = 2
    while path.exists():
        path = directory / f"{stem}_{number}.json"
        number += 1
    return path


def run_bench(
    questions_path: Path,
    condition_path: Path,
    repeats: int,
    root: Path,
    out_dir: Path | None = None,
    *,
    dry_run: bool = False,
    yes: bool = False,
    no_budget: bool = False,
    floor: bool = False,
    baseline_path: Path | None = None,
    runner: Runner = subprocess_runner,
    copy_fn: Callable[..., Path] = prepare_clean_copy,
    dirty_fn: Callable[[Path, list[str]], list[str]] = git_dirty,
    preflight_fn: Callable[[dict[str, Any], Path], list[str]] = check_requires,
    today: str | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> tuple[int, Path | None]:
    """Код выхода и путь записи. Код 2 — отказ (нет --yes, нет бюджета, нет индекса) или ошибка набора.

    ``root`` — репозиторий-источник (из него ``git archive``); сессия идёт в чистой копии. ``floor`` — один
    тривиальный вопрос теми же флагами: фиксированные накладные расходы.
    """
    out = out or sys.stdout
    err = err or sys.stderr
    root = Path(root)
    try:
        qset = load_questions(questions_path)
        condition = load_condition(condition_path)
        baseline = load_baseline(baseline_path or effective_thresholds(qset, condition).get("baseline"))
    except (OSError, ValueError, KeyError) as exc:
        print(f"ОШИБКА: {exc}", file=err)
        return 2, None
    if repeats < 1:
        print("ОШИБКА: --repeats должно быть >= 1", file=err)
        return 2, None
    if int(condition["expected_tokens"]) <= 0:
        print(f"ОШИБКА: у условия {condition['name']} expected_tokens должно быть > 0 (оценка стоимости).", file=err)
        return 2, None
    if floor:
        qset = {**qset, "name": f"floor-{qset['name']}", "questions": [FLOOR_QUESTION], "thresholds": FLOOR_THRESHOLDS}

    print(cost_line(repeats, condition), file=out)
    print(budget_line(repeats, condition), file=out)
    dirty = dirty_fn(root, expected_paths(qset))
    if dirty:
        print(
            "!!! ВНИМАНИЕ: эталонные файлы изменены в рабочем дереве (git status): "
            + "; ".join(dirty[:5])
            + ". Прогон идёт в копии repo_sha, но проверьте эталон: `bench.py verify-set` !!!",
            file=err,
        )

    prompt = build_prompt(qset["questions"], condition, floor)
    if dry_run:
        run_root = clean_copy_path(qset, condition)
        mcp = mcp_config_dest(run_root, condition) if condition["mcp_config"] else None
        cmd = build_command(condition, mcp_config=mcp, run_root=run_root)
        state = "уже есть" if run_root.exists() else "будет создана при реальном запуске"
        print(
            f"[dry-run] чистая копия {qset['repo_sha']} (без: {', '.join(qset['exclude']) or '-'}): "
            f"{run_root} ({state})",
            file=out,
        )
        print(f"[dry-run] промпт ({len(prompt)} симв.) идёт через stdin", file=out)
        for problem in preflight_fn(condition, run_root):
            print(f"[dry-run] предпроверка не пройдена: {problem}", file=out)
        for index in range(1, repeats + 1):
            print(f"[dry-run] повтор {index}: {shlex.join(cmd)}", file=out)
        print("[dry-run] промпт:\n" + prompt, file=out)
        return 0, None
    if condition["max_budget_usd"] is None and not no_budget:
        print(
            "ОТКАЗ: у условия нет max_budget_usd (потолка расхода); задайте его или повторите с --no-budget.", file=err
        )
        return 2, None
    if not yes:
        print("ОТКАЗ: реальный запуск стоит токенов; повторите с --yes (или проверьте командой --dry-run).", file=err)
        return 2, None

    try:
        run_root = Path(copy_fn(qset, condition, root, err=err))
    except (OSError, RuntimeError) as exc:
        print(f"ОШИБКА чистой копии: {exc}", file=err)
        return 2, None
    problems = preflight_fn(condition, run_root)
    if problems:
        for problem in problems:
            print(f"ОТКАЗ: {problem}", file=err)
        return 2, None
    mcp = render_mcp_config(condition, root, run_root)
    cmd = build_command(condition, mcp_config=mcp, run_root=run_root)

    prefixes = (str(run_root.resolve()),)
    repeat_records = []
    for index in range(1, repeats + 1):
        print(f"повтор {index}/{repeats}...", file=err)
        session = runner(cmd, prompt, run_root)
        rep = _repeat_record(index, session, qset["questions"], condition, prefixes)
        if rep["error"]:
            print(f"повтор {index}: сессия с ошибкой (код {rep['returncode']}): {rep['error']}", file=err)
        repeat_records.append(rep)

    date = today or datetime.date.today().isoformat()
    record: dict[str, Any] = {
        "set": qset["name"],
        "repo_sha": qset["repo_sha"],
        "source_root": str(root),
        "root": prefixes[0],
        "date": date,
        "condition": condition["name"],
        "model": condition["model"],
        "condition_def": condition,
        "thresholds": effective_thresholds(qset, condition),
        "baseline": baseline,
        "command": cmd,
        "questions": qset["questions"],
        "repeats": repeat_records,
    }
    summarize_record(record)
    directory = Path(out_dir) if out_dir else root / "data" / "nav_bench"
    directory.mkdir(parents=True, exist_ok=True)
    path = _unique_path(directory, f"{date}_{qset['name']}_{condition['name']}")
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = render_markdown(record)
    path.with_suffix(".md").write_text(markdown, encoding="utf-8")
    print(markdown, file=out)
    print(f"записано: {path}", file=out)
    return 0, path


def score_command(
    run_path: Path, questions_path: Path | None, out: TextIO | None = None, baseline_path: Path | None = None
) -> int:
    out = out or sys.stdout
    record = load_json(run_path)
    questions = load_questions(questions_path)["questions"] if questions_path else record["questions"]
    print(render_markdown(rescore_record(record, questions, baseline_path)), file=out)
    return 0


def compare_command(path_a: Path, path_b: Path, out: TextIO | None = None) -> int:
    print(render_compare(load_json(path_a), load_json(path_b)), file=out or sys.stdout)
    return 0


def verify_set_command(
    questions_path: Path,
    root: Path,
    out: TextIO | None = None,
    show_fn: Callable[[Path, str, str], str | None] = git_show,
) -> int:
    out = out or sys.stdout
    qset = load_questions(questions_path)
    problems, checked = verify_set(qset, root, show_fn)
    for problem in problems:
        print(f"ПРОБЛЕМА: {problem}", file=out)
    print(
        f"verify-set {qset['name']} @ {qset['repo_sha']}: проверено записей {checked}, проблем {len(problems)}",
        file=out,
    )
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        prog="bench.py", description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    for name, helptext in (
        ("run", "прогнать условие по набору вопросов"),
        ("floor", "один тривиальный вопрос: накладные расходы"),
    ):
        run = sub.add_parser(name, help=helptext)
        run.add_argument("--questions", required=True, type=Path)
        run.add_argument("--condition", required=True, type=Path)
        run.add_argument("--repeats", type=int, default=3 if name == "run" else 1)
        run.add_argument("--dry-run", action="store_true", help="напечатать команды и оценку, ничего не запускать")
        run.add_argument("--yes", action="store_true", help="подтвердить расход токенов на реальный запуск")
        run.add_argument("--no-budget", action="store_true", help="разрешить запуск без max_budget_usd")
        run.add_argument(
            "--baseline", type=Path, default=None, help="запись базового прогона для относительных порогов"
        )
        run.add_argument("--out", type=Path, default=None, help="каталог записи (по умолчанию <root>/data/nav_bench)")
        run.add_argument("--root", type=Path, default=Path("."), help="репозиторий-источник для git archive")

    rescore = sub.add_parser("score", help="пересчитать оценку записи прогона")
    rescore.add_argument("--run", required=True, type=Path)
    rescore.add_argument("--questions", type=Path, default=None, help="другой набор (по умолчанию тот, что в записи)")
    rescore.add_argument("--baseline", type=Path, default=None)

    compare = sub.add_parser("compare", help="две записи рядом")
    compare.add_argument("run_a", type=Path)
    compare.add_argument("run_b", type=Path)

    verify = sub.add_parser("verify-set", help="сверить эталон набора с кодом на repo_sha (git show)")
    verify.add_argument("--questions", required=True, type=Path)
    verify.add_argument("--root", type=Path, default=Path("."))

    args = parser.parse_args(argv)
    if args.command in ("run", "floor"):
        code, _ = run_bench(
            args.questions,
            args.condition,
            args.repeats,
            args.root,
            args.out,
            dry_run=args.dry_run,
            yes=args.yes,
            no_budget=args.no_budget,
            floor=args.command == "floor",
            baseline_path=args.baseline,
        )
        return code
    if args.command == "score":
        return score_command(args.run, args.questions, baseline_path=args.baseline)
    if args.command == "verify-set":
        return verify_set_command(args.questions, args.root)
    return compare_command(args.run_a, args.run_b)


if __name__ == "__main__":
    sys.exit(main())
