"""Журнал команд ПК → робот (``wire_commands.md``): всё, что видно в журнале обмена, построчно и с расшифровкой.

Это показ для человека, вердикт аудита он не меняет: итог проверки CVT_JOB берётся из уже вычисленных строк
``AuditResult``. Чистые функции без ввода-вывода. Номера строк — физические строки файлов (открыть исходник и
перейти на строку), не ведущие ``#n`` (это сквозной счётчик журнала).
"""

# ruff: noqa: E501 - строки таблиц и расшифровок длинные по природе
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from scripts.wire_audit import core
from scripts.wire_audit.core import AuditResult, Row

_REG = re.compile(r"^in\s+W\*?\s+(0x[0-9A-Fa-f]+)\s*=\s*(-?\d+)")
_STOP = re.compile(r"^in\s+W\*?\s+STOP_REQ\s*=\s*(-?\d+)")
_BUF = re.compile(r"^in\s+W\*?\s+SC_BUF\[([^\]]*)\]\s*\((\d+) слов\)")
_REPEAT = re.compile(r"^…\s*×(\d+)")
_REPLY_TEXT = re.compile(r"\(([^)]*)\)\s*$")

_STOP_LEVEL = {1: "SOFT (мягкий)", 2: "HARD (жёсткий)", 3: "HALT (аварийный)"}
_OP_RU = {
    "CVT_JOB": "Задание конвейера",
    "SC_RUN": "Запуск сценария",
    "SERVO": "Серво",
    "PARAM_SET": "Запись параметра",
    "PARAM_APPLY": "Применение параметров",
}
_SC_RUN_ARGS = ("count", "sc_id", "offset", "spd_pct", "accel", "accur")
# id параметра робота → имя (Services/robot_comm/tests/param_ids.snapshot, протокол v2); нет id — «id N»
_PARAM_NAMES = {
    0: "P_SPD_DEFAULT",
    1: "P_SPD_JOG",
    2: "P_SPD_L",
    3: "P_ACC_L",
    4: "P_SPD_J",
    5: "P_ACC_J",
    6: "P_OVERLAP",
    7: "P_ACCUR_DEFAULT",
    8: "P_JOG_MAX",
    9: "P_HAND",
    10: "P_JOG_CONT_MAX",
    11: "P_JOG_LEASE_MS",
    12: "P_DEC_STOP",
    16: "P_HOME_X",
    17: "P_HOME_Y",
    18: "P_HOME_Z",
    19: "P_HOME_RZ",
    20: "P_PLACE_X",
    21: "P_PLACE_Y",
    22: "P_PLACE_Z",
    23: "P_PLACE_RZ",
    24: "P_PICK_Z",
    25: "P_PICK_RZ",
    32: "P_GRIP_MS",
    33: "P_ZONE_MIN",
    34: "P_ZONE_MAX",
    35: "P_BELT_FACTOR",
    36: "P_BELT_DIR",
    37: "P_TRIG_X",
    38: "P_TRIG_Y",
    39: "P_ZONE_END_X",
    40: "P_ZONE_END_Y",
    41: "P_NG_RADIUS",
    42: "P_DO_GRIP_CH",
    48: "P_WS_R_MIN",
    49: "P_WS_R_MAX",
    50: "P_WS_Z_MIN",
    51: "P_WS_Z_MAX",
    52: "P_WS_RZ_MIN",
    53: "P_WS_RZ_MAX",
    54: "P_WS_BOX_EN",
    55: "P_WS_X_MIN",
    56: "P_WS_X_MAX",
    57: "P_WS_Y_MIN",
    58: "P_WS_Y_MAX",
    59: "P_WS_ANG_MIN",
    60: "P_WS_ANG_MAX",
    64: "P_VFD_PROFILE",
    65: "P_VFD_SLAVE",
    66: "P_VFD_BAUD",
    67: "P_VFD_FRAME",
    68: "P_VFD_MODE",
    69: "P_VFD_POLL_MS",
    70: "P_VFD_RX_TRIES",
    71: "P_VFD_LINK_FAILS",
    96: "P_WDG_TIMEOUT_MS",
    97: "P_TLM_EVERY",
    98: "P_CONFIG_EPOCH",
}
_STANDARD_SKIPS = ("нет в слове", "заняты", "ниже порога", "слово не задано")
_PREFIX_NOTE = "роботу не передаётся"


