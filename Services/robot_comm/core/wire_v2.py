"""Провод сценария v2: квантование, упаковка записей в слова u16, разбор, нарезка на куски пинг-понга.

Purpose:
    Сторона клиента (программы провода не знают, ``programs/program.py``): ``Scenario`` в мм и ° ->
    слова буфера ``SC_BUF`` по protocol-spec §7.1. Координата округляется шагом ``round_step`` (кратен шагу провода
    ``1 / WIRE_SCALE``), затем умножается на ``WIRE_SCALE``; округление везде — половина от нуля (как
    ``params_v2.to_raw``). После округления зона проверяется заново теми же вызовами, что в ``compile_program``:
    точка у границы может выйти за зону. Чистые функции, без транспорта и состояния.

Public API:
    ``quantize``, ``encode_scenario``, ``decode_record``, ``plan_chunks``. Отказы — ``programs.CompileError``
    (формат ``шаг N: причина``, без входных значений).

Stability: lite
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from Services.robot_comm.core.protocol_v2 import ACT, CONSTANTS, KIND, REASON, REASON_TEXT
from Services.robot_comm.programs import geometry
from Services.robot_comm.programs.program import CompileError, Scenario

__all__ = ["decode_record", "encode_scenario", "plan_chunks", "quantize"]

_KIND_NAME = {code: name for name, code in KIND.items()}
_ACT_NAME = {code: name for name, code in ACT.items()}


def _round_half_away(value: float) -> int:
    """Ближайшее целое, половина — от нуля (как ``params_v2.to_raw``)."""
    magnitude = int(math.floor(abs(value) + 0.5))
    return -magnitude if value < 0 else magnitude


def _fail(step: int, reason: int) -> CompileError:
    """Отказ в формате ``compile_program._fail``: индекс шага и текст причины, без значений."""
    return CompileError(step, reason, f"шаг {step}: {REASON_TEXT[reason]}")


def quantize(v: float, round_step: float) -> float:
    """Ближайшее к ``v`` кратное ``round_step`` (половина — от нуля). Pre: ``round_step > 0``."""
    return _round_half_away(v / round_step) * round_step


def encode_scenario(
    scenario: Scenario, *, params: Mapping[str, float], round_step: float
) -> tuple[tuple[int, ...], ...]:
    """Записи сценария -> слова провода u16, по ``SC_STRIDE`` (6) на запись (protocol-spec §7.1).

    X, Y, Z, RZ = ``round_half_away(quantize(v, round_step) * WIRE_SCALE)`` в ``W_MIN..W_MAX``, затем ``& 0xFFFF``;
    OP = ``KIND[kind] + 256 * ACT[action]``; APARAM как есть.

    Pre: ``params`` — словарь ``compile_program`` (``P_WS_*`` в мм и °); ``round_step`` кратен шагу провода.
    Post: кортеж записей той же длины, что ``scenario.records``.
    Raises: ``CompileError(step_of[i], R_OUT_OF_ZONE | R_DEAD_ZONE, ...)`` — округлённая запись вне зоны
    (точка, вне ``W_MIN..W_MAX``, или отрезок от предыдущей округлённой записи для не-JOINT).
    """
    scale = CONSTANTS["WIRE_SCALE"]
    w_min, w_max = CONSTANTS["W_MIN"], CONSTANTS["W_MAX"]
    ws = geometry.Workspace.from_params(params)
    out: list[tuple[int, ...]] = []
    prev: tuple[float, float] | None = None
    for i, record in enumerate(scenario.records):
        step = scenario.step_of[i]
        ints = [_round_half_away(quantize(v, round_step) * scale) for v in (record.x, record.y, record.z, record.rz)]
        if not all(w_min <= n <= w_max for n in ints):
            raise _fail(step, REASON["R_OUT_OF_ZONE"])
        x, y, z, rz = (n / scale for n in ints)
        reason = geometry.check_point(ws, x, y, z, rz)
        if reason:
            raise _fail(step, reason)
        if prev is not None and record.kind != "JOINT":
            reason = geometry.check_segment(ws, prev[0], prev[1], x, y)
            if reason:
                raise _fail(step, reason)
        prev = (x, y)
        op = KIND[record.kind] + 256 * ACT[record.action]
        out.append((*(n & 0xFFFF for n in ints), op, record.aparam))
    return tuple(out)


def _s16(word: int) -> int:
    word = int(word)
    return word - 0x10000 if word >= 0x8000 else word


def decode_record(words: Sequence[int]) -> tuple[float, float, float, float, str, str, int]:
    """Слова одной записи -> ``(x, y, z, rz, kind, action, aparam)``; ``kind`` / ``action`` — имена.

    Принимает и u16 (дополнительный код), и знаковые слова. Raises: ``ValueError`` — не ``SC_STRIDE`` слов или
    неизвестный код KIND / ACT.
    """
    if len(words) != CONSTANTS["SC_STRIDE"]:
        raise ValueError("запись: число слов не равно SC_STRIDE")
    scale = CONSTANTS["WIRE_SCALE"]
    x, y, z, rz = (_s16(w) / scale for w in words[:4])
    op = int(words[4]) & 0xFFFF
    kind = _KIND_NAME.get(op & 0xFF)
    action = _ACT_NAME.get(op >> 8)
    if kind is None or action is None:
        raise ValueError("запись: неизвестный код KIND или ACT")
    return x, y, z, rz, kind, action, int(words[5]) & 0xFFFF


def plan_chunks(kinds: Sequence[str], half: int, step_of: Sequence[int]) -> tuple[tuple[int, int], ...]:
    """Нарезка на куски пинг-понга ``(start, count)``: жадно, конец куска — последняя не-LINE_PASS запись окна.

    Окно — ``[start, min(start + half, n))``. Окно без EXACT-записи: полное -> ``CompileError(step_of[start + half - 1],
    0, ...)`` (ряд из ``half`` и более LINE_PASS подряд не делится на куски); обрезанное концом сценария (последняя
    запись LINE_PASS) -> ``CompileError(step_of[n - 1], R_LAST_PASS, ...)``, как в ``compile_program``.
    Pre: ``half >= 1``, ``len(step_of) == len(kinds)``. Post: куски подряд, сумма ``count`` = ``n``.
    """
    n = len(kinds)
    chunks: list[tuple[int, int]] = []
    start = 0
    while start < n:
        end = min(start + half, n)
        last = next((j for j in range(end - 1, start - 1, -1) if kinds[j] != "LINE_PASS"), None)
        if last is None:
            if end - start == half:
                step = step_of[start + half - 1]
                raise CompileError(step, 0, f"шаг {step}: ряд LINE_PASS из {half} и более записей не делится на куски")
            raise _fail(step_of[n - 1], REASON["R_LAST_PASS"])
        chunks.append((start, last - start + 1))
        start = last + 1
    return tuple(chunks)
