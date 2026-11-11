"""nav_bench — как быстро ИИ-агент находит нужное ``файл:строка`` и понимает архитектуру при заданном условии.

    python scripts/nav_bench/bench.py run --questions Q.json --condition C.json --repeats 3 [--dry-run] [--yes]
    python scripts/nav_bench/bench.py floor --questions Q.json --condition C.json [--dry-run] [--yes]
    python scripts/nav_bench/bench.py score --run data/nav_bench/<файл>.json [--baseline B.json]
    python scripts/nav_bench/bench.py compare A.json B.json
    python scripts/nav_bench/bench.py verify-set --questions Q.json
    python scripts/nav_bench/bench.py ceiling --questions Q.json --reference R.json [--min N]
    python scripts/nav_bench/bench.py ceiling --questions Q.json --text T.json [--root R] [--min N]

Один повтор = одна headless-сессия ``claude -p``, которая отвечает на ВСЕ вопросы набора. Сессия идёт в ЧИСТОЙ КОПИИ
репозитория без путей ``exclude`` набора, чтобы эталон не лежал рядом с кодом: ``git archive <repo_sha>`` (набор
``"copy": "archive"``, по умолчанию, без .git) либо клон с историей git до ``repo_sha`` (``"copy": "clone"``).
Реальный запуск стоит денег: без ``--yes`` он не стартует; без ``max_budget_usd`` — только с ``--no-budget``.
``--dry-run`` ничего не запускает. Подробности и формат наборов — README.md рядом.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import fnmatch
import functools
import hashlib
import json
import os
import posixpath
import re
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
COPY_MODES = ("archive", "clone")  # поле набора copy: git archive без .git либо клон с историей до repo_sha
PLACEHOLDERS = ("repo_root", "repo_sha", "run_root")  # подстановки в bash_allow и prompt_prefix

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
    "bash_allow": [],  # шаблоны Bash ("git log *"): Bash только по ним (+ аудит); {repo_root} {repo_sha} {run_root}
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
def _copy_mode(qset: dict[str, Any]) -> Any:
    return qset.get("copy", "archive")


def clean_copy_path(qset: dict[str, Any], condition: dict[str, Any], temp_base: Path | None = None) -> Path:
    """``%TEMP%/nav_bench/<sha>-<hash>``; hash = exclude набора + имя условия + context_files условия (иначе копия
    от условия с картой осталась бы видна условию без карты, а граф graphify, собранный внутри копии, — условиям
    grep-read и qex)."""
    fields = {
        "exclude": sorted(qset["exclude"]),
        "condition": condition["name"],
        "context": sorted(condition["context_files"]),
    }
    if _copy_mode(qset) != "archive":  # ключ archive-копий не меняется: готовые копии остаются годными
        fields["copy"] = _copy_mode(qset)
    key = json.dumps(fields)
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


def _git_raw(cwd: Path, *args: str, stdin: bytes | None = None) -> bytes:
    done = subprocess.run(["git", "-C", str(cwd), *args], input=stdin, capture_output=True)
    if done.returncode != 0:
        stderr = done.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {' '.join(args[:2])} не удался: {stderr}")
    return done.stdout


def _clone_with_history(repo_root: Path, sha: str, dest: Path, exclude: list[str]) -> None:
    """Клон ``repo_root`` в пустой ``dest``: дерево и история до ``sha``, больше ничего.

    ``clone --shared`` -> ``checkout --detach sha`` -> все ссылки и reflog удалены (иначе ``git log --all`` дал бы
    эталон) -> ``repack -a -d`` без ``-l`` забирает объекты из источника, после чего ``alternates`` убирается (иначе
    ``Read`` источника достаёт любой файл) -> пути ``exclude`` помечены ``skip-worktree`` (иначе ``git status``
    назвал бы удалённое; в индексе есть файлы, не каталоги). Сами пути удаляет вызывающий.
    """
    done = subprocess.run(["git", "clone", "-q", "--shared", str(repo_root), str(dest)], capture_output=True)
    if done.returncode != 0:
        raise RuntimeError(f"git clone не удался: {done.stderr.decode('utf-8', errors='replace').strip()}")
    _git_raw(dest, "checkout", "-q", "--detach", sha)
    _git_raw(dest, "remote", "remove", "origin")
    refs = _git_raw(dest, "for-each-ref", "--format=%(refname)").decode("utf-8").split()
    if refs:
        _git_raw(dest, "update-ref", "--stdin", stdin="".join(f"delete {ref}\n" for ref in refs).encode("utf-8"))
    _git_raw(dest, "reflog", "expire", "--expire=now", "--all")
    _git_raw(dest, "repack", "-a", "-d", "-q")
    (dest / ".git" / "objects" / "info" / "alternates").unlink(missing_ok=True)
    if exclude:
        tracked = _git_raw(dest, "--literal-pathspecs", "ls-files", "-z", "--", *exclude)
        if tracked:
            _git_raw(dest, "update-index", "--skip-worktree", "-z", "--stdin", stdin=tracked)


def prepare_clean_copy(
    qset: dict[str, Any],
    condition: dict[str, Any],
    repo_root: Path,
    temp_base: Path | None = None,
    err: TextIO | None = None,
) -> Path:
    """Копия на ``repo_sha`` без ``exclude`` + ``context_files`` условия. Набор ``copy``: ``archive`` (умолчание) —
    ``git archive``, в копии нет .git; ``clone`` — клон с историей до ``repo_sha`` (``_clone_with_history``).

    Каталог собирается во временном соседе и переименовывается: недоделанная копия не переиспользуется.
    Уже существующая копия с тем же sha+hash берётся как есть.
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
        if _copy_mode(qset) == "clone":
            _clone_with_history(repo_root, qset["repo_sha"], tmp, qset["exclude"])
        else:
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


# --- verify-set: предупреждения о слабых местах эталона ------------------------------------------------
NOTE_TOLERANCE_RE = re.compile(r"tolerance (\d+)|(\d+)-line tolerance", re.IGNORECASE)
NOTE_ANCHOR_RE = re.compile(r"anchor line (\d+)", re.IGNORECASE)
FILE_QUESTION_RE = re.compile(r"(?i)\b(which|what)\b[^?]{0,40}\bfiles?\b")


def _distinct(values: list[int]) -> list[int]:
    """Значения без повторов, в порядке появления."""
    return list(dict.fromkeys(values))