@dataclass
class Rec:
    """Запись журнала обмена: команда-блок, STOP_REQ, служебная запись регистра или заметка."""

    kind: str  # cmd | stop | reg | note
    t: datetime
    first: int
    last: int
    lead: int
    seq: int | None = None
    op: str = ""
    op_code: int | None = None
    op_lead: int | None = None  # ведущий #n строки CMD_OPCODE (ключ к Job.line)
    argc: int | None = None
    args: dict[int, int] = field(default_factory=dict)
    value: int | None = None
    addr: str = ""
    text: str = ""
    replies: list[tuple[int, int, int, str, int]] = field(default_factory=list)  # (seq, status, errno, text, line)
    repeats: int = 0
    collapsed: bool = False  # PARAM_SET при подключении: в общей таблице


def fmt(value: float) -> str:
    """Десятичная запятая и настоящий минус: ``-342.5`` → ``−342,5``."""
    return f"{value:.1f}".replace("-", "−").replace(".", ",")


def _clock(t: datetime) -> str:
    return f"{t:%H:%M:%S},{t.microsecond // 1000:03d}"


def _span(rec: Rec) -> str:
    return f"{rec.first}" if rec.first == rec.last else f"{rec.first}–{rec.last}"


def parse_commands(exchange_text: str) -> list[Rec]:
    """Все записи последней инкарнации журнала обмена в порядке файла, с физическими номерами строк."""
    rows: list[tuple[int, int, datetime, int, str]] = []  # (физ. строка, ведущий #, время, внутренний #, текст)
    for phys, raw in enumerate(exchange_text.splitlines(), start=1):
        m = core._EX_LINE.match(raw)
        stamp = core.parse_ts(m.group(2)) if m else None
        if m and stamp:
            rows.append((phys, int(m.group(1)), stamp, int(m.group(3)), m.group(4).strip()))
    start = max((i for i, row in enumerate(rows) if row[3] == 1), default=0)

    recs: list[Rec] = []
    by_inner: dict[int, Rec] = {}
    by_seq: dict[int, Rec] = {}
    cur: Rec | None = None
    for phys, lead, stamp, inner, body in rows[start:]:
        if m := core._EX_SEQ.match(body):
            cur = Rec("cmd", stamp, phys, phys, lead, seq=int(m.group(1)))
            recs.append(cur)
            by_inner[inner] = cur
        elif m := core._EX_OPCODE.match(body):
            if cur is not None:
                cur.op, cur.op_lead, cur.last = m.group(1).strip(), lead, phys
                code = re.search(r"=\s*(\d+)", body)
                cur.op_code = int(code.group(1)) if code else None
        elif m := core._EX_REPLY.match(body):
            seq, status, errno = int(m.group(1)), int(m.group(2)), int(m.group(3))
            text = (_REPLY_TEXT.search(body) or [None, ""])[1]
            target = by_seq.get(seq)
            if target is None:
                recs.append(
                    Rec("note", stamp, phys, phys, lead, text=f"ответ робота RES_SEQ {seq} статус {status} ({text})")
                )
            else:
                if not target.replies:
                    target.last = phys
                target.replies.append((seq, status, errno, text, phys))
        elif cur is not None and (m := core._EX_ARGC.match(body)):
            cur.argc, cur.last = int(m.group(1)), phys
        elif cur is not None and (m := core._EX_ARG.match(body)):
            cur.args[int(m.group(1))], cur.last = int(m.group(2)), phys
        elif cur is not None and core._EX_FLAG.match(body):
            cur.last = phys
            if cur.seq is not None:
                by_seq[cur.seq] = cur
            cur = None
        elif m := _STOP.match(body):
            rec = Rec("stop", stamp, phys, phys, lead, value=int(m.group(1)))
            recs.append(rec)
            by_inner[inner] = rec
        elif m := _REG.match(body):
            rec = Rec("reg", stamp, phys, phys, lead, value=int(m.group(2)), addr=m.group(1))
            recs.append(rec)
            by_inner[inner] = rec
        elif m := _BUF.match(body):
            recs.append(
                Rec("note", stamp, phys, phys, lead, text=f"буфер сценария SC_BUF[{m.group(1)}] ({m.group(2)} слов)")
            )
        elif m := _REPEAT.match(body):
            target = by_inner.get(inner)
            if target is not None:
                target.repeats += int(m.group(1))
                target.last = phys
        elif body.startswith("connect ok"):
            recs.append(Rec("note", stamp, phys, phys, lead, text="соединение с роботом установлено (connect ok)"))
        elif body.startswith("disconnect"):
            recs.append(Rec("note", stamp, phys, phys, lead, text="соединение с роботом закрыто (disconnect)"))
    _collapse_connect_params(recs)
    return recs


