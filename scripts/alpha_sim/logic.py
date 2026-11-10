"""Скрипт α (P4): чистая логика без ввода-вывода — литералы случаев B/D/C, разбор журналов, судьи, углы, печать.

Контракт — plans/word-layout/tasks/P4.md (Д3, Д4, Д6). Ничего не знает про драйвер и стенд: на входе строки
журналов и словари ответов, на выходе ``Row`` / ``CaseResult`` и строки печати.
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass

_PREFIX = "WordLayoutPlugin: "
_NUM = r"-?\d+(?:\.\d+)?"
_EPS = 1e-9  # границы окон включительные: запас на двоичную арифметику

# --- Углы -----------------------------------------------------------------------------------------------------------


def wrap180(x: float) -> float:
    """Угол в (-180, 180]: 180.0 → 180.0, -180.0 → 180.0, 359.6 → ≈ -0.4. Нулевой знак убирается."""
    r = math.fmod(x, 360.0)
    if r > 180.0:
        r -= 360.0
    elif r <= -180.0:
        r += 360.0
    return r + 0.0


def _num(text: str) -> float:
    """Число из строки журнала; ``-0.0`` приводится к ``0.0``."""
    return float(text) + 0.0


# --- Разбор журнала layout --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DiskLine:
    letter: str
    angle: float
    cell: int | None
    pick: tuple[float, float] | None
    place: tuple[float, float, float, float] | None  # x, y, z, r
    progress: tuple[int, int] | None
    skip: str | None  # текст после «пропуск: » дословно


_DISK_RE = re.compile(rf"^{re.escape(_PREFIX)}диск '([^']+)' ({_NUM})° → (.*)$", re.DOTALL)
_TAKE_RE = re.compile(
    rf"^ячейка (\d+):(?: взять\(({_NUM}),({_NUM})\) →)? положить x({_NUM}) y({_NUM}) z({_NUM}) r({_NUM})° "
    r"\[(\d+)/(\d+)\]$"
)
_SKIP_PREFIX = "пропуск: "
_WORD_RE = re.compile(rf"^{re.escape(_PREFIX)}слово '(.+)' \(источник: [^)]*\)$")
_CHANGE_RE = re.compile(
    rf"^{re.escape(_PREFIX)}смена слова '(.+)' → '(.+)' \(источник: [^)]*\) — ячейки с нуля "
    r"\(было заполнено (\d+)/(\d+)\)$"
)


def parse_layout_line(msg: str) -> DiskLine | None:
    """Строка диска журнала ``layout``; всё прочее (в том числе строка слова) → ``None``."""
    m = _DISK_RE.match(msg)
    if m is None:
        return None
    letter, angle, rest = m.group(1), _num(m.group(2)), m.group(3)
    if rest.startswith(_SKIP_PREFIX):
        return DiskLine(letter, angle, None, None, None, None, rest[len(_SKIP_PREFIX) :])
    t = _TAKE_RE.match(rest)
    if t is None:
        return None
    pick = (_num(t.group(2)), _num(t.group(3))) if t.group(2) is not None else None
    place = (_num(t.group(4)), _num(t.group(5)), _num(t.group(6)), _num(t.group(7)))
    return DiskLine(letter, angle, int(t.group(1)), pick, place, (int(t.group(8)), int(t.group(9))), None)


def parse_word_line(msg: str) -> tuple[str, str | None, int | None, int | None] | None:
    """«слово 'W' (источник: …)» → (W, None, None, None); «смена слова 'A' → 'B' …» → (B, A, k, n)."""
    m = _WORD_RE.match(msg)
    if m is not None:
        return (m.group(1), None, None, None)
    c = _CHANGE_RE.match(msg)
    if c is not None:
        return (c.group(2), c.group(1), int(c.group(3)), int(c.group(4)))
    return None


# --- Разбор журнала обмена --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CvtJob:
    args: dict[int, int]
    argc: int | None
    res_status: int | None
    res_errno: int | None


_OPCODE_RE = re.compile(r"^W\*? CMD_OPCODE = (\d+) \(([^)]*)\)")
_ARGC_RE = re.compile(r"^W\*? CMD_ARGC = (\d+)")
_ARG_RE = re.compile(r"^W\*? CMD_ARGS\[(\d+)\] = (-?\d+)")
_RES_RE = re.compile(r"RES_STATUS = (-?\d+), RES_ERRNO = (-?\d+)")


def parse_cvt_jobs(texts: list[str]) -> list[CvtJob]:
    """Блоки ``CVT_JOB`` из текстов журнала обмена по порядку. Блок другой команды (SC_RUN…) — не задание.

    Блок открывает строка ``CMD_OPCODE``; ``ARGC``/``ARGS`` и ``RES_*`` относятся к последнему открытому блоку.
    Ответ без своего блока и ответ блока, который уже получил ответ, игнорируются.
    """
    jobs: list[dict] = []
    cur: dict | None = None  # открытый блок; cur["cvt"] False — чужая команда, её строки пропускаются
    for text in texts:
        op = _OPCODE_RE.match(text)
        if op is not None:
            cur = {"cvt": op.group(2) == "CVT_JOB", "args": {}, "argc": None, "status": None, "errno": None}
            if cur["cvt"]:
                jobs.append(cur)
            continue
        if cur is None or not cur["cvt"]:
            continue
        argc = _ARGC_RE.match(text)
        if argc is not None:
            cur["argc"] = int(argc.group(1))
            continue
        arg = _ARG_RE.match(text)
        if arg is not None:
            cur["args"][int(arg.group(1))] = int(arg.group(2))
            continue
        if text.startswith("R "):
            res = _RES_RE.search(text)
            if res is not None and cur["status"] is None:
                cur["status"], cur["errno"] = int(res.group(1)), int(res.group(2))
    return [CvtJob(j["args"], j["argc"], j["status"], j["errno"]) for j in jobs]


def merge_exchange_lines(acc: dict[int, dict], lines: list[dict]) -> None:
    """Склейка ответов ``robot_exchange_log_get``: строка с тем же ``seq`` ЗАМЕНЯЕТ прежнюю (растёт ``n``)."""
    for ln in lines:
        acc[int(ln["seq"])] = dict(ln)


_FILE_LINE_RE = re.compile(r"\brobot_main: #(\d+) (.*)$")


def parse_exchange_file_line(line: str) -> tuple[int, str] | None:
    """Строка файла журнала обмена ``… robot_main: #<seq> [in|out] <текст>`` → (seq, текст); ведущий ``#<n>`` не seq."""
    m = _FILE_LINE_RE.search(line)
    if m is None:
        return None
    rest = re.sub(r"^(?:in|out)\s+", "", m.group(2).strip())
    return int(m.group(1)), rest.strip()