def _enclosing_function(tree: ast.AST, line: int) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Самая вложенная функция, где ``lineno < line <= end_lineno`` (строка def сама функцию не охватывает)."""
    found = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.lineno < line <= (node.end_lineno or 0):
            if found is None or node.lineno > found.lineno:
                found = node
    return found


def verify_set_warnings(
    qset: dict[str, Any], root: Path, show_fn: Callable[[Path, str, str], str | None] = git_show
) -> list[str]:
    """Предупреждения о слабых местах эталона; на код возврата ``verify-set`` не влияют.

    а) число в ``note`` («tolerance N», «N-line tolerance», «anchor line N») не совпадает с записями вопроса;
    б) оцениваемый вопрос про файл («which/what … file»), а эталон требует строку;
    в) путь из ``exclude`` с тем же текстом на ``repo_sha``, что у ожидаемого пути (двойник);
    г) окно ``line ± tolerance`` выходит за объемлющую функцию (``.py``).
    Допуск, которого в записи нет, — ``score.TOLERANCE_LINES``. Нет файла на ``repo_sha`` — запись пропускается.
    """
    warnings: list[str] = []
    cache: dict[str, str | None] = {}
    trees: dict[str, ast.AST | None] = {}

    def text_of(path: str) -> str | None:
        if path not in cache:
            cache[path] = show_fn(root, qset["repo_sha"], path)
        return cache[path]

    def tree_of(path: str) -> ast.AST | None:
        if path not in trees:
            text = text_of(path)
            try:
                trees[path] = None if text is None else ast.parse(text)
            except (SyntaxError, ValueError):
                trees[path] = None
        return trees[path]

    for question in qset["questions"]:
        qid = question["id"]
        items = question.get("expected") or []
        tols = [int(item.get("tolerance", score.TOLERANCE_LINES)) for item in items]
        lines = [item["line"] for item in items if item.get("line") is not None]

        note = str(question.get("note") or "")
        found = NOTE_TOLERANCE_RE.search(note)
        if found:
            number = int(found.group(1) or found.group(2))
            if number not in tols:
                shown = ", ".join(map(str, _distinct(tols)))
                warnings.append(f"{qid}: note: tolerance {number}, в записи tolerance {shown}")
        found = NOTE_ANCHOR_RE.search(note)
        if found:
            number = int(found.group(1))
            if number not in lines:
                shown = ", ".join(map(str, _distinct(lines))) or "null"
                warnings.append(f"{qid}: note: anchor line {number}, в записи line {shown}")

        if question.get("scored", True) and FILE_QUESTION_RE.search(str(question.get("question") or "")):
            with_line = next((item for item in items if item.get("line") is not None), None)
            if with_line is not None:
                warnings.append(
                    f"{qid}: вопрос о файле, эталон требует строку: {with_line['path']}:{with_line['line']}"
                )

        for twin in qset.get("exclude") or []:
            twin_text = text_of(twin)
            if twin_text is None:
                continue
            same = next((p for p in dict.fromkeys(i["path"] for i in items) if text_of(p) == twin_text), None)
            if same is not None:
                warnings.append(f"{qid}: двойник {twin} исключён, текст равен {same}")

        for item, tol in zip(items, tols, strict=True):
            line, path = item.get("line"), item["path"]
            if line is None or not path.endswith(".py"):
                continue
            tree = tree_of(path)
            func = None if tree is None else _enclosing_function(tree, int(line))
            if func is not None and (line - tol < func.lineno or line + tol > func.end_lineno):
                warnings.append(
                    f"{qid}: окно {path}:{line} ±{tol} выходит за {func.name} ({func.lineno}-{func.end_lineno})"
                )
    return warnings


# --- ceiling: потолок набора по справочнику адресов ------------------------------------------------------
_ADDR_LINE_RE = re.compile(r"^[\w./-]+\.\w+:\d+$")
_ADDR_PY_RE = re.compile(r"^[\w./-]+\.py(::.*)?$")


def reference_addresses(obj: Any, path: str | None = None) -> set[tuple[str, int | None]]:
    """Адреса ``(путь, строка | None)`` из произвольного JSON эталона (3.1 или ``atlas ref --format json``).

    Словарь со строковым ``path`` задаёт путь потомкам. ``path`` + целый ``line`` — адрес со строкой; ``path`` без
    ключа ``line`` и без ``path_expr`` — адрес без строки. Строки ``путь:строка`` и ``путь.py[::имя]`` — тоже адреса.
    """
    found: set[tuple[str, int | None]] = set()
    if isinstance(obj, str):
        if _ADDR_LINE_RE.match(obj):
            file, _, number = obj.rpartition(":")
            found.add((file, int(number)))
        elif _ADDR_PY_RE.match(obj):
            found.add((obj.split("::", 1)[0], None))
    elif isinstance(obj, list):
        for child in obj:
            found |= reference_addresses(child, path)
    elif isinstance(obj, dict):
        own = obj.get("path") if isinstance(obj.get("path"), str) else None
        path = own or path
        line = obj.get("line")
        if path is not None and isinstance(line, int) and not isinstance(line, bool):
            found.add((path, line))
        elif own is not None and "line" not in obj and "path_expr" not in obj:
            found.add((own, None))
        for key, child in obj.items():
            if key != "path":  # сам путь — не отдельный адрес без строки
                found |= reference_addresses(child, path)
    return found


def _reachable(item: dict[str, Any], addrs: set[tuple[str, int | None]]) -> bool:
    want = score.normalize_path(str(item["path"]))
    return any(
        file == want and score.location_matches(file if line is None else f"{file}:{line}", item)
        for file, line in addrs
    )


def ceiling(qset: dict[str, Any], addrs: set[tuple[str, int | None]]) -> tuple[list[str], int, int]:
    """Какие оцениваемые вопросы набора достижимы по адресам: (строки отчёта, достижимо, оцениваемых).

    Вопрос достижим, если по ``require`` (``all`` / ``any``) каждая / хоть одна ожидаемая запись есть среди адресов
    (то же сравнение, что при оценке: путь и окно ``line ± tolerance``). Вопросы без ``expected`` не считаются.
    """
    report: list[str] = []
    reached = total = 0
    for question in qset["questions"]:
        items = question.get("expected") or []
        if not question.get("scored", True) or not items:
            continue
        total += 1
        flags = [_reachable(item, addrs) for item in items]
        ok = all(flags) if question.get("require", "any") == "all" else any(flags)
        reached += ok
        report.append(f"{question['id']} reachable={'yes' if ok else 'no'}")
        if not ok:
            for item, flag in zip(items, flags, strict=True):
                if flag:
                    continue
                if item.get("line") is None:
                    report.append(f"  {item['path']} -> нет в эталоне")
                else:
                    tol = int(item.get("tolerance", score.TOLERANCE_LINES))
                    report.append(f"  {item['path']}:{item['line']} ±{tol} -> нет в эталоне")
    return report, reached, total


# --- ceiling --text: потолок набора по тексту паспортов atlas (Task 3.3) -----------------------------------
ATLAS_TIMEOUT_S = 600
TARGET_VERBS = ("ref", "map")
# опции, которыми цель могла бы сменить ревизию, корень, срез или размер паспорта; бенч ставит их сам
TARGET_FORBIDDEN_OPTIONS = ("--format", "--ref", "--root", "--exclude", "--budget", "--all", "--full")

type AtlasRunner = Callable[[list[str], Path], tuple[int, str, str]]

_HEAD_RE = re.compile(r"^== .+ ==$")  # первая строка паспорта: `== <id> ==`, `== unit <id> ==`
_ENVELOPE_RE = re.compile(r"^(?P<path>[^;]+?)(?::\d+)?; sha ")  # вторая строка: `<path>[:<line>]; sha …`
_TEXT_ADDR_RE = re.compile(r"(?<![\w./-])([\w./-]+\.\w+):(\d+)")  # `_ADDR_LINE_RE`, поиском, с границей слева
_TEXT_FILE_RE = re.compile(r"(?<![\w./-])([\w./-]+\.py)(?![\w./-]|:[\w:])")  # токен целиком, без `:N` и `::имя`
_MEMBER_LINE_RE = re.compile(r"  :(\d+)$")  # конец строки члена: `  :17`


def _forbidden_option(arg: str) -> bool:
    """Опция из ``TARGET_FORBIDDEN_OPTIONS``: целиком, ``--x=…`` или сокращением (argparse принимает ``--bud``)."""
    if not arg.startswith("--"):
        return False
    name = arg.split("=", 1)[0]
    return any(option.startswith(name) for option in TARGET_FORBIDDEN_OPTIONS)


def load_targets(path: Path, qset: dict[str, Any]) -> dict[str, list[list[str]]]:
    """Цели ``{"set": <имя набора>, "targets": {<qid>: [[<argv atlas>], ...]}}``; вопрос без целей отсутствует в ответе.

    ``ValueError``: ``set`` не равен ``name`` набора; qid не из набора; argv пуст или не из строк; ``argv[0]`` не
    ``ref``/``map``; в argv опция из ``TARGET_FORBIDDEN_OPTIONS``; id в argv вопроса больше записей его ``expected``.
    """
    data = load_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("targets"), dict):
        raise ValueError(f"{path}: нужен объект с полями set и targets (объект)")
    if data.get("set") != qset["name"]:
        raise ValueError(f"{path}: set {data.get('set')!r} не равен имени набора {qset['name']!r}")
    by_id = {question["id"]: question for question in qset["questions"]}
    found: dict[str, list[list[str]]] = {}
    for qid, argvs in data["targets"].items():
        if qid not in by_id:
            raise ValueError(f"{path}: вопроса {qid!r} нет в наборе {qset['name']!r}")
        if not isinstance(argvs, list):
            raise ValueError(f"{path}: {qid}: цели — список argv")
        ids = 0
        for argv in argvs:
            if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) for arg in argv):
                raise ValueError(f"{path}: {qid}: argv — непустой список строк: {argv!r}")
            if argv[0] not in TARGET_VERBS:
                raise ValueError(f"{path}: {qid}: argv[0] — одно из {TARGET_VERBS}: {argv!r}")
            bad = next((arg for arg in argv[1:] if _forbidden_option(arg)), None)
            if bad is not None:
                raise ValueError(f"{path}: {qid}: опцию {bad!r} ставит бенч, в цели её нет")
            ids += len(argv) - 1
        limit = len(by_id[qid].get("expected") or [])
        if ids > limit:
            raise ValueError(f"{path}: {qid}: id целей {ids} больше записей expected {limit}")
        if argvs:
            found[qid] = [list(argv) for argv in argvs]
    return found


def _run_atlas(cmd: list[str], cwd: Path) -> tuple[int, str, str]:
    """Один запуск atlas путём (без PYTHONPATH: кодовый корень atlas находит сам).

    Протокол раннера: ``(код, stdout, stderr)``; таймаут — ``subprocess.TimeoutExpired`` (его превращает в ошибку
    ``atlas_texts``): молча заниженный потолок читался бы как «потолок ниже --min».
    """
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["PYTHONUTF8"] = "1"
    done = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=ATLAS_TIMEOUT_S,
    )
    return done.returncode, done.stdout, done.stderr


def atlas_texts(
    qset: dict[str, Any], targets: dict[str, list[list[str]]], root: Path, runner: AtlasRunner | None = None
) -> dict[str, tuple[str, list[str]]]:
    """Текст паспортов целей каждого вопроса: ``{qid: (текст, проблемы)}``; вопроса без целей в ответе нет.

    Паспорта строятся в клоне ``root`` на ``repo_sha`` набора (временный каталог ``nav_bench_text_*``, удаляется
    всегда): кэш atlas ложится в клон, не в ``root``. Код atlas — текущего дерева. Код atlas не 0 — проблема
    ``  atlas <argv>: код N: <последняя строка stderr>``, stdout всё равно разбирается (atlas печатает паспорта
    остальных id). Нет ``repo_sha`` в ``root``, сбой git при клоне, таймаут atlas (``subprocess.TimeoutExpired`` от
    раннера) — ``RuntimeError``.
    """
    runner = runner or _run_atlas
    texts: dict[str, tuple[str, list[str]]] = {}
    if not targets:
        return texts
    sha = qset["repo_sha"]
    known = subprocess.run(["git", "-C", str(root), "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True)
    if known.returncode != 0:
        raise RuntimeError(f"repo_sha {sha} набора нет в репозитории {root}")
    atlas = PKG_DIR.parent / "atlas"
    clone = Path(tempfile.mkdtemp(prefix="nav_bench_text_"))
    try:
        done = subprocess.run(
            ["git", "clone", "-q", "--shared", "--no-checkout", str(root), str(clone)], capture_output=True
        )
        if done.returncode != 0:
            raise RuntimeError(f"git clone не удался: {done.stderr.decode('utf-8', errors='replace').strip()}")
        _git_raw(clone, "checkout", "-q", "--detach", sha)
        for qid, argvs in targets.items():
            parts: list[str] = []
            problems: list[str] = []
            for argv in argvs:
                cmd = [sys.executable, str(atlas), *argv, "--format", "passport", "--ref", sha, "--root", str(clone)]
                for prefix in qset.get("exclude") or []:
                    cmd += ["--exclude", prefix]
                try:
                    code, stdout, stderr = runner(cmd, clone)
                except subprocess.TimeoutExpired:
                    raise RuntimeError(f"atlas {' '.join(argv)}: таймаут {ATLAS_TIMEOUT_S} с") from None
                parts.append(stdout)
                if code != 0:
                    last = stderr.strip().splitlines()[-1] if stderr.strip() else ""
                    problems.append(f"  atlas {' '.join(argv)}: код {code}: {last}".rstrip())
            texts[qid] = ("\n\n".join(parts), problems)
    finally:
        _rmtree_force(clone)
    return texts


def text_blocks(text: str) -> list[tuple[str, set[tuple[str, int | None]]]]:
    """Блоки текста паспортов: ``(id, адреса)`` на каждую строку ``== … ==``, в порядке текста.

    id — строка заголовка без ``== `` и `` ==`` как есть (``unit u``, ``file p``, ``путь::qualname``, id ошибки).
    Адреса блока — по правилам ``text_addresses`` (а–г); строки до первого заголовка и после строки без конверта
    (``not found``, ``ambiguous``) до следующего заголовка адресов не дают.
    """
    blocks: list[tuple[str, set[tuple[str, int | None]]]] = []
    found: set[tuple[str, int | None]] | None = None  # адреса открытого блока; None — блок не открыт или закрыт
    path: str | None = None
    expect_envelope = False
    for line in text.splitlines():
        if _HEAD_RE.match(line):
            found = set()
            blocks.append((line[3:-3], found))
            path, expect_envelope = None, True
            continue
        if found is None:
            continue
        if expect_envelope:
            expect_envelope = False
            envelope = _ENVELOPE_RE.match(line)
            if envelope is None:
                found = None
                continue
            candidate = envelope.group("path")
            path = candidate if candidate.endswith(".py") else None
        found.update((file, int(number)) for file, number in _TEXT_ADDR_RE.findall(line))
        found.update((file, None) for file in _TEXT_FILE_RE.findall(line))
        member = _MEMBER_LINE_RE.search(line)
        if member is not None and path is not None:
            found.add((path, int(member.group(1))))
    return blocks


def text_addresses(text: str) -> set[tuple[str, int | None]]:
    """Адреса ``(путь, строка | None)`` из текста паспортов atlas; других правил нет.

    а) ``== … ==`` открывает паспорт; следующая строка ``<path>[:<line>]; sha …`` задаёт его путь, если тот кончается
       на ``.py``, иначе пути нет; блок без такой строки (``not found``, ``ambiguous``) адресов не даёт;
    б) токен ``путь:строка`` — как ``_ADDR_LINE_RE``, поиском, с границей слева;
    в) токен целиком ``путь.py`` (без ``:N`` и ``::имя``) — ``(путь, None)``;
    г) конец строки ``  :N`` (член класса или файла) — ``(путь паспорта, N)``.

    Объединение адресов всех блоков ``text_blocks``.
    """
    return set().union(*(addrs for _, addrs in text_blocks(text)))


def _strict_key(item: dict[str, Any]) -> str | None:
    """Id блока, который должен найти запись: ``путь::symbol``; записи без ``symbol`` (непустая строка) — ``None``."""
    symbol = item.get("symbol")
    if not isinstance(symbol, str) or not symbol:
        return None
    return f"{score.normalize_path(str(item['path']))}::{symbol}"


def ceiling_text_both(
    qset: dict[str, Any], texts: dict[str, tuple[str, list[str]]]
) -> tuple[list[str], int, int | None, int]:
    """Как ``ceiling``, но адреса вопроса — только из текста ЕГО целей (``texts[qid]``): общего пула нет.

    Возвращает (строки отчёта, K по окну, K' строгое | ``None``, N). Вопрос без записи в ``texts`` — «нет целей»,
    недостижим. Строгое чтение (Task 3.4): запись с ``symbol`` (непустая строка) строго найдена, только если в блоках
    текста ЕЁ вопроса есть блок с id ``путь::symbol`` и адрес этого блока попал в окно записи; запись без ``symbol`` —
    как по окну. K' — число вопросов, достижимых по строгим флагам (``require`` тот же); ``None``, если ни у одной
    записи оцениваемых вопросов нет ``symbol``.

    Строки отчёта: ``<qid> reachable=yes|no`` (при ok и не строгом ok — ``reachable=yes (строго no)``); на каждую
    запись ``expected`` ``  <путь>[:<строка> ±<допуск>] -> найден|найден вне блока записи|нет в тексте``; проблемы
    atlas; ``  нет целей``.
    """
    report: list[str] = []
    reached = strict_reached = total = 0
    any_symbol = False
    for question in qset["questions"]:
        items = question.get("expected") or []
        if not question.get("scored", True) or not items:
            continue
        total += 1
        qid = question["id"]
        text, problems = texts.get(qid, ("", []))
        blocks = text_blocks(text)
        addrs = set().union(*(block_addrs for _, block_addrs in blocks))
        flags = [_reachable(item, addrs) for item in items]
        strict_flags = []
        for item, flag in zip(items, flags, strict=True):
            key = _strict_key(item)
            any_symbol |= key is not None
            strict_flags.append(
                flag if key is None else flag and any(bid == key and _reachable(item, ba) for bid, ba in blocks)
            )
        all_required = question.get("require", "any") == "all"
        ok = all(flags) if all_required else any(flags)
        strict_ok = all(strict_flags) if all_required else any(strict_flags)
        reached += ok
        strict_reached += strict_ok
        report.append(f"{qid} reachable={'yes' if ok else 'no'}{' (строго no)' if ok and not strict_ok else ''}")
        for item, flag, strict_flag in zip(items, flags, strict_flags, strict=True):
            if item.get("line") is None:
                where = str(item["path"])
            else:
                where = f"{item['path']}:{item['line']} ±{int(item.get('tolerance', score.TOLERANCE_LINES))}"
            verdict = ("найден" if strict_flag else "найден вне блока записи") if flag else "нет в тексте"
            report.append(f"  {where} -> {verdict}")
        report.extend(problems)
        if qid not in texts:
            report.append("  нет целей")
    return report, reached, strict_reached if any_symbol else None, total


def ceiling_text(qset: dict[str, Any], texts: dict[str, tuple[str, list[str]]]) -> tuple[list[str], int, int]:
    """``ceiling_text_both`` без строгого числа: ``(строки отчёта, K по окну, N)``."""
    report, reached, _, total = ceiling_text_both(qset, texts)
    return report, reached, total


def _require_committed(root: Path, paths: list[Path]) -> None:
    """Файлы лежат в ``root``, отслеживаются git и чисты (запись 11 п. 1): иначе ``ValueError``."""
    base = Path(root).resolve()
    rels: list[str] = []
    for path in paths:
        try:
            rels.append(Path(path).resolve().relative_to(base).as_posix())
        except ValueError:
            raise ValueError(f"{path}: вне репозитория {root}") from None
    for rel in rels:
        known = subprocess.run(["git", "-C", str(base), "ls-files", "--error-unmatch", "--", rel], capture_output=True)
        if known.returncode != 0:
            raise ValueError(f"{rel}: не в git — заморозь набор и цели коммитом")
    dirty = git_dirty(base, rels)
    if dirty:
        raise ValueError(f"есть незакоммиченные правки ({'; '.join(dirty)}) — заморозь набор и цели коммитом")


def ceiling_text_command(
    questions_path: Path,
    targets_path: Path,
    root: Path,
    minimum: int | None = None,
    out: TextIO | None = None,
    runner: AtlasRunner | None = None,
    code_root: Path | None = None,
) -> int:
    """Код: 0; с ``minimum`` при достижимых по окну (K, не строгое K') меньше него — 1; ошибка ввода, git, таймаут
    atlas, Q/T или код atlas не в коммите — 2.

    Итог ``ceiling-text <набор>: K/N``; при строгом числе K' (есть запись с ``symbol``) — ``… (строго K'/N)``.

    Первая строка вывода — ``atlas-код: <HEAD дерева с кодом atlas>`` (``code_root``, по умолчанию корень репозитория
    этого ``bench.py``; `` +правки``, если ``scripts/atlas`` с незакоммиченными правками). С ``minimum`` набор, цели
    (в ``root``) и ``scripts/atlas`` должны быть в git и чистыми: потолок по правленным на лету целям или коду ничего
    не доказывает.
    """
    out = out or sys.stdout
    code_root = Path(code_root) if code_root is not None else PKG_DIR.parents[1]
    try:
        qset = load_questions(questions_path)
        targets = load_targets(targets_path, qset)
        if minimum is not None:
            _require_committed(root, [questions_path, targets_path])
        code_sha = _git_raw(code_root, "rev-parse", "HEAD").decode("utf-8").strip()
        code_dirty = bool(git_dirty(code_root, ["scripts/atlas"]))
        if minimum is not None and code_dirty:
            raise ValueError("scripts/atlas с незакоммиченными правками — заморозь код atlas коммитом")
        texts = atlas_texts(qset, targets, root, runner)
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 2
    report, reached, strict, total = ceiling_text_both(qset, texts)
    print(f"atlas-код: {code_sha}{' +правки' if code_dirty else ''}", file=out)
    for row in report:
        print(row, file=out)
    suffix = "" if strict is None else f" (строго {strict}/{total})"
    print(f"ceiling-text {qset['name']}: {reached}/{total}{suffix}", file=out)
    return 1 if minimum is not None and reached < minimum else 0


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


def check_history_copy(condition: dict[str, Any], run_root: Path, repo_sha: str) -> list[str]:
    """Условие с ``bash_allow`` идёт только в копии с историей: ``git rev-parse HEAD`` копии начинается с ``repo_sha``
    (sha набора бывает коротким). Копия без ``.git`` (``copy: archive``) или на другом коммите — проблема."""
    if not condition["bash_allow"]:
        return []
    head = ""
    if repo_sha and (Path(run_root) / ".git").exists():
        done = subprocess.run(
            ["git", "-C", str(run_root), "rev-parse", "HEAD"], capture_output=True, text=True, encoding="utf-8"
        )
        head = done.stdout.strip() if done.returncode == 0 else ""
    if head and head.startswith(repo_sha):
        return []
    return [
        f"в копии {run_root} нет истории git на repo_sha {repo_sha}: условие с bash_allow требует набор с "
        '"copy": "clone"'
    ]


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


def unknown_placeholders(condition: dict[str, Any]) -> list[str]:
    """Имена ``{имя}`` в ``bash_allow`` и ``prompt_prefix``, которых нет в ``PLACEHOLDERS``."""
    texts = [*condition["bash_allow"], condition["prompt_prefix"]]
    names = [name for text in texts for name in re.findall(r"\{(\w+)\}", text)]
    return list(dict.fromkeys(name for name in names if name not in PLACEHOLDERS))


def _posix(path: Path | str) -> str:
    return str(path).replace("\\", "/")


def resolve_placeholders(
    text: str,
    *,
    repo_root: Path | str | None = None,
    repo_sha: str | None = None,
    run_root: Path | str | None = None,
) -> str:
    """Подставляет ``{repo_root}`` ``{repo_sha}`` ``{run_root}`` (пути — в posix-виде); не заданные остаются как есть,
    кроме ``{run_root}``: без копии это ``.``."""
    mapping = {"run_root": _posix(run_root or ".")}
    if repo_root is not None:
        mapping["repo_root"] = _posix(repo_root)
    if repo_sha is not None:
        mapping["repo_sha"] = repo_sha
    return _subst(text, mapping)


def build_command(
    condition: dict[str, Any],
    claude_bin: str = CLAUDE_BIN,
    *,
    mcp_config: Path | str | None = None,
    run_root: Path | str | None = None,
    repo_root: Path | str | None = None,
    repo_sha: str | None = None,
) -> list[str]:
    """Командная строка одной сессии. Сам промпт идёт через stdin (длина, кавычки).

    Непустой ``bash_allow``: ``Bash`` в ``--tools``, ``Bash(<шаблон>)`` в ``--allowedTools``, а
    ``--setting-sources user`` не грузит источники project и local: ``.claude/settings.json`` и
    ``settings.local.json`` копии (в них ``Bash(*)`` и другие разрешения, которые сложились бы с ``--allowedTools``).
    ``~/.claude/settings.json`` пользователя остаётся в силе. Возможный побочный эффект: проектный CLAUDE.md и
    project-хуки в этом режиме не грузятся (для CLI не проверено живым прогоном). Остальное — аудит
    ``audit_violations``.
    """
    resolve = functools.partial(resolve_placeholders, repo_root=repo_root, repo_sha=repo_sha, run_root=run_root)
    bash_allow = [resolve(pattern) for pattern in condition["bash_allow"]]
    output_format = condition["output_format"]
    cmd = [claude_bin, "-p", "--output-format", output_format]
    if output_format == "stream-json":
        cmd.append("--verbose")
    cmd += ["--model", condition["model"], "--no-session-persistence"]
    if condition["allowed_tools"] or bash_allow:
        tools = [*builtin_tools(condition["allowed_tools"]), *(["Bash"] if bash_allow else [])]
        cmd += ["--tools", ",".join(dict.fromkeys(tools))]
        cmd += ["--allowedTools", ",".join([*condition["allowed_tools"], *(f"Bash({item})" for item in bash_allow)])]
    if bash_allow:
        cmd += ["--setting-sources", "user"]
    if condition["disallowed_tools"]:
        cmd += ["--disallowedTools", ",".join(condition["disallowed_tools"])]
    if mcp_config is not None:
        cmd += ["--mcp-config", str(mcp_config)]
    cmd.append("--strict-mcp-config")  # только серверы из --mcp-config; без него — никаких MCP
    if condition["max_budget_usd"] is not None:
        cmd += ["--max-budget-usd", str(condition["max_budget_usd"])]
    if condition["prompt_prefix"]:
        cmd += ["--append-system-prompt", resolve(condition["prompt_prefix"])]
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
    события type=assistant: message.content[] с блоками tool_use, message.usage; события type=user с блоками
    tool_result{tool_use_id, is_error}: у вызова Bash поле ``denied`` = is_error его результата).
    НЕ ПРОВЕРЕНО ЖИВЫМ ПРОГОНОМ.

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
    tool_uses: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for block in blocks:
        if block.get("type") == "tool_use":
            args = block.get("input") or {}
            target = args.get("file_path") or args.get("path") or args.get("pattern") or args.get("command")
            entry: dict[str, Any] = {"name": block.get("name"), "target": target}
            for key in ("pattern", "glob"):  # шаблон поиска рядом с target: путь берётся раньше шаблона
                if key in args:
                    entry[key] = args[key]
            if str(block.get("name")).casefold() == "bash":
                entry["denied"] = False  # станет True, если tool_result этого вызова — ошибка (отказ или код != 0)
            tool_uses.append(entry)
            if isinstance(block.get("id"), str):
                by_id[block["id"]] = entry
    for event in events:
        if event.get("type") != "user":
            continue
        for block in (event.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                entry = by_id.get(block.get("tool_use_id"), {})
                if "denied" in entry:
                    entry["denied"] = bool(block.get("is_error"))

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


BASH_CHAIN = (";", "&&", "||", "|", "&", "\n", ">", "<", "`", "$(")  # склейка команд, перенаправление, подстановка
# --open-files-in-pager=<cmd> исполняет команду; git принимает и сокращения (--out=, --open=)
BASH_LONG_FLAGS = ("--output", "--git-dir", "--work-tree", "--open-files-in-pager")
BASH_SHORT_FLAG = "O"  # git grep -O<пейджер> / git log -O<файл>; регистр значим: -o — другой флаг
# Короткие флаги, берущие значение, зависят от подкоманды (по `git help`). У git log/show/blame: -S -G -L (поиск,
# диапазон), -e -f (шаблон, файл шаблонов), -A -B -C -m (контекст, число). У git grep -G и -L — флаги БЕЗ значения
# (``-GOsh`` — это -G и -O, пейджер запускается), -S там нет вовсе, поэтому для git grep и всех неопознанных команд
# набор уже: ``e f A B C m`` (fail-closed). В связке ``-xyz`` остаток токена после буквы со значением — значение:
# ``-SOrder`` у log, ``-eObject``, ``-L:OnClick:f.py`` у log/blame не содержат флага -O. Буквы ``n`` нет ни в одном
# наборе: у git grep ``-n`` — флаг без значения (``-nOsh`` — это -n и -O), а у git log ``-n<число>`` буквы O нет.
BASH_VALUE_FLAGS_LOG = frozenset("SGLefABCm")
BASH_VALUE_FLAGS_STRICT = frozenset("efABCm")
BASH_LOG_COMMAND = re.compile(r"^\s*git\s+(log|show|blame)\b")
BASH_TEXT_LIMIT = 80
# Аудит видит слова shlex, а git получает слова ПОСЛЕ раскрытий shell ($'..', $"..", ${..}, $IFS, {a,b}, глоб, `~`,
# обратная косая); shlex их не делает, поэтому `$'-O'cmd` для него чист, а git видит -O. Класс закрыт белым списком:
# вне кавычек допустимы буквы, цифры и эти символы (они ничего не раскрывают ни в bash, ни в zsh), `~` — только внутри
# слова (`HEAD~3`); внутри '...' допустимо всё; внутри "..." — всё, кроме `$` и обратной кавычки. Остальное — bash-meta.
BASH_PLAIN = frozenset("_./:=@%+,-^ \t")
BASH_EXPANDS_IN_DQ = frozenset("$`")


def _bash_template_regex(template: str) -> re.Pattern[str]:
    """``*`` -> группа ``(.*)`` (в том числе через перевод строки), остальное — литерал; регистр значим."""
    return re.compile("(.*)".join(re.escape(part) for part in template.split("*")), re.DOTALL)


def _norm_arg(text: str, prefixes: tuple[str, ...]) -> str:
    """posix, casefold, без ``./`` и без префикса копии; ``..`` схлопывается."""
    text = re.sub(r"/{2,}", "/", text.replace("\\", "/").casefold())  # ``a//b`` и ``//a`` — те же пути
    for prefix in prefixes:
        if text == prefix:
            return ""
        if text.startswith(prefix + "/"):
            text = text[len(prefix) + 1 :]
            break
    while text.startswith("./"):
        text = text[2:]
    return posixpath.normpath(text) if text else ""


def _short_cluster_has_open_flag(token: str, value_flags: frozenset[str]) -> bool:
    """``-xyz`` слева направо: ``O`` до флага, берущего значение, — это -O; после такого флага остаток — значение."""
    for char in token[1:]:
        if char == BASH_SHORT_FLAG:
            return True
        if char in value_flags:
            return False
    return False


def _has_shell_expansion(group: str) -> bool:
    """``True`` — shell может построить слово иначе, чем shlex (см. ``BASH_PLAIN``); непарная кавычка — тоже."""
    quote, escaped, prev = "", False, " "
    for char in group:
        if quote == "'":
            quote = "" if char == "'" else quote
        elif quote == '"':
            if char in BASH_EXPANDS_IN_DQ:
                return True
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True  # `\"` не закрывает кавычку
            elif char == '"':
                quote = ""
        elif char in "'\"":
            quote = char
        elif char == "~":
            if prev in " \t=:":  # начало слова или после `=`/`:` — тильда раскрывается
                return True
        elif not (char.isalnum() or char in BASH_PLAIN):
            return True
        prev = char
    return bool(quote)


def _bash_group_rule(
    group: str, exclude: list[str], prefixes: tuple[str, ...], value_flags: frozenset[str]
) -> str | None:
    """Правило, которое нарушает текст группы ``*`` шаблона, или ``None``."""
    try:
        tokens = shlex.split(group, posix=True)
    except ValueError:
        tokens = group.split()
    # shlex в posix-режиме съедает обратную косую (``a\\b`` -> ``ab``): пути ищутся и в «сырых» словах
    for token in (
        *tokens,
        *group.split(),
    ):  # путь: токен целиком и его куски по ``:`` и ``=`` (<rev>:<путь>, --opt=<путь>)
        for piece in (token, *re.split(r"[:=]", token)):
            path = _norm_arg(piece, prefixes)
            if path and any(path == item or path.startswith(item + "/") for item in exclude):
                return "bash-exclude"
    if any(mark in group for mark in BASH_CHAIN):
        return "bash-chain"
    if _has_shell_expansion(group):  # иначе токены shlex ниже — не те слова, что получит git
        return "bash-meta"
    for token in tokens:
        if token.startswith("--"):
            name = token.split("=", 1)[0]
            if len(name) > 2 and any(flag.startswith(name) for flag in BASH_LONG_FLAGS):
                return "bash-flag"
        elif token.startswith("-") and _short_cluster_has_open_flag(token, value_flags):
            return "bash-flag"
    return None


def _bash_rule(command: str, patterns: list[str], exclude: list[str], prefixes: tuple[str, ...]) -> str | None:
    """``None`` — команда укладывается в шаблон, а тексты его групп ``*`` чисты; иначе имя нарушенного правила.
    Литералы шаблона доверенные: проверяются только группы."""
    exclude = [item for item in (_norm_arg(item, ()) for item in exclude) if item]
    norm_prefixes = tuple(_norm_root(prefix) for prefix in prefixes)
    # набор букв со значением — по подкоманде; git grep и всё неопознанное — строгий набор (fail-closed)
    value_flags = BASH_VALUE_FLAGS_LOG if BASH_LOG_COMMAND.match(command) else BASH_VALUE_FLAGS_STRICT
    first = "bash-pattern"
    matched = False
    for template in patterns:
        found = _bash_template_regex(template).fullmatch(command.strip())
        if found is None:
            continue
        rules = [_bash_group_rule(group, exclude, norm_prefixes, value_flags) for group in found.groups()]
        bad = next((rule for rule in rules if rule), None)
        if bad is None:
            return None
        if not matched:
            first, matched = bad, True
    return first


def audit_violations(
    tool_uses: list[dict[str, Any]],
    allowed_tools: list[str],
    context_files: list[str],
    prefixes: tuple[str, ...],
    audit_reads: bool = False,
    bash_allow: list[str] | None = None,
    exclude: list[str] | None = None,
) -> list[str]:
    """Аудит по списку разрешённого: любой tool_use вне ``allowed_tools`` — нарушение; при ``audit_reads`` и любое
    чтение вне ``context_files``. Имена и пути сравниваются без учёта регистра, пути — в posix-виде.

    ``bash_allow`` (шаблоны с ``*``, уже с подставленными плейсхолдерами) делает ``Bash`` допустимым, но каждая его
    команда проверяется: нет шаблона — ``bash-pattern``; в группе ``*`` путь из ``exclude`` — ``bash-exclude``, склейка
    или перенаправление — ``bash-chain``, раскрытие shell (``$`` ``{`` ``*`` ``\\`` и т. п. вне кавычек, ``$`` в
    ``"..."``) — ``bash-meta``, флаг ``--output`` ``-O`` ``--git-dir`` ``--work-tree`` — ``bash-flag``.
    Текст нарушения: ``<правило>:<команда до 80 символов>``. Аудит видит только аргументы: ``git log -p`` без пути
    покажет и исключённые пути, а ``git grep x HEAD`` — файлы из ``exclude`` на ``repo_sha``.
    """
    allowed_paths = {score.normalize_path(path).casefold() for path in context_files}
    bad = []
    for use in tool_uses:
        name, target = str(use.get("name") or ""), use.get("target") or ""
        if bash_allow and name.casefold() == "bash":
            rule = _bash_rule(str(target), bash_allow, exclude or [], prefixes)
            if rule:
                shown = str(target).replace("\n", "\\n")
                bad.append(f"{rule}:{shown[:BASH_TEXT_LIMIT]}")
        elif allowed_tools and not _tool_allowed(name, allowed_tools):
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
    bash_allow: list[str] | None = None,
    exclude: list[str] | None = None,
) -> dict[str, Any]:
    """``bash_allow`` — шаблоны условия с подставленными плейсхолдерами, ``exclude`` — из набора (для аудита Bash)."""
    parsed = parse_session_output(session.stdout)
    text = _answer_text(parsed, len(questions))
    scored = score.score_run(questions, text, prefixes)
    turns = parsed["turns"]
    max_turns = condition["max_turns"]
    violations = audit_violations(
        parsed["tool_uses"],
        condition["allowed_tools"],
        condition["context_files"],
        prefixes,
        condition["audit_reads"],
        bash_allow,
        exclude,
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
    record = load_json(Path(path))
    return {"path": str(path), "set": record.get("set"), "aggregate": record["aggregate"]}


def baseline_set_problem(baseline: dict[str, Any] | None, set_name: str) -> str | None:
    """Текст ошибки, если база снята на другом наборе вопросов (медианы чужого набора не сравнимы)."""
    if baseline and baseline.get("set") and baseline["set"] != set_name:
        return f"база {baseline['path']} снята на наборе {baseline['set']!r}, а прогон идёт на {set_name!r}."
    return None


def rescore_record(
    record: dict[str, Any], questions: list[dict[str, Any]], baseline_path: Path | None = None
) -> dict[str, Any]:
    """Оценка заново по сохранённому тексту (эталон поправили — повторять сессии не надо)."""
    prefixes = tuple(record.get("prefixes") or (record["root"],))
    for rep in record["repeats"]:
        rep["score"] = score.score_run(questions, rep["final_text"], prefixes)
    record["questions"] = questions
    if baseline_path:
        record["baseline"] = load_baseline(baseline_path)
        problem = baseline_set_problem(record["baseline"], record["set"])
        if problem:
            raise ValueError(problem)
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
        "| # | hits | файл (справка) | false | факты | hits (все) | вызовы | контекст | накоп. | cache read | сек "
        "| ходы | статус | заметки |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
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
        files_cell = f"{sc['files_hit']}/{sc['scored']}" if "files_hit" in sc else "н/д"  # у старой записи ключа нет
        lines.append(
            f"| {rep['index']} | {sc['hits']}/{sc['scored']} | {files_cell} | {sc['false']} "
            f"| {sc['facts_hit']}/{sc['facts_scored']} "
            f"| {sc['total_hits']}/{sc['total']} | {_fmt(rep['tool_calls'])} | {_fmt(rep['final_context_tokens'])} "
            f"| {_fmt(rep['cumulative_tokens'])} | {_fmt(rep['cache_read_tokens'])} | {_fmt(rep['wall_s'])} "
            f"| {_fmt(rep['turns'])} | {_fmt(rep['subtype'])} | {'; '.join(notes)} |"
        )
    for stat_name in ("min", "median", "max"):
        lines.append(
            f"| **{stat_name}** | {_fmt(agg['hits'][stat_name])} | | {_fmt(agg['false'][stat_name])} "
            f"| {_fmt(agg['facts_hit'][stat_name])} | | {_fmt(agg['tool_calls'][stat_name])} "
            f"| {_fmt(agg['final_context_tokens'][stat_name])} | {_fmt(agg['cumulative_tokens'][stat_name])} "
            f"| {_fmt(agg['cache_read_tokens'][stat_name])} | {_fmt(agg['wall_s'][stat_name])} | | | |"
        )
    lines += ["", "вердикт — только hits по правилу V3; `файл` — справка"]
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
    history_fn: Callable[[dict[str, Any], Path, str], list[str]] = check_history_copy,
    today: str | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> tuple[int, Path | None]:
    """Код выхода и путь записи. Код 2 — отказ (нет --yes, нет бюджета, нет индекса) или ошибка набора.

    ``root`` — репозиторий-источник (из него ``git archive`` или ``git clone``); сессия идёт в чистой копии.
    ``floor`` — один тривиальный вопрос теми же флагами: фиксированные накладные расходы.
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
    if _copy_mode(qset) not in COPY_MODES:
        print("ОТКАЗ: copy набора должен быть archive или clone", file=err)
        return 2, None
    unknown = unknown_placeholders(condition)
    if unknown:
        for name in unknown:
            print(f"ОТКАЗ: неизвестный плейсхолдер {{{name}}} (есть: {', '.join(PLACEHOLDERS)})", file=err)
        return 2, None
    problem = None if floor else baseline_set_problem(baseline, qset["name"])  # floor с любой базой: пороги вырезаны
    if problem:
        print(f"ОШИБКА: {problem}", file=err)
        return 2, None
    if floor:  # относительные пороги к базе при одном тривиальном вопросе бессмысленны
        kept = {k: v for k, v in condition["thresholds"].items() if not k.endswith("_ratio_max")}
        condition = {**condition, "thresholds": kept}
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
        cmd = build_command(
            condition, mcp_config=mcp, run_root=run_root, repo_root=root.resolve(), repo_sha=qset["repo_sha"]
        )
        state = "уже есть" if run_root.exists() else "будет создана при реальном запуске"
        print(
            f"[dry-run] чистая копия {qset['repo_sha']} (без: {', '.join(qset['exclude']) or '-'}): "
            f"{run_root} ({state})" + (f", copy: {_copy_mode(qset)}" if _copy_mode(qset) != "archive" else ""),
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
    ratio_keys = [key for key in effective_thresholds(qset, condition) if key.endswith("_ratio_max")]
    if ratio_keys and baseline is None:
        print(
            f"ОТКАЗ: пороги {', '.join(ratio_keys)} считаются от базового прогона, а --baseline не задан "
            "(без базы вердикт был бы UNMEASURED); снимите базу условием grep-read и передайте её.",
            file=err,
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
    problems = [*history_fn(condition, run_root, qset["repo_sha"]), *preflight_fn(condition, run_root)]
    if problems:
        for problem in problems:
            print(f"ОТКАЗ: {problem}", file=err)
        return 2, None
    mcp = render_mcp_config(condition, root, run_root)
    cmd = build_command(
        condition, mcp_config=mcp, run_root=run_root, repo_root=root.resolve(), repo_sha=qset["repo_sha"]
    )
    bash_allow = [
        resolve_placeholders(item, repo_root=root.resolve(), repo_sha=qset["repo_sha"], run_root=run_root)
        for item in condition["bash_allow"]
    ]

    # cwd сессии — run_root как есть, а агент может назвать и раскрытый путь (короткое %TEMP%, симлинк): оба вида
    prefixes = tuple(dict.fromkeys((str(run_root.resolve()), str(run_root))))
    repeat_records = []
    for index in range(1, repeats + 1):
        print(f"повтор {index}/{repeats}...", file=err)
        session = runner(cmd, prompt, run_root)
        rep = _repeat_record(
            index, session, qset["questions"], condition, prefixes, bash_allow=bash_allow, exclude=qset["exclude"]
        )
        if rep["error"]:
            print(f"повтор {index}: сессия с ошибкой (код {rep['returncode']}): {rep['error']}", file=err)
        repeat_records.append(rep)

    date = today or datetime.date.today().isoformat()
    record: dict[str, Any] = {
        "set": qset["name"],
        "repo_sha": qset["repo_sha"],
        "source_root": str(root),
        "root": prefixes[0],
        "prefixes": list(prefixes),
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
    try:
        record = load_json(run_path)
        questions = load_questions(questions_path)["questions"] if questions_path else record["questions"]
        rescored = rescore_record(record, questions, baseline_path)
    except (OSError, ValueError, KeyError) as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 2
    print(render_markdown(rescored), file=out)
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
    warnings = verify_set_warnings(qset, root, show_fn)
    for warning in warnings:
        print(f"ПРЕДУПРЕЖДЕНИЕ: {warning}", file=out)
    print(f"предупреждений {len(warnings)}", file=out)
    return 1 if problems else 0


def ceiling_command(
    questions_path: Path, reference_path: Path, minimum: int | None = None, out: TextIO | None = None
) -> int:
    """Код: 0; с ``minimum`` при достижимых меньше него — 1; нет файла или не JSON — 2."""
    out = out or sys.stdout
    try:
        qset = load_questions(questions_path)
        addrs = reference_addresses(load_json(reference_path))
    except (OSError, ValueError, KeyError) as exc:
        print(f"ОШИБКА: {exc}", file=sys.stderr)
        return 2
    report, reached, total = ceiling(qset, addrs)
    for row in report:
        print(row, file=out)
    print(f"ceiling {qset['name']}: {reached}/{total}", file=out)
    return 1 if minimum is not None and reached < minimum else 0


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
        run.add_argument(
            "--root", type=Path, default=Path("."), help="репозиторий-источник для git archive / git clone"
        )

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

    ceil = sub.add_parser("ceiling", help="какие ожидаемые адреса набора есть в JSON-эталоне или в тексте паспортов")
    ceil.add_argument("--questions", required=True, type=Path)
    source = ceil.add_mutually_exclusive_group(required=True)
    source.add_argument("--reference", type=Path, help="JSON эталона 3.1 или `atlas ref --format json`")
    source.add_argument("--text", type=Path, help="JSON целей (форма — README): паспорта atlas на repo_sha набора")
    ceil.add_argument("--root", type=Path, default=Path("."), help="репозиторий-источник клона на repo_sha (с --text)")
    ceil.add_argument("--min", type=int, default=None, help="код 1, если достижимых меньше N (--text: K по окну)")

    args = parser.parse_args(argv)
    if args.command == "ceiling":
        if args.text is not None:
            return ceiling_text_command(args.questions, args.text, args.root, args.min)
        return ceiling_command(args.questions, args.reference, args.min)
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
