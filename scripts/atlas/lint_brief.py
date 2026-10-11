"""Проверка брифа задачи `atlas lint-brief <файл>` и общая проверка лимитов для хука `lint-brief.sh` (Task 1.9c).

Purpose: форма брифа (ADR-ATL-004 §2: H1, метки, строки тела, FACTS/ACCEPTANCE по §2.5), повтор команд строк факта
    (`replay.py`), REDS, `<id>.injections.json` (§3) и `PROBE`. Лимиты DESIGN/FILES/REDS и тексты отказов хука — одна
    функция на два режима: файл даёт находки, промпт спавна (`spawn_violations`) — строки отказа. Метки и блоки —
    `plans_ledger._brief_label_positions` и `_label_blocks`.
Public API: Finding, Result, lint, run, spawn_violations.
Stability: lite
    Исключение из правила PEP 695: синтаксис не выше Python 3.11 — модуль грузит хук на каждый спавн под `$PY`,
    который может быть старше `.venv`. `scripts.atlas.brief` (grimp/griffe) импортируется внутри функции.
"""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

from scripts.atlas import replay
from scripts.atlas.tree import AtlasError
from scripts import plans_ledger as pl

__all__ = ["Finding", "Result", "lint", "run", "spawn_violations"]

_ROLES = ("tester", "developer", "teamlead", "junior", "debugger")
_NAME = re.compile(rf"^(?P<id>{pl._TASK_ID})(?:\.(?P<role>{'|'.join(_ROLES)}))?\.md$")
_MAIN = ("TASK", "ROLE", "CHAIN", "FACTS", "DESIGN", "FILES", "REDS", "ACCEPTANCE", "TESTS", "OUT OF SCOPE")
_ROLE_REQUIRED = tuple(n for n in _MAIN if n not in ("FACTS", "ACCEPTANCE"))
_EXTRA = ("TRAPS", "HANDOFF IN", "FORBIDDEN PATHS", "GUARDS", "PROBE", "COMMIT", "REPORT", "BRIEF-OVERRIDE")
_BODY_CHECKED = ("DESIGN", "FILES", "REDS", "FACTS", "ACCEPTANCE", "TESTS", "OUT OF SCOPE")
_MAX_FILES = 6
_ENTRY = re.compile(r"^[ \t]*(?:\d+\.|[-*])[ \t]+")
_BULLET = re.compile(r"^(?:\d+\.|[-*])[ \t]+")
_OPEN = re.compile(r"^<!-- atlas:facts ([0-9a-f]{7}) -->$")
_CLOSE = "<!-- /atlas:facts -->"
_ITEM = re.compile(r"^[ \t]*(?:- |\d+\. )")
_FACT = re.compile(r"^[ \t]*- (?P<what>.+?) — `(?P<cmd>[^`]+)` → (?:`(?P<lit>[^`]+)`|exit (?P<code>\d+))$")
_TIMING = re.compile(
    r"(?<![\w.])\d+(?:[.,]\d+)? ?(?:(?:с|сек)(?![ \t]+[а-яёa-z])|s|ms|мс)(?!\w)|\bin \d+(?:[.,]\d+)?s(?!\w)"
)
_RED = re.compile(_ENTRY.pattern + r"(\S+\.py)::(\S+)")
_NODEID = re.compile(r"^[^\s:]+\.py::\S+$")
_INJ_KEYS = {"id", "prop", "file", "old", "new", "forecast", "observed", "test"}
_RACE = re.compile(r"(?<![^\W\d_])(?:гонк|race|lost-wakeup|реентер|reentran|одновременн)", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str  # "error" | "warning"
    line: int | None  # 1-based; None — у находки нет строки
    text: str


@dataclass
class Result:
    findings: list[Finding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # строки «не сверено (вне allow-list)»
    checked: int = 0  # строк факта, у которых команду запустили
    outside: int = 0  # строк факта вне allow-list

    def add(self, code: str, text: str, idx: int | None = None, sev: str = "error") -> None:
        self.findings.append(Finding(code, sev, None if idx is None else idx + 1, text))


class _Doc:
    """Метки и блоки файла брифа: индексы строк; метки в ограждениях не считаются."""

    def __init__(self, text: str) -> None:
        self.lines = text.splitlines()
        self.fenced = [f for _, f in pl._unfenced_lines(text)]
        self.pos = pl._brief_label_positions(text)
        self.first: dict[str, int] = {}
        for i, name in self.pos:
            self.first.setdefault(name, i)

    def span(self, name: str) -> list[int]:
        """Индексы строк тела: после строки метки до следующей метки (нет метки — пусто)."""
        if name not in self.first:
            return []
        start = self.first[name]
        return list(range(start + 1, next((i for i, _ in self.pos if i > start), len(self.lines))))

    def body(self, name: str) -> list[str]:
        return [self.lines[i] for i in self.span(name)]

    def text(self, name: str) -> str:  # остаток строки метки после `:` и тело метки
        head = self.lines[self.first[name]].partition(":")[2] if name in self.first else ""
        return "\n".join([head, *self.body(name)])


def _na(lines: list[str]) -> bool:  # первая непустая строка без маркера пункта начинается с `n/a`
    first = next((ln.strip() for ln in lines if ln.strip()), "")
    return _BULLET.sub("", first).strip().lower().startswith("n/a")


def _limits(blocks: dict[str, list[str]], max_files: int, spawn: bool) -> list[tuple[str, str]]:
    """(код, текст) нарушений лимитов; `blocks` — тела без строки метки; `spawn` добавляет «блока нет» и REPORT."""
    out: list[tuple[str, str]] = []
    for name in ("DESIGN", "FILES", "REDS"):  # порядок хука до 1.9c: поблочно, затем REPORT
        body = blocks.get(name, [])
        n = sum(1 for ln in body if (ln.strip() if name == "DESIGN" else _ENTRY.match(ln)))
        if name not in blocks:
            out += [(f"{name}_MISSING", f"{name} block missing")] if spawn else []
        elif name == "DESIGN" and n < 3:
            out.append(("DESIGN_SHORT", f"DESIGN has {n} non-empty line(s) (need >= 3)"))
        elif name == "FILES" and n > max_files:
            out.append(("FILES_TOO_MANY", f"FILES lists {n} paths (max {max_files})"))
        elif name == "REDS" and n > 10 and not _na(body):
            out.append(("REDS_TOO_MANY", f"REDS lists {n} tests (max 10, or 'n/a')"))
    return out + ([("REPORT_MISSING", "REPORT block missing")] if spawn and "REPORT" not in blocks else [])


def spawn_violations(prompt: str, max_files: int = _MAX_FILES) -> list[str]:
    """Строки отказа хука для промпта спавна; блок — без строки метки и без пропуска ограждений, как читает хук."""
    blocks = {name: lines[1:] for name, lines in pl._label_blocks(prompt.splitlines()).items()}
    return [text for _, text in _limits(blocks, max_files, True)]


def _parse_name(name: str) -> tuple[str, str | None]:
    if not (m := _NAME.match(name)):
        raise AtlasError(f"lint-brief: имя файла не по форме tasks/<id>.md или tasks/<id>.<роль>.md: {name}")
    return m["id"], m["role"]


def _form(doc: _Doc, res: Result, ident: str, role: str | None) -> None:
    head = next((i for i, ln in enumerate(doc.lines) if ln.startswith("# ") and not doc.fenced[i]), None)
    shape = f"# Task {ident} — <суть>" if role is None else f"# {ident} — бриф {role}"
    line = "" if head is None else doc.lines[head].rstrip()
    if not (re.match(rf"# Task {re.escape(ident)} — \S", line) if role is None else line == shape):
        res.add("H1", f"заголовок H1 должен быть `{shape}`", head)
    if missing := [n for n in (_MAIN if role is None else _ROLE_REQUIRED) if n not in doc.first]:
        res.add("LABEL_MISSING", "нет обязательных меток: " + ", ".join(missing))
    names = [n for _, n in doc.pos]
    for name in dict.fromkeys(names):
        if name not in (*_MAIN, *_EXTRA):
            res.add("LABEL_UNKNOWN", f"метка {name} не из набора брифа", doc.first[name], "warning")
        if names.count(name) > 1:
            res.add("LABEL_DUPLICATE", f"метка {name} дважды; действует первая", doc.first[name], "warning")
    for name in _BODY_CHECKED:
        for i in doc.span(name):
            if not doc.fenced[i] and pl._ANY_FIELD_LABEL_RE.match(doc.lines[i]):
                res.add("BODY_LABEL", f"строка тела {name} открывает чужую метку (ADR §2.4): {doc.lines[i].strip()}", i)
    for code, text in _limits({name: doc.body(name) for name in doc.first}, _MAX_FILES, False):
        res.add(code, text, doc.first.get(code.split("_")[0]))


def _facts(root: Path, doc: _Doc, res: Result, do_replay: bool) -> str | None:
    """FACTS и ACCEPTANCE: маркеры, грамматика §2.5, время в литерале, повтор команд; возвращает sha7 маркера."""
    sha, rows = None, []
    if "FACTS" in doc.first:
        span = doc.span("FACTS")
        opened = next((i for i in span if _OPEN.match(doc.lines[i])), None)
        closed = next((i for i in span if opened is not None and i > opened and doc.lines[i] == _CLOSE), None)
        if closed is None:
            res.add("FACTS_MARKER", f"у метки FACTS нет пары маркеров atlas:facts (`{_CLOSE}`)", doc.first["FACTS"])
        else:
            sha = _OPEN.match(doc.lines[opened])[1]  # type: ignore[index]
            rows = [i for i in range(opened + 1, closed) if doc.lines[i].strip()]
    rows += [i for i in doc.span("ACCEPTANCE") if not doc.fenced[i] and _ITEM.match(doc.lines[i])]
    runs: dict[str, replay.Replay | None] = {}
    for i in rows:
        if not (m := _FACT.match(doc.lines[i])):
            res.add("FACT_FORM", f"строка не по грамматике ADR §2.5: {doc.lines[i].strip()}", i)
        elif m["lit"] and _TIMING.search(m["lit"]):
            res.add("LITERAL_TIMING", f"литерал со временем не воспроизводится: {m['lit']}", i)
        elif do_replay:
            _replay_line(root, res, runs, i, m)
    return sha


def _replay_line(root: Path, res: Result, runs: dict[str, replay.Replay | None], i: int, m: re.Match[str]) -> None:
    cmd, lit, code = m["cmd"], m["lit"], m["code"]
    try:
        shlex.split(cmd)
    except ValueError as exc:
        res.add("FACT_FORM", f"команда не разбирается shlex ({exc}): {cmd}", i)
        return
    if cmd not in runs:
        runs[cmd] = replay.run(root, cmd)
    if (got := runs[cmd]) is None:
        res.outside += 1
        res.notes.append(f"  не сверено (вне allow-list): {cmd}")
        return
    res.checked += 1
    if got.timed_out:
        res.add("FACT_TIMEOUT", f"команда не завершилась в срок, дерево процессов убито: {cmd}", i)
    elif lit and lit not in got.out:
        first = next((ln.strip()[:120] for ln in got.out.splitlines() if ln.strip()), f"пусто, код {got.code}")
        res.add("FACT_MISMATCH", f"литерал не найден в выводе: {lit}\n  вывод: {first}", i)
    elif not lit and got.code != int(code):
        res.add("FACT_MISMATCH", f"код возврата {got.code}, ожидался {code}", i)


def _task_files(path: Path, ident: str, doc: _Doc) -> set[str]:
    """Первые слова пунктов FILES этого брифа и файлов роли той же задачи рядом."""
    first_words = lambda d: {m[1] for ln in d.body("FILES") if (m := re.match(_ENTRY.pattern + r"(\S+)", ln))}  # noqa: E731
    files = first_words(doc)
    for other in sorted(path.parent.glob(f"{ident}.*.md")):
        if other != path and (m := _NAME.match(other.name)) and m["role"] and m["id"] == ident:
            files |= first_words(_Doc(other.read_bytes().decode("utf-8-sig", "replace")))
    return files


def _collect(root: Path, cache: dict[str, replay.Replay | None], do_replay: bool, rel: str) -> replay.Replay | None:
    """Сбор тестов файла: один `pytest --collect-only` на файл; без повтора (`--no-replay`) — None."""
    if do_replay and rel not in cache:
        cache[rel] = replay.run(root, f"python -m pytest --collect-only -q -p no:cacheprovider {shlex.quote(rel)}")
    return cache.get(rel)


def _has(got: replay.Replay | None, name: str) -> bool:
    return any(ln.endswith(f"::{name}") or f"::{name}[" in ln for ln in (got.out.splitlines() if got else []))


def _reds(root: Path, doc: _Doc, res: Result, planned: set[str], col) -> set[str]:  # type: ignore[no-untyped-def]
    """Проверка REDS; возвращает nodeid из REDS (для forecast инъекций)."""
    seen: set[str] = set()
    if _na(doc.body("REDS")):
        return seen
    for i in doc.span("REDS"):
        if not (m := _RED.match(doc.lines[i])):
            continue
        (rel, name), got = m.groups(), None
        seen.add(f"{rel}::{name}")
        if not (root / rel).is_file():
            if rel not in planned:
                res.add("REDS_NO_FILE", f"файла {rel} нет и он не назван в FILES", i)
        elif got := col(rel):
            tail = " | ".join(ln.strip() for ln in got.out.splitlines() if ln.strip())[-200:]
            if got.timed_out or got.code not in (0, 5):
                res.add("REDS_COLLECT_FAILED", f"{rel} не собирается (код {got.code}): {tail}", i)
            elif rel not in planned and not _has(got, name):
                res.add("REDS_NOT_COLLECTED", f"{rel}::{name} не среди собранных тестов, файла нет в FILES", i)
    return seen


def _inj_problems(n: int, obj: object) -> list[str]:
    if not isinstance(obj, dict) or set(obj) != _INJ_KEYS:
        return [f"нужен объект с ключами {sorted(_INJ_KEYS)}"]
    nodes = lambda v: isinstance(v, list) and all(isinstance(x, str) and _NODEID.match(x) for x in v)  # noqa: E731
    checks = [
        (obj["id"] == f"inj-{n}", f"id {obj['id']!r} вместо inj-{n}"),
        (isinstance(obj["old"], str) and obj["old"] != "", "old — непустая строка"),
        (all(isinstance(obj[k], str) for k in ("prop", "file", "new", "test")), "prop, file, new, test — строки"),
        (nodes(obj["forecast"]), "forecast — список nodeid `<файл>.py::<имя>`"),
        (obj["observed"] is None or nodes(obj["observed"]), "observed — null или список nodeid"),
    ]
    return [msg for ok, msg in checks if not ok]


def _injections(root: Path, path: Path, res: Result, reds: set[str], planned: set[str], col) -> None:  # type: ignore[no-untyped-def]
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_bytes().decode("utf-8-sig"))
    except ValueError as exc:
        return res.add("INJ_FORM", f"не JSON: {exc}")
    if not isinstance(data, list):
        return res.add("INJ_FORM", "файл — не массив объектов (ADR §3)")
    for n, obj in enumerate(data, 1):
        if problems := _inj_problems(n, obj):
            res.add("INJ_FORM", f"inj-{n}: " + "; ".join(problems))
            continue
        target = (root / obj["file"]).resolve()
        if root not in target.parents or not target.is_file():
            res.add("INJ_FILE_MISSING", f"inj-{n}: файла {obj['file']} нет")
        else:
            text, old = (s.replace("\r\n", "\n") for s in (target.read_bytes().decode("utf-8", "replace"), obj["old"]))
            if (at := text.find(old)) < 0:
                res.add("INJ_OLD_MISSING", f"inj-{n}: old не найден в {obj['file']}")
            elif text.find(old, at + 1) >= 0:
                res.add("INJ_OLD_AMBIGUOUS", f"inj-{n}: old входит в {obj['file']} больше одного раза")
        for node in obj["forecast"]:
            rel, _, name = node.partition("::")
            if node not in reds and rel not in planned and not ((root / rel).is_file() and _has(col(rel), name)):
                res.add("INJ_FORECAST_UNKNOWN", f"inj-{n}: forecast {node}: нет в REDS и FILES, тест не собран")


def _probe(root: Path, path: Path, doc: _Doc, res: Result) -> None:
    if "PROBE" in doc.first:
        rel = next((w for w in (w.strip("`") for w in doc.text("PROBE").split()) if w.endswith(".md")), None)
        if rel is None or not any((base / rel).is_file() for base in (root, path.parent.parent)):
            res.add(
                "PROBE_MISSING", f"PROBE: файла {rel or '<не назван>'} нет ни от корня, ни от плана", doc.first["PROBE"]
            )
    elif _RACE.search(re.sub(r"`[^`]*`", "", doc.text("DESIGN") + "\n" + doc.text("TRAPS"))):
        res.add("RACE_WITHOUT_PROBE", "в DESIGN/TRAPS гонка или реентерабельность, метки PROBE нет", None, "warning")


def lint(root: Path, path: Path, *, replay: bool = True, fresh: bool = True) -> Result:  # noqa: A002
    """Проверить бриф `path` (внутри `root`): находки, строки «не сверено», счётчики."""
    root, path = root.resolve(), path.resolve()
    ident, role = _parse_name(path.name)
    doc, res = _Doc(path.read_bytes().decode("utf-8-sig", "replace")), Result()
    _form(doc, res, ident, role)
    if _facts(root, doc, res, replay) and fresh:
        from scripts.atlas import brief  # тяжёлый импорт (grimp/griffe): только здесь

        try:
            code, out = brief.check(root, path)
        except AtlasError as exc:  # неизвестный sha маркера, битый modules.yaml: ошибка, не молчание
            code, out = 1, [str(exc)]
        if code:
            res.add("FACTS_STALE", out[0], doc.first["FACTS"])
    planned, col = _task_files(path, ident, doc), partial(_collect, root, {}, replay)
    reds = _reds(root, doc, res, planned, col)
    if role is None:
        _injections(root, path.with_name(f"{ident}.injections.json"), res, reds, planned, col)
    _probe(root, path, doc, res)
    return res


def run(root: Path, file: str, *, replay: bool = True, fresh: bool = True) -> tuple[int, list[str]]:  # noqa: A002
    """Строки вывода и код: 0 — ошибок нет, 1 — есть ошибка; нет файла, плохое имя, файл вне корня — AtlasError (2)."""
    target = Path(file).resolve()
    if not target.is_file():
        raise AtlasError(f"lint-brief: нет файла {file}")
    if root.resolve() not in target.parents:
        raise AtlasError(f"lint-brief: файл вне репозитория {root.as_posix()}: {file}")
    res = lint(root, target, replay=replay, fresh=fresh)
    shown = Path(file).as_posix()
    inj = Path(file).with_name(f"{_parse_name(target.name)[0]}.injections.json").as_posix()
    lines = [
        f"{inj if f.code.startswith('INJ_') else shown}{f':{f.line}' if f.line else ''}: {f.severity} {f.code} {f.text}"
        for f in res.findings
    ]
    errors = sum(f.severity == "error" for f in res.findings)
    summary = (
        f"lint-brief: ошибок {errors}, предупреждений {len(res.findings) - errors}, "
        f"сверено {res.checked}, вне allow-list {res.outside}"
    )
    return (1 if errors else 0), [*lines, *res.notes, summary]