def _collapse_connect_params(recs: list[Rec]) -> None:
    """PARAM_SET до первой другой команды — «параметры при подключении» (одна таблица)."""
    for rec in recs:
        if rec.kind in ("stop",) or (rec.kind == "cmd" and rec.op != "PARAM_SET"):
            return
        if rec.kind == "cmd":
            rec.collapsed = True


# ------------------------------------------------------------------------- слова и расчёт ожидаемого слова


def signed_word(word: int) -> int:
    """Слово ≥ 32768 — отрицательное: ``слово − 65536``."""
    unsigned = word % 65536
    return unsigned - 65536 if unsigned >= 32768 else unsigned


def _calc(value: float) -> str:
    """Расчёт слова из значения: ``−342,5×10=−3425 → +65536``."""
    n = core.round_half_away(value * core.WIRE_SCALE)
    text = f"{fmt(value)}×10={n}".replace("-", "−")
    return f"{text} → +65536" if n < 0 else f"{text} → &0xFFFF"


def _verdict_of(wire: int | None, expected: int) -> str:
    """✓ точно, ≈ ±1 слово (допуск аудита), ✗ иначе."""
    if wire is None:
        return "✗ (слова нет)"
    diff = (wire - expected + 32768) % 65536 - 32768
    if diff == 0:
        return "✓"
    return "≈" if abs(diff) == 1 else "✗"


_TOL_LAYOUT = "≈ (допуск ±1 из-за округления журнала)"
_TOL_REGISTER = "≈ (допуск аудита ±1 слово)"


def _word_row(index: int, name: str, source: str, calc: str, expected: int, wire: int | None, note: str) -> str:
    verdict = _verdict_of(wire, expected)
    shown = note if verdict == "≈" else verdict
    wire_text = "—" if wire is None else str(wire)
    return f"| ARGS[{index}] | {name} | {source} | {calc} | {expected} | {wire_text} | {shown} |"


def _calc_rows(job_args: dict[int, int], row: Row, regs: core.Regs, word: str) -> list[str]:
    disk = row.disk
    assert disk is not None and disk.cell is not None
    cell = disk.cell
    place_x, place_y = core.expected_place_xy(regs, cell)
    lines = [
        "| слово | имя | исходное значение и откуда | расчёт | ожидается | на проводе | итог |",
        "|---|---|---|---|---|---|---|",
        "| ARGS[0], ARGS[1] | ecap | энкодер ленты | не считается: нет независимого источника | — | "
        f"{job_args.get(0, '—')}, {job_args.get(1, '—')} | — |",
    ]
    if disk.px is not None:
        lines.append(
            _word_row(
                2,
                "pick x",
                f"{fmt(disk.px)} мм (layout «взять»)",
                _calc(disk.px),
                core.encode_word(disk.px),
                job_args.get(2),
                _TOL_LAYOUT,
            )
        )
    if disk.py is not None:
        lines.append(
            _word_row(
                3,
                "pick y",
                f"{fmt(disk.py)} мм (layout «взять»)",
                _calc(disk.py),
                core.encode_word(disk.py),
                job_args.get(3),
                _TOL_LAYOUT,
            )
        )
    lines.append(
        _word_row(
            4,
            "pick z",
            f"{fmt(regs.pick_z_mm)} мм (registers.json pick_z_mm)",
            _calc(regs.pick_z_mm),
            core.encode_word(regs.pick_z_mm),
            job_args.get(4),
            _TOL_REGISTER,
        )
    )
    lines.append(
        f"| ARGS[5] | flags | правило драйвера: бит0 = pick z задан, бит1 = укладка задана | 1 + 2 = 3 | 3 | {job_args.get(5, '—')} | "
        f"{'✓' if job_args.get(5) == 3 else '✗'} |"
    )
    pitch = core.expected_pitch(regs)
    lines.append(
        _word_row(
            6,
            "place x",
            f"{fmt(place_x)} мм (first_x {fmt(regs.first_x)} + {cell}×шаг {fmt(pitch)} по {fmt(regs.line_angle_deg)}°)",
            _calc(place_x),
            core.encode_word(place_x),
            job_args.get(6),
            _TOL_REGISTER,
        )
    )
    lines.append(
        _word_row(
            7,
            "place y",
            f"{fmt(place_y)} мм (first_y {fmt(regs.first_y)} + {cell}×шаг {fmt(pitch)} по {fmt(regs.line_angle_deg)}°; ячейка {cell} слова {word})",
            _calc(place_y),
            core.encode_word(place_y),
            job_args.get(7),
            _TOL_REGISTER,
        )
    )
    lines.append(
        _word_row(
            8,
            "place z",
            f"{fmt(regs.place_z_mm)} мм (registers.json place_z_mm)",
            _calc(regs.place_z_mm),
            core.encode_word(regs.place_z_mm),
            job_args.get(8),
            _TOL_REGISTER,
        )
    )
    options = core.expected_rz_options(regs, disk.net)
    wire_rz = job_args.get(9)
    best = min(options, key=lambda v: abs(_diff(wire_rz, core.encode_word(v)))) if wire_rz is not None else options[0]
    corr = core.expected_corr(regs, disk.net)
    origin = (
        "с робота: robot_param_get_all"
        if regs.p_pick_source == "robot_param_get_all"
        else "умолчание"
        if (regs.p_pick_source or "").startswith("default") or not regs.p_pick_from_register
        else "файл регистров"
    )
    lines.append(
        _word_row(
            9,
            "rz",
            f"{fmt(best)}° = P_PICK_RZ {fmt(regs.p_pick_rz_deg)} ({origin}) + доворот {fmt(corr)}°",
            _calc(best),
            core.encode_word(best),
            wire_rz,
            _TOL_LAYOUT,
        )
    )
    return lines


