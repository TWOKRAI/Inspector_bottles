#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Классификатор срывов `git commit` / `git merge` по транскриптам Claude Code (Task 2.3).

Определения (CLI, попытка, классы, писатель A1, hidden) — в плане
plans/2026-10-03_commit-mechanism/tasks/2.3.md; здесь они реализованы буквально, регэкспы
не пересказаны в README. Только stdlib.

Запуск:
    python scripts/commit_audit/classify.py --root <каталог projects> --since YYYY-MM-DD \
        --until YYYY-MM-DD [--project-substr Inspector-vision-Inspector-bottles] [--json]

Устройство: небольшие чистые функции (strip_heredocs, mask_quotes, find_invocations,
classify_result, writer_split, hidden_flag, table) и сканер транскриптов (TranscriptScanner),
который склеивает `tool_use` с его `tool_result` и ведёт историю писателей `.py` по каждому файлу.
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Iterator

# ----------------------------------------------------------------------------------------------
# строки таблицы и значения по умолчанию
# ----------------------------------------------------------------------------------------------
CLASS_ROWS = [
    "A1",
    "A1-Edit/Write",
    "A1-F401",
    "A1-Bash",
    "A1-undecided",
    "A2",
    "A3",
    "C1",
    "C2",
    "C4",
    "B1",
    "B2",
]
ROW_ORDER = [*CLASS_ROWS, "hidden"]
DEFAULT_PROJECT_SUBSTR = "Inspector-vision-Inspector-bottles"

# ----------------------------------------------------------------------------------------------
# (b) распознавание команды
# ----------------------------------------------------------------------------------------------
# заголовок heredoc; `<<<` (here-string) не заголовок
HEREDOC_RE = re.compile(r"""(?<!<)<<(?!<)-?[ \t]*(['"]?)([A-Za-z_]\w*)\1""")

SEG = r"(?:^|&&|\|\||[;|(\n{]|\bthen\b|\bdo\b|\belse\b|`|\$\()[ \t]*(?:[A-Za-z_]\w*=\S*[ \t]+)*"
GITOPTS = r"git(?:[ \t]+(?:-C[ \t]+\S+|-c[ \t]+\S+|--no-pager|--git-dir=\S+|--work-tree=\S+))*[ \t]+"
_VERB_TAIL = r"(?![-\w])(?P<args>[^\n;&|]*)(?P<tail>[^\n;&]*)"
COMMIT_RE = re.compile(SEG + GITOPTS + "commit" + _VERB_TAIL, re.MULTILINE)
MERGE_RE = re.compile(SEG + GITOPTS + "merge" + _VERB_TAIL, re.MULTILINE)
ADD_RE = re.compile(SEG + GITOPTS + r"(?:add|rm)(?![-\w])(?P<args>[^\n;&|]*)", re.MULTILINE)
CD_RE = re.compile(SEG + r"cd[ \t]+(?P<target>\S)", re.MULTILINE)
GLOBAL_WRITER_RE = re.compile(
    SEG + GITOPTS + r"(?:merge(?![-\w])|cherry-pick|rebase|pull|apply|stash[ \t]+pop|reset[ \t]+--hard)",
    re.MULTILINE,
)
# конвейер одной команды: `&` допустим только в `&>` и `|&`, `||` и `;` обрывают
PIPELINE_RE = re.compile(r"(?:[^\n;&|]|&>|\|&|\|(?!\|))*")