def regs_from_introspect(reply: dict) -> dict:
    """Регистр ``word_layout`` из ответа ``introspect_registers``: спуск по ``result`` (до 4 уровней)."""
    node: object = reply
    for _ in range(5):
        if not isinstance(node, dict):
            return {}
        regs = node.get("registers")
        if isinstance(regs, dict):
            word = regs.get("word_layout")
            return word if isinstance(word, dict) else {}
        node = node.get("result")
    return {}


# --- Литералы случаев (Д4) --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Expect:
    letter: str
    angle: float
    cell: int | None
    progress: tuple[int, int] | None
    skip: str | None
    args7: int | None
    args9: tuple[int, int] | None  # окно ARGS[9] включительно


@dataclass(frozen=True)
class Case:
    case_id: str
    word: str
    discs: tuple[tuple[str, float], ...]
    expects: tuple[Expect, ...]
    word_line: str
    jobs: int
    regs: dict  # word_norm, slots_total, slots_filled, done, jobs_emitted (литерал Д4)


# Ячейки 0…8: y, ARGS[7] (design.md §2.3).
_CELL_Y = {0: -440.0, 1: -330.0, 2: -220.0, 3: -110.0, 4: 0.0, 5: 110.0, 6: 220.0, 7: 330.0, 8: 440.0}
_CELL_A7 = {0: 61136, 1: 62236, 2: 63336, 3: 64436, 4: 0, 5: 1100, 6: 2200, 7: 3300, 8: 4400}
# Окна ARGS[9] по углу подачи.
_WIN9 = {0: (64486, 64586), 30: (64186, 64286), 60: (63886, 63986), 90: (63586, 63686),
         300: (65086, 65186), 330: (64786, 64886)}  # fmt: skip
