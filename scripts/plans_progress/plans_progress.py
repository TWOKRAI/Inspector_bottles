#!/usr/bin/env python3
"""plans_progress — прогресс планов по единому эталону строки задачи (module-contract: new-lite).

Интерфейс (CLI, только stdlib)::

    python scripts/plans_progress/plans_progress.py [--root DIR] [--order PATH]
        [--json] [--html [PATH]] [--check] [--baseline PATH] [--sync-order]

* ``--root DIR``   каталог с ``plans/`` и ``plans/_archive/`` (по умолчанию корень репозитория);
* ``--order PATH`` ``ORDER.md`` (по умолчанию ``<root>/plans/queue/ORDER.md``); файла нет -> полосы
  и ярусы ``null``, не ошибка;
* ``--json``       stdout: список планов ``{plan, path, archived, lane, tier, done, total,
  dropped, unknown, tasks:[{id, title, status, ref}]}``;
* ``--html [PATH]`` самодостаточная страница (по умолчанию ``<root>/data/plans_progress.html``);
* ``--check``      печатает находки линта; exit 1, если есть блокирующая находка вне базы;
* ``--baseline P`` файл строк ``<план>:<КОД>`` (``<план>:<КОД>:<id>`` для UNKNOWN_STATUS и
  DUP_ID); находка из базы не блокирует (храповик: база только убывает).

Статусы задачи: ``done | pending | in_progress | blocked | deferred | superseded | unknown``.
``unknown`` (``?``) бывает только у пункта списка без слова набора.

Pre:  ``root/plans`` читается как каталог планов; файлы — UTF-8 (BOM и CRLF допустимы).
Post: файлы планов не пишутся. Пишут только два флага: ``--html`` — страницу по заданному пути
      (по умолчанию ``data/plans_progress.html``), ``--sync-order`` — строки между маркерами
      ``progress:begin``/``progress:end`` в ORDER.md (атомарно, остальные байты не меняются; писатель — лид
      на ``main``). ``done`` — число задач ``done``; ``total`` = всего - ``dropped`` (deferred +
      superseded) - ``unknown``.

Правила разбора (эталон) — ``plans/2026-10-02_plans-progress-dashboard.md``, «Формат задачи».
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# ----------------------------------------------------------------------------- статусы

CANON_BY_WORD = {
    "DONE": "done",
    "PENDING": "pending",
    "IN PROGRESS": "in_progress",
    "IN_PROGRESS": "in_progress",
    "BLOCKED": "blocked",
    "DEFERRED": "deferred",
    "SUPERSEDED": "superseded",
    "SKIPPED": "superseded",
    "CANCELLED": "superseded",
}
DROPPED = ("deferred", "superseded")

# Слово набора не примыкает к букве/цифре/`_`/`-`: `[DONE-ish]`, `[UNDONE]`, `[DONE_x]` — не статус.
_WORD_RE = re.compile(r"(?<![\w-])(IN[ _]PROGRESS|DONE|PENDING|BLOCKED|DEFERRED|SUPERSEDED|SKIPPED|CANCELLED)(?![\w-])")
_SNYATA_RE = re.compile(r"(?<![\w-])СНЯТА(?![\w-])")

# Id задачи (эталон): 1.3, 1.3a, 1b.2a, 1b.2b-pre, 1.3h-c-fix, T1.
ID_PATTERN = r"[A-Z]{0,2}[0-9]+[a-z]?(?:\.[0-9]+[a-z]*)?(?:-[a-z0-9]+)*"
ID_RE = re.compile(ID_PATTERN)
# Конец id: пробел или `: ~ * , ;`, точка не перед цифрой (`1.4.`), конец строки.
_ID_END = r"(?=[\s:~*,;]|\.(?!\d)|$)"

ITEM_RE = re.compile(
    r"^(?P<indent>[ \t]*)[-*+][ \t]+(?P<cb>\[[ xX]\][ \t]+)?(?P<pre>(?:\*\*|~~|__)*)"
    r"Task[ \t]+(?P<id>" + ID_PATTERN + r")" + _ID_END
)
BULLET_RE = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+")
HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t]*$")
HEAD_TASK_RE = re.compile(r"^(?:\*\*)?Task[ \t]+(?P<id>" + ID_PATTERN + r")" + _ID_END + r"(?P<rest>.*)$")
FENCE_RE = re.compile(r"^[ \t]*(?:```|~~~)")
# `Task <токен>` с цифрой, но не id по эталону (кириллическая `Т.1`): находка TASK_ID_UNPARSED
UNPARSED_ITEM_RE = re.compile(r"^[ \t]*[-*+][ \t]+(?:\[[ xX]\][ \t]+)?(?:\*\*|~~|__)*Task[ \t]+(?P<tok>\S*\d\S*)")
UNPARSED_HEAD_RE = re.compile(r"^(?:\*\*)?Task[ \t]+(?P<tok>\S*\d\S*)")
STATUS_LINE_RE = re.compile(r"\*\*Статус:?\*\*:?[ \t]*(?P<rest>.*)$")
CHECKBOX_RE = re.compile(r"^[ \t]*[-*+][ \t]+\[(?P<mark>[ xX])\]")
HASH_RE = re.compile(r"`([0-9a-f]{7,40})`")
PHASE_FILE_RE = re.compile(r"^phase-(\d+)[a-z]?(?:-[^.]*)?\.md$")
QUARTER_RE = re.compile(r"^\d{4}-Q[1-4]$")
DATED_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_")
TABLE_ID_RE = re.compile(r"^(?P<mark>[✓✔\s]*)(?P<id>T\d+(?:\.[A-Za-z0-9]+)?)(?=\s|$)")

SERVICE_NAMES = {"queue", "_archive", "QUEUE.md", "README.md"}
RESULT_FILE_RE = re.compile(r"\.result-.+\.md$")  # итоги задач `<план>.result-1.1.md` — не планы


def is_service_name(name: str) -> bool:
    return name.startswith(".") or name in SERVICE_NAMES or bool(RESULT_FILE_RE.search(name))


# ----------------------------------------------------------------------------- модель


@dataclass
class Task:
    id: str
    title: str
    status: str
    ref: str | None = None
    unmarked: bool = False  # задача из заголовка без признаков статуса: pending «по умолчанию»


@dataclass
class Plan:
    name: str
    rel: str
    archived: bool
    tasks: list[Task] = field(default_factory=list)
    dup_ids: list[str] = field(default_factory=list)  # id у двух и более пунктов списка
    dup_headings: list[str] = field(default_factory=list)  # id у двух и более заголовков
    conflicts: list[str] = field(default_factory=list)  # id со STATUS_CONFLICT
    unclosed_fence: list[str] = field(default_factory=list)  # файлы с нечётным числом ограждений
    unparsed: list[str] = field(default_factory=list)  # `Task <токен>` с неразобранным id
    bad_encoding: list[str] = field(default_factory=list)  # файлы не в UTF-8
    lane: str | None = None
    tier: str | None = None
    info: list[tuple[str, str]] = field(default_factory=list)  # из ORDER.md: (метка, текст)

    def count(self, status: str) -> int:
        return sum(1 for t in self.tasks if t.status == status)

    @property
    def unmarked(self) -> int:
        return sum(1 for t in self.tasks if t.unmarked)

    @property
    def dropped(self) -> int:
        return sum(self.count(s) for s in DROPPED)

    @property
    def unknown(self) -> int:
        return self.count("unknown")

    @property
    def done(self) -> int:
        return self.count("done")

    @property
    def total(self) -> int:
        return len(self.tasks) - self.dropped - self.unknown


@dataclass
class Finding:
    code: str
    plan: str
    task_id: str | None
    blocking: bool
    text: str

    @property
    def key(self) -> str:
        """Ключ базы: id входит только у UNKNOWN_STATUS и DUP_ID (новый id в известном плане не прячется)."""
        if self.code in ("UNKNOWN_STATUS", "DUP_ID") and self.task_id:
            return f"{self.plan}:{self.code}:{self.task_id}"
        return f"{self.plan}:{self.code}"

    def line(self, known: bool = False) -> str:
        who = self.plan + (f":{self.task_id}" if self.task_id else "")
        level = "blocking" if self.blocking else "info"
        tail = " (известна, в базе)" if known else ""
        return f"{self.code} {who} {level} — {self.text}{tail}"


# ----------------------------------------------------------------------------- чтение текста


def read_text(path: Path, bad: list[str] | None = None) -> str:
    """UTF-8 (BOM допустим), переводы строк нормализованы в LF.

    Файл не в UTF-8 читается с заменой символов, а его имя попадает в `bad` (находка NOT_UTF8).
    """
    raw = path.read_bytes()
    try:
        data = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        data = raw.decode("utf-8-sig", errors="replace")
        if bad is not None and path.name not in bad:
            bad.append(path.name)
    return data.replace("\r\n", "\n").replace("\r", "\n")


def natural_key(text: str) -> list:
    """Ключ естественной сортировки: `phase-2` раньше `phase-10`; типы по позициям чередуются."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text)]