# ----------------------------------------------------------------------------------------------
# (d), (e), (f) сигнатуры
# ----------------------------------------------------------------------------------------------
NOT_EXECUTED_RE = re.compile(
    r"^(?:Error: )?(?:Permission to use Bash|The server-side auto mode classifier|"
    r"PreToolUse:Bash hook error: (?!.*protect-branch))"
)
COMMIT_SUCCESS_RE = re.compile(r"^\[[^\]\n]+? [0-9a-f]{7,40}\] ", re.MULTILINE)
MERGE_SUCCESS_RE = re.compile(
    r"^(?:Merge made by the '\S+' strategy\.|Fast-forward[ \t]*$|Already up to date\.)", re.MULTILINE
)
STATUS_RE = re.compile(r"^(?P<label>\S.*?)\.{3,}(?:\([^)\n]*\))?(?P<st>Passed|Failed|Skipped)[ \t]*$")
STATUS_MAX_LINE = 300  # длиннее — не строка статуса хука (см. hook_blocks)
RUFF_LABEL_RE = re.compile(r"^ruff(?: \(legacy alias\)| check)?$")
RUFF_MODIFIED_RE = re.compile(r"^- files were modified by this hook", re.MULTILINE)
RUFF_FIXED_RE = re.compile(r"^Found \d+ errors? \((\d+) fixed", re.MULTILINE)
E501_RE = re.compile(r"^(?:\S+:\d+:\d+: )?E501 Line too long", re.MULTILINE)
A2_LABELS = {"trim trailing whitespace", "fix end of files"}
A3_RE = re.compile(r"^[ \t]*error: \S.*: patch does not apply[ \t]*$", re.MULTILINE)
B1_RE = re.compile(r"^[ \t]*- Branch has a plan \(.+\) but commit is missing matching `Refs:` trailer\.", re.MULTILINE)
B2_RE = re.compile(r"^[ \t]*- Unknown type 'merge'\.", re.MULTILINE)
C2_RE = re.compile(
    r"^(?:/usr/bin/)?bash: (?:-c: )?line \d+: (?:unexpected EOF while looking for matching|"
    r"warning: here-document at line \d+ delimited by end-of-file)",
    re.MULTILINE,
)
C4_RE = re.compile(
    r"^(?:error: could not read file '-'|fatal: could not read log file '.+': No such file or directory)[ \t]*$",
    re.MULTILINE,
)

# ----------------------------------------------------------------------------------------------
# (g) писатели .py
# ----------------------------------------------------------------------------------------------
TOOL_WRITERS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
PY_TOKEN_RE = re.compile(r"""[^\s"'`;&|<>()=]+\.py\b""")
# запись python ищется в СЫРОМ тексте команды (код python — в кавычках или heredoc, маска его прячет)
PYWRITE_RE = re.compile(r"""write_text\(|\.write\(|\bopen\([^)\n]*['"][wa]\+?b?['"]""")
# команды с целями записи: у каждой цели записи свой разбор аргументов (write_targets)
CP_RE = re.compile(SEG + r"(?:cp|mv|install|rsync)(?![\w-])(?P<args>[^\n;&|]*)", re.MULTILINE)
SED_RE = re.compile(SEG + r"sed(?![\w-])(?P<args>[^\n;&|]*)", re.MULTILINE)
TEE_RE = re.compile(SEG + r"tee(?![\w-])(?P<args>[^\n;&|]*)", re.MULTILINE)
RESTORE_RE = re.compile(SEG + GITOPTS + r"(?:checkout|restore)(?![-\w])(?P<args>[^\n;&|]*)", re.MULTILINE)
FOR_RE = re.compile(SEG + r"for[ \t]+(?P<var>[A-Za-z_]\w*)[ \t]+in[ \t]+(?P<items>[^\n;&|]*)", re.MULTILINE)
REDIRECT_RE = re.compile(r"(?<![>&])>>?(?!F\d)[ \t]*")
RUFF_FORMAT_RE = re.compile(r"\bruff[ \t]+format\b")
# слова, при которых разбор вообще имеет смысл: остальные команды (ls, cat...) не трогаем
INTEREST_RE = re.compile(
    r"commit|merge|\.py|ruff|\badd\b|\brm\b|cherry-pick|\bpull\b|\bapply\b|\brebase\b|\breset\b|stash"
)


# ==============================================================================================
# 1. разбор текста команды
# ==============================================================================================
def strip_heredocs(text: str) -> str:
    """Снять тела heredoc (и строку-разделитель): заголовок остаётся в своей строке.

    Незакрытый heredoc, как в bash, съедает всё до конца команды.
    """
    out: list[str] = []
    waiting: list[str] = []  # разделители, чьё тело ещё читается (по порядку заголовков)
    for line in text.split("\n"):
        if waiting:
            if line.strip() == waiting[0]:
                waiting.pop(0)
            continue
        out.append(line)
        if "<<" in line:
            waiting.extend(m.group(2) for m in HEREDOC_RE.finditer(line))
    return "\n".join(out)