_PLACE_X = 320.0
_PLACE_Z = -132.0
_PICK_X = (454.9, 461.5)
_PICK_Y = (-344.0, -342.0)
_R_TOL = 5.0
_FEED_TOL = 0.5
_FIXED_ARGS = {4: 64216, 5: 3, 6: 3200, 8: 64216}
_A2 = (4549, 4615)
_A3 = (62096, 62116)

_SKIP_B = "нет в слове 'ПЕРЕМИРИЕ'"
_SKIP_D = "нет в слове 'МИР'"
_SKIP_FULL = "ячейки 'Е' заняты (1, 3, 8)"


def _expect(letter: str, angle: float, cell: int | None, progress: tuple[int, int] | None, skip: str | None) -> Expect:
    taken = cell is not None
    return Expect(
        letter=letter,
        angle=angle,
        cell=cell,
        progress=progress,
        skip=skip,
        args7=_CELL_A7[cell] if cell is not None else None,
        args9=_WIN9[int(angle)] if taken else None,
    )


def _case(case_id: str, word: str, spec: list, word_line: str, jobs: int, regs: dict) -> Case:
    expects = tuple(_expect(*row) for row in spec)
    return Case(case_id, word, tuple((e.letter, e.angle) for e in expects), expects, word_line, jobs, regs)


CASES: dict[str, Case] = {
    "B": _case(
        "B",
        "ПЕРЕМИРИЕ",
        [
            ("Р", 0.0, 2, (1, 9), None),
            ("А", 0.0, None, None, _SKIP_B),
            ("Е", 30.0, 1, (2, 9), None),
            ("И", 60.0, 5, (3, 9), None),
            ("Е", 90.0, 3, (4, 9), None),
            ("Б", 0.0, None, None, _SKIP_B),
            ("Р", 300.0, 6, (5, 9), None),
            ("Е", 330.0, 8, (6, 9), None),
            ("И", 30.0, 7, (7, 9), None),
            ("Е", 60.0, None, None, _SKIP_FULL),
            ("П", 90.0, 0, (8, 9), None),
            ("М", 300.0, 4, (9, 9), None),
        ],  # fmt: skip
        f"{_PREFIX}слово 'ПЕРЕМИРИЕ' (источник: регистр)",
        9,
        {"word_norm": "ПЕРЕМИРИЕ", "slots_total": 9, "slots_filled": 9, "jobs_emitted": 9, "done": True},
    ),
    "D": _case(
        "D",
        "МИР",
        [
            ("П", 0.0, None, None, _SKIP_D),
            ("М", 30.0, 0, (1, 3), None),
            ("Е", 0.0, None, None, _SKIP_D),
            ("И", 90.0, 1, (2, 3), None),
            ("Р", 300.0, 2, (3, 3), None),
        ],  # fmt: skip
        f"{_PREFIX}смена слова 'ПЕРЕМИРИЕ' → 'МИР' (источник: регистр) — ячейки с нуля (было заполнено 9/9)",
        3,
        {"word_norm": "МИР", "slots_total": 3, "slots_filled": 3, "jobs_emitted": 12, "done": True},
    ),
    "C": _case(
        "C",
        "ПЕРЕМИРИЕ",
        [
            ("Е", 0.0, 1, (1, 9), None),
            ("Е", 30.0, 3, (2, 9), None),
            ("Е", 60.0, 8, (3, 9), None),
            ("Е", 90.0, None, None, _SKIP_FULL),
        ],  # fmt: skip
        f"{_PREFIX}смена слова 'МИР' → 'ПЕРЕМИРИЕ' (источник: регистр) — ячейки с нуля (было заполнено 3/3)",
        3,
        {"word_norm": "ПЕРЕМИРИЕ", "slots_total": 9, "slots_filled": 3, "jobs_emitted": 15, "done": False},
    ),
}