def mask_code(text: str) -> str:
    """Код-спаны `…` заменяются на NUL той же длины: индексы совпадают с исходным текстом."""
    return re.sub(r"(`+)(.+?)\1", lambda m: "\x00" * len(m.group(0)), text, flags=re.S)


def clean_md(text: str, limit: int = 400) -> str:
    """Ячейка ORDER.md в простой текст: ссылки -> подпись, без `**` и обратных кавычек."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.replace("**", "").replace("`", "").replace("\\|", "|")
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# ----------------------------------------------------------------------------- статус из текста


def _groups(masked: str):
    """Верхнеуровневые группы `[...]` (с вложенностью); незакрытая идёт до конца текста."""
    i, n = 0, len(masked)
    while i < n:
        if masked[i] != "[":
            i += 1
            continue
        depth, j = 0, i
        while j < n:
            if masked[j] == "[":
                depth += 1
            elif masked[j] == "]":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        end = j + 1 if j < n else n
        yield i, end
        i = end


def canon_of(word: str) -> str:
    return CANON_BY_WORD[word.replace("_", " ")]


def find_status(text: str) -> tuple[str, int] | None:
    """Первая группа `[...]` со словом набора -> (статус, начало группы); иначе `СНЯТА` -> superseded."""
    masked = mask_code(text)
    for start, end in _groups(masked):
        m = _WORD_RE.search(masked, start, end)
        if m:
            return canon_of(m.group(1)), start
    m = _SNYATA_RE.search(masked)
    if m:
        return "superseded", m.start()
    return None


_TAIL_WORD_RE = re.compile(
    r"(?<![\w-])(DONE|ЗАКРЫТ[АО]?|СДЕЛАН[АО]?|SUPERSEDED|СНЯТА|DEFERRED|ОТЛОЖЕН[АО]?)(?![\w-])", re.IGNORECASE
)
_TAIL_CANON = {
    "DONE": "done",
    "ЗАКРЫТ": "done",
    "ЗАКРЫТА": "done",
    "ЗАКРЫТО": "done",
    "СДЕЛАН": "done",
    "СДЕЛАНА": "done",
    "СДЕЛАНО": "done",
    "SUPERSEDED": "superseded",
    "СНЯТА": "superseded",
    "DEFERRED": "deferred",
    "ОТЛОЖЕН": "deferred",
    "ОТЛОЖЕНА": "deferred",
    "ОТЛОЖЕНО": "deferred",
}
_TAIL_MARK_RE = re.compile(r"[✅✔✓]")
# После слова статуса допустимы только даты, хеши, пунктуация и скобочное пояснение до конца строки.
_TAIL_REST_RE = re.compile(
    r"^(?:[\s*+,;.:)\]\x00]|\d{4}-\d{2}-\d{2}|\d{1,2}-\d{2}|[0-9a-f]{7,40}(?!\w))*(?:\(.*)?$", re.DOTALL
)


def find_tail_status(rest: str) -> str | None:
    """Статус в строке заголовка вне `[...]`: `✅`, `— DONE 50df705f`, `(ЗАКРЫТА 2026-08-03)`.

    Слово считается статусом, только если после него идут даты, хеши и пояснение в скобках: слово в
    середине названия («починить DONE-детектор», «DONE: переключает…») статусом не является.
    `ЧАСТИЧНО` отсекает всё после себя: «⚠️ ЧАСТИЧНО (… шаг 3 отложен)» — не отложена, а не закрыта.
    """
    masked = mask_code(rest)
    partial = re.search(r"ЧАСТИЧНО", masked, re.IGNORECASE)
    limit = partial.start() if partial else len(masked)
    found: list[tuple[int, str]] = []
    mark = _TAIL_MARK_RE.search(masked)
    if mark and mark.start() < limit:
        found.append((mark.start(), "done"))
    for m in _TAIL_WORD_RE.finditer(masked):
        if m.start() < limit and _TAIL_REST_RE.match(masked[m.end() :]):
            found.append((m.start(), _TAIL_CANON[m.group(1).upper()]))
            break
    if found:
        return min(found)[1]
    return "pending" if partial else None


def find_bare_word(text: str) -> str | None:
    """Слово набора где угодно в тексте (для строки `**Статус:** BLOCKED`)."""
    m = _WORD_RE.search(mask_code(text))
    return canon_of(m.group(1)) if m else None


# ----------------------------------------------------------------------------- пункты раздела порядка


@dataclass
class Item:
    id: str
    title: str
    status: str
    ref: str | None
    indent: int
    conflict: bool = False


def is_section_title(title: str) -> bool:
    t = re.sub(r"[*_`]", "", title).strip().casefold()
    t = re.sub(r"^\d+[.)]\s*", "", t)  # нумерация: `3. Порядок выполнения`, `2) Execution order`
    return t.startswith(("порядок выполнения", "execution order")) or t == "порядок"


def _finish_item(m: re.Match, cont: list[str]) -> Item:
    first_rest = m.string[m.end() :]
    text = " ".join([first_rest.strip(), *cont]).strip()
    found = find_status(text)
    status = found[0] if found else "unknown"
    start = found[1] if found else len(text)
    ref = None
    if found:
        h = HASH_RE.search(text, start)
        ref = h.group(1) if h else None
    if status == "unknown" and "~~" in m.group("pre"):
        status = "superseded"  # `~~Task X.Y~~` без слова набора
    # название: первая строка без группы статуса
    title_src = first_rest
    first_found = find_status(first_rest)
    if first_found:
        title_src = first_rest[: first_found[1]]
    title = re.sub(r"^[\s:.\-—–*~_]+", "", title_src).replace("**", "").replace("~~", "").strip()
    title = " ".join(title.split())[:160]
    cb = m.group("cb")
    mark = cb.strip()[1] if cb else None
    mark = "x" if mark in ("x", "X") else mark
    conflict = False
    if mark == "x" and status not in ("done", "unknown"):
        conflict = True
    if mark == " " and status == "done":
        conflict = True
    return Item(
        id=m.group("id"),
        title=title,
        status=status,
        ref=ref,
        indent=len(m.group("indent").expandtabs(4)),
        conflict=conflict,
    )


def has_unclosed_fence(text: str) -> bool:
    """Нечётное число ограждений: разбор остаток файла после открытого ограждения пропускает."""
    return sum(1 for ln in text.split("\n") if FENCE_RE.match(ln)) % 2 == 1


def parse_items(text: str, unparsed: list[str] | None = None) -> tuple[list[Item], bool]:
    """Пункты `- Task <id>` раздела порядка -> (задачи после снятия родителей, были ли пункты вообще).

    Строки `- Task <токен>` с неразобранным id добавляются в `unparsed`.
    """
    items: list[Item] = []
    cur: tuple[re.Match, list[str]] | None = None
    sec_level: int | None = None
    in_fence = False

    def close() -> None:
        nonlocal cur
        if cur is not None:
            items.append(_finish_item(*cur))
            cur = None

    for line in text.split("\n"):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            close()
            continue
        if in_fence:
            continue
        hm = HEADING_RE.match(line)
        if hm:
            close()
            level = len(hm.group(1))
            if sec_level is not None and level <= sec_level:
                sec_level = None
            if sec_level is None and level >= 2 and is_section_title(hm.group(2)):
                sec_level = level
            continue
        if sec_level is None:
            continue
        if not line.strip():
            close()
            continue
        im = ITEM_RE.match(line)
        if im:
            close()
            cur = (im, [])
        elif BULLET_RE.match(line):
            close()
            bad = UNPARSED_ITEM_RE.match(line)
            if bad and unparsed is not None:
                unparsed.append(bad.group("tok"))
        elif cur is not None:
            cur[1].append(line.strip())
    close()

    kept: list[Item] = []
    for i, it in enumerate(items):
        # родитель без маркера, у которого следующий пункт глубже, — не задача
        if it.status == "unknown" and i + 1 < len(items) and items[i + 1].indent > it.indent:
            continue
        kept.append(it)
    return kept, bool(items)


# ----------------------------------------------------------------------------- задачи из заголовков


@dataclass
class HeadTask:
    id: str
    title: str
    status: str  # итоговый (для набора из заголовков)
    line_status: str | None  # слово набора в `**Статус:**` тела
    unmarked: bool = False  # нет `**Статус:**`, группы и хвоста в заголовке, чекбоксов


def _checkbox_status(body: list[str]) -> str:
    marks = [m.group("mark") for m in (CHECKBOX_RE.match(ln) for ln in body) if m]
    return "done" if marks and all(x in "xX" for x in marks) else "pending"


def _status_line(body: list[str]) -> str | None:
    for ln in body:
        m = STATUS_LINE_RE.search(ln)
        if m:
            return find_bare_word(m.group("rest"))
    return None


def parse_heading_tasks(text: str, unparsed: list[str] | None = None) -> list[HeadTask]:
    """Заголовки `#{2,6} Task <id>`; тело — до заголовка не глубже или до следующего Task-заголовка."""
    lines = text.split("\n")
    heads: list[tuple[int, int, re.Match]] = []  # (индекс строки, уровень, совпадение)
    other: list[tuple[int, int]] = []  # любые заголовки (индекс, уровень)
    in_fence = False
    for idx, line in enumerate(lines):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        hm = HEADING_RE.match(line)
        if not hm:
            continue
        level = len(hm.group(1))
        other.append((idx, level))
        tm = HEAD_TASK_RE.match(hm.group(2)) if level >= 2 else None
        if tm:
            heads.append((idx, level, tm))
        elif level >= 2 and unparsed is not None:
            bad = UNPARSED_HEAD_RE.match(hm.group(2))
            if bad:
                unparsed.append(bad.group("tok"))
    result: list[HeadTask] = []
    for idx, level, tm in heads:
        end = len(lines)
        for j, lv in other:
            if j <= idx:
                continue
            is_task = any(h[0] == j for h in heads)
            if lv <= level or is_task:
                end = j
                break
        body = lines[idx + 1 : end]
        line_status = _status_line(body)
        rest = tm.group("rest")
        group = find_status(rest)
        title = re.sub(r"^[\s:.\-—–*~_]+", "", rest[: group[1]] if group else rest).replace("**", "").strip()
        tail = None if (line_status or group) else find_tail_status(rest)
        if line_status:
            status = line_status
        elif group:
            status = group[0]
        elif tail:
            status = tail
        else:
            status = _checkbox_status(body)
        unmarked = not (line_status or group or tail or any(CHECKBOX_RE.match(ln) for ln in body))
        result.append(HeadTask(tm.group("id"), " ".join(title.split())[:160], status, line_status, unmarked))
    return result


# ----------------------------------------------------------------------------- таблица `✓` и tasks/<id>.md


def parse_table_tasks(text: str) -> list[Task]:
    tasks: list[Task] = []
    in_fence = False
    for line in text.split("\n"):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip())]
        cells = cells[1:-1] if cells and cells[0] == "" and cells[-1] == "" else cells
        if not cells:
            continue
        first = cells[0].replace("*", "").replace("`", "").strip()
        m = TABLE_ID_RE.match(first)
        if not m:
            continue
        tid = m.group("id")
        if tid.endswith(".x"):
            continue
        status = "done" if "✓" in m.group("mark") or "✔" in m.group("mark") else "pending"
        title = clean_md(cells[1], 160) if len(cells) > 1 else ""
        tasks.append(Task(tid, title, status))
    return tasks


def parse_task_file(path: Path, bad: list[str] | None = None) -> Task | None:
    if not ID_RE.fullmatch(path.stem):
        return None
    body = read_text(path, bad).split("\n")
    title = ""
    for ln in body:
        hm = HEADING_RE.match(ln)
        if hm:
            tm = HEAD_TASK_RE.match(hm.group(2))
            if tm:
                title = " ".join(re.sub(r"^[\s:.\-—–*~_]+", "", tm.group("rest")).split())[:160]
            break
    line_status = _status_line(body)
    status = line_status or _checkbox_status(body)
    unmarked = not line_status and not any(CHECKBOX_RE.match(ln) for ln in body)
    return Task(path.stem, title, status, None, unmarked)


# ----------------------------------------------------------------------------- план целиком


def _dedupe_first(tasks: list[Task]) -> list[Task]:
    seen: set[str] = set()
    out = []
    for t in tasks:
        if t.id not in seen:
            seen.add(t.id)
            out.append(t)
    return out


def analyze_plan(name: str, main: Path, plan_dir: Path | None, rel: str, archived: bool) -> Plan:
    """Набор задач (N1): пункты раздела порядка; иначе заголовки -> таблица `✓` -> tasks/<id>.md."""
    plan = Plan(name=name, rel=rel, archived=archived)
    main_text = read_text(main, plan.bad_encoding) if main.is_file() else ""

    head_files: list[tuple[str, str]] = [(main.name, main_text)] if main.is_file() else []
    table_texts: list[str] = [main_text] if main.is_file() else []
    task_files: list[Path] = []
    fence_texts: list[tuple[str, str]] = list(head_files)  # файлы, где ищем незакрытое ограждение
    if plan_dir is not None:
        siblings = sorted((p for p in plan_dir.iterdir() if p.is_file()), key=lambda p: natural_key(p.name))
        for p in siblings:
            if PHASE_FILE_RE.match(p.name):
                head_files.append((p.name, read_text(p, plan.bad_encoding)))
                fence_texts.append(head_files[-1])
        for p in siblings:
            if p.name == "tasks.md" or (p.name.startswith("tasks-") and p.suffix == ".md"):
                table_texts.append(read_text(p, plan.bad_encoding))
                fence_texts.append((p.name, table_texts[-1]))
        tdir = plan_dir / "tasks"
        if tdir.is_dir():
            task_files = sorted((p for p in tdir.glob("*.md") if p.is_file()), key=lambda p: natural_key(p.name))

    plan.unclosed_fence = [name_ for name_, text in fence_texts if has_unclosed_fence(text)]
    heads: list[HeadTask] = []
    for _fname, text in head_files:
        heads.extend(parse_heading_tasks(text, plan.unparsed))
    counts: dict[str, int] = {}
    for h in heads:
        counts[h.id] = counts.get(h.id, 0) + 1
    plan.dup_headings = [i for i, c in counts.items() if c > 1]

    items, had_items = parse_items(main_text, plan.unparsed)
    if had_items:
        plan.tasks = [Task(it.id, it.title, it.status, it.ref) for it in items]
        seen: dict[str, int] = {}
        for it in items:
            seen[it.id] = seen.get(it.id, 0) + 1
        plan.dup_ids = [i for i, c in seen.items() if c > 1]
        conflicts: list[str] = []
        by_id: dict[str, str] = {}
        for it in items:
            by_id.setdefault(it.id, it.status)
            if it.conflict and it.id not in conflicts:
                conflicts.append(it.id)
        for h in heads:
            st = by_id.get(h.id)
            if st and st != "unknown" and h.line_status and h.line_status != st and h.id not in conflicts:
                conflicts.append(h.id)
        plan.conflicts = conflicts
        return plan

    if heads:
        plan.tasks = _dedupe_first([Task(h.id, h.title, h.status, None, h.unmarked) for h in heads])
        return plan
    table: list[Task] = []
    for text in table_texts:
        table.extend(parse_table_tasks(text))
    if table:
        plan.tasks = _dedupe_first(table)
        return plan
    files = [t for t in (parse_task_file(p, plan.bad_encoding) for p in task_files) if t]
    plan.tasks = _dedupe_first(files)
    return plan


# ----------------------------------------------------------------------------- поиск планов


def _plan_entries(base: Path, archived: bool, root: Path) -> list[Plan]:
    plans: list[Plan] = []
    if not base.is_dir():
        return plans
    for entry in sorted(base.iterdir(), key=lambda p: p.name):
        n = entry.name
        if is_service_name(n):
            continue
        if entry.is_file() and entry.suffix == ".md":
            plans.append(analyze_plan(entry.stem, entry, None, entry.relative_to(root).as_posix(), archived))
        elif entry.is_dir():
            main = entry / "plan.md"
            rel = (main if main.is_file() else entry).relative_to(root).as_posix()
            plans.append(analyze_plan(n, main, entry, rel, archived))
    return plans


def discover(root: Path) -> list[Plan]:
    plans_dir = root / "plans"
    plans = _plan_entries(plans_dir, False, root)
    arch = plans_dir / "_archive"
    if arch.is_dir():
        for entry in sorted(arch.iterdir(), key=lambda p: p.name):
            if entry.name.startswith(".") or RESULT_FILE_RE.search(entry.name):
                continue
            if entry.is_dir() and QUARTER_RE.match(entry.name):
                plans.extend(_plan_entries(entry, True, root))
            elif entry.name != "README.md":
                if entry.is_file() and entry.suffix == ".md":
                    plans.append(analyze_plan(entry.stem, entry, None, entry.relative_to(root).as_posix(), True))
                elif entry.is_dir():
                    main = entry / "plan.md"
                    rel = (main if main.is_file() else entry).relative_to(root).as_posix()
                    plans.append(analyze_plan(entry.name, main, entry, rel, True))
    return plans


# ----------------------------------------------------------------------------- ORDER.md


@dataclass
class OrderRow:
    tier: str
    name: str
    lane: str | None
    info: list[tuple[str, str]]


_TIER_HEAD_RE = re.compile(r"^#{2,6}[ \t]+4\.([123])(?!\d)")
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def _name_from_href(href: str) -> str | None:
    href = href.split("#", 1)[0].strip()
    if not href or re.match(r"^[a-z]+://", href):
        return None
    parts = [p for p in href.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    if not parts:
        return None
    if parts[-1] == "plan.md" and len(parts) >= 2:
        return parts[-2]
    last = parts[-1]
    return last[:-3] if last.endswith(".md") else last


def parse_order(path: Path) -> list[OrderRow]:
    """Таблицы §4.1/4.2/4.3 `ORDER.md`: порядок строк, полоса (только §4.1), связь по basename плана."""
    if not path.is_file():
        return []
    rows: list[OrderRow] = []
    seen: set[str] = set()
    tier: str | None = None
    for line in read_text(path).split("\n"):
        hm = HEADING_RE.match(line)
        if hm:
            tm = _TIER_HEAD_RE.match(line)
            tier = f"4.{tm.group(1)}" if tm else None
            continue
        if tier is None or not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip())]
        cells = cells[1:-1] if cells and cells[0] == "" and cells[-1] == "" else cells
        if not cells:
            continue
        names = [n for n in (_name_from_href(h) for h in _LINK_RE.findall(cells[0])) if n]
        if not names:
            continue
        lane: str | None = None
        info: list[tuple[str, str]] = []

        def cell(i: int) -> str:
            return clean_md(cells[i]) if len(cells) > i else ""

        if tier == "4.1":
            lane_raw = cell(1)
            lane = None if lane_raw in ("", "—", "-", "–") else lane_raw
            info = [("Статус", cell(2)), ("Следующий шаг", cell(3))]
        elif tier == "4.2":
            info = [("Остаток", cell(1)), ("Триггер", cell(2))]
        else:
            info = [("Факт", cell(1))]
        for n in names:
            if n not in seen:
                seen.add(n)
                rows.append(OrderRow(tier, n, lane, [(k, v) for k, v in info if v]))
    return rows


def apply_order(plans: list[Plan], rows: list[OrderRow]) -> None:
    by_name = {r.name: r for r in rows}
    for p in plans:
        r = by_name.get(p.name)
        if r:
            p.tier, p.lane, p.info = r.tier, r.lane, r.info


def page_order(plans: list[Plan], rows: list[OrderRow]) -> tuple[list[Plan], list[Plan]]:
    """(живые в порядке страницы, архив): §4.1 -> §4.2 -> §4.3 по строкам, затем вне ORDER.md по имени."""
    live = [p for p in plans if not p.archived]
    ordered: list[Plan] = []
    used: set[int] = set()
    for r in rows:
        for p in live:
            if p.name == r.name and id(p) not in used:
                used.add(id(p))
                ordered.append(p)
    rest = sorted((p for p in live if id(p) not in used), key=lambda p: p.name)
    archive = sorted((p for p in plans if p.archived), key=lambda p: p.name)
    return ordered + rest, archive


# ----------------------------------------------------------------------------- находки


def build_findings(plans: list[Plan]) -> list[Finding]:
    """Находки живых планов; архивные планы линт не смотрит (формат старый, шкала без находок)."""
    out: list[Finding] = []
    for p in plans:
        if p.archived:
            continue
        in_41 = p.tier == "4.1"
        if not p.tasks:
            out.append(Finding("NO_TASKS", p.name, None, in_41, "в плане не найдено ни одной задачи"))
        if p.unclosed_fence:
            files = ", ".join(p.unclosed_fence)
            text = f"нечётное число ограждений кода, остаток файла не разобран: {files}"
            out.append(Finding("UNCLOSED_FENCE", p.name, None, in_41, text))
        if p.unparsed:
            text = f"строк Task с неразобранным id: {len(p.unparsed)} (первая: «{p.unparsed[0]}»)"
            out.append(Finding("TASK_ID_UNPARSED", p.name, None, False, text))
        if p.bad_encoding:
            out.append(Finding("NOT_UTF8", p.name, None, False, f"файл не в UTF-8: {', '.join(p.bad_encoding)}"))
        for t in p.tasks:
            if t.status == "unknown":
                out.append(
                    Finding("UNKNOWN_STATUS", p.name, t.id, in_41, f"пункт Task {t.id} без слова набора статуса")
                )
        for i in p.dup_ids:
            out.append(Finding("DUP_ID", p.name, i, True, f"id {i} у двух и более пунктов списка"))
        for i in p.dup_headings:
            out.append(Finding("DUP_HEADING", p.name, i, False, f"заголовок Task {i} встречается повторно"))
        for i in p.conflicts:
            out.append(Finding("STATUS_CONFLICT", p.name, i, False, "пункт списка и второй статус расходятся"))
        if not DATED_NAME_RE.match(p.name):
            out.append(Finding("NO_DATE_IN_NAME", p.name, None, False, "в имени нет даты: close план не примет"))
        if p.unmarked:
            out.append(
                Finding(
                    "NO_STATUS_MARK",
                    p.name,
                    None,
                    False,
                    f"{p.unmarked} из {len(p.tasks)} задач без отметки статуса, считаются PENDING",
                )
            )
        st = {t.status for t in p.tasks}
        if p.tasks and not (st & {"unknown", "pending", "in_progress", "blocked"}) and "done" in st:
            out.append(Finding("ALL_DONE_NOT_ARCHIVED", p.name, None, False, "все задачи закрыты, план не в архиве"))
    return out


def load_baseline(path: Path) -> set[str]:
    keys: set[str] = set()
    for ln in read_text(path).split("\n"):
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            keys.add(ln)
    return keys


# ----------------------------------------------------------------------------- блок прогресса в ORDER.md

BEGIN_MARK = "<!-- progress:begin -->"
END_MARK = "<!-- progress:end -->"


def block_lines(live: list[Plan], archive: list[Plan]) -> list[str]:
    """Строки блока: по строке на живой план (порядок страницы) и счётчик архива. Шкала — та же `_tally`."""
    return [f"- {p.name} — {_tally(p.done, p.total)}" for p in live] + [f"в архиве: {len(archive)}"]


def locate_block(lines: list[str]) -> tuple[int, int] | str:
    """Индексы строк маркеров (begin, end) или текст ошибки. Маркер — строка целиком (пробелы по краям не в счёт)."""
    marks = [(i, ln.strip()) for i, ln in enumerate(lines) if ln.strip() in (BEGIN_MARK, END_MARK)]
    kinds = [m[1] for m in marks]
    if kinds == [BEGIN_MARK, END_MARK]:
        return marks[0][0], marks[1][0]
    return (
        f"нужна ровно одна пара маркеров {BEGIN_MARK} / {END_MARK} отдельными строками, "
        f"найдено: progress:begin {kinds.count(BEGIN_MARK)}, progress:end {kinds.count(END_MARK)}"
        + ("" if sorted(kinds) != [BEGIN_MARK, END_MARK] else "; progress:end стоит раньше progress:begin")
    )


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", errors="surrogateescape")


def sync_order(order: Path, live: list[Plan], archive: list[Plan]) -> tuple[int, str]:
    """Переписывает только строки между маркерами; остальные байты (и EOL файла) не трогает.

    Возвращает (код, сообщение): 0 — готово или уже актуально, 2 — файла или маркеров нет, файл не менялся.
    """
    if not order.is_file():
        return 2, f"ошибка --sync-order: нет файла ORDER: {order}"
    raw = order.read_bytes()
    text = _decode(raw)
    lines = text.split("\n")
    found = locate_block(lines)
    if isinstance(found, str):
        return 2, f"ошибка --sync-order: {order}: {found}"
    begin, end = found
    eol_tail = "\r" if "\r\n" in text else ""
    new_lines = lines[: begin + 1] + [ln + eol_tail for ln in block_lines(live, archive)] + lines[end:]
    new_text = "\n".join(new_lines)
    if new_text == text:
        return 0, f"ORDER уже актуален: {order}"
    # атомарно: временный файл рядом + os.replace; при сбое ORDER не тронут, временный файл удалён
    tmp = order.with_name(f".{order.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(new_text.encode("utf-8", errors="surrogateescape"))
        os.replace(tmp, order)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return 0, f"ORDER обновлён: {order}"


def on_main_branch(root: Path) -> bool:
    """`main` только если root — корень git-репозитория (вложенный в чужой репозиторий корень — не main)."""

    def git(*args: str) -> str | None:
        try:
            cp = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        return cp.stdout.strip() if cp.returncode == 0 else None

    # `branch --show-current`, а не `rev-parse --abbrev-ref HEAD`: тег `main` на detached HEAD даёт `heads/main`
    top, branch = git("rev-parse", "--show-toplevel"), git("branch", "--show-current")
    if not top or branch != "main":
        return False
    try:
        return os.path.samefile(top, root)
    except OSError:
        return False


def order_block_findings(order: Path, live: list[Plan], archive: list[Plan], root: Path) -> list[Finding]:
    """Дрейф блока: проверяется только на `main`, в ветках, detached HEAD и вне git — нет."""
    if not order.is_file() or not on_main_branch(root):
        return []
    lines = _decode(order.read_bytes()).split("\n")
    found = locate_block(lines)
    if isinstance(found, str):
        return [Finding("ORDER_BLOCK_MISSING", order.name, None, True, f"нет блока прогресса: {found}")]
    body = [ln.rstrip("\r") for ln in lines[found[0] + 1 : found[1]]]
    if body != block_lines(live, archive):
        return [
            Finding(
                "ORDER_BLOCK_STALE",
                order.name,
                None,
                True,
                "блок прогресса устарел: python scripts/plans_progress/plans_progress.py --sync-order",
            )
        ]
    return []


def run_check(plans: list[Plan], baseline: set[str], out, extra: list[Finding] | None = None) -> int:
    findings = build_findings(plans) + list(extra or [])
    checked = sum(1 for p in plans if not p.archived)
    new_blocking = 0
    blocking = 0
    present = set()
    for f in findings:
        known = f.blocking and f.key in baseline
        if f.blocking:
            blocking += 1
            present.add(f.key)
            if not known:
                new_blocking += 1
        print(f.line(known), file=out)
    info = len(findings) - blocking
    stale = len(baseline - present)
    print(
        f"Итог: проверено планов {checked}; блокирующих {blocking}, из них новых {new_blocking}; "
        f"информационных {info}; устаревших строк базы {stale}",
        file=out,
    )
    return 1 if new_blocking else 0


# ----------------------------------------------------------------------------- JSON


def to_json(plans: list[Plan]) -> str:
    data = [
        {
            "plan": p.name,
            "path": p.rel,
            "archived": p.archived,
            "lane": p.lane,
            "tier": p.tier,
            "done": p.done,
            "total": p.total,
            "dropped": p.dropped,
            "unknown": p.unknown,
            "unmarked": p.unmarked,
            "tasks": [{"id": t.id, "title": t.title, "status": t.status, "ref": t.ref} for t in p.tasks],
        }
        for p in plans
    ]
    return json.dumps(data, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------------- HTML

CSS = """
:root{--bg:#fafafa;--fg:#1d2024;--muted:#5d6670;--card:#fff;--line:#d9dde2;--accent:#2f6fdb;
--done:#2e9d56;--pending:#c3c9d1;--in_progress:#e0a21a;--blocked:#d6453d;--deferred:#8d96a3;
--superseded:#b9a6c9;--unknown:#e68a00}
@media (prefers-color-scheme: dark){:root{--bg:#14171a;--fg:#e4e7ea;--muted:#98a2ad;--card:#1d2126;
--line:#323841;--accent:#6ea0ff;--done:#43b56c;--pending:#4a525d;--in_progress:#e6b13a;
--blocked:#e5645c;--deferred:#76808d;--superseded:#8d7ba0;--unknown:#f0a030}}
*{box-sizing:border-box}
body{margin:0;padding:16px;background:var(--bg);color:var(--fg);
font:15px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1000px;margin:0 auto}
h1{font-size:1.4rem;margin:0 0 4px}
.meta{color:var(--muted);font-size:.85rem;margin-bottom:16px}
.lanes{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:8px;margin-bottom:16px}
.lane{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.lane b{display:block;margin-bottom:2px}
details.plan,details#archive{background:var(--card);border:1px solid var(--line);border-radius:8px;
margin-bottom:8px;padding:0 12px}
details#archive>details.plan{margin:8px 0}
summary{cursor:pointer;padding:9px 0;display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center}
summary .name{font-weight:600}
.badge{font-size:.75rem;color:var(--muted);border:1px solid var(--line);border-radius:10px;padding:0 7px}
progress{width:140px;height:10px;accent-color:var(--accent)}
.tally{font-variant-numeric:tabular-nums;font-size:.85rem}
.body{padding:2px 0 10px}
.info{margin:2px 0;color:var(--muted);font-size:.85rem}
.cells{display:flex;flex-wrap:wrap;gap:3px;margin:8px 0}
.cell{display:inline-block;min-width:34px;padding:1px 5px;border-radius:4px;font-size:.72rem;
text-align:center;color:#fff;background:var(--pending)}
.cell[data-status="done"]{background:var(--done)}
.cell[data-status="in_progress"]{background:var(--in_progress)}
.cell[data-status="blocked"]{background:var(--blocked)}
.cell[data-status="deferred"]{background:var(--deferred)}
.cell[data-status="superseded"]{background:var(--superseded)}
.cell[data-status="unknown"]{background:var(--unknown)}
ul.tasks{margin:0;padding-left:0;list-style:none;font-size:.88rem}
ul.tasks li{padding:2px 0;border-top:1px solid var(--line)}
.st{display:inline-block;min-width:92px;color:var(--muted);font-size:.78rem}
code{font-size:.8rem;color:var(--muted)}
.chip.warn{font-size:.75rem;color:var(--in_progress);border:1px solid var(--in_progress);
border-radius:10px;padding:0 7px}
.cell[data-unmarked="1"]{outline:2px dashed var(--in_progress);outline-offset:-2px}
"""

STATUS_RU = {
    "done": "готово",
    "pending": "ожидает",
    "in_progress": "в работе",
    "blocked": "заблокировано",
    "deferred": "отложено",
    "superseded": "снято",
    "unknown": "статус не задан",
}


def _e(text: object) -> str:
    return html.escape(str(text), quote=True)


def _tally(done: int, total: int) -> str:
    if total <= 0:
        return f"{done} из {total}"
    return f"{done} из {total} · {int(100 * done / total + 0.5)}%"


def _plan_html(p: Plan) -> str:
    attrs = f'class="plan" data-plan="{_e(p.name)}" data-tier="{_e(p.tier or "")}" data-lane="{_e(p.lane or "")}"'
    s = [f"<details {attrs}>", "<summary>", f'<span class="name">{_e(p.name)}</span>']
    if p.lane:
        s.append(f'<span class="badge">полоса {_e(p.lane)}</span>')
    if p.tier:
        s.append(f'<span class="badge">§{_e(p.tier)}</span>')
    if p.tasks:
        s.append(f'<progress value="{p.done}" max="{max(p.total, 1)}"></progress>')
        extra = []
        if p.dropped:
            extra.append(f"снято/отложено {p.dropped}")
        if p.unknown:
            extra.append(f"без статуса {p.unknown}")
        tail = f" ({', '.join(extra)})" if extra else ""
        s.append(f'<span class="tally">{_e(_tally(p.done, p.total) + tail)}</span>')
        if p.unmarked:
            s.append(
                '<span class="chip warn" data-chip="unmarked" '
                'title="статус не размечен, цифра может быть занижена">'
                f"⚠ {p.unmarked} без отметки</span>"
            )
    else:
        s.append('<span class="tally">нет задач в эталонном формате</span>')
    s.append("</summary>")
    s.append('<div class="body">')
    s.append(f'<div class="info">{_e(p.rel)}</div>')
    for label, text in p.info:
        s.append(f'<div class="info"><b>{_e(label)}:</b> {_e(text)}</div>')
    if p.tasks:
        s.append('<div class="cells">')
        for t in p.tasks:
            tip = f"{t.id} — {t.title} [{STATUS_RU[t.status]}]"
            mark = ' data-unmarked="1"' if t.unmarked else ""
            s.append(f'<span class="cell" data-status="{t.status}"{mark} title="{_e(tip)}">{_e(t.id)}</span>')
        s.append("</div>")
        s.append('<ul class="tasks">')
        for t in p.tasks:
            ref = f" <code>{_e(t.ref)}</code>" if t.ref else ""
            s.append(
                f'<li data-status="{t.status}"><span class="st">{STATUS_RU[t.status]}</span>'
                f"<b>{_e(t.id)}</b> {_e(t.title)}{ref}</li>"
            )
        s.append("</ul>")
    s.append("</div>")
    s.append("</details>")
    return "\n".join(s)


def git_sha(root: Path) -> str:
    try:
        cp = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "—"
    sha = cp.stdout.strip()
    return sha if cp.returncode == 0 and sha else "—"


def to_html(live: list[Plan], archive: list[Plan], root: Path) -> str:
    lanes: dict[str, list[int]] = {}
    for p in live:
        agg = lanes.setdefault(p.lane or "—", [0, 0, 0])
        agg[0] += p.done
        agg[1] += p.total
        agg[2] += 1
    built = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M UTC%z")
    parts = [
        "<!doctype html>",
        '<html lang="ru"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Прогресс планов</title>",
        f"<style>{CSS}</style></head><body><main>",
        "<h1>Прогресс планов</h1>",
        f'<div class="meta">собрано {_e(built)} · SHA {_e(git_sha(root))} · живых планов {len(live)}, '
        f"в архиве {len(archive)}</div>",
        '<section class="lanes">',
    ]
    for lane, (done, total, n) in lanes.items():
        parts.append(
            f'<div class="lane"><b>Полоса {_e(lane)} · планов {n}</b>'
            f'<progress value="{done}" max="{max(total, 1)}"></progress> '
            f'<span class="tally">{_e(_tally(done, total))}</span></div>'
        )
    parts.append("</section>")
    parts.extend(_plan_html(p) for p in live)
    a_done = sum(p.done for p in archive)
    a_total = sum(p.total for p in archive)
    parts.append('<details id="archive">')
    parts.append(f"<summary>Архив · {len(archive)} планов · итого {_e(_tally(a_done, a_total))}</summary>")
    parts.extend(_plan_html(p) for p in archive)
    parts.append("</details>")
    parts.append("</main></body></html>")
    return "\n".join(parts) + "\n"


# ----------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Прогресс планов по единому эталону строки задачи")
    ap.add_argument("--root", type=Path, default=REPO_ROOT, help="каталог с plans/ (по умолчанию корень репозитория)")
    ap.add_argument("--order", type=Path, default=None, help="ORDER.md (по умолчанию <root>/plans/queue/ORDER.md)")
    ap.add_argument("--json", action="store_true", help="список планов в JSON на stdout")
    ap.add_argument(
        "--html", nargs="?", const="", default=None, metavar="PATH", help="страница (data/plans_progress.html)"
    )
    ap.add_argument("--check", action="store_true", help="линт; exit 1 при блокирующей находке вне базы")
    ap.add_argument("--baseline", type=Path, default=None, help="файл известных блокирующих находок")
    ap.add_argument("--sync-order", action="store_true", help="переписать блок прогресса между маркерами в ORDER.md")
    return ap


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    root: Path = args.root.resolve()
    order_path = args.order if args.order is not None else root / "plans" / "queue" / "ORDER.md"
    if args.check:
        # молчаливый зелёный на пустом корне хуже красного: --check обязан что-то проверить
        if not (root / "plans").is_dir():
            print(f"ошибка: нет каталога plans/ в корне {root}", file=sys.stderr)
            return 2
        if args.baseline is not None and not args.baseline.is_file():
            print(f"ошибка: база не найдена: {args.baseline}", file=sys.stderr)
            return 2
    plans = discover(root)
    if args.check and not any(not p.archived for p in plans):
        print(f"ошибка: в {root / 'plans'} нет ни одного живого плана", file=sys.stderr)
        return 2
    rows = parse_order(order_path)
    apply_order(plans, rows)
    live, archive = page_order(plans, rows)
    ordered = live + archive
    code = 0

    if args.sync_order:
        code, message = sync_order(order_path, live, archive)
        print(message, file=sys.stderr if (args.json or code) else sys.stdout)
        if code:
            return code
    if args.json:
        print(to_json(ordered))
    if args.html is not None:
        target = Path(args.html) if args.html else root / "data" / "plans_progress.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(to_html(live, archive, root), encoding="utf-8")
        print(f"страница записана: {target}", file=sys.stderr if args.json else sys.stdout)
    if args.check:
        baseline = load_baseline(args.baseline) if args.baseline else set()
        extra = order_block_findings(order_path, live, archive, root)
        code = run_check(ordered, baseline, sys.stderr if args.json else sys.stdout, extra)
    if not (args.json or args.html is not None or args.check or args.sync_order):
        for p in ordered:
            tag = "архив" if p.archived else (p.tier or "—")
            print(f"{p.name:48} {tag:6} {_tally(p.done, p.total)}")
    return code


if __name__ == "__main__":
    sys.exit(main())