def mask_quotes(text: str) -> str:
    """Заменить СОДЕРЖИМОЕ кавычек на `Q` (кавычки остаются, длина текста сохраняется).

    Автомат многострочный: цитата может идти через строки; внутри `"…"` обратная косая
    экранирует следующий символ, внутри `'…'` — нет. Вне кавычек `\\x` пропускается парой.
    Незакрытая кавычка маскирует остаток текста (bash тоже читает до конца).
    """
    out: list[str] = []
    i, n = 0, len(text)
    special = re.compile(r"""[\\"']""")
    while i < n:
        m = special.search(text, i)
        if m is None:
            out.append(text[i:])
            break
        j = m.start()
        out.append(text[i:j])
        ch = text[j]
        if ch == "\\":
            out.append(text[j : j + 2])
            i = j + 2
        elif ch == "'":
            end = text.find("'", j + 1)
            end = n if end == -1 else end
            out.append("'" + "Q" * (end - j - 1) + ("'" if end < n else ""))
            i = end + 1
        else:  # двойная кавычка
            k = j + 1
            while k < n and text[k] != '"':
                k += 2 if text[k] == "\\" else 1
            k = min(k, n)
            out.append('"' + "Q" * (k - j - 1) + ('"' if k < n else ""))
            i = k + 1
    return "".join(out)


def normalise_redirects(masked: str) -> str:
    """`2>&1` → `2>F1`: убрать `&` из перенаправлений, не меняя длину текста."""
    return re.sub(r"(\d?)>&(\d)", r"\1>F\2", masked)


@dataclass(frozen=True)
class Invocation:
    kind: str  # "commit" | "merge"
    args_start: int  # смещение аргументов в тексте команды
    args: str
    pipeline: str  # от аргументов до конца конвейера


def find_invocations(masked: str) -> tuple[list[Invocation], int]:
    """Все `git … commit|merge` (кроме `--dry-run`, `--abort`, `--quit`) по порядку в тексте и число пропущенных."""
    found: list[Invocation] = []
    skipped = 0
    for kind, regex in (("commit", COMMIT_RE), ("merge", MERGE_RE)):
        for m in regex.finditer(masked):
            args = m.group("args")
            if kind == "commit" and "--dry-run" in args:
                skipped += 1
                continue
            if kind == "merge" and re.search(r"--(?:abort|quit)(?![-\w])", args):
                skipped += 1
                continue
            start = m.start("args")
            pipeline = PIPELINE_RE.match(masked, start).group(0)  # type: ignore[union-attr]
            found.append(Invocation(kind, start, args, pipeline))
    found.sort(key=lambda inv: inv.args_start)
    return found, skipped


@dataclass
class AddSpec:
    """Пути одной команды `git add|rm`: файлы `.py`, каталоги-префиксы, «все»."""

    files: list[str] = field(default_factory=list)
    dirs: list[str] = field(default_factory=list)
    everything: bool = False


def _words(args: str) -> list[str]:
    return [a or b or c for a, b, c in re.findall(r"\"([^\"]*)\"|'([^']*)'|(\S+)", args)]


def normalise_path(path: str) -> str:
    """Нижний регистр, `\\`→`/`, `/d/…` → `d:/…`, без ведущего `./`."""
    p = path.replace("\\", "/").lower()
    m = re.match(r"^/([a-z])/", p)
    if m:
        p = m.group(1) + ":/" + p[3:]
    while p.startswith("./"):
        p = p[2:]
    return p


def expand_vars(word: str, text: str) -> str:
    """Подставить `$VAR` / `${VAR}` из присваиваний `VAR=` той же команды; нераскрытое остаётся с `$`."""

    def value(m: re.Match[str]) -> str:
        found = _assigned_value(m.group(1) or m.group(2), text)
        return m.group(0) if found is None else found

    return re.sub(r"\$(?:\{(\w+)\}|(\w+))", value, word)


def parse_add(args: str, text: str = "") -> AddSpec:
    spec = AddSpec()
    words: list[str] = []
    for word in _words(args):
        # `F="a.py b.py"; git add $F` — раскрытая переменная даёт несколько слов, как в оболочке
        words.extend(expand_vars(word, text).split() if "$" in word else [word])
    for word in words:
        if word == "--":
            continue
        if word.startswith("-"):
            if word in ("-A", "--all", "-u", "--update", "-a"):
                spec.everything = True
        elif word in (".", "./"):
            spec.everything = True
        elif "$" in word or any(c in word for c in "*?["):
            continue  # нераскрытую переменную и шаблон без оболочки не раскрыть
        elif word.lower().endswith(".py"):
            spec.files.append(normalise_path(word))
        else:
            spec.dirs.append(normalise_path(word).rstrip("/"))
    return spec


def commit_takes_all(args: str) -> bool:
    """`git commit -a` / `--all` / кластер флагов с `a` (до первого флага с аргументом)."""
    for word in args.split():
        if word == "--all":
            return True
        if word.startswith("-") and not word.startswith("--"):
            for ch in word[1:]:
                if ch == "a":
                    return True
                if ch in "mFCcts":
                    break
    return False