def _diff(wire: int | None, expected: int) -> int:
    return 0 if wire is None else abs((wire - expected + 32768) % 65536 - 32768)


# ------------------------------------------------------------------------- блоки команд


def _reply_line(rec: Rec) -> str:
    if not rec.replies:
        return "Ответ:    нет ✗"
    seq, status, _errno, text, line = rec.replies[0]
    mark = "✓" if seq == rec.seq else "✗"
    late = (
        f"; поздний ответ ещё {len(rec.replies) - 1} раз (строки {', '.join(str(r[4]) for r in rec.replies[1:])})"
        if len(rec.replies) > 1
        else ""
    )
    return f"Ответ:    RES_SEQ {seq} = CMD_SEQ {mark}   статус {status} ({text}){late}"


def _words_text(rec: Rec) -> str:
    return ", ".join(f"ARGS[{i}]={rec.args[i]}" for i in sorted(rec.args)) or "слов нет"


def _decode_lines(rec: Rec) -> list[str]:
    a = rec.args
    if rec.op == "CVT_JOB":
        d = core.decode_cvt(a)
        pick = (d["pick_x"], d["pick_y"], d["pick_z"])
        place = (d["place_x"], d["place_y"], d["place_z"])
        show = lambda vs: " ".join(f"{n} {'—' if v is None else fmt(v)}" for n, v in zip("xyz", vs))  # noqa: E731
        return [
            f"Взять:    {show(pick)} мм",
            f"Положить: {show(place)} мм   поворот {'—' if d['place_rz'] is None else fmt(d['place_rz'])}°",
            f"Флаги {d['flags']} (бит0 = pick z задан, бит1 = укладка задана), ecap {d['ecap']} (энкодер ленты, не мм)",
        ]
    if rec.op == "SC_RUN":
        return ["Сценарий: " + ", ".join(f"{n} {a.get(i, '—')}" for i, n in enumerate(_SC_RUN_ARGS))]
    if rec.op == "SERVO":
        on = a.get(0)
        return [f"Серво: on {on} ({'ВКЛ' if on else 'ВЫКЛ'})"]
    if rec.op == "PARAM_SET":
        pid = a.get(0)
        return [f"Параметр {_param_name(pid)} = {a.get(1, '—')} (сырое слово)"]
    return [f"расшифровки нет (опкод {rec.op or rec.op_code}); сырые слова: {_words_text(rec)}"]


def _param_name(pid: int | None) -> str:
    return _PARAM_NAMES.get(pid, f"id {pid}") if pid is not None else "id ?"


def _check_text(row: Row | None, rec: Rec) -> str:
    if rec.op != "CVT_JOB":
        return "ПРОВЕРКА: не проверяется аудитом координат (аудит судит только CVT_JOB)"
    if row is None:
        status = rec.replies[0][1] if rec.replies else None
        why = (
            "отказ робота (повтор после E_BUSY не судится)"
            if status not in (None, 1)
            else "нет строки аудита (см. «лишнее» в audit.md)"
        )
        return f"ПРОВЕРКА: — {why}"
    parts = [row.result]
    parts.append(f"колонка А: {row.col_a}")
    if row.col_b != "-":
        parts.append(f"колонка Б: {row.col_b}")
    return "ПРОВЕРКА: " + "; ".join(parts)


