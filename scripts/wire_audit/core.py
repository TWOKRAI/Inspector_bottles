"""Ядро аудита провода CVT_JOB: по файлам журналов проверяет, что слова, ушедшие роботу, верны.

Чистые функции без ввода-вывода: разборщики (``parse_exchange``, ``parse_layout``, ``parse_passports``,
``parse_sim_seqs``), расшифровка (``decode_cvt``), ожидания (``expected_*``), судья (``audit``) и таблица
(``render``). Файлы читает ``__main__``. Время не читается, сеть не трогается.

Аудит независим от α: свои разборщики и литералы, код скрипта α не импортируется и не читается. Ожидания считаются
здесь же из регистров, слова и сырого угла сети, а не берутся из драйвера и не из полей ``положить``/``взять``
строки диска (кроме проверки «передача»: слова взятия против ``взять(px,py)`` строки диска).

Приведение слова к проводу — ``round_half_away(v·10)`` по модулю 65536 (WIRE_SCALE = 10: десятые доли мм и
градуса). Допуск колонки А — один квант: ±0,10 мм / ±0,10° плюс 1e-6.
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime

WIRE_SCALE = 10
_WORD_MOD = 65536
_TOL = 0.10
_EPS = 1e-6
_FLAGS_WORD = 3  # бит0 z != 0, бит1 есть place
_ARGC = 10
# Окно α взято из сим-калибровки; на железе/β задавать флагом. Слова провода, 1 слово = 0,1 мм.
_ALPHA_X_WINDOW = (4549, 4615)  # окно α для ARGS[2]
_ALPHA_Y_WINDOW = (62096, 62116)  # окно α для ARGS[3]
# Выход за окно не дальше запаса — шум центроида сети (PASS~), дальше — FAIL «окно». Флаг ``--pick-margin-mm``.
_PICK_MARGIN_DEFAULT_MM = 5.0
_ZONE_DEFAULT_MM = 500.0
_P_PICK_DEFAULT_DEG = -100.0
_RZ_TILDE_DEG = 15.0  # |e| > 15 град — «ТОЧНОСТЬ сети», не FAIL
_RUN_MIN_DISKS = 9  # столько судимых дисков нужно для вердикта по медиане e
_RUN_MEDIAN_FAIL_DEG = 10.0
_PICK_X_ZERO_MM = 458.2  # x взятия сима при lateral 0 (apps/line_sim/pipeline.yaml)
_PX_PER_MM = 8.163265  # масштаб сима, px/мм
_PICK_X_PASS_MM = 1.0
_PICK_X_YELLOW_MM = 2.0
_WRAP_EDGE_DEG = 179.95  # у ±180 печать с одним знаком после запятой не различает сторону

# индексы слов CVT_JOB
I_ECAP_LO, I_ECAP_HI, I_PICK_X, I_PICK_Y, I_PICK_Z, I_FLAGS, I_PLACE_X, I_PLACE_Y, I_PLACE_Z, I_PLACE_RZ = range(10)

_TS_FORMAT = "%Y-%m-%d %H:%M:%S,%f"
_TS = r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3})"
_NUM = r"(-?\d+(?:\.\d+)?)"

_EX_LINE = re.compile(rf"^#(\d+)\s+{_TS}\s+\[[^\]]*\]\s+\S*robot_main:\s+#(\d+)\s+(.*)$")
_EX_SEQ = re.compile(r"^in\s+W\*?\s+CMD_SEQ\s*=\s*(\d+)")
_EX_OPCODE = re.compile(r"^in\s+W\*?\s+CMD_OPCODE\s*=\s*\d+\s*\(([^)]*)\)")
_EX_ARGC = re.compile(r"^in\s+W\*?\s+CMD_ARGC\s*=\s*(\d+)")
_EX_ARG = re.compile(r"^in\s+W\*?\s+CMD_ARGS\[(\d+)\]\s*=\s*(-?\d+)")
_EX_FLAG = re.compile(r"^in\s+W\*?\s+CMD_FLAG\s*=")
_EX_REPLY = re.compile(
    r"^(?:out|in)\s+R\s+RES_SEQ\.\.\+\d+\s+RES_SEQ\s*=\s*(\d+),\s*RES_STATUS\s*=\s*(\d+),\s*RES_ERRNO\s*=\s*(-?\d+)"
)

_LAY_LINE = re.compile(rf"^#(\d+)\s+{_TS}\s+\[[^\]]*\]\s+(.*)$")
_LAY_INIT = "LoggerManager initialized"
_LAY_PLUGIN = "WordLayoutPlugin: "
_LAY_WORD = re.compile(r"^слово '(.*?)' \(источник")
_LAY_CHANGE = re.compile(r"^смена слова '(.*?)' → '(.*?)' \(источник")
_LAY_PICK = re.compile(rf"^диск '(.+?)' {_NUM}° → ячейка (\d+): взять\({_NUM},\s*{_NUM}\)")
_LAY_SKIP = re.compile(rf"^диск '(.+?)' {_NUM}° → пропуск: (.*)$")

_SIM_CMD = re.compile(r"\[v2\]\s+CMD\s+seq=(\d+)\s+op=CVT_JOB")

TABLE_HEADER = ("#", "заливка", "буква", "сеть°", "ячейка", "x", "y", "rz", "ecap", "seq", "ответ", "А", "Б", "итог")

NOT_COVERED = (
    "pick y и ecap: проверяется только окно α для ARGS[3], расчёта нет; ecap только печатается",
    "pick x против общих углов калибровки и масштаба сим/рецепт: не видно (масштаб 8,163 против 6,135 px/мм)",
    "rz против истины: только ±30° сети; сдвиг нуля до 10° не виден; знак не виден на подачах 0°/180°",
    "angle_valid=False (полная симметрия буквы): доворот не проверяется",
    "место укладки: сим его не проверяет, судится только слово провода",
)


class AuditError(Exception):
    """Отказ аудита: ``code`` — код возврата CLI (2 — аргументы/не поддержано, 3 — вход не читается)."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ------------------------------------------------------------------------- числа и слова