# ----------------------------------------------------------------------------------------------
# (c) каталог попытки
# ----------------------------------------------------------------------------------------------
def _is_absolute(path: str) -> bool:
    return path.startswith("/") or re.match(r"^[A-Za-z]:/", path) is not None


def _read_word(text: str, pos: int) -> str:
    if text[pos] in "\"'":
        end = text.find(text[pos], pos + 1)
        return text[pos + 1 : len(text) if end == -1 else end]
    m = re.compile(r"[^\s;&|)]+").match(text, pos)
    return m.group(0) if m else ""


def _assigned_value(name: str, text: str) -> str | None:
    m = re.search(rf"(?<![\w$]){re.escape(name)}=(\"[^\"]*\"|'[^']*'|[^\s;&|]+)", text)
    return m.group(1).strip("\"'") if m else None


def resolve_cd(current: str, target: str, text: str) -> str:
    """Каталог после `cd target`; нераскрываемая цель оставляет прежний каталог."""
    m = re.match(r"\$\{?(\w+)\}?(.*)$", target)
    if m:
        value = _assigned_value(m.group(1), text)
        if value is None:
            return current
        target = value + m.group(2)
    if "$" in target or "`" in target or target.startswith("~") or target == "-":
        return current
    target = target.replace("\\", "/")
    path = target if _is_absolute(target) else f"{current}/{target}"
    return posixpath.normpath(path)


def attempt_directory(text: str, masked: str, cwd: str, first_start: int) -> str:
    """Последний `cd X` до первого `git … commit|merge`; иначе `cwd` записи."""
    current = cwd.replace("\\", "/")
    for m in CD_RE.finditer(masked):
        if m.start() >= first_start:
            break
        current = resolve_cd(current, _read_word(text, m.start("target")), text)
    return current


def in_repo(path: str) -> bool:
    p = path.lower().replace("\\", "/")
    return "inspector_vision/inspector_bottles" in p and "/temp/" not in p and "/tmp" not in p and "commitlab" not in p


# ----------------------------------------------------------------------------------------------
# (h) hidden
# ----------------------------------------------------------------------------------------------
def _is_filter(stage: str) -> bool:
    words = stage.split()
    if not words:
        return False
    program = posixpath.basename(words[0])
    if program in ("tail", "head"):
        return True
    if program == "grep":
        for flag in words[1:]:
            if flag == "--invert-match" or (re.fullmatch(r"-[A-Za-z]+", flag) and "v" in flag):
                return False
        return True
    return False


def hidden_flag(pipeline: str) -> bool:
    """Скрыт ли вывод команды: `2>/dev/null`, `&>/dev/null` или `2>&1 | tail|head|grep` (без `-v`)."""
    parts = re.split(r"(\|&|\|)", pipeline)
    command_stage = parts[0]
    if re.search(r"(?:2|&)>[ \t]*/dev/null", command_stage):
        return True
    stderr_in_pipe = "2>F1" in command_stage
    for i in range(1, len(parts), 2):
        if parts[i] == "|&":
            stderr_in_pipe = True
        if stderr_in_pipe and _is_filter(parts[i + 1]):
            return True
    return False


# ==============================================================================================
# 2. результат: классы, исход
# ==============================================================================================
def hook_blocks(text: str) -> list[tuple[str, str, str]]:
    """Блоки хуков (label, статус, тело): от строки статуса до следующей.

    STATUS_RE применяется к одной строке за раз и только к коротким строкам (настоящая строка статуса
    ~80 знаков): на одной строке в миллион точек ленивый `.*?` перед `\\.{3,}` был бы квадратичным.
    """
    found: list[tuple[int, int, re.Match[str]]] = []  # (начало строки, конец строки, совпадение)
    pos = 0
    for line in text.split("\n"):
        if len(line) <= STATUS_MAX_LINE:
            m = STATUS_RE.match(line)
            if m:
                found.append((pos, pos + len(line), m))
        pos += len(line) + 1
    blocks = []
    for i, (_, line_end, m) in enumerate(found):
        body_end = found[i + 1][0] if i + 1 < len(found) else len(text)
        blocks.append((m.group("label"), m.group("st"), text[line_end:body_end]))
    return blocks


