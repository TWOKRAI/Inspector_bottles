#!/usr/bin/env python3
"""plans_progress — прогресс планов по единому эталону строки задачи (module-contract: new-lite).

Интерфейс (CLI, только stdlib)::

    python scripts/plans_progress/plans_progress.py [--root DIR] [--order PATH]
        [--json] [--html [PATH]] [--check] [--baseline PATH] [--sync-order]
        [--who] [--now ISO] [--active-window N[mhd]]

* ``--root DIR``   каталог с ``plans/`` и ``plans/_archive/`` (по умолчанию корень репозитория);
* ``--order PATH`` ``ORDER.md`` (по умолчанию ``<root>/plans/queue/ORDER.md``); файла нет -> полосы
  и ярусы ``null``, не ошибка;
* ``--json``       stdout: список планов ``{plan, path, archived, lane, tier, done, total,
  dropped, unknown, unmarked, header_status, tasks:[{id, title, status, ref, after, ready}],
  after, after_reason, waiting_on, ready, dep_unknown, dep_cycle, active}``; новые ключи — в конце объекта:
  поле плана ``После:`` / ``After:`` -> ``after`` (имена планов), ``waiting_on`` (условия ``⛔``),
  ``after_reason`` (текст после `` — ``); ``(после N.M)`` у пункта -> ``tasks[].after``;
  ``ready`` — можно брать в работу (см. README); ``dep_unknown``/``dep_cycle`` — имена планов;
  ``active`` — worktree со свежим сигналом журнала, привязанные к плану: ``{branch, worktree, via,
  sessions, agents, last_signal}``;
* ``--who``       stdout: только ``{"active": [...], "orphans": [...]}`` (активные с ``plan`` и без плана);
  не сочетается с ``--json``/``--html``/``--check``/``--sync-order`` (exit 2);
* ``--now ISO``   «сейчас» для окна (местное, без пояса); ``--active-window N[mhd]`` — окно свежести (``6h``);
  неверное значение -> exit 2;
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

Правила разбора (эталон) — ``plans/2026-10-02_plans-progress-dashboard/design.md``, «Формат задачи».
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
from datetime import datetime, timedelta
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
UNPARSED_ITEM_RE = re.compile(
    r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+(?:\[[ xX]\][ \t]+)?(?:\*\*|~~|__)*Task[ \t]+(?P<tok>\S*\d\S*)"
)
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
    after: list[str] = field(default_factory=list)  # id задач того же плана из `(после N.M)`
    ready: bool = False  # можно брать в работу: заполняет resolve_deps


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
    numbered: list[str] = field(default_factory=list)  # `1. Task <id>:` — нумерованные пункты вне эталона
    bad_encoding: list[str] = field(default_factory=list)  # файлы не в UTF-8
    lane: str | None = None
    tier: str | None = None
    header_status: str | None = None  # слово набора из строки `Статус:` в шапке плана
    info: list[tuple[str, str]] = field(default_factory=list)  # из ORDER.md: (метка, текст)
    after: list[str] = field(default_factory=list)  # имена планов из поля `После:`
    after_reason: str = ""  # текст после ` — ` в поле `После:`
    waiting_on: list[str] = field(default_factory=list)  # условия `⛔ …` из поля `После:`
    has_after_field: bool = False  # в первых 30 строках есть строка `После:`, даже `—`; в --json не выводится
    header_branch: str = ""  # ветка из строки `Ветка:` / `Branch:` шапки; в --json не выводится
    active: list[dict] = field(default_factory=list)  # worktree со свежим сигналом, привязанные к плану
    ready: bool = False  # заполняет resolve_deps
    dep_unknown: list[str] = field(default_factory=list)  # имена из `after`, которых нет среди планов
    dep_cycle: list[str] = field(default_factory=list)  # участники цикла, в котором стоит этот план
    task_dep_unknown: list[tuple[str, str]] = field(default_factory=list)  # (id задачи, id, которого нет в плане)
    task_dep_cycle: list[str] = field(default_factory=list)  # id задач — участников цикла

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


# Латиница — только ВЕРХНИМ регистром («done» в названии — не статус); кириллица — без учёта регистра.
_TAIL_WORD_RE = re.compile(
    r"(?<![\w-])((?-i:DONE|SUPERSEDED|DEFERRED)|(?i:ЗАКРЫТ[АО]?|СДЕЛАН[АО]?|СНЯТА|ОТЛОЖЕН[АО]?))(?![\w-])"
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
_TAIL_PARTIAL_RE = re.compile(r"ЧАСТИЧНО|PARTIAL", re.IGNORECASE)
# Перед словом статуса обязателен разделитель: начало хвоста, тире, `(`, знак, `**`, `]`, `:`.
_TAIL_SEPARATORS = ("—", "–", "(", "✅", "✔", "✓", "**", "]", ":")
# После слова/знака допустимы только даты, хеши, пунктуация и скобочное пояснение до конца строки.
_TAIL_REST_RE = re.compile(
    r"^(?:[\s*+,;.:)\]\x00]|\d{4}-\d{2}-\d{2}|\d{1,2}-\d{2}|[0-9a-f]{7,40}(?!\w))*(?:\(.*)?$", re.DOTALL
)


# Слово сразу после `(`: дальше обязательна дата, хеш, запятая или `)` — «(DONE позже, после 3.1)» не статус.
_TAIL_PAREN_RE = re.compile(r"\s*(?:\d{4}-\d{2}-\d{2}|[0-9a-f]{7,40}(?!\w)|[,)\x00])")


def _tail_separator(masked: str, pos: int) -> str | None:
    """`start` (перед позицией только пробелы), сам разделитель или None."""
    before = masked[:pos].rstrip()
    if not before:
        return "start"
    return next((sep for sep in _TAIL_SEPARATORS if before.endswith(sep)), None)


def find_tail_status(rest: str) -> str | None:
    """Статус в строке заголовка вне `[...]`: `✅`, `— DONE 50df705f`, `(ЗАКРЫТА 2026-08-03, ADR-1)`.

    Слово принимается, только если перед ним разделитель и после него идут даты, хеши, пунктуация или
    пояснение в скобках; слово сразу после `(` принимается с любым текстом до конца. «перевести план в DONE»,
    «не DONE», «done» строчными, «DONE-детектор» статусом не являются. Знак ✅✔✓ принимается после тире, в
    начале хвоста или в хвостовой позиции (дальше только дата/хеш/скобки): «кнопка ✅ в тулбаре» — нет.
    `ЧАСТИЧНО`/`PARTIAL` отсекают всё после себя: «⚠️ PARTIAL (шаг 3 отложен)» — не отложена, а не закрыта.
    """
    masked = mask_code(rest)
    partial = _TAIL_PARTIAL_RE.search(masked)
    limit = partial.start() if partial else len(masked)
    found: list[tuple[int, str]] = []
    for m in _TAIL_MARK_RE.finditer(masked):
        if m.start() >= limit:
            break
        if _tail_separator(masked, m.start()) in ("start", "—", "–") or _TAIL_REST_RE.match(masked[m.end() :]):
            found.append((m.start(), "done"))
            break
    for m in _TAIL_WORD_RE.finditer(masked):
        if m.start() >= limit:
            break
        sep = _tail_separator(masked, m.start())
        tail = masked[m.end() :]
        ok = _TAIL_PAREN_RE.match(tail) if sep == "(" else _TAIL_REST_RE.match(tail)
        if sep is not None and ok:
            found.append((m.start(), _TAIL_CANON[m.group(1).upper()]))
            break
    if found:
        return min(found)[1]
    return "pending" if partial else None


_HEADER_LINE_RE = re.compile(
    r"^\s*(?:>\s*)*(?:[-*+]\s+)?(?:\*\*)?(?:Статус|Status)(?:\*\*)?\s*:(?:\*\*)?\s*(?P<rest>.*)$"
)
_HEADER_WORD_RE = re.compile(
    r"(?<![\w-])(IN[ _]PROGRESS|DONE|PENDING|BLOCKED|DEFERRED|SUPERSEDED|SKIPPED|CANCELLED"
    r"|ЗАКРЫТ[АО]?|СНЯТ[АО]?)(?![\w-])"
)


def find_header_status(text: str) -> str | None:
    """Первая строка `Статус:` / `**Статус:**` / `- **Статус:**` / `> Статус:` в первых 30 строках -> слово набора."""
    for line in text.split("\n")[:30]:
        m = _HEADER_LINE_RE.match(line)
        if not m:
            continue
        # слово принимается только в начале значения (после `**`, `>`, скобок, эмодзи): «P1 + P2 DONE»,
        # «В работе. … DONE», «Phase 1-3 DONE; остался Phase 4» статусом плана не являются
        lead = re.sub(r"^[\W_]+", "", mask_code(m.group("rest")))
        w = _HEADER_WORD_RE.match(lead)
        if not w:
            return None
        word = w.group(1)
        if word.startswith("ЗАКРЫТ"):
            return "done"
        if word.startswith("СНЯТ"):
            return "superseded"
        return canon_of(word)
    return None


_AFTER_LINE_RE = re.compile(r"^\s*(?:>\s*)*(?:[-*+]\s+)?(?:\*\*)?(?:После|After)(?:\*\*)?\s*:(?:\*\*)?\s*(?P<rest>.*)$")
_AFTER_REASON_RE = re.compile(r" [—–] ")


def after_field_value(text: str) -> str | None:
    """Значение первой строки `После:` / `After:` в первых 30 строках; нет строки — None.

    Пустое значение (`- **После:**`) — тоже строка. Строки внутри ограждения кода пропускаются.
    """
    in_fence = False
    for line in text.split("\n")[:30]:
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        m = None if in_fence else _AFTER_LINE_RE.match(line)
        if m:
            return m.group("rest").strip()
    return None


def find_after(text: str) -> tuple[list[str], list[str], str]:
    """Поле `После:` / `After:` в первых 30 строках -> (имена планов, условия `⛔`, причина).

    Первая подходящая строка выигрывает (`after_field_value`). Значение режется по первому
    ` — ` / ` – `: слева список через запятую, справа причина. Элемент с `⛔` — условие (текст после знака),
    остальные — имена планов: href markdown-ссылки или имя в обратных кавычках, через `_name_from_href`;
    повтор хранится один раз.
    """
    value = after_field_value(text)
    if value is None:
        return [], [], ""
    parts = _AFTER_REASON_RE.split(value, maxsplit=1)
    reason = parts[1].strip() if len(parts) > 1 else ""
    plans: list[str] = []
    conditions: list[str] = []
    for raw in parts[0].split(","):
        item = raw.strip()
        if not item or item in ("—", "-", "–"):
            continue
        if "⛔" in item:
            conditions.append(item.split("⛔", 1)[1].strip() or "⛔")
            continue
        link = _LINK_RE.search(item)
        target = link.group(1) if link else item.replace("`", "").strip()
        name = _name_from_href(target) or target
        if name not in plans:
            plans.append(name)
    return plans, conditions, reason


_BRANCH_LINE_RE = re.compile(
    r"^\s*(?:>\s*)*(?:[-*+]\s+)?(?:\*\*)?(?:Ветка|Branch)(?:\*\*)?\s*:(?:\*\*)?\s*(?P<rest>.*)$"
)
_BRANCH_TOKEN_RE = re.compile(r"[^\s`,;()]+(?:/[^\s`,;()]+)+")


def find_header_branch(text: str) -> str:
    """Ветка из первой строки `Ветка:` / `Branch:` в первых 30 строках (вне ограждений кода); нет — `""`.

    Разметка `- **…:**` и обратные кавычки допустимы; берётся первый токен вида `тип/имя`, хвост
    (`— трек`, `(от main)`) отброшен.
    """
    in_fence = False
    for line in text.split("\n")[:30]:
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        m = None if in_fence else _BRANCH_LINE_RE.match(line)
        if m:
            tok = _BRANCH_TOKEN_RE.search(m.group("rest").replace("`", ""))
            return tok.group(0).rstrip(".") if tok else ""
    return ""


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
    after: list[str] = field(default_factory=list)


# `(после 1.1, 1.0)` / `(after 1.1)`: регистр не важен только у слова, id — по эталону; после id не должно
# стоять символа id (`1.2B` — не id `1.2`) и `.символ` (`1.2.3`, `1.2.a`, `T2.W` — не id); дата `2026-09-25` — не id.
_AFTER_ID = r"(?!\d{4}-\d{2}-\d{2})" + ID_PATTERN + r"(?![\w-]|\.\w)"
TASK_AFTER_RE = re.compile(r"\((?i:после|after)[ \t]+(" + _AFTER_ID + r"(?:[ \t]*,[ \t]*" + _AFTER_ID + r")*)")


def find_task_after(text: str) -> list[str]:
    """`(после N.M, K.L; …)` в тексте пункта (код-спаны не читаются) -> id по порядку, без повторов."""
    m = TASK_AFTER_RE.search(mask_code(text))
    if not m:
        return []
    ids: list[str] = []
    for raw in m.group(1).split(","):
        tid = raw.strip()
        if tid not in ids:
            ids.append(tid)
    return ids


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
        after=find_task_after(text),
    )


def has_unclosed_fence(text: str) -> bool:
    """Нечётное число ограждений: разбор остаток файла после открытого ограждения пропускает."""
    return sum(1 for ln in text.split("\n") if FENCE_RE.match(ln)) % 2 == 1


def parse_items(
    text: str, unparsed: list[str] | None = None, numbered: list[str] | None = None
) -> tuple[list[Item], bool]:
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
            if bad:
                tok = bad.group("tok").rstrip(".:,;")
                if re.match(r"^[ \t]*\d+[.)]", line) and ID_RE.fullmatch(tok):
                    if numbered is not None:
                        numbered.append(tok)  # `1. Task 1.1:` с корректным id: вне эталона из-за нумерации
                elif unparsed is not None:
                    unparsed.append(tok)
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
    plan.header_status = find_header_status(main_text)
    plan.after, plan.waiting_on, plan.after_reason = find_after(main_text)
    plan.has_after_field = after_field_value(main_text) is not None
    plan.header_branch = find_header_branch(main_text)

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

    items, had_items = parse_items(main_text, plan.unparsed, plan.numbered)
    if had_items:
        plan.tasks = [Task(it.id, it.title, it.status, it.ref, after=it.after) for it in items]
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


# ----------------------------------------------------------------------------- порядок между планами

TASK_CLOSED = ("done", "deferred", "superseded")
TASK_OPEN = ("unknown", "pending", "in_progress", "blocked")


def plan_closed(p: Plan) -> bool:
    """Закрыт: архив, §4.3, шапка done/superseded или есть задачи и ни одной незавершённой."""
    if p.archived or p.tier == "4.3" or p.header_status in ("done", "superseded"):
        return True
    return bool(p.tasks) and not any(t.status in TASK_OPEN for t in p.tasks)


def cycle_groups(edges: list[list[int]]) -> dict[int, list[int]]:
    """Узлы в цикле (включая ссылку на себя) -> все участники их цикла, по возрастанию номера.

    Итеративный Тарьян: цепочка из тысяч узлов не упирается в лимит рекурсии.
    """
    n = len(edges)
    order = [-1] * n
    low = [0] * n
    on_stack = [False] * n
    stack: list[int] = []
    groups: dict[int, list[int]] = {}
    counter = 0
    for root in range(n):
        if order[root] != -1:
            continue
        order[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack[root] = True
        work = [(root, 0)]
        while work:
            v, i = work[-1]
            if i < len(edges[v]):
                work[-1] = (v, i + 1)
                w = edges[v][i]
                if order[w] == -1:
                    order[w] = low[w] = counter
                    counter += 1
                    stack.append(w)
                    on_stack[w] = True
                    work.append((w, 0))
                elif on_stack[w]:
                    low[v] = min(low[v], order[w])
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[v])
            if low[v] == order[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack[w] = False
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1 or v in edges[v]:
                    comp.sort()
                    for w in comp:
                        groups[w] = comp
    return groups


def resolve_deps(plans: list[Plan]) -> None:
    """Заполняет `ready`, `dep_unknown`, `dep_cycle` у планов и `ready` у задач; нужен `tier` (после apply_order).

    Имя плана ищется среди ВСЕХ планов; при живой и архивной копии решает архивная. Граф циклов строится
    только по незакрытым планам (задачам): закрытый узел цикл разрывает.
    """
    closed = {id(p): plan_closed(p) for p in plans}
    by_name: dict[str, Plan] = {}
    for p in plans:
        cur = by_name.get(p.name)
        if cur is None or (p.archived and not cur.archived):
            by_name[p.name] = p
    nodes = [p for p in plans if not closed[id(p)]]
    pos = {id(p): i for i, p in enumerate(nodes)}
    edges = [[pos[id(q)] for n in p.after if (q := by_name.get(n)) is not None and id(q) in pos] for p in nodes]
    groups = cycle_groups(edges)
    for p in plans:
        p.dep_unknown = [n for n in p.after if n not in by_name]
        p.dep_cycle = [nodes[j].name for j in groups.get(pos.get(id(p), -1), [])]
        p.ready = (
            not closed[id(p)]
            and not p.waiting_on
            and not p.dep_unknown
            and not p.dep_cycle
            and all(closed[id(by_name[n])] for n in p.after)
        )
        _resolve_task_deps(p)


def _resolve_task_deps(p: Plan) -> None:
    by_id: dict[str, Task] = {}
    for t in p.tasks:
        by_id.setdefault(t.id, t)
    p.task_dep_unknown = [(t.id, i) for t in p.tasks if t.status not in TASK_CLOSED for i in t.after if i not in by_id]
    nodes = [t for t in p.tasks if t.status not in TASK_CLOSED]
    pos = {id(t): i for i, t in enumerate(nodes)}
    edges = [[pos[id(q)] for i in t.after if (q := by_id.get(i)) is not None and id(q) in pos] for t in nodes]
    groups = cycle_groups(edges)
    p.task_dep_cycle = []
    for j in sorted(groups):
        if nodes[j].id not in p.task_dep_cycle:
            p.task_dep_cycle.append(nodes[j].id)
    in_cycle = {id(nodes[j]) for j in groups}
    for t in p.tasks:
        t.ready = (
            p.ready
            and t.status == "pending"
            and id(t) not in in_cycle
            and all(i in by_id and by_id[i].status in TASK_CLOSED for i in t.after)
        )


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
        if p.header_status == "done" and p.total > p.done:
            text = f"шапка: {p.header_status}, задачи {p.done} из {p.total}"
            out.append(Finding("HEADER_STATUS_CONFLICT", p.name, None, False, text))
        if p.numbered:
            text = (
                f"нумерованный пункт вне эталона (используйте `- Task …`): {len(p.numbered)} "
                f"(первый: «{p.numbered[0]}»)"
            )
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
        # закрытый план ничего не ждёт: ключ `dep_unknown` в --json остаётся, находка по нему — шум
        for n in [] if plan_closed(p) else p.dep_unknown:
            out.append(Finding("DEP_UNKNOWN", p.name, None, in_41, f"нет плана {clean_md(n, 80)}"))
        if p.dep_cycle:
            text = f"цикл ожидания между планами: {', '.join(clean_md(n, 80) for n in p.dep_cycle)}"
            out.append(Finding("DEP_CYCLE", p.name, None, in_41, text))
        for tid, missing in p.task_dep_unknown:
            out.append(Finding("DEP_UNKNOWN", p.name, tid, in_41, f"нет задачи {clean_md(missing, 80)}"))
        for tid in p.task_dep_cycle:
            out.append(Finding("DEP_CYCLE", p.name, tid, in_41, f"задача {clean_md(tid, 80)} в цикле ожидания"))
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


def trust_counts(p: Plan) -> tuple[int, int]:
    """(пунктов без слова набора, задач без отметки статуса): общий источник для блока, CLI и страницы."""
    return p.unknown, p.unmarked


def trust_suffix(p: Plan) -> str:
    """Хвост строки `· без статуса K` / `· без отметки K` — только при K > 0, формат `N из M` не меняется."""
    unknown, unmarked = trust_counts(p)
    return (f" · без статуса {unknown}" if unknown > 0 else "") + (f" · без отметки {unmarked}" if unmarked > 0 else "")


def queue_scope(live: list[Plan]) -> tuple[list[Plan], list[Plan], list[Plan], list[Plan]]:
    """Живые планы по секциям страницы: (очередь §4.1, ждут §4.2, не в ORDER, закрытые §4.3). Порядок сохраняется."""
    return (
        [p for p in live if p.tier == "4.1"],
        [p for p in live if p.tier == "4.2"],
        [p for p in live if p.tier is None],
        [p for p in live if p.tier == "4.3"],
    )


def block_lines(live: list[Plan], archive: list[Plan]) -> list[str]:
    """Строки блока: планы §4.1, §4.2 и без яруса (порядок страницы) и счётчик `в архиве`.

    `в архиве` = архивные планы + закрытые §4.3. Шкала — та же `_tally`, что у страницы.
    """
    queue, waiting, unlisted, closed = queue_scope(live)
    shown = queue + waiting + unlisted
    return [f"- {p.name} — {_tally(p.done, p.total)}{trust_suffix(p)}" for p in shown] + [
        f"в архиве: {len(archive) + len(closed)}"
    ]


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
        return [Finding("ORDER_BLOCK_MISSING", order.name, None, False, f"нет блока прогресса: {found}")]
    body = [ln.rstrip("\r") for ln in lines[found[0] + 1 : found[1]]]
    if body != block_lines(live, archive):
        return [
            Finding(
                "ORDER_BLOCK_STALE",
                order.name,
                None,
                False,
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


# ----------------------------------------------------------------------------- активные worktree

GIT_TIMEOUT = 10  # секунд на один вызов git: зависший git не вешает страницу
DEFAULT_WINDOW = "6h"  # не измерено: окно «свежести» сигнала журнала
_WINDOW_RE = re.compile(r"([0-9]{1,9})([mhd])")  # не больше 9 цифр: int() не упрётся в лимит длины строки
_WINDOW_UNITS = {"m": "minutes", "h": "hours", "d": "days"}
_GIT_ENV_DROP = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")  # хук коммита выставляет их сам
_REFS_TOKEN_RE = re.compile(r"plans/[^\s,;)]+")


def parse_window(text: str) -> timedelta | None:
    """`30m` / `6h` / `1d` -> интервал; иное (и слишком большое число) -> None."""
    m = _WINDOW_RE.fullmatch(text)
    if not m:
        return None
    try:
        return timedelta(**{_WINDOW_UNITS[m.group(2)]: int(m.group(1))})
    except OverflowError:
        return None


def parse_now(text: str) -> datetime | None:
    """ISO-время местное, без пояса; с поясом и мусор -> None."""
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    return value if value.tzinfo is None else None


def _git(args: list[str], cwd: Path | str) -> str | None:
    """stdout git-команды или None: сбой запуска, таймаут и ненулевой код — одно и то же «шаг не дал ответа»."""
    env = {k: v for k, v in os.environ.items() if k not in _GIT_ENV_DROP}
    try:
        cp = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT,
            env=env,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return cp.stdout if cp.returncode == 0 else None


def git_worktrees(root: Path) -> list[tuple[str, str]]:
    """[(путь worktree как в porcelain, ветка)]; ветка `""` на detached HEAD.

    Корни есть только если `root` — верхний каталог своего репозитория (`os.path.samefile`): корень внутри
    чужого репозитория, вне git или подкаталог репозитория дают пустой список. Главное дерево — тоже корень.
    """
    top = _git(["rev-parse", "--show-toplevel"], root)
    if not top or not top.strip():
        return []
    try:
        if not os.path.samefile(top.strip(), root):
            return []
    except OSError:
        return []
    listing = _git(["worktree", "list", "--porcelain"], root)
    out: list[tuple[str, str]] = []
    for block in (listing or "").replace("\r\n", "\n").split("\n\n"):
        path, branch, bare = "", "", False
        for line in block.split("\n"):
            if line.startswith("worktree "):
                path = line[len("worktree ") :]
            elif line.startswith("branch "):
                ref = line[len("branch ") :].strip()
                branch = ref[len("refs/heads/") :] if ref.startswith("refs/heads/") else ref
            elif line == "bare":
                bare = True
        if path and not bare:
            out.append((path, branch))
    return out


def read_signal(worktree: Path | str, now: datetime, window: timedelta) -> dict | None:
    """Свежие строки `<worktree>/data/agent-journal.jsonl` -> {sessions, agents, last_signal}; свежих нет -> None.

    Не считаются: битый JSON, не-объект, `event` не строка или пуст, `ts` не строка / не ISO / с поясом.
    Свежая: `now - ts <= окно`, будущее тоже свежее. `last_signal` — наибольший `ts` строкой как в журнале.
    """
    try:
        text = (Path(worktree) / "data" / "agent-journal.jsonl").read_bytes().decode("utf-8-sig", errors="replace")
    except OSError:
        return None
    sessions: set[str] = set()
    agents: set[str] = set()
    last: tuple[datetime, str] | None = None
    for line in text.split("\n"):  # не splitlines: U+2028 внутри строки JSON не конец записи
        try:
            obj = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if not isinstance(obj, dict):
            continue
        event, ts = obj.get("event"), obj.get("ts")
        if not isinstance(event, str) or not event or not isinstance(ts, str):
            continue
        try:
            when = datetime.fromisoformat(ts)
        except ValueError:
            continue
        if when.tzinfo is not None or now - when > window:
            continue
        for key, bucket in (("session_id", sessions), ("agent_id", agents)):
            value = obj.get(key)
            if isinstance(value, str) and value:
                bucket.add(value)
        if last is None or when > last[0]:
            last = (when, ts)
    if last is None:
        return None
    return {"sessions": len(sessions), "agents": len(agents), "last_signal": last[1]}


def plan_name_from_ref(value: str) -> str | None:
    """Имя плана из пути или голого имени: первый сегмент после `plans/` (и `_archive/`, `<квартал>/`), без `.md`."""
    parts = [p for p in value.strip().replace("\\", "/").split("/") if p not in ("", ".")]
    if parts and parts[0] == "plans":
        parts = parts[1:]
    if parts and parts[0] == "_archive":
        parts = parts[1:]
        if parts and QUARTER_RE.match(parts[0]):
            parts = parts[1:]
    if not parts:
        return None
    name = parts[0][:-3] if parts[0].endswith(".md") else parts[0]
    return name or None


def find_plan(plans: list[Plan], name: str | None) -> Plan | None:
    """План по имени: сначала живой, потом архивный."""
    if not name:
        return None
    for archived in (False, True):
        for p in plans:
            if p.name == name and p.archived is archived:
                return p
    return None


def _step_plan_ref(worktree: Path | None, plans: list[Plan]) -> Plan | None:
    if worktree is None:
        return None
    value = _git(["config", "--worktree", "--get", "plan.ref"], worktree)
    return find_plan(plans, plan_name_from_ref(value)) if value and value.strip() else None


def _newest_refs_token(message: str) -> str | None:
    """Первый токен `plans/…` строк `Refs:` сообщения (и их продолжений с отступом); нет — None."""
    in_refs = False
    for line in message.split("\n"):
        if re.match(r"^\s*Refs:", line):
            in_refs = True
        elif not (in_refs and line[:1] in (" ", "\t")):
            in_refs = False
        if in_refs:
            m = _REFS_TOKEN_RE.search(line)
            if m:
                return m.group(0).rstrip(".")
    return None


def _step_refs(branch: str, repo_root: Path, plans: list[Plan]) -> Plan | None:
    """Самый новый коммит `main..<ветка>` с токеном `plans/…` в `Refs:`; неизвестное имя — к старым не идём."""
    if not branch:
        return None
    log = _git(["log", "-z", "--format=%B", f"main..refs/heads/{branch}", "--"], repo_root)
    for message in (log or "").split("\0"):
        token = _newest_refs_token(message)
        if token is not None:
            return find_plan(plans, plan_name_from_ref(token))
    return None


def _step_header(branch: str, plans: list[Plan]) -> Plan | None:
    """Строка `Ветка:` шапки: сначала живые планы, архивные — если у живых нет; два плана одного уровня — нет плана."""
    if not branch:
        return None
    for archived in (False, True):
        hits = [p for p in plans if p.archived is archived and p.header_branch == branch]
        if hits:
            return hits[0] if len(hits) == 1 else None
    return None


def resolve_plan(branch: str, worktree: Path | None, repo_root: Path, plans: list[Plan]) -> tuple[Plan, str] | None:
    """(план, шаг) первого успешного шага `plan_ref` -> `refs` -> `header`; ни один не дал плана -> None.

    `worktree=None` (ветка без каталога) пропускает только шаг `plan_ref`. `repo_root` — каталог, где `main`.
    """
    for via, found in (
        ("plan_ref", lambda: _step_plan_ref(worktree, plans)),
        ("refs", lambda: _step_refs(branch, repo_root, plans)),
        ("header", lambda: _step_header(branch, plans)),
    ):
        plan = found()
        if plan is not None:
            return plan, via
    return None


def collect_active(
    root: Path, plans: list[Plan], now: datetime, window: timedelta
) -> tuple[list[tuple[Plan, dict]], list[dict]]:
    """([(план, запись)], сироты) по worktree со свежим сигналом; git на корень — только после свежей строки."""
    active: list[tuple[Plan, dict]] = []
    orphans: list[dict] = []
    for path, branch in git_worktrees(root):
        signal = read_signal(path, now, window)
        if signal is None:
            continue
        found = resolve_plan(branch, Path(path), root, plans)
        if found is None:
            orphans.append({"branch": branch, "worktree": path, **signal})
        else:
            plan, via = found
            active.append((plan, {"branch": branch, "worktree": path, "via": via, **signal}))
    return active, orphans


def attach_active(plans: list[Plan], active: list[tuple[Plan, dict]]) -> None:
    for plan, entry in sorted(active, key=lambda pe: pe[1]["worktree"]):
        plan.active.append(entry)


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
            "header_status": p.header_status,
            "tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "status": t.status,
                    "ref": t.ref,
                    "after": t.after,
                    "ready": t.ready,
                }
                for t in p.tasks
            ],
            "after": p.after,
            "after_reason": p.after_reason,
            "waiting_on": p.waiting_on,
            "ready": p.ready,
            "dep_unknown": p.dep_unknown,
            "dep_cycle": p.dep_cycle,
            "active": p.active,  # новые ключи — только в конец (README)
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
details.plan,details#archive,details#waiting{background:var(--card);border:1px solid var(--line);border-radius:8px;
margin-bottom:8px;padding:0 12px}
details#archive>details.plan,details#waiting>details.plan{margin:8px 0}
h2{font-size:1.05rem;margin:16px 0 8px}
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
.chip{font-size:.75rem;color:var(--muted);border:1px solid var(--line);border-radius:10px;padding:0 7px}
.chip.warn{font-size:.75rem;color:var(--in_progress);border:1px solid var(--in_progress);
border-radius:10px;padding:0 7px}
.chip.ok{color:var(--done);border-color:var(--done)}
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


READY_UNDEFINED = "не определено (поле «После:» не заполнено ни у одного плана)"


def deps_in_use(plans: list[Plan]) -> bool:
    """Хоть у одного НЕзакрытого плана есть строка `После:` (`has_after_field`; `—`, пустая и `⛔ …` считаются).

    Пока ложно, `ready` у всех планов верен «по умолчанию», и страница не называет планы готовыми.
    """
    return any(p.has_after_field and not plan_closed(p) for p in plans)


def startable(p: Plan, in_use: bool) -> bool:
    """Можно начинать: поле кем-то заполнено, у плана §4.1 своё поле, `ready`, есть незавершённая задача.

    Только §4.1: `ready` стоит и у планов §4.2, а очередь они не занимают. План без собственной строки `После:`
    не называется готовым: `ready` у него «по умолчанию».
    """
    return in_use and p.tier == "4.1" and p.has_after_field and p.ready and any(t.status in TASK_OPEN for t in p.tasks)


def ready_summary(queue: list[Plan], in_use: bool) -> str:
    """Текст после `можно начинать: ` в `#ready` (уже экранированный)."""
    if not in_use:
        return READY_UNDEFINED
    names = _e(", ".join(p.name for p in queue if startable(p, in_use)) or "нет")
    without = sum(1 for p in queue if not p.has_after_field)
    return f"{names} · поле не заполнено у {without} из {len(queue)} планов очереди" if without else names


def _dep_chips(p: Plan, in_use: bool) -> list[str]:
    """Чипы `ready`, `after`, `waiting`, `cycle` незакрытого плана, в этом порядке."""
    chips: list[str] = []
    if startable(p, in_use):
        chips.append('<span class="chip ok" data-chip="ready">можно начинать</span>')
    title = f' title="{_e(p.after_reason)}"' if p.after_reason else ""
    for name in p.after:
        unknown = name in p.dep_unknown
        cls = "chip warn" if unknown else "chip"
        mark = ' data-unknown="1"' if unknown else ""
        chips.append(f'<span class="{cls}" data-chip="after"{mark}{title}>после: {_e(name)}</span>')
    for cond in p.waiting_on:
        chips.append(f'<span class="chip" data-chip="waiting"{title}>ждёт: {_e(cond)}</span>')
    if p.dep_cycle:
        chips.append(f'<span class="chip warn" data-chip="cycle">⚠ цикл: {_e(", ".join(p.dep_cycle))}</span>')
    return chips


def _plan_html(p: Plan, in_use: bool) -> str:
    attrs = f'class="plan" data-plan="{_e(p.name)}" data-tier="{_e(p.tier or "")}" data-lane="{_e(p.lane or "")}"'
    if startable(p, in_use):
        attrs += ' data-ready="true"'
    s = [f"<details {attrs}>", "<summary>", f'<span class="name">{_e(p.name)}</span>']
    if p.lane:
        s.append(f'<span class="badge">полоса {_e(p.lane)}</span>')
    if p.tier:
        s.append(f'<span class="badge">§{_e(p.tier)}</span>')
    unknown, unmarked = trust_counts(p)
    unfinished = p.total > p.done
    warn = p.header_status == "done" and p.tier in ("4.1", "4.2") and unfinished
    shelved = not warn and (p.tier == "4.3" or p.header_status in ("done", "superseded"))
    if p.tasks:
        if not shelved:
            s.append(f'<progress value="{p.done}" max="{max(p.total, 1)}"></progress>')
        extra = []
        if p.dropped:
            extra.append(f"снято/отложено {p.dropped}")
        if unknown:
            extra.append(f"без статуса {unknown}")
        tail = f" ({', '.join(extra)})" if extra else ""
        s.append(f'<span class="tally">{_e(_tally(p.done, p.total) + tail)}</span>')
        if unmarked:
            s.append(
                '<span class="chip warn" data-chip="unmarked" '
                'title="статус не размечен, цифра может быть занижена">'
                f"⚠ {unmarked} без отметки</span>"
            )
    else:
        s.append('<span class="tally">нет задач в эталонном формате</span>')
    if warn:
        s.append(
            '<span class="chip warn" data-chip="header-conflict" title="шапка плана говорит DONE, задачи не закрыты">'
            f"⚠ шапка: DONE, задачи {p.done} из {p.total}</span>"
        )
    elif shelved:
        word = "снят" if p.header_status == "superseded" else "закрыт"
        counts = f" · задачи {p.done} из {p.total}" if p.tasks and unfinished else ""
        s.append(f'<span class="chip" data-chip="closed" title="план закрыт или поглощён">{word}{counts}</span>')
    if not plan_closed(p):
        s.extend(_dep_chips(p, in_use))
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
    """Страница: очередь §4.1, `#waiting` §4.2, `#unlisted` (нет в ORDER.md), `#archive` (архив + закрытые §4.3)."""
    queue, waiting, unlisted, closed = queue_scope(live)
    shelved = closed + archive
    lanes: dict[str, list[int]] = {}
    for p in queue + waiting + unlisted:
        agg = lanes.setdefault(p.lane or "—", [0, 0, 0])
        agg[0] += p.done
        agg[1] += p.total
        agg[2] += 1
    in_use = deps_in_use(live + archive)
    ready_text = ready_summary(queue, in_use)
    built = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M UTC%z")
    parts = [
        "<!doctype html>",
        '<html lang="ru"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Прогресс планов</title>",
        f"<style>{CSS}</style></head><body><main>",
        "<h1>Прогресс планов</h1>",
        f'<div class="meta">собрано {_e(built)} · SHA {_e(git_sha(root))}</div>',
        f'<div class="meta">в очереди {len(queue)} · ждут {len(waiting)} · не в ORDER {len(unlisted)} · '
        f"закрыто и в архиве {len(shelved)}</div>",
        f'<div class="meta" id="ready">можно начинать: {ready_text}</div>',
        '<section class="lanes">',
    ]
    for lane, (done, total, n) in lanes.items():
        parts.append(
            f'<div class="lane"><b>Полоса {_e(lane)} · планов {n}</b>'
            f'<progress value="{done}" max="{max(total, 1)}"></progress> '
            f'<span class="tally">{_e(_tally(done, total))}</span></div>'
        )
    parts.append("</section>")
    parts.append('<section id="queue">')
    parts.extend(_plan_html(p, in_use) for p in queue)
    parts.append("</section>")
    parts.append('<details id="waiting">')
    parts.append(f"<summary>Ждут триггера · {len(waiting)} планов (ORDER.md §4.2)</summary>")
    parts.extend(_plan_html(p, in_use) for p in waiting)
    parts.append("</details>")
    if unlisted:
        parts.append('<section id="unlisted">')
        parts.append(f"<h2>Нет в ORDER.md · {len(unlisted)}</h2>")
        parts.extend(_plan_html(p, in_use) for p in unlisted)
        parts.append("</section>")
    a_done = sum(p.done for p in shelved)
    a_total = sum(p.total for p in shelved)
    parts.append('<details id="archive">')
    parts.append(
        f"<summary>Закрыто и в архиве · {len(shelved)} планов (§4.3 и _archive/) · "
        f"итого {_e(_tally(a_done, a_total))}</summary>"
    )
    parts.extend(_plan_html(p, in_use) for p in shelved)
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
    ap.add_argument("--who", action="store_true", help="активные worktree и сироты: объект JSON на stdout")
    ap.add_argument("--now", default=None, metavar="ISO", help="текущее время для окна: местное, без пояса")
    ap.add_argument(
        "--active-window",
        default=DEFAULT_WINDOW,
        metavar="N[mhd]",
        help=f"окно свежести сигнала (по умолчанию {DEFAULT_WINDOW})",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    # сообщения не повторяют значение флага: оно может быть чем угодно
    window = parse_window(args.active_window)
    if window is None:
        print("ошибка: --active-window — число и единица измерения (минуты, часы, дни)", file=sys.stderr)
        return 2
    now = datetime.now() if args.now is None else parse_now(args.now)
    if now is None:
        print("ошибка: --now — время ISO местное, без пояса", file=sys.stderr)
        return 2
    if args.who and (args.json or args.html is not None or args.check or args.sync_order):
        print("ошибка: --who не сочетается с другими режимами вывода", file=sys.stderr)
        return 2
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
    resolve_deps(plans)
    live, archive = page_order(plans, rows)
    ordered = live + archive
    code = 0
    if args.json or args.who:
        active, orphans = collect_active(root, ordered, now, window)
        attach_active(ordered, active)
    if args.who:
        by_path = lambda e: e["worktree"]  # noqa: E731
        who = {
            "active": sorted(({"plan": p.name, **e} for p, e in active), key=by_path),
            "orphans": sorted(orphans, key=by_path),
        }
        print(json.dumps(who, ensure_ascii=False, indent=2))
        return 0

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
            print(f"{p.name:48} {tag:6} {_tally(p.done, p.total)}{trust_suffix(p)}")
    return code


if __name__ == "__main__":
    sys.exit(main())