def _layout_index(layout_text: str) -> dict[tuple[datetime, str, float], int]:
    """Физическая строка layout/messages.log по ключу (время, буква, сеть°) последней инкарнации."""
    found: list[tuple[int, datetime, str]] = []
    start = 0
    for phys, raw in enumerate(layout_text.splitlines(), start=1):
        m = core._LAY_LINE.match(raw)
        stamp = core.parse_ts(m.group(2)) if m else None
        if not (m and stamp):
            continue
        if core._LAY_INIT in m.group(3):
            start = len(found)
        found.append((phys, stamp, m.group(3)))
    index: dict[tuple[datetime, str, float], int] = {}
    for phys, stamp, message in found[start:]:
        _, sep, body = message.partition(core._LAY_PLUGIN)
        if not sep:
            continue
        m = core._LAY_PICK.match(body) or core._LAY_SKIP.match(body)
        if m:
            index[(stamp, m.group(1), float(m.group(2)))] = phys
    return index


def _origin_lines(
    row: Row, regs: core.Regs, result: AuditResult, layout_line: int | None, sim_seen: set[int] | None, seq: int | None
) -> list[str]:
    disk = row.disk
    if disk is None:
        return ["диска-источника нет (лишнее задание)"]
    fill = int(row.fill) if row.fill.isdigit() else 0
    word = result.words[fill - 1] if 1 <= fill <= len(result.words) else "—"
    place_y = core.expected_place_xy(regs, disk.cell)[1] if disk.cell is not None else None
    ref = f"      layout/messages.log:{layout_line}" if layout_line else ""
    corr = core.expected_corr(regs, disk.net)
    op = "+" if regs.angle_invert else "−"
    out = [
        f"  диск «{disk.letter}», сеть {fmt(disk.net)}° → ячейка {disk.cell} слова {word} → y {'—' if place_y is None else fmt(place_y)} мм{ref}",
        f"  доворот = angle_zero {fmt(regs.angle_zero_deg)} {op} {fmt(disk.net)} (wrap к ±180°) = {fmt(corr)}°; поворот = P_PICK_RZ {fmt(regs.p_pick_rz_deg)} + доворот {fmt(corr)} = {fmt(regs.p_pick_rz_deg + corr)}°",
    ]
    extra = []
    if row.passport is not None:
        p = row.passport
        angle = "—" if p.angle_deg is None else fmt(p.angle_deg)
        lateral = "—" if p.lateral_px is None else fmt(p.lateral_px)
        extra.append(f"метка сима: {p.object_id or 'объект'} «{p.letter}» угол {angle}°, lateral {lateral} px")
    if sim_seen is not None and seq is not None:
        extra.append(f"сим принял seq {'✓' if seq in sim_seen else '✗'}")
    if extra:
        out.append("  " + "; ".join(extra))
    return out


def _stop_lines(rec: Rec) -> list[str]:
    n = rec.value or 0
    level = _STOP_LEVEL.get(n % 4, f"уровень {n % 4}")
    return [f"Запись STOP_REQ = {n}: номер стопа {n // 4}, уровень {level} (n = номер×4 + уровень)"]


# ------------------------------------------------------------------------- план слова


def _plan_cell(regs: core.Regs, cell: int) -> tuple[float, float, float]:
    """Куда класть ячейку ``cell``: x, y из регистров (``first + cell·шаг`` вдоль линии), z = ``place_z_mm``."""
    x, y = core.expected_place_xy(regs, cell)
    return x, y, regs.place_z_mm


def _plan_zero_rz(regs: core.Regs) -> float:
    """Поворот диска, пришедшего ровно (сеть 0°): ``P_PICK_RZ + wrap180(angle_zero − знак·0)``."""
    return regs.p_pick_rz_deg + core.expected_corr(regs, 0.0)


def _rz_origin(regs: core.Regs) -> str:
    if regs.p_pick_source == "robot_param_get_all":
        return "с робота: robot_param_get_all"
    if (regs.p_pick_source or "").startswith("default") or not regs.p_pick_from_register:
        return "умолчание"
    return "файл регистров"


