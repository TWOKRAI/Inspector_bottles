# -*- coding: utf-8 -*-
"""Слепая приёмка T2.4 (RED до кода): «буква ровная» — поворот диска при укладке на v2-хосте.

``place_rz`` берётся из продукта: ``WordAssembler.offer(label, angle_deg, angle_valid, *, zero_deg,
sign)`` отдаёт ``job["angle_deg"]`` — ОТНОСИТЕЛЬНЫЙ доворот. Абсолютный RZ укладки (сл. провода,
0.1 град) = ``P_PICK_RZ`` (читается клиентом, ``param_get``) + доворот. Правило «RZ робота до задания +
доворот» НЕ используется: после ``CVT_JOB`` инструмент остаётся в позе укладки, и на втором диске
подряд ``TLM_RZ`` != ``P_PICK_RZ``.

Три диска подряд, без ``HOME`` между ними, углы-литералы 30, -45, 0 град (не все нулевые).
Итоговый угол буквы = угол диска + ``TOOL_SIGN`` * (RZ укладки по ``TLM_RZ`` - ``P_PICK_RZ``) по
модулю 360; допуск 1 град. Ожидаемый итог — 0 град («ровная»), литерал.
"""

from __future__ import annotations

import pytest

from Plugins.processing.word_layout.assembler import WordAssembler
from Plugins.sim.robot_host.tests.host_harness import (
    close_client,
    free_port,
    make_host,
    open_client,
    read_reg,
    run_with_deadline,
    to_s16,
    wait_done_hb,
)
from Services.robot_comm import ROBOT_AVAILABLE

pytestmark = [
    pytest.mark.skipif(not ROBOT_AVAILABLE, reason="pymodbus не установлен"),
]

# ⚑ GATE-1: знак связи «поворот RZ робота -> поворот буквы на диске». +1 = RZ против часовой
# даёт поворот буквы против часовой. Подтверждается на железе; если в продукте знак обратный,
# тест ПАДАЕТ (а не подгоняется).
TOOL_SIGN = +1

_DISC_ANGLES_DEG = [30.0, -45.0, 0.0]
_TOLERANCE_DEG = 1.0
# pick/place — литералы ядра, принимаемые при P_HAND = 1 (Services/robot_comm/tests/test_sim_v2_cvt_wdg_vfd.py).
_PICK_MM = (300.0, -200.0)
_PLACE_MM = (400.0, 100.0)


def _wrap180(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


def test_letter_is_straight_after_placement() -> None:
    """После каждой из трёх укладок угол буквы (диск + ``TOOL_SIGN`` * (RZ укладки - ``P_PICK_RZ``))
    равен 0 град с допуском 1 град.

    НЕ доказывает: что ``TOOL_SIGN = +1`` верен на железе (⚑ GATE-1: тест лишь падает при другом знаке
    в продукте); что единица ``TLM_RZ`` — 0.1 град (принято по ``P_PICK_RZ``: scale 10); поведение при
    ``angle_valid=False``; что ``TLM_RZ`` после ``DONE`` — поза именно укладки (принято по DESIGN)."""
    port = free_port()
    plugin, ctx, _services, workers = make_host(port, protocol="v2")
    device = None
    try:
        run_with_deadline(lambda: plugin.start(ctx), timeout=10.0, label="start")
        device, client = open_client(port)
        assert read_reg(device, "TLM_PROTO_VER")[0] == 0x0200, "хост не v2"

        p_pick_rz_deg = run_with_deadline(lambda: client.param_get("P_PICK_RZ"), timeout=5.0, label="param_get") / 10.0
        run_with_deadline(lambda: client.servo(True), timeout=5.0, label="servo")

        assembler = WordAssembler.from_word("AAA", (0.0, 0.0), (100.0, 0.0))
        failures: list[str] = []
        for number, disc_deg in enumerate(_DISC_ANGLES_DEG, start=1):
            job = assembler.offer("A", disc_deg, True, zero_deg=0.0, sign=1.0)
            assert job is not None, f"диск {number}: матчер отказал (слотов 3, дисков 3)"
            place_rz_deg = p_pick_rz_deg + job["angle_deg"]

            run_with_deadline(client.kick_heartbeat, timeout=5.0, label="hb")
            res = run_with_deadline(
                lambda: client.cvt_job(
                    0,
                    _PICK_MM[0],
                    _PICK_MM[1],
                    0.0,
                    2,  # flags бит1: укладка из place_* (иначе P_PLACE_*, place_rz игнорируется); правка лида
                    _PLACE_MM[0],
                    _PLACE_MM[1],
                    0.0,
                    place_rz_deg,
                ),
                timeout=5.0,
                label="cvt_job",
            )
            wait_done_hb(client, res.seq)

            rz_deg = to_s16(read_reg(device, "TLM_RZ")[0]) / 10.0
            letter_deg = _wrap180(disc_deg + TOOL_SIGN * (rz_deg - p_pick_rz_deg))
            if abs(letter_deg) > _TOLERANCE_DEG:
                failures.append(
                    f"диск {number} ({disc_deg} град): доворот {job['angle_deg']}, "
                    f"TLM_RZ {rz_deg}, P_PICK_RZ {p_pick_rz_deg} -> буква {letter_deg:.2f} град"
                )
        assert not failures, "буква не ровная:\n" + "\n".join(failures)
    finally:
        if device is not None:
            close_client(device)
        try:
            run_with_deadline(lambda: plugin.shutdown(ctx), timeout=10.0, label="shutdown")
        finally:
            workers.stop_all()