def classify_result(text: str) -> list[str]:
    """Метки класса по тексту `tool_result` своей попытки (без разбивки A1 по писателю)."""
    found: set[str] = set()
    for label, status, body in hook_blocks(text):
        if status != "Failed":
            continue
        if label == "ruff format":
            found.add("A1")
        if RUFF_LABEL_RE.match(label):
            fixed = [int(n) for n in RUFF_FIXED_RE.findall(body)]
            if RUFF_MODIFIED_RE.search(body) or any(n >= 1 for n in fixed):
                found.add("A1-F401")
            if E501_RE.search(body):
                found.add("C1")
        if label in A2_LABELS:
            found.add("A2")
    for name, regex in (("A3", A3_RE), ("B1", B1_RE), ("B2", B2_RE), ("C2", C2_RE), ("C4", C4_RE)):
        if regex.search(text):
            found.add(name)
    return [row for row in CLASS_ROWS if row in found]


def outcome_of(classes: list[str], kinds: set[str], text: str) -> str:
    """failure — есть метка; success — строка успеха своего вида; иначе unknown."""
    if classes:
        return "failure"
    if "commit" in kinds and COMMIT_SUCCESS_RE.search(text):
        return "success"
    if "merge" in kinds and MERGE_SUCCESS_RE.search(text):
        return "success"
    return "unknown"


def result_text(content: object) -> str:
    """Текст `tool_result`: строка или список блоков; CRLF → LF."""
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        text = "\n".join(parts)
    else:
        text = ""
    return text.replace("\r\n", "\n")


# ==============================================================================================
# 3. A1 по писателю (g)
# ==============================================================================================
@dataclass
class Event:
    """Запись истории транскрипта: писатель `.py`, `git add|rm` или граница попытки."""

    kind: str  # "tool" | "bash" | "fmt" | "add" | "attempt"
    path: str = ""  # для "tool": нормализованный путь
    names: frozenset[str] = frozenset()  # для "bash"/"fmt": имена файлов (нижний регистр)
    everything: bool = False  # писатель трогает все файлы (merge, pull, ruff format без имён…)
    add: AddSpec | None = None


def same_file(tool_path: str, staged: str) -> bool:
    return tool_path == staged or tool_path.endswith("/" + staged) or staged.endswith("/" + tool_path)


def _is_py(word: str) -> bool:
    return "$" not in word and word.lower().endswith(".py")


def _base(path: str) -> str:
    return posixpath.basename(path.replace("\\", "/")).lower()


def _args_words(text: str, m: re.Match[str]) -> list[str]:
    """Слова аргументов без флагов (слова берём из текста: пути в кавычках в маске — это `Q`)."""
    return [w for w in _words(text[m.start("args") : m.end("args")]) if not w.startswith("-")]


def write_targets(raw: str, text: str, masked: str) -> frozenset[str]:
    """Имена `.py`, в которые команда ПИШЕТ (нижний регистр, без каталога).

    Цели записи: `>`/`>>`; последний аргумент `cp|mv|install|rsync` (каталог — тогда `.py`-источники);
    файлы `sed -i`; аргументы `tee`; пути `git checkout|restore`; элементы списка `for X in …; do … cp … $X`;
    python (`write_text(`, `.write(`, `open(…,'w'|'a')`) — по сырому тексту (с телами heredoc), имена — все
    `.py`-токены сырого текста. Аргументы `git add|rm|commit` и чтения именами записи не считаются.
    """
    names: set[str] = set()
    if PYWRITE_RE.search(raw):
        names.update(_base(t) for t in PY_TOKEN_RE.findall(raw))
    for m in REDIRECT_RE.finditer(masked):
        if m.end() < len(text):
            word = _read_word(text, m.end())
            if _is_py(word):
                names.add(_base(word))
    loops = {
        m.group("var"): [w for w in _words(text[m.start("items") : m.end("items")]) if _is_py(w)]
        for m in FOR_RE.finditer(masked)
    }
    for m in CP_RE.finditer(masked):
        words = _args_words(text, m)
        if not words:
            continue
        if _is_py(words[-1]):
            names.add(_base(words[-1]))
        else:
            names.update(_base(w) for w in words[:-1] if _is_py(w))
        args = text[m.start("args") : m.end("args")]
        for var, items in loops.items():
            if re.search(rf"\${{?{var}(?!\w)", args):
                names.update(_base(w) for w in items)
    for m in SED_RE.finditer(masked):
        if any(re.match(r"-[A-Za-z]*i|--in-place", w) for w in _words(text[m.start("args") : m.end("args")])):
            names.update(_base(w) for w in _args_words(text, m) if _is_py(w))
    for regex in (TEE_RE, RESTORE_RE):
        for m in regex.finditer(masked):
            names.update(_base(w) for w in _args_words(text, m) if _is_py(w))
    return frozenset(names)