def plan_section(words: list[str], regs: core.Regs) -> list[str]:
    """«ПЛАН СЛОВА» по каждому слову заливок: только слово и регистры, журнал команд не читается.

    Правило (``Plugins/processing/word_layout``, ``geometry.pitch_positions``): ячейка = индекс буквы в слове, позиция
    ``first + индекс·шаг`` вдоль линии, слово любой длины с одним шагом (без центровки); шаг ``pitch_mm`` или два радиуса
    диска. Слово повторилось — ссылка на первую заливку с таким словом.
    """
    out = ["## ПЛАН СЛОВА (из слова и registers.json, без журнала команд)", ""]
    seen: dict[str, int] = {}
    zero_rz = _plan_zero_rz(regs)
    for fill, word in enumerate(words, start=1):
        if word in seen:
            out += [f"ПЛАН СЛОВА «{word}» (заливка {fill}): как в заливке {seen[word]}", ""]
            continue
        seen[word] = fill
        out += [
            f"ПЛАН СЛОВА «{word}» (заливка {fill}): ячейка → буква → куда класть",
            "",
            "| ячейка | буква | x, мм | y, мм | z, мм | слова ARGS[6,7,8] | поворот, если диск пришёл ровно (сеть 0°) |",
            "|---|---|---|---|---|---|---|",
        ]
        for cell, letter in enumerate(word):
            x, y, z = _plan_cell(regs, cell)
            wire = f"{core.encode_word(x)} · {core.encode_word(y)} · {core.encode_word(z)}"
            out.append(
                f"| {cell} | {letter} | {fmt(x)} | {fmt(y)} | {fmt(z)} | {wire} | {fmt(zero_rz)}° → {core.encode_word(zero_rz)} |"
            )
        out.append("")
        repeated = [
            f"{letter}: ячейки {', '.join(str(i) for i, c in enumerate(word) if c == letter)}"
            for letter in dict.fromkeys(word)
            if word.count(letter) > 1
        ]
        if repeated:
            out.append(f"Буква встречается несколько раз ({'; '.join(repeated)}) — диск берёт первую свободную из них.")
            out.append("")
    out += [
        f"Поворот диска = P_PICK_RZ ({fmt(regs.p_pick_rz_deg)}°, {_rz_origin(regs)}) + доворот; доворот = wrap180(angle_zero − знак·угол сети), "
        f"поэтому для угла сети 0° поворот = {fmt(zero_rz)}°, для другого угла — {fmt(zero_rz)}° + (−угол сети) без сворачивания.",
        "",
    ]
    return out


def _plan_fact_line(rec: Rec, row: Row, regs: core.Regs, words: list[str]) -> str | None:
    """Строка «ПО ПЛАНУ … ФАКТ на проводе … → ✓/✗» для блока CVT_JOB; ``None`` — диска или ячейки нет."""
    disk = row.disk
    if disk is None or disk.cell is None:
        return None
    fill = int(row.fill) if row.fill.isdigit() else 0
    word = words[fill - 1] if 1 <= fill <= len(words) else ""
    letter = word[disk.cell] if 0 <= disk.cell < len(word) else "?"
    x, y, z = _plan_cell(regs, disk.cell)
    fact = core.decode_cvt(rec.args)
    verdicts = [_verdict_of(rec.args.get(i), core.encode_word(v)) for i, v in ((6, x), (7, y), (8, z))]
    mark = "✓" if all(v == "✓" for v in verdicts) else "≈" if all(v in ("✓", "≈") for v in verdicts) else "✗"
    shown = " ".join(
        f"{n} {'—' if fact[k] is None else fmt(fact[k])}"
        for n, k in (("x", "place_x"), ("y", "place_y"), ("z", "place_z"))
    )
    letter_note = (
        "" if letter == disk.letter else f" (в плане в ячейке {disk.cell} буква «{letter}», а диск «{disk.letter}» ✗)"
    )
    return (
        f"ПО ПЛАНУ: ячейка {disk.cell}, буква {disk.letter} → положить x {fmt(x)}, y {fmt(y)}, z {fmt(z)} (из плана слова); "
        f"ФАКТ на проводе: {shown.replace(' y', ', y').replace(' z', ', z')} → {mark}{letter_note}"
    )


def _skip_plan_text(row: Row, regs: core.Regs, words: list[str]) -> str:
    """Для диска без команды: куда по плану положили бы эту букву."""
    disk = row.disk
    assert disk is not None
    fill = int(row.fill) if row.fill.isdigit() else 0
    word = words[fill - 1] if 1 <= fill <= len(words) else ""
    cells = [i for i, c in enumerate(word) if c == disk.letter]
    if not word:
        return "слова ещё нет — плана нет"
    if not cells:
        return f"буквы «{disk.letter}» нет в слове «{word}» — ячейки по плану нет"
    return "по плану ячейки этой буквы: " + "; ".join(
        f"ячейка {i} (x {fmt(_plan_cell(regs, i)[0])}, y {fmt(_plan_cell(regs, i)[1])}, z {fmt(_plan_cell(regs, i)[2])})"
        for i in cells
    )


# ------------------------------------------------------------------------- сборка файла