# --- Результаты и судьи ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    index: int | None  # строка диска — номер в списке с 1; проверка — None
    check: str  # "disk" | "word_line" | "lines.count" | "jobs.count" | "regs.<поле>" | "feed" | "word_set" | ...
    given: str  # диск: f"{буква} {угол подачи:.1f}°"
    observed: str
    ok: bool
    reasons: tuple[str, ...]  # каждая начинается ключом поля


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    rows: tuple[Row, ...]
    checks: tuple[Row, ...]
    ok: bool


def _given(letter: str, angle: float) -> str:
    return f"{letter} {angle + 0.0:.1f}°"


def _in(value: float, lo: float, hi: float) -> bool:
    return lo - _EPS <= value <= hi + _EPS


def _judge_line(e: Expect, line: DiskLine, feed: tuple[str, float] | None) -> list[str]:
    """Причины FAIL строки диска (без задания): буква, решение, ячейка, прогресс, забор, место, r, подача."""
    why: list[str] = []
    if line.letter != e.letter:
        why.append(f"letter {line.letter} ≠ {e.letter}")
    if e.skip is not None:
        if line.skip != e.skip:
            got = f"пропуск: {line.skip}" if line.skip is not None else f"ячейка {line.cell}"
            why.append(f"decision {got} ≠ пропуск: {e.skip}")
    elif line.skip is not None:
        why.append(f"decision пропуск: {line.skip} ≠ ячейка {e.cell}")
    else:
        why.extend(_judge_taken(e, line))
    if feed is not None:
        f_letter, f_angle = feed
        if f_letter != line.letter or abs(wrap180(line.angle - f_angle)) > _FEED_TOL + _EPS:
            why.append(f"feed подано {_given(f_letter, f_angle)}, сеть {_given(line.letter, line.angle)}")
    return why


def _judge_taken(e: Expect, line: DiskLine) -> list[str]:
    why: list[str] = []
    if line.cell != e.cell:
        why.append(f"cell {line.cell} ≠ {e.cell}")
    if line.progress != e.progress:
        why.append(f"progress {line.progress} ≠ {e.progress}")
    if line.pick is None:
        why.append("pick нет координаты забора")
    elif not (_in(line.pick[0], *_PICK_X) and _in(line.pick[1], *_PICK_Y)):
        why.append(f"pick {line.pick} вне окна x{_PICK_X} y{_PICK_Y}")
    if line.place is None or e.cell is None:
        why.append("place нет")
        return why
    x, y, z, r = line.place
    want = (_PLACE_X, _CELL_Y[e.cell], _PLACE_Z)
    if (x, y, z) != want:
        why.append(f"place {(x, y, z)} ≠ {want}")
    want_r = wrap180(0.0 - e.angle)
    if abs(wrap180(r - want_r)) > _R_TOL + _EPS:
        why.append(f"r {r} вне окна {want_r}±{_R_TOL}")
    return why


def _judge_job(e: Expect, job: CvtJob | None) -> list[str]:
    if job is None:
        return ["нет задания"]
    why: list[str] = []
    if job.argc != 10:
        why.append(f"argc {job.argc} ≠ 10")
    args = job.args

    def chk(i: int, ok: bool, want: str) -> None:
        if i not in args:
            why.append(f"ARGS[{i}] нет")
        elif not ok:
            why.append(f"ARGS[{i}] {args[i]} ≠ {want}")

    chk(2, 2 in args and _A2[0] <= args[2] <= _A2[1], f"{_A2[0]}…{_A2[1]}")
    chk(3, 3 in args and _A3[0] <= args[3] <= _A3[1], f"{_A3[0]}…{_A3[1]}")
    for i, want in _FIXED_ARGS.items():
        chk(i, args.get(i) == want, str(want))
    chk(7, args.get(7) == e.args7, str(e.args7))
    lo, hi = e.args9 if e.args9 is not None else (0, -1)
    chk(9, 9 in args and lo <= args[9] <= hi, f"{lo}…{hi}")
    if job.res_status != 1:
        why.append(f"res_status {job.res_status} ≠ 1")
    if job.res_errno != 0:
        why.append(f"res_errno {job.res_errno} ≠ 0")
    return why