def command_events(raw: str, text: str, masked: str) -> list[Event]:
    """События команды: `git add|rm`, писатели Bash (по целям записи), `ruff format`."""
    events: list[Event] = []
    for m in ADD_RE.finditer(masked):
        events.append(Event("add", add=parse_add(text[m.start("args") : m.end("args")], text)))
    if GLOBAL_WRITER_RE.search(masked):
        events.append(Event("bash", everything=True))
    written = write_targets(raw, text, masked)
    if written:
        events.append(Event("bash", names=written))
    if RUFF_FORMAT_RE.search(masked):
        named = frozenset(_base(t) for t in PY_TOKEN_RE.findall(text))
        events.append(Event("fmt", names=named, everything=not named))
    return events


@dataclass
class Composition:
    files: list[str] = field(default_factory=list)
    dirs: list[str] = field(default_factory=list)
    everything: bool = False


def compose(
    history: list[Event], since: int, call_start: int, same_adds: list[AddSpec], takes_all: bool
) -> Composition:
    """Состав коммита: `git add|rm` вызова до коммита; нет — `git add` предыдущих вызовов после прошлой попытки."""
    adds = list(same_adds) or [e.add for e in history[since:call_start] if e.kind == "add" and e.add]
    comp = Composition(everything=takes_all)
    for spec in adds:
        comp.files += spec.files
        comp.dirs += spec.dirs
        comp.everything = comp.everything or spec.everything
    return comp


def candidate_files(history: list[Event], since: int, comp: Composition) -> list[str]:
    """`.py` коммита: названные файлы; для «всех» и каталогов — записанные после прошлой попытки."""
    files = list(comp.files)
    if comp.everything or comp.dirs:
        for e in history[since:]:
            if e.kind == "tool":
                haystack = "/" + e.path
                if comp.everything or any(f"/{d}/" in haystack for d in comp.dirs):
                    files.append(e.path)
            elif e.kind in ("bash", "fmt") and comp.everything:
                files.extend(e.names)
    return list(dict.fromkeys(files))


def last_writer(history: list[Event], staged: str) -> str | None:
    base = posixpath.basename(staged)
    for e in reversed(history):
        if e.kind == "tool" and same_file(e.path, staged):
            return "tool"
        if e.kind in ("bash", "fmt") and (e.everything or base in e.names):
            return "bash" if e.kind == "bash" else "fmt"
    return None


def writer_split(history: list[Event], comp: Composition, since: int) -> str:
    """A1-Bash — есть писатель Bash; A1-Edit/Write — все писали Edit|Write; иначе A1-undecided."""
    writers = [last_writer(history, f) for f in candidate_files(history, since, comp)]
    if "bash" in writers:
        return "A1-Bash"
    if writers and all(w == "tool" for w in writers):
        return "A1-Edit/Write"
    return "A1-undecided"


# ==============================================================================================
# 4. сканирование транскриптов
# ==============================================================================================
@dataclass
class Attempt:
    tool_use_id: str
    kinds: set[str]
    classes: list[str]
    hidden: bool
    outcome: str


@dataclass
class ScanStats:
    malformed_lines: int = 0
    no_timestamp: int = 0
    no_result: int = 0
    not_executed: int = 0
    files: int = 0
    files_skipped_by_mtime: int = 0
    outside_repo: int = 0
    skipped_invocations: int = 0


class FileState:
    """История одного транскрипта: события писателей и граница прошлой попытки."""

    def __init__(self) -> None:
        self.events: list[Event] = []
        self.last_attempt = -1
        self.cwd = ""


@dataclass
class Pending:
    tool_use_id: str
    state: FileState
    kinds: set[str]
    hidden: bool
    in_window: bool
    since: int
    call_start: int
    upto: int
    same_adds: list[AddSpec]
    takes_all: bool


def local_date(timestamp: object) -> date | None:
    if not isinstance(timestamp, str):
        return None
    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone().date()
    except ValueError:
        return None