_HOW_TO_READ = """## Как читать

- Слова на проводе — 16-битные числа без знака. Слово больше 32767 — отрицательное: **слово − 65536**, потом **÷ 10**.
  Квант 0,1 мм (и 0,1°): значение × 10, округление от нуля, затем `& 0xFFFF`.
- Номера строк `robot_exchange.log:N` и `layout/messages.log:N` — физические строки файла: откройте файл и перейдите на строку.
- «ЧТО ПОЛУЧАЕТ РОБОТ» — только то, что есть на проводе. «ОТКУДА ВЗЯЛ ПК» — контекст проверки, роботу не передаётся
  (буква диска и сеть° на провод не идут).
- Допуск ±1 слово: значения из журнала layout даны с одним знаком после запятой, поэтому слово может отличаться
  на единицу от пересчёта («≈»). ✗ — расхождение больше допуска (то же, что решает аудит; здесь только показ).

Пример (CMD_SEQ 57111, живой прогон): слова `15912, 0, 4606, 62111, 64216, 3, 3200, 4400, 64216, 64764` →
pick x = 4606 → **460,6**; pick y = 62111 − 65536 = −3425 → **−342,5**; pick z = 64216 − 65536 = −1320 → **−132,0**;
флаги 3; place x = 3200 → **320,0**; place y = 4400 → **440,0**; place z = −132,0; rz = 64764 − 65536 = −772 → **−77,2°**.
"""


def _rz_note(recs: list[Rec]) -> str:
    over, total = [], 0
    for rec in recs:
        if rec.kind == "cmd" and rec.op == "CVT_JOB" and 9 in rec.args:
            total += 1
            rz = signed_word(rec.args[9]) / core.WIRE_SCALE
            if abs(rz) > 180.0:
                over.append(rz)
    if not over:
        return f"Поворот rz: ни у одного из {total} заданий |rz| не превышает 180°."
    example = max(over, key=abs)
    folded = core.wrap180(example)
    return (
        f"Поворот rz: у {len(over)} из {total} заданий |rz| > 180° (например {fmt(example)}°); на провод идёт как есть, "
        f"не свёрнут к {'+' if folded > 0 else ''}{fmt(folded)}°. Допустимый диапазон оси RZ на роботе подтвердить на железе."
    )