def _job_suffix(job: CvtJob | None) -> str:
    if job is None:
        return " | CVT_JOB нет"
    return f" | CVT_JOB ARGS[7]={job.args.get(7)} ARGS[9]={job.args.get(9)} RES={job.res_status}"


def _check(name: str, observed: str, reasons: list[str]) -> Row:
    return Row(None, name, "", observed, not reasons, tuple(reasons))


def _judge_regs(case: Case, regs: dict, before: int) -> list[Row]:
    rows: list[Row] = []
    for field, literal in case.regs.items():
        name = f"regs.{field}"
        if field not in regs:
            rows.append(_check(name, "нет поля", [f"{field} нет в регистрах"]))
            continue
        got = regs[field]
        if field == "jobs_emitted":
            delta = got - before
            if delta != case.jobs:
                rows.append(_check(name, str(got), [f"{field} {got} − {before} = {delta} ≠ {case.jobs}"]))
                continue
            note = f" (каскад от прошлого случая: литерал {literal})" if got != literal else ""
            rows.append(_check(name, f"{got}{note}", []))
        else:
            rows.append(_check(name, str(got), [] if got == literal else [f"{field} {got} ≠ {literal}"]))
    return rows


def judge_case(
    case_id: str,
    lines: list[str],
    jobs: list[CvtJob] | None,
    regs: dict | None,
    feed: list[tuple[str, float]] | None,
    jobs_emitted_before: int,
) -> CaseResult:
    """Судья случая. ``jobs``/``regs``/``feed`` равны ``None`` — эти проверки не делаются (только журнал layout)."""
    case = CASES[case_id]
    disks: list[tuple[str, DiskLine]] = []  # (сообщение, разбор) строк диска по порядку
    word_msg: str | None = None
    word_pos: int | None = None
    first_disk_pos: int | None = None
    for pos, msg in enumerate(lines):
        line = parse_layout_line(msg)
        if line is not None:
            disks.append((msg, line))
            if first_disk_pos is None:
                first_disk_pos = pos
        elif word_msg is None and parse_word_line(msg) is not None:
            word_msg, word_pos = msg, pos

    n_exp = len(case.expects)
    rows: list[Row] = []
    taken_seen = 0
    for i in range(max(len(disks), n_exp)):
        e = case.expects[i] if i < n_exp else None
        if i >= len(disks):
            assert e is not None
            rows.append(Row(i + 1, "disk", _given(e.letter, e.angle), "нет строки", False, ("нет строки",)))
            continue
        msg, line = disks[i]
        observed = msg[len(_PREFIX) :] if msg.startswith(_PREFIX) else msg
        if e is None:
            rows.append(Row(i + 1, "disk", _given(line.letter, line.angle), observed, False, ("лишняя строка",)))
            continue
        why = _judge_line(e, line, feed[i] if feed is not None and i < len(feed) else None)
        if line.skip is None:
            if jobs is not None:
                job = jobs[taken_seen] if taken_seen < len(jobs) else None
                why.extend(_judge_job(e, job) if e.skip is None else [])
                observed += _job_suffix(job)
            taken_seen += 1
        rows.append(Row(i + 1, "disk", _given(e.letter, e.angle), observed, not why, tuple(why)))

    checks: list[Row] = []
    word_reasons: list[str] = []
    if word_msg is None:
        word_reasons.append("word_line нет строки слова")
    else:
        if word_msg != case.word_line:
            word_reasons.append(f"word_line {word_msg!r} ≠ {case.word_line!r}")
        if first_disk_pos is not None and word_pos is not None and word_pos > first_disk_pos:
            word_reasons.append("word_line после первой строки диска")
    checks.append(_check("word_line", word_msg if word_msg is not None else "нет строки", word_reasons))
    count_reasons = [] if len(disks) == n_exp else [f"lines.count строк диска {len(disks)} ≠ {n_exp}"]
    checks.append(_check("lines.count", str(len(disks)), count_reasons))
    if jobs is not None:
        cnt = [] if len(jobs) == case.jobs else [f"jobs.count заданий {len(jobs)} ≠ {case.jobs}"]
        checks.append(_check("jobs.count", str(len(jobs)), cnt))
    if regs is not None:
        checks.extend(_judge_regs(case, regs, jobs_emitted_before))
    ok = all(r.ok for r in rows) and all(c.ok for c in checks)
    return CaseResult(case_id, tuple(rows), tuple(checks), ok)