class TranscriptScanner:
    """Читает транскрипты построчно; склеивает `tool_use` и `tool_result`; дедуплицирует по `tool_use.id`."""

    def __init__(self, since: date, until: date, stats: ScanStats) -> None:
        self.since, self.until, self.stats = since, until, stats
        self.seen_ids: set[str] = set()
        self.pending: dict[str, Pending] = {}
        self.attempts: list[Attempt] = []

    # -- файл ------------------------------------------------------------------------------
    def scan_file(self, path: Path) -> None:
        self.stats.files += 1
        state = FileState()
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    record = None
                if not isinstance(record, dict):
                    self.stats.malformed_lines += 1
                    continue
                self.scan_record(record, state)

    def scan_record(self, record: dict, state: FileState) -> None:
        if isinstance(record.get("cwd"), str):
            state.cwd = record["cwd"]
        message = record.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            return
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                self.on_tool_use(block, record, state)
            elif block.get("type") == "tool_result":
                self.on_tool_result(block)

    # -- tool_use --------------------------------------------------------------------------
    def on_tool_use(self, block: dict, record: dict, state: FileState) -> None:
        tool_id = block.get("id")
        if not isinstance(tool_id, str) or tool_id in self.seen_ids:
            return
        self.seen_ids.add(tool_id)
        tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
        name = block.get("name")
        if name in TOOL_WRITERS:
            path = tool_input.get("file_path") or tool_input.get("notebook_path")
            if isinstance(path, str) and path.lower().endswith(".py"):
                state.events.append(Event("tool", path=normalise_path(path)))
        elif name == "Bash" and isinstance(tool_input.get("command"), str):
            self.on_bash(tool_id, tool_input["command"], record, state)

    def on_bash(self, tool_id: str, command: str, record: dict, state: FileState) -> None:
        if not INTEREST_RE.search(command):
            return
        text = strip_heredocs(command)
        masked = normalise_redirects(mask_quotes(text))
        call_start = len(state.events)
        state.events.extend(command_events(command, text, masked))
        invocations, skipped = find_invocations(masked)
        self.stats.skipped_invocations += skipped
        if not invocations:
            return
        first = invocations[0]
        cwd = record["cwd"] if isinstance(record.get("cwd"), str) else state.cwd
        if not in_repo(attempt_directory(text, masked, cwd, first.args_start)):
            self.stats.outside_repo += 1
            return
        day = local_date(record.get("timestamp"))
        if day is None:
            self.stats.no_timestamp += 1
        commit = next((inv for inv in invocations if inv.kind == "commit"), None)
        same_adds = [
            parse_add(text[m.start("args") : m.end("args")], text)
            for m in ADD_RE.finditer(masked)
            if m.start() < first.args_start
        ]
        self.pending[tool_id] = Pending(
            tool_use_id=tool_id,
            state=state,
            kinds={inv.kind for inv in invocations},
            hidden=any(hidden_flag(inv.pipeline) for inv in invocations),
            in_window=day is not None and self.since <= day <= self.until,
            since=state.last_attempt + 1,
            call_start=call_start,
            upto=len(state.events),
            same_adds=same_adds,
            takes_all=commit is not None and commit_takes_all(commit.args),
        )
        state.events.append(Event("attempt"))
        state.last_attempt = len(state.events) - 1

    # -- tool_result -----------------------------------------------------------------------
    def on_tool_result(self, block: dict) -> None:
        pending = self.pending.pop(block.get("tool_use_id"), None)  # type: ignore[arg-type]
        if pending is not None:
            self.finish(pending, result_text(block.get("content")))

    def finish(self, p: Pending, text: str) -> None:
        if NOT_EXECUTED_RE.match(text):
            if p.in_window:
                self.stats.not_executed += 1
            return
        classes = classify_result(text)
        if "A1" in classes:
            history = p.state.events[: p.upto]
            comp = compose(history, p.since, p.call_start, p.same_adds, p.takes_all)
            classes.append(writer_split(history, comp, p.since))
            # попытка с A1: хук переписал файлы коммита — для следующей попытки писатель «fmt»
            names = frozenset(posixpath.basename(f) for f in candidate_files(history, p.since, comp))
            p.state.events.append(Event("fmt", names=names, everything=comp.everything))
        if p.in_window:
            self.attempts.append(Attempt(p.tool_use_id, p.kinds, classes, p.hidden, outcome_of(classes, p.kinds, text)))

    def finish_all(self) -> None:
        """Попытки без `tool_result`: считаем исполненными, исход unknown."""
        for p in list(self.pending.values()):
            self.stats.no_result += 1
            self.finish(p, "")
        self.pending.clear()