def _summary_table(result: AuditResult, recs: list[Rec], layout_idx: dict) -> list[str]:
    seq_of_line = {r.op_lead: r for r in recs if r.kind == "cmd" and r.op == "CVT_JOB"}
    lines = [
        "| диск | время | буква (на ПК, роботу не передаётся) | сеть° | ячейка | CMD_SEQ | pick x, y | place x, y | rz° | проверка |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for n, row in enumerate(result.rows, start=1):
        disk, job = row.disk, row.job
        rec = seq_of_line.get(job.line) if job is not None else None
        when = _clock(disk.t) if disk else (_clock(job.t) if job else "—")
        if rec is not None:
            d = core.decode_cvt(rec.args)
            coords = [
                f"{fmt(d['pick_x'])}, {fmt(d['pick_y'])}"
                if d["pick_x"] is not None and d["pick_y"] is not None
                else "—",
                f"{fmt(d['place_x'])}, {fmt(d['place_y'])}"
                if d["place_x"] is not None and d["place_y"] is not None
                else "—",
                fmt(d["place_rz"]) if d["place_rz"] is not None else "—",
            ]
            seq, check = str(rec.seq), row.result
        else:
            coords, seq = ["—", "—", "—"], "—"
            check = "команды нет" + (f" ({disk.skip_reason})" if disk and disk.skip_reason else f" — {row.result}")
        letter, net, cell = (
            (disk.letter, fmt(disk.net), str(disk.cell) if disk.cell is not None else "—") if disk else ("—", "—", "—")
        )
        lines.append(
            f"| {n} | {when} | {letter} | {net} | {cell} | {seq} | {coords[0]} | {coords[1]} | {coords[2]} | {check} |"
        )
    return lines


def render_commands(
    exchange_text: str,
    layout_text: str,
    registers: dict,
    result: AuditResult,
    sim_journal: list[dict] | None = None,
) -> str:
    """Текст ``wire_commands.md``; ``result`` — уже вычисленный ``core.audit`` на тех же входах."""
    regs = core.load_registers(registers)
    recs = parse_commands(exchange_text)
    layout_idx = _layout_index(layout_text)
    sim_seen = core.parse_sim_seqs(sim_journal) if sim_journal is not None else None
    row_of_job = {row.job.line: row for row in result.rows if row.job is not None}

    out = ["# Журнал команд ПК → робот", "", _HOW_TO_READ]
    out += plan_section(result.words, regs)
    out += [_rz_note(recs), ""]
    out += ["## Сводка: диск → команда → координаты → проверка", ""]
    out += _summary_table(result, recs, layout_idx) + [""]

    params = [r for r in recs if r.collapsed]
    if params:
        out += [
            "## Параметры при подключении",
            "",
            "| id | имя | значение (сырое слово) | ответ | строки |",
            "|---|---|---|---|---|",
        ]
        for r in params:
            reply = f"{r.replies[0][1]} ({r.replies[0][3]})" if r.replies else "нет"
            out.append(
                f"| {r.args.get(0, '—')} | {_param_name(r.args.get(0))} | {r.args.get(1, '—')} | {reply} | robot_exchange.log:{_span(r)} |"
            )
        out.append("")

    out += ["## Команды по времени", ""]
    n = 0
    for rec in recs:
        if rec.collapsed:
            continue
        if rec.kind == "reg":
            rep = f", повтор записи {rec.repeats} раз" if rec.repeats else ""
            out.append(
                f"· {_clock(rec.t)} служебная запись регистра {rec.addr} = {rec.value}{rep} (не команда роботу)   robot_exchange.log:{_span(rec)}"
            )
            out.append("")
            continue
        if rec.kind == "note":
            out.append(f"· {_clock(rec.t)} {rec.text}   robot_exchange.log:{_span(rec)}")
            out.append("")
            continue
        n += 1
        if rec.kind == "stop":
            out += [
                f"№{n} · {_clock(rec.t)} · Запрос остановки (STOP_REQ)" + f"      robot_exchange.log:{_span(rec)}",
                "",
                "ЧТО ПОЛУЧАЕТ РОБОТ  (только то, что есть на проводе)",
            ]
            out += ["  " + line for line in _stop_lines(rec)]
            if rec.repeats:
                out.append(f"  повтор записи {rec.repeats} раз")
            out += ["ПРОВЕРКА: не проверяется аудитом координат", ""]
            continue
        name = _OP_RU.get(rec.op, rec.op or "команда")
        out += [
            f"№{n} · {_clock(rec.t)} · CMD_SEQ {rec.seq} · {name} ({rec.op})      robot_exchange.log:{_span(rec)}",
            "",
        ]
        out.append("ЧТО ПОЛУЧАЕТ РОБОТ  (только то, что есть на проводе)")
        out.append(f"  слова: {_words_text(rec)}")
        out += ["  " + line for line in _decode_lines(rec)]
        out.append("  " + _reply_line(rec))
        if rec.repeats:
            out.append(f"  повтор записи {rec.repeats} раз")
        row = row_of_job.get(rec.op_lead) if rec.op == "CVT_JOB" else None
        if rec.op == "CVT_JOB" and row is not None and row.disk is not None:
            disk = row.disk
            layout_line = layout_idx.get((disk.t, disk.letter, round(disk.net, 1)))
            out += ["", "ОТКУДА ВЗЯЛ ПК  (роботу НЕ передаётся — контекст для проверки)"]
            out += _origin_lines(row, regs, result, layout_line, sim_seen, rec.seq)
            fill = int(row.fill) if row.fill.isdigit() else 0
            word = result.words[fill - 1] if 1 <= fill <= len(result.words) else "—"
            plan_line = _plan_fact_line(rec, row, regs, result.words)
            if plan_line:
                out += ["", plan_line]
            out += ["", "РАСЧЁТ СЛОВ  (исходные координаты → ожидаемое слово → что на проводе)"]
            out += _calc_rows(rec.args, row, regs, word)
        out += ["", _check_text(row, rec), ""]

    out += ["## Диски без команды", ""]
    skipped = [r for r in result.rows if r.disk is not None and r.job is None]
    if not skipped:
        out.append("нет")
    for row in skipped:
        disk = row.disk
        assert disk is not None
        reason = disk.skip_reason
        layout_line = layout_idx.get((disk.t, disk.letter, round(disk.net, 1)))
        ref = f"layout/messages.log:{layout_line}" if layout_line else "layout/messages.log"
        if reason is None:
            verdict = f"⚠ проверить: взятие в ячейку {disk.cell} без команды роботу ({row.result})"
            reason = f"ячейка {disk.cell}"
        elif any(s in reason for s in _STANDARD_SKIPS):
            verdict = "команды роботу нет — штатно"
        else:
            verdict = "⚠ проверить: причина пропуска не из списка штатных"
        out.append(
            f"- {_clock(disk.t)} · диск «{disk.letter}» ({_PREFIX_NOTE}), сеть {fmt(disk.net)}° · "
            f"{_skip_plan_text(row, regs, result.words)}; почему не выдан: {reason} · {verdict} · {ref}"
        )
    out.append("")
    return "\n".join(out)