def judge_journal(case_id: str, lines: list[str]) -> CaseResult:
    """Судья только журнала layout: строки диска, слово, счёт строк (без заданий, регистров, подачи)."""
    return judge_case(case_id, lines, None, None, None, 0)


# --- Углы (Д6) --------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AngleRow:
    letter: str
    fed: float
    net: float
    delta: float  # wrap180(net - fed)
    delta_inv: float  # wrap180(net + fed)


@dataclass(frozen=True)
class AngleReport:
    rows: tuple[AngleRow, ...]
    verdict: str  # "совпала" | "инвертирована" | "иное" | "не определить" | "не измерено"
    median_delta: float | None


def angle_report(pairs: list[tuple[str, float, float]]) -> AngleReport:
    """Конвенция угла: диски с подачей не 0°/180°; все |Δ| ≤ 5 → совпала, иначе все |Δинв| ≤ 5 → инвертирована."""
    rows = tuple(AngleRow(letter, fed, net, wrap180(net - fed), wrap180(net + fed)) for letter, fed, net in pairs)
    if not rows:
        return AngleReport((), "не измерено", None)
    informative = [r for r in rows if r.fed % 180.0 != 0.0]
    if not informative:
        return AngleReport(rows, "не определить", None)
    if all(abs(r.delta) <= _R_TOL + _EPS for r in informative):
        verdict = "совпала"
    elif all(abs(r.delta_inv) <= _R_TOL + _EPS for r in informative):
        verdict = "инвертирована"
    else:
        verdict = "иное"
    return AngleReport(rows, verdict, statistics.median(r.delta for r in informative))


# --- Дом, стоп, остановка ---------------------------------------------------------------------------------------------


def _find_index(texts: list[str], needle: str, start: int = 0) -> int | None:
    for i in range(start, len(texts)):
        if texts[i].strip() == needle:
            return i
    return None


def judge_home(reply: dict, park_state: dict | None, texts: list[str]) -> Row:
    """«Домой» (``robot_park_all``): ответ ``done``, статус догнал ответ, на проводе SERVO 0 (SC_RUN при ``moved``)."""
    res = reply.get("result") if isinstance(reply.get("result"), dict) else reply
    robot = (res.get("robots") or {}).get("robot_main") or {}
    home = robot.get("home")
    why: list[str] = []
    if res.get("status") != "ok":
        why.append(f"status {res.get('status')} ≠ ok")
    if robot.get("result") != "done":
        why.append(f"robot_main {robot.get('result')} ≠ done")
    if home not in ("moved", "already"):
        why.append(f"home {home} ∉ moved/already")
    seq = robot.get("seq")
    if not isinstance(park_state, dict) or park_state.get("seq") != seq or park_state.get("state") != "done":
        why.append(f"park статус {park_state} не догнал ответ seq {seq}")
    # SERVO, за которым в своём блоке (до следующего CMD_OPCODE) идёт CMD_ARGS[0] = 0.
    servo_at: int | None = None
    for i, text in enumerate(texts):
        if text.strip() != "W* CMD_OPCODE = 65 (SERVO)":
            continue
        for follow in texts[i + 1 :]:
            if "CMD_OPCODE" in follow:
                break
            if follow.strip() == "W* CMD_ARGS[0] = 0":
                servo_at = i
                break
        if servo_at is not None:
            break
    if servo_at is None:
        why.append("servo нет SERVO с CMD_ARGS[0] = 0")
    if home == "moved":
        sc_run = _find_index(texts, "W* CMD_OPCODE = 48 (SC_RUN)")
        if sc_run is None or (servo_at is not None and sc_run > servo_at):
            why.append("sc_run нет SC_RUN до SERVO при home moved")
    if any("STOP_REQ" in t for t in texts):
        why.append("STOP_REQ строка STOP_REQ при park")
    observed = f"status={res.get('status')} robot_main={robot.get('result')} home={home} seq={seq} park={park_state}"
    return Row(None, "home", "", observed, not why, tuple(why))