def wrap180(deg: float) -> float:
    """Угол к диапазону (−180, 180]: кратчайший доворот."""
    d = (float(deg) + 180.0) % 360.0 - 180.0
    return 180.0 if d == -180.0 else d


def round_half_away(x: float) -> int:
    """Округление «от нуля» на половинке: 0,5 → 1, −0,5 → −1."""
    return int(math.copysign(math.floor(abs(x) + 0.5), x))


def to_unsigned(word: int) -> int:
    """Слово провода без знака 0..65535 (в журнале −1000 встречается как 64536)."""
    return int(word) % _WORD_MOD


def to_signed(word: int) -> int:
    """Слово ≥ 32768 → n − 65536."""
    u = to_unsigned(word)
    return u - _WORD_MOD if u >= 32768 else u


def encode_word(value: float) -> int:
    """Значение (мм или градусы) → слово провода 0..65535."""
    return round_half_away(value * WIRE_SCALE) % _WORD_MOD


def word_matches(word: int, value: float) -> bool:
    """Слово провода совпадает с ожидаемым значением в пределах одного кванта (0,10 плюс 1e-6)."""
    diff = (to_unsigned(word) - encode_word(value) + _WORD_MOD // 2) % _WORD_MOD - _WORD_MOD // 2
    return abs(diff) / WIRE_SCALE <= _TOL + _EPS


def parse_ts(text: str) -> datetime | None:
    """Наивная локальная метка вида ``2026-11-12 13:33:27,133``; не метка — None."""
    try:
        return datetime.strptime(text.strip(), _TS_FORMAT)
    except ValueError:
        return None


# ------------------------------------------------------------------------- журнал обмена


@dataclass
class Job:
    """Один блок ``CVT_JOB`` журнала обмена."""

    line: int  # номер строки файла (ведущий ``#n``) у ``CMD_OPCODE``
    t: datetime
    seq: int | None
    argc: int | None = None
    args: dict[int, int] = field(default_factory=dict)
    seq_pos: int = -1  # позиция строки CMD_SEQ среди разобранных строк
    flag_pos: int | None = None  # позиция строки CMD_FLAG; None — блок оборван
    replies: list[tuple[int, int]] = field(default_factory=list)  # (status, errno) строк R по порядку файла

    @property
    def first_reply(self) -> tuple[int, int] | None:
        return self.replies[0] if self.replies else None

    @property
    def accepted(self) -> bool:
        reply = self.first_reply
        return reply is not None and reply[0] == 1


def parse_exchange(text: str) -> list[Job]:
    """Блоки ``CVT_JOB`` последней инкарнации журнала обмена (от последней строки с номером ``#1``).

    Блок открывает ``CMD_OPCODE`` с именем ``CVT_JOB``; ``CMD_SEQ`` стоит перед ним. Ответ — первая строка R с
    ``RES_SEQ == CMD_SEQ`` после ``CMD_FLAG`` блока; последующие такие строки (до следующего блока с тем же seq)
    тоже собираются: ``audit`` сравнивает их статусы с первой. Остальные строки пропускаются молча.
    """
    rows: list[tuple[int, datetime, int, str]] = []
    for raw in text.splitlines():
        m = _EX_LINE.match(raw)
        stamp = parse_ts(m.group(2)) if m else None
        if m and stamp:
            rows.append((int(m.group(1)), stamp, int(m.group(3)), m.group(4).strip()))
    start = max((pos for pos, row in enumerate(rows) if row[2] == 1), default=0)
    rows = rows[start:]

    jobs: list[Job] = []
    seq_marks: list[tuple[int, int]] = []  # (позиция, seq) у блока любой команды
    reply_rows: list[tuple[int, int, int, int]] = []  # (позиция, seq, status, errno)
    cur: Job | None = None
    pending_seq: int | None = None
    pending_pos = -1
    for pos, (line_no, stamp, _n, body) in enumerate(rows):
        if m := _EX_SEQ.match(body):
            pending_seq, pending_pos, cur = int(m.group(1)), pos, None
            seq_marks.append((pos, pending_seq))
        elif m := _EX_OPCODE.match(body):
            cur = None
            if m.group(1).strip() == "CVT_JOB":
                cur = Job(line=line_no, t=stamp, seq=pending_seq, seq_pos=pending_pos)
                jobs.append(cur)
        elif m := _EX_REPLY.match(body):
            reply_rows.append((pos, int(m.group(1)), int(m.group(2)), int(m.group(3))))
        elif cur is None:
            continue
        elif m := _EX_ARGC.match(body):
            cur.argc = int(m.group(1))
        elif m := _EX_ARG.match(body):
            cur.args[int(m.group(1))] = int(m.group(2))
        elif _EX_FLAG.match(body):
            cur.flag_pos, cur = pos, None

    for job in jobs:
        if job.flag_pos is None or job.seq is None:
            continue
        limit = min((p for p, s in seq_marks if p > job.seq_pos and s == job.seq), default=len(rows))
        job.replies = [(st, er) for p, sq, st, er in reply_rows if sq == job.seq and job.flag_pos < p < limit]
    return jobs


def decode_cvt(args: dict[int, int]) -> dict[str, int | float | None]:
    """Расшифровка слов CVT_JOB: мм и градусы = слово / 10 (знаковое), ecap = ARGS[1]·65536 + ARGS[0]."""

    def val(index: int) -> float | None:
        return to_signed(args[index]) / WIRE_SCALE if index in args else None

    ecap = None
    if I_ECAP_LO in args and I_ECAP_HI in args:
        ecap = to_unsigned(args[I_ECAP_HI]) * _WORD_MOD + to_unsigned(args[I_ECAP_LO])
    return {
        "ecap": ecap,
        "pick_x": val(I_PICK_X),
        "pick_y": val(I_PICK_Y),
        "pick_z": val(I_PICK_Z),
        "flags": to_unsigned(args[I_FLAGS]) if I_FLAGS in args else None,
        "place_x": val(I_PLACE_X),
        "place_y": val(I_PLACE_Y),
        "place_z": val(I_PLACE_Z),
        "place_rz": val(I_PLACE_RZ),
    }


def _same_args(a: Job, b: Job) -> bool:
    keys = range(I_PICK_X, I_PLACE_RZ + 1)
    return bool(a.args) and all(a.args.get(i) == b.args.get(i) for i in keys)


def find_retries(jobs: list[Job]) -> set[int]:
    """Индексы отказанных блоков, за которыми идёт блок с теми же ARGS[2..9] и статусом 1 (E_BUSY-повтор).

    Цепочка «отказ, отказ, принято» с одинаковыми словами тоже повтор: считается с хвоста.
    """
    retried: set[int] = set()
    for i in range(len(jobs) - 2, -1, -1):
        a, b = jobs[i], jobs[i + 1]
        reply = a.first_reply
        if reply is not None and reply[0] != 1 and _same_args(a, b) and (b.accepted or (i + 1) in retried):
            retried.add(i)
    return retried


# ------------------------------------------------------------------------- журнал диска


@dataclass
class WordEvent:
    """Строка ``слово '…'`` или ``смена слова '…' → '…'``: режет журнал на заливки."""

    t: datetime
    word: str  # слово, которое действует после строки


@dataclass
class Disk:
    """Строка диска: взятие (``cell`` задан) или пропуск (``skip_reason`` задан)."""

    t: datetime
    letter: str
    net: float  # сырой угол сети, градусы
    cell: int | None = None
    px: float | None = None
    py: float | None = None
    skip_reason: str | None = None


def parse_layout(text: str) -> list[WordEvent | Disk]:
    """События последней инкарнации журнала диска (от последней ``LoggerManager initialized``) по времени.

    Порядок при равных метках — порядок строк файла. Остальные строки пропускаются молча.
    """
    parsed: list[tuple[datetime, str]] = []
    start = 0
    for raw in text.splitlines():
        m = _LAY_LINE.match(raw)
        stamp = parse_ts(m.group(2)) if m else None
        if not (m and stamp):
            continue
        if _LAY_INIT in m.group(3):
            start = len(parsed)
        parsed.append((stamp, m.group(3)))

    events: list[WordEvent | Disk] = []
    for stamp, message in parsed[start:]:
        _, sep, body = message.partition(_LAY_PLUGIN)
        if not sep:
            continue
        if m := _LAY_CHANGE.match(body):
            events.append(WordEvent(stamp, m.group(2)))
        elif m := _LAY_WORD.match(body):
            events.append(WordEvent(stamp, m.group(1)))
        elif m := _LAY_PICK.match(body):
            events.append(
                Disk(stamp, m.group(1), float(m.group(2)), int(m.group(3)), float(m.group(4)), float(m.group(5)))
            )
        elif m := _LAY_SKIP.match(body):
            events.append(Disk(stamp, m.group(1), float(m.group(2)), skip_reason=m.group(3)))
    events.sort(key=lambda e: e.t)  # сортировка устойчивая: равные метки остаются в порядке файла
    return events


# ------------------------------------------------------------------------- регистры и ожидания


@dataclass(frozen=True)
class Regs:
    first_x: float
    first_y: float
    pitch_mm: float
    disk_radius_mm: float
    line_angle_deg: float
    place_z_mm: float
    pick_z_mm: float
    angle_zero_deg: float
    angle_invert: bool
    p_pick_rz_deg: float
    p_pick_from_register: bool
    p_pick_source: str | None = None  # ``p_pick_rz_source`` файла регистров (пишет сборщик), иначе None


_REQUIRED_REGISTERS = (
    "first_x",
    "first_y",
    "pitch_mm",
    "disk_radius_mm",
    "line_angle_deg",
    "place_z_mm",
    "pick_z_mm",
    "angle_zero_deg",
    "angle_invert",
    "use_pitch",
)


def load_registers(data: dict) -> Regs:
    """Регистры из JSON-словаря. ``use_pitch=false`` — «не поддержано» (код 2)."""
    missing = [k for k in _REQUIRED_REGISTERS if k not in data]
    if missing:
        raise AuditError(2, "в регистрах нет обязательных полей: " + ", ".join(missing))
    try:
        floats = {k: float(data[k]) for k in _REQUIRED_REGISTERS if k not in ("angle_invert", "use_pitch")}
        p_pick = float(data["p_pick_rz_deg"]) if "p_pick_rz_deg" in data else _P_PICK_DEFAULT_DEG
    except (TypeError, ValueError) as exc:
        raise AuditError(2, "в регистрах нечисловое значение") from exc
    if not data["use_pitch"]:
        raise AuditError(2, "не поддержано: use_pitch=false (укладка по слотам без шага)")
    return Regs(
        angle_invert=bool(data["angle_invert"]),
        p_pick_rz_deg=p_pick,
        p_pick_from_register="p_pick_rz_deg" in data,
        p_pick_source=data["p_pick_rz_source"] if isinstance(data.get("p_pick_rz_source"), str) else None,
        **floats,
    )


def expected_pitch(regs: Regs) -> float:
    """Шаг ячеек: ``pitch_mm`` или два радиуса диска при ``pitch_mm`` 0."""
    return regs.pitch_mm or 2.0 * regs.disk_radius_mm


def expected_place_xy(regs: Regs, cell: int) -> tuple[float, float]:
    """Место укладки ячейки ``cell``: ``first + cell·pitch`` по линии ``line_angle``."""
    angle = math.radians(regs.line_angle_deg)
    step = cell * expected_pitch(regs)
    return regs.first_x + step * math.cos(angle), regs.first_y + step * math.sin(angle)


def expected_corr(regs: Regs, net_deg: float) -> float:
    """Доворот диска по сырому углу сети: ``wrap180(angle_zero − sign·a)``."""
    sign = -1.0 if regs.angle_invert else 1.0
    return wrap180(regs.angle_zero_deg - sign * net_deg)


def expected_rz_options(regs: Regs, net_deg: float) -> list[float]:
    """Допустимые ``place rz``: у ±180° печать сети не различает сторону, поэтому два значения (разница 360°)."""
    corr = expected_corr(regs, net_deg)
    options = [regs.p_pick_rz_deg + corr]
    if abs(corr) >= _WRAP_EDGE_DEG:
        options.append(regs.p_pick_rz_deg + corr - math.copysign(360.0, corr))
    return options


# ------------------------------------------------------------------------- судья


@dataclass
class Row:
    """Строка таблицы: строка диска или служебная («лишнее» до первого взятия, «лишнее у сима»)."""

    ordinal: str
    fill: str = "-"
    letter: str = "-"
    net: str = "-"
    cell: str = "-"
    x: str = "-"
    y: str = "-"
    rz: str = "-"
    ecap: str = "-"
    seq: str = "-"
    answer: str = "-"
    col_a: str = "-"
    col_b: str = "-"
    reasons: list[str] = field(default_factory=list)
    tilde: bool = False
    disk: Disk | None = None
    job: Job | None = None
    reach_warn: bool = False
    window_warn: bool = False
    passport: Passport | None = None  # паспорт сима, поставленный в пару строке диска (столбец Б)

    def add(self, *reasons: str) -> None:
        self.reasons.extend(r for r in reasons if r not in self.reasons)

    @property
    def result(self) -> str:
        if self.reasons:
            return "FAIL: " + "; ".join(self.reasons)
        return "PASS~" if self.tilde else "PASS"

    @property
    def failed(self) -> bool:
        return bool(self.reasons)

    def cells(self) -> list[str]:
        raw = [
            self.ordinal,
            self.fill,
            self.letter,
            self.net,
            self.cell,
            self.x,
            self.y,
            self.rz,
            self.ecap,
            self.seq,
            self.answer,
            self.col_a,
            self.col_b,
            self.result,
        ]
        return [c.replace("|", "/") for c in raw]


@dataclass
class AuditResult:
    rows: list[Row]
    words: list[str]
    words_given: bool  # True — слова из --words, False — из журнала диска («слово не независимо»)
    p_pick_rz_deg: float
    p_pick_from_register: bool
    p_pick_source: str | None
    zone_max_mm: float
    pick_margin_mm: float
    run_lines: list[str]  # строки между таблицей и блоком «Не покрыто»
    run_fail: bool
    notes: list[str]
    picks: int
    jobs: int
    skips: int
    retries: int
    warnings: int

    @property
    def fails(self) -> int:
        return sum(1 for r in self.rows if r.failed) + (1 if self.run_fail else 0)

    @property
    def exit_code(self) -> int:
        return 1 if self.fails or (self.picks > 0 and self.jobs == 0) else 0

    @property
    def summary(self) -> str:
        verdict = "FAIL" if self.exit_code else "PASS"
        return (
            f"ИТОГ: {verdict} (взятий {self.picks}, заданий {self.jobs}, FAIL {self.fails}, "
            f"пропусков {self.skips}, повторов {self.retries}, предупреждений {self.warnings})"
        )


def _window_excess_mm(word: int | None, window: tuple[int, int]) -> float:
    """На сколько мм слово провода вышло за окно α (0 — внутри или слова нет)."""
    if word is None:
        return 0.0
    value = to_unsigned(word)
    return max(window[0] - value, value - window[1], 0) / WIRE_SCALE


def _check_words(
    job: Job, disk: Disk, regs: Regs, zone_max_mm: float, pick_margin_mm: float = _PICK_MARGIN_DEFAULT_MM
) -> tuple[list[str], bool, str | None]:
    """Колонка А: слова одного задания против ожиданий.

    Возвращает (причины FAIL, предупреждение о досягаемости, пометка «съём вне окна α»). Выход pick x/y за окно α
    не дальше ``pick_margin_mm`` — не FAIL, а ``PASS~`` с пометкой (шум центроида сети); дальше — причина «окно».
    Проверка «слово = взять(px, py) журнала диска» (``передача``) от окна не зависит и остаётся FAIL.
    """
    reasons: list[str] = []
    args = job.args
    if job.argc != _ARGC:
        reasons.append("argc")
    reasons.extend(f"нет ARGS[{i}]" for i in range(_ARGC) if i not in args)

    def bad(index: int, value: float) -> bool:
        return index in args and not word_matches(args[index], value)

    cell = disk.cell if disk.cell is not None else 0
    place_x, place_y = expected_place_xy(regs, cell)
    if I_FLAGS in args and to_unsigned(args[I_FLAGS]) != _FLAGS_WORD:
        reasons.append("flags")
    if bad(I_PLACE_X, place_x):
        reasons.append("x")
    if bad(I_PLACE_Y, place_y):
        reasons.append("y")
    if bad(I_PLACE_Z, regs.place_z_mm) or bad(I_PICK_Z, regs.pick_z_mm):
        reasons.append("z")
    if I_PLACE_RZ in args and not any(word_matches(args[I_PLACE_RZ], v) for v in expected_rz_options(regs, disk.net)):
        reasons.append("rz")
    if (disk.px is not None and bad(I_PICK_X, disk.px)) or (disk.py is not None and bad(I_PICK_Y, disk.py)):
        reasons.append("передача")
    over_mm = max(
        _window_excess_mm(args.get(I_PICK_X), _ALPHA_X_WINDOW), _window_excess_mm(args.get(I_PICK_Y), _ALPHA_Y_WINDOW)
    )
    window_note: str | None = None
    if over_mm > _EPS:
        if over_mm <= pick_margin_mm + _EPS:
            window_note = f"съём вне окна α на {over_mm:.1f} мм (шум центроида сети)"
        else:
            reasons.append("окно")
    return reasons, math.hypot(place_x, place_y) > zone_max_mm, window_note


def _job_reasons(job: Job, seq_counts: dict[int, int]) -> list[str]:
    """Причины FAIL по самому заданию: дубль seq, ответ, статус."""
    reasons: list[str] = []
    if job.seq is not None and seq_counts.get(job.seq, 0) > 1:
        reasons.append("дубль seq")
    reply = job.first_reply
    if reply is None:
        reasons.append("нет ответа")
        return reasons
    if reply[0] != 1:
        reasons.append(f"статус {reply[0]}")
    if any(other != reply for other in job.replies[1:]):
        reasons.append("ответ противоречив")
    return reasons


def _integrity_reasons(job: Job) -> list[str]:
    reasons = [] if job.argc == _ARGC else ["argc"]
    return reasons + [f"нет ARGS[{i}]" for i in range(_ARGC) if i not in job.args]


def _fill_wire_cells(row: Row, job: Job) -> None:
    """Колонки x/y/rz/ecap/seq/ответ из слов задания."""
    wire = decode_cvt(job.args)

    def fmt(value: float | int | None) -> str:
        return "-" if value is None else f"{value:.1f}"

    row.x, row.y, row.rz = fmt(wire["place_x"]), fmt(wire["place_y"]), fmt(wire["place_rz"])
    row.ecap = "-" if wire["ecap"] is None else str(wire["ecap"])
    row.seq = "-" if job.seq is None else str(job.seq)
    reply = job.first_reply
    row.answer = "-" if reply is None else f"{reply[0]}/{reply[1]}"


def _bind_jobs(picks: list[Row], jobs: list[Job], regs: Regs) -> dict[int, Job]:
    """Привязка «взятие ↔ задание» (DESIGN п.6): первое по строкам файла свободное задание с временем ≥ времени
    взятия, словом ARGS[7] ожидаемой ячейки и временем меньше следующего взятия в ту же ячейку."""
    taken = [False] * len(jobs)
    bound: dict[int, Job] = {}
    for k, row in enumerate(picks):
        disk = row.disk
        assert disk is not None and disk.cell is not None
        y_word = encode_word(expected_place_xy(regs, disk.cell)[1])
        upper = next((p.disk.t for p in picks[k + 1 :] if p.disk and p.disk.cell == disk.cell), None)
        for ji, job in enumerate(jobs):
            if taken[ji] or job.t < disk.t:
                continue
            if I_PLACE_Y not in job.args or to_unsigned(job.args[I_PLACE_Y]) != y_word:
                continue
            if upper is not None and job.t >= upper:
                continue
            taken[ji] = True
            bound[k] = job
            break
    return bound


@dataclass
class Passport:
    """Паспорт объекта сима (``--sim-objects``)."""

    letter: str
    angle_deg: float | None
    lateral_px: float | None
    t: datetime
    object_id: str = ""


def parse_passports(items: list[dict]) -> tuple[list[Passport], int]:
    """Паспорта по времени (устойчиво) и число отброшенных записей (нет буквы или метки ``t``)."""
    out: list[Passport] = []
    skipped = 0
    for item in items:
        stamp = parse_ts(str(item.get("t", ""))) if isinstance(item, dict) else None
        letter = item.get("class_name") if isinstance(item, dict) else None
        if stamp is None or not isinstance(letter, str):
            skipped += 1
            continue
        out.append(
            Passport(
                letter,
                _num(item.get("angle_deg")),
                _num(item.get("lateral_px")),
                stamp,
                str(item.get("object_id", "")),
            )
        )
    out.sort(key=lambda p: p.t)
    return out, skipped


def _num(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def parse_sim_seqs(items: list[dict]) -> set[int]:
    """Множество ``seq`` строк ``[v2] CMD seq=… op=CVT_JOB`` журнала сим-робота (дубли ``(t, side, text)`` склеены)."""
    seen: set[tuple[str, str, str]] = set()
    seqs: set[int] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        key = (str(item.get("t")), str(item.get("side")), str(item.get("text")))
        if key in seen:
            continue
        seen.add(key)
        if m := _SIM_CMD.search(key[2]):
            seqs.add(int(m.group(1)))
    return seqs


def _judge_passport(job: Job, disk: Disk, passport: Passport, regs: Regs) -> tuple[str, list[str], bool, float | None]:
    """Колонка Б одного диска: (текст ячейки, причины FAIL, жёлтая зона, ошибка доворота e)."""
    wire = decode_cvt(job.args)
    parts: list[str] = []
    reasons: list[str] = []
    tilde = False
    err: float | None = None
    rz = wire["place_rz"]
    if passport.angle_deg is not None and rz is not None:
        if min(abs(passport.angle_deg % 360.0), abs(passport.angle_deg % 360.0 - 180.0)) < _EPS:
            parts.append("rz не судится, подача 0°/180°")
        else:
            corr_wire = wrap180(float(rz) - regs.p_pick_rz_deg)
            err = wrap180(corr_wire - expected_corr(regs, passport.angle_deg))
            parts.append(f"e={err:+.1f}°")
            tilde = abs(err) > _RZ_TILDE_DEG + _EPS
    pick_x = wire["pick_x"]
    if passport.lateral_px is not None and pick_x is not None:
        dx = float(pick_x) - (_PICK_X_ZERO_MM - passport.lateral_px / _PX_PER_MM)
        parts.append(f"dx={dx:+.1f}")
        if abs(dx) > _PICK_X_YELLOW_MM + _EPS:
            reasons.append("x")
        elif abs(dx) > _PICK_X_PASS_MM + _EPS:
            tilde = True
    head = "FAIL: x" if reasons else ("PASS~" if tilde else "PASS")
    return (f"{head} ({', '.join(parts)})" if parts else head), reasons, tilde, err


def _attach_extra(rows: list[Row], job: Job, reasons: list[str]) -> None:
    """Лишнее задание: FAIL у ближайшей предшествующей по времени строки диска, иначе служебная строка."""
    prior = [r for r in rows if r.disk is not None and r.disk.t <= job.t]
    if prior:
        target = prior[-1]
        where = " (seq {}, после пропуска)" if target.disk and target.disk.skip_reason is not None else " (seq {})"
        target.add("лишнее" + where.format(job.seq), *reasons)
        return
    extra = Row(ordinal="-", job=job)
    _fill_wire_cells(extra, job)
    extra.add(f"лишнее (seq {job.seq}, до первого взятия)", *reasons)
    rows.insert(0, extra)


def audit(
    exchange_text: str,
    layout_text: str,
    registers: dict,
    *,
    words: list[str] | None = None,
    zone_max_mm: float = _ZONE_DEFAULT_MM,
    pick_margin_mm: float = _PICK_MARGIN_DEFAULT_MM,
    sim_objects: list[dict] | None = None,
    sim_journal: list[dict] | None = None,
) -> AuditResult:
    """Судит провод: строка диска ↔ задание, колонки А и Б, третий наблюдатель, счётчики.

    Исключения ``AuditError``: код 2 — регистры, число слов ``--words`` не равно числу строк слова журнала диска,
    слово с пробелом.
    """
    regs = load_registers(registers)
    all_jobs = parse_exchange(exchange_text)
    events = parse_layout(layout_text)

    journal_words = [e.word for e in events if isinstance(e, WordEvent)]
    if words is not None and len(words) != len(journal_words):
        raise AuditError(
            2,
            "число слов --words не равно числу строк слова и смены слова в журнале диска "
            f"(--words: {len(words)}, в журнале диска строк слова {len(journal_words)})",
        )
    fill_words = list(words) if words is not None else journal_words
    if any(re.search(r"\s", w) or not w for w in fill_words):
        raise AuditError(2, "не поддержано: слово с пробелом или пустое слово")
    wrong_fills = (
        {n + 1 for n, (j, w) in enumerate(zip(journal_words, fill_words)) if j.upper() != w.upper()}
        if words is not None
        else set()
    )

    rows = _disk_rows(events, fill_words, wrong_fills)
    retried = find_retries(all_jobs)
    seq_counts: dict[int, int] = {}
    for i, job in enumerate(all_jobs):
        if i not in retried and job.seq is not None:
            seq_counts[job.seq] = seq_counts.get(job.seq, 0) + 1
    live = [job for i, job in enumerate(all_jobs) if i not in retried]

    picks = [r for r in rows if r.disk is not None and r.disk.cell is not None]
    bound = _bind_jobs(picks, live, regs)
    bound_ids = {id(j) for j in bound.values()}
    sim_seen = parse_sim_seqs(sim_journal) if sim_journal is not None else None

    for k, row in enumerate(picks):
        job = bound.get(k)
        if job is None:
            row.add("потеря")
            continue
        _judge_bound(row, job, regs, zone_max_mm, pick_margin_mm, seq_counts, sim_seen)

    run_lines, run_fail, no_passport = _column_b(rows, picks, bound, regs, sim_objects)
    for job in live:
        if id(job) not in bound_ids:
            extra_reasons = _integrity_reasons(job) + _job_reasons(job, seq_counts)
            if sim_seen is not None and job.accepted and job.seq not in sim_seen:
                extra_reasons.append("сим не видел")
            _attach_extra(rows, job, extra_reasons)
    if sim_seen is not None:
        mine = {job.seq for job in live if job.accepted}
        for seq in sorted(sim_seen - mine):
            extra = Row(ordinal="-", seq=str(seq))
            extra.add(f"лишнее у сима (seq {seq})")
            rows.append(extra)
    for n, row in enumerate(r for r in rows if r.ordinal != "-"):
        row.ordinal = str(n + 1)

    notes = []
    if sim_objects is not None and no_passport:
        notes.append(f"дисков без паспорта сима: {no_passport} (не FAIL)")
    return AuditResult(
        rows=rows,
        words=fill_words,
        words_given=words is not None,
        p_pick_rz_deg=regs.p_pick_rz_deg,
        p_pick_from_register=regs.p_pick_from_register,
        p_pick_source=regs.p_pick_source,
        zone_max_mm=zone_max_mm,
        pick_margin_mm=pick_margin_mm,
        run_lines=run_lines,
        run_fail=run_fail,
        notes=notes,
        picks=len(picks),
        jobs=len(live),
        skips=sum(1 for r in rows if r.disk is not None and r.disk.skip_reason is not None),
        retries=len(retried),
        warnings=sum(1 for r in rows if r.reach_warn or r.window_warn),
    )


def _disk_rows(events: list[WordEvent | Disk], fill_words: list[str], wrong_fills: set[int]) -> list[Row]:
    """Строки таблицы по строкам диска: заливка, слово, ячейка (принадлежит букве слова, не повторяется)."""
    rows: list[Row] = []
    used: dict[int, set[int]] = {}
    fill = 0
    for ev in events:
        if isinstance(ev, WordEvent):
            fill += 1
            continue
        row = Row(ordinal="", fill=str(fill), letter=ev.letter, net=f"{ev.net:.1f}", disk=ev)
        rows.append(row)
        if fill in wrong_fills:
            row.add("слово")
        if ev.cell is None:
            continue
        row.cell = str(ev.cell)
        word = fill_words[fill - 1] if fill >= 1 else ""
        taken = used.setdefault(fill, set())
        if not (0 <= ev.cell < len(word)) or word[ev.cell].upper() != ev.letter.upper() or ev.cell in taken:
            row.add("ячейка")
        taken.add(ev.cell)
    return rows


def _judge_bound(
    row: Row,
    job: Job,
    regs: Regs,
    zone_max_mm: float,
    pick_margin_mm: float,
    seq_counts: dict[int, int],
    sim_seen: set[int] | None,
) -> None:
    disk = row.disk
    assert disk is not None
    row.job = job
    _fill_wire_cells(row, job)
    a_reasons, warn, window_note = _check_words(job, disk, regs, zone_max_mm, pick_margin_mm)
    if a_reasons:
        row.col_a = "FAIL: " + "; ".join(a_reasons)
    else:
        row.col_a = "PASS~" if warn or window_note else "PASS"
        if window_note:
            row.col_a += f": {window_note}"
        row.reach_warn = warn
        row.window_warn = window_note is not None
        row.tilde = warn or window_note is not None
    row.add(*a_reasons, *_job_reasons(job, seq_counts))
    if sim_seen is not None and job.accepted and job.seq not in sim_seen:
        row.add("сим не видел")


def _column_b(
    rows: list[Row], picks: list[Row], bound: dict[int, Job], regs: Regs, sim_objects: list[dict] | None
) -> tuple[list[str], bool, int]:
    """Столбец Б по паспортам сима: колонка Б строк и медиана e. Возвращает (строки, run_fail, без паспорта).

    Привязка (ред. 3, прогон 1b): паспорт ставится в пару КО ВСЕМ строкам диска (и взятиям, и пропускам) в порядке
    времени — диску достаётся самый поздний ещё не занятый паспорт с ``p.t <= disk.t`` (время строки диска, не
    задания). Один паспорт — не более одного диска; нет такого паспорта — «нет паспорта». Буква НЕ критерий привязки:
    сеть путает буквы (М→И), а пропущенный диск обязан израсходовать свой паспорт, иначе пары сбиваются. Буква диска
    ≠ буква паспорта — «не судится: буква сети X ≠ паспорт Y» (``~``, не FAIL, в медиану e не входит). Столбец Б
    выводится только у взятий с привязанным заданием; у пропусков пара лишь расходует паспорт.

    Допущение: задержка распознавания (паспорт → строка диска) меньше шага подачи, поэтому строка диска позже
    паспорта своего объекта, но раньше паспорта следующего. В прогоне 1b: шаг ~8,1 с, задержка ~4,3 с. На другом
    стенде (иная скорость ленты, иная нагрузка сети) это проверять.
    """
    if sim_objects is None:
        return [], False, 0
    passports, skipped = parse_passports(sim_objects)
    free = list(passports)
    pick_index = {id(row): k for k, row in enumerate(picks)}
    errors: list[float] = []
    no_passport = 0
    letter_mismatch = 0
    for row in rows:
        disk = row.disk
        if disk is None:
            continue
        match = next((p for p in reversed(free) if p.t <= disk.t), None)
        if match is not None:
            free.remove(match)
        job = bound.get(pick_index[id(row)]) if id(row) in pick_index else None
        if job is None:
            continue  # пропуск или взятие без задания: пара только расходует паспорт
        if match is None:
            row.col_b = "нет паспорта"
            no_passport += 1
            continue
        if match.letter.upper() != disk.letter.upper():
            row.passport = match
            row.col_b = f"не судится: буква сети {disk.letter} ≠ паспорт {match.letter}"
            row.tilde = True
            letter_mismatch += 1
            continue
        row.passport = match
        text, reasons, tilde, err = _judge_passport(job, disk, match, regs)
        row.col_b = text
        row.add(*reasons)
        row.tilde = row.tilde or tilde
        if err is not None:
            errors.append(err)
    lines = [f"Столбец Б: паспортов {len(passports)}" + (f", отброшено записей {skipped}" if skipped else "")]
    if letter_mismatch:
        lines.append(f"Столбец Б: не судится из-за буквы сети ≠ паспорт: {letter_mismatch} (не FAIL, не в медиане)")
    run_fail = False
    if len(errors) >= _RUN_MIN_DISKS:
        median = statistics.median(errors)
        if abs(median) > _RUN_MEDIAN_FAIL_DEG:
            run_fail = True
            lines.append(f"ПРОГОН: FAIL сдвиг нуля или знак (медиана e = {median:+.1f}°)")
        else:
            lines.append(f"Столбец Б: медиана e = {median:+.1f}° по {len(errors)} дискам, в норме")
    else:
        lines.append(
            f"Столбец Б: rz по прогону не судится (судимых дисков {len(errors)}, нужно не меньше {_RUN_MIN_DISKS})"
        )
    return lines, run_fail, no_passport


# ------------------------------------------------------------------------- вывод


def _md_row(cells: list[str] | tuple[str, ...]) -> str:
    return "| " + " | ".join(cells) + " |"


def _p_pick_origin(result: AuditResult) -> str:
    """Откуда ``p_pick_rz_deg``: по пометке сборщика (``p_pick_rz_source``), иначе по наличию ключа в файле."""
    if result.p_pick_source == "robot_param_get_all":
        return "с робота: robot_param_get_all"
    if result.p_pick_source is not None and result.p_pick_source.startswith("default"):
        return "умолчание: не получен"
    if result.p_pick_from_register:
        return "из файла регистров, источник не указан"
    return "умолчание: в файле регистров нет"


def render(result: AuditResult, commands_link: str | None = None) -> str:
    """Отчёт: шапка, таблица Markdown, строки прогона, «Не покрыто независимо», итоговая строка (последняя)."""
    out = ["# Аудит провода CVT_JOB", ""]
    if result.words:
        listed = ", ".join(f"{n}={w}" for n, w in enumerate(result.words, start=1))
        source = "--words" if result.words_given else "журнал диска"
        out.append(f"Слова заливок: {listed} (источник: {source})")
    else:
        out.append("Слова заливок: нет")
    if not result.words_given:
        out.append("слово не независимо: взято из журнала диска, --words не задан")
    origin = _p_pick_origin(result)
    out.append(f"p_pick_rz_deg: {result.p_pick_rz_deg} ({origin})")
    out.append(f"--zone-max-mm: {result.zone_max_mm}")
    out.append(f"--pick-margin-mm: {result.pick_margin_mm}")
    out.extend(result.notes)
    if commands_link:
        out.append(f"Журнал команд роботу (построчно, с расшифровкой): {commands_link}")
    out += ["", _md_row(TABLE_HEADER), _md_row(["---"] * len(TABLE_HEADER))]
    out.extend(_md_row(row.cells()) for row in result.rows)
    out.append("")
    out.extend(result.run_lines)
    if result.run_lines:
        out.append("")
    out.append("Не покрыто независимо:")
    out.extend(f"- {item}" for item in NOT_COVERED)
    out += ["", result.summary]
    return "\n".join(out) + "\n"