def transcript_files(root: Path, project_substr: str, since: date, stats: ScanStats) -> Iterator[Path]:
    """`*.jsonl` каталогов проекта (включая `subagents/`); файлы с mtime раньше окна пропущены."""
    since_ts = datetime.combine(since, time.min).timestamp()
    for entry in sorted(os.scandir(root), key=lambda e: e.name):
        if entry.is_dir() and project_substr in entry.name:
            for path in sorted(Path(entry.path).rglob("*.jsonl")):
                if path.stat().st_mtime >= since_ts:
                    yield path
                else:
                    stats.files_skipped_by_mtime += 1


def iter_attempts(root: Path, project_substr: str, since: date, until: date, stats: ScanStats) -> list[Attempt]:
    scanner = TranscriptScanner(since, until, stats)
    for path in transcript_files(root, project_substr, since, stats):
        scanner.scan_file(path)
    scanner.finish_all()
    return scanner.attempts


# ==============================================================================================
# 5. таблица и вывод
# ==============================================================================================
def per100(count: int, total: int) -> float:
    return round(100.0 * count / total, 2) if total else 0.0


def table(attempts: list[Attempt], not_executed: int) -> dict:
    commit_calls = sum(1 for a in attempts if "commit" in a.kinds)
    merge_calls = sum(1 for a in attempts if "merge" in a.kinds)
    rows: dict[str, dict] = {}
    for row in ROW_ORDER:
        hit = [a for a in attempts if (a.hidden if row == "hidden" else row in a.classes)]
        commit = sum(1 for a in hit if "commit" in a.kinds)
        merge = sum(1 for a in hit if "merge" in a.kinds)
        rows[row] = {
            "commit": commit,
            "per100_commit": per100(commit, commit_calls),
            "merge": merge,
            "per100_merge": per100(merge, merge_calls),
        }
    return {
        "table": rows,
        "commit_calls": commit_calls,
        "merge_calls": merge_calls,
        "both_calls": sum(1 for a in attempts if {"commit", "merge"} <= a.kinds),
        "not_executed": not_executed,
        "any_failure": sum(1 for a in attempts if a.classes),
        "attempts": {
            a.tool_use_id: {"kinds": sorted(a.kinds), "classes": a.classes, "hidden": a.hidden, "outcome": a.outcome}
            for a in attempts
        },
    }


def render_markdown(report: dict) -> str:
    lines = [
        "| class | commit | per100_commit | merge | per100_merge |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in ROW_ORDER:
        r = report["table"][row]
        lines.append(f"| {row} | {r['commit']} | {r['per100_commit']:.2f} | {r['merge']} | {r['per100_merge']:.2f} |")
    lines.append("")
    for key in ("commit_calls", "merge_calls", "both_calls", "not_executed", "any_failure"):
        lines.append(f"{key}: {report[key]}")
    return "\n".join(lines)


def report_stats(stats: ScanStats) -> None:
    """Сводка пропусков и допущений — всегда в stderr; ненулевые пункты по строке. Пустой stderr не бывает."""
    print(
        f"classify: {stats.files} file(s) read, {stats.files_skipped_by_mtime} skipped (mtime before --since)",
        file=sys.stderr,
    )
    notes = [
        (stats.malformed_lines, "malformed JSONL line(s) skipped"),
        (stats.no_timestamp, "attempt(s) without a parsable timestamp (not counted in the window)"),
        (stats.no_result, "attempt(s) without tool_result (counted, outcome unknown)"),
        (stats.outside_repo, "attempt(s) outside the repo (cwd/cd outside it, or scratch/tmp/commitlab; not counted)"),
        (stats.skipped_invocations, "git commit/merge invocation(s) skipped (--dry-run, --abort, --quit)"),
    ]
    for count, text in notes:
        if count:
            print(f"classify: {count} {text}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Классификатор срывов git commit/merge по транскриптам Claude Code.")
    parser.add_argument("--root", required=True, type=Path, help="каталог projects с транскриптами")
    parser.add_argument("--since", required=True, type=date.fromisoformat, help="YYYY-MM-DD, включительно (местное)")
    parser.add_argument("--until", required=True, type=date.fromisoformat, help="YYYY-MM-DD, включительно (местное)")
    parser.add_argument("--project-substr", default=DEFAULT_PROJECT_SUBSTR, help="подстрока имени каталога проекта")
    parser.add_argument("--json", action="store_true", help="JSON вместо таблицы markdown")
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        parser.error(f"--root не каталог: {args.root}")
    stats = ScanStats()
    attempts = iter_attempts(args.root, args.project_substr, args.since, args.until, stats)
    report = table(attempts, stats.not_executed)
    print(json.dumps(report, ensure_ascii=False) if args.json else render_markdown(report))
    report_stats(stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