_STOP_RE = re.compile(r"STOP_REQ = (\d+)")


def judge_stop(file_lines: list[str], after_seq: int) -> Row:
    """Чистый стоп по файлу журнала: после ``after_seq`` один SOFT ``STOP_REQ`` (n % 4 == 1), затем disconnect."""
    parsed = [p for p in (parse_exchange_file_line(ln) for ln in file_lines) if p is not None and p[0] > after_seq]
    parsed.sort(key=lambda p: p[0])
    if not parsed:
        return Row(None, "stop", "", "нет строк", False, (f"нет строк журнала после seq {after_seq}",))
    stops = [(seq, int(m.group(1))) for seq, text in parsed if (m := _STOP_RE.search(text))]
    why: list[str] = []
    note = ""
    if len(stops) != 1:
        why.append(f"STOP_REQ строк {len(stops)} ≠ 1")
    else:
        stop_seq, n = stops[0]
        if n % 4 != 1:
            why.append(f"STOP_REQ n={n}, n % 4 = {n % 4} ≠ 1 (не SOFT)")
        if not any(text == "disconnect" and seq > stop_seq for seq, text in parsed):
            why.append("disconnect нет после STOP_REQ")
        if any("(SERVO)" in text for seq, text in parsed if seq < stop_seq):
            note = " | стоп сделал свой park"
    observed = f"STOP_REQ {[n for _, n in stops]}, строк после seq {after_seq}: {len(parsed)}{note}"
    return Row(None, "stop", "", observed, not why, tuple(why))


_NOT_VISIBLE = "итог детей не виден (предел драйвера)"


def judge_shutdown(reply: dict, port_free: bool) -> Row:
    """``system_shutdown``: FAIL при отказе, таймауте, занятом порте; пометка о пределе драйвера — при ``pm_gone``."""
    accepted = reply.get("accepted")
    timed_out = reply.get("timed_out")
    unconfirmed = reply.get("unconfirmed")
    pm_gone = reply.get("pm_gone")
    why: list[str] = []
    note = ""
    if accepted is False:
        why.append("accepted False")
    if timed_out is True:
        why.append("timed_out True")
    if port_free is False:
        why.append("port порт прототипа не освободился")
    if not why and not (accepted is True and not unconfirmed):
        if pm_gone is True:
            note = f" | {_NOT_VISIBLE}: unconfirmed={unconfirmed}"
        else:
            why.append(f"pm_gone {pm_gone} при unconfirmed={unconfirmed}, accepted={accepted}")
    observed = (
        f"accepted={accepted} timed_out={timed_out} pm_gone={pm_gone} port_free={port_free} "
        f"outcomes={reply.get('outcomes')}{note}"
    )
    return Row(None, "shutdown", "", observed, not why, tuple(why))


# --- Печать и код выхода ----------------------------------------------------------------------------------------------


def format_row(case_id: str, row: Row) -> str:
    verdict = "PASS" if row.ok else ("FAIL: " + "; ".join(row.reasons) if row.reasons else "FAIL")
    if row.index is not None:
        return f"{case_id} #{row.index} вход {row.given} → наблюдение: {row.observed} → {verdict}"
    return f"{case_id} {row.check}: {row.observed} → {verdict}"


def format_summary(statuses: dict[str, str | None], rc: int) -> str:
    parts = " ".join(f"{key}={statuses.get(key) or '—'}" for key in ("B", "D", "C", "ДОМОЙ", "СТОП"))
    return f"итог: {parts} → код {rc} (вердикт α — Task 1.2, не этот скрипт)"


def exit_code(results: list[CaseResult | Row], precondition_error: bool = False) -> int:
    """3 — предусловие; 1 — хоть одна проверка не прошла; 0 — всё PASS."""
    if precondition_error:
        return 3
    return 1 if any(not r.ok for r in results) else 0
