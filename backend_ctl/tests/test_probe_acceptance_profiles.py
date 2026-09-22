# -*- coding: utf-8 -*-
"""Hazard-тесты автора (Task 1.4 плана line-sim): профили приложений зонда
`probe_observability_consumer_acceptance` — офлайн, стенд не поднимается.

Что может сломаться в ЭТОМ механизме:
* прототипный профиль разойдётся с прежними константами → прогон без аргументов
  перестанет воспроизводить baseline (51 строка, те же вердикты);
* в теле семей останется захардкоженное имя процесса прототипа → на симе строка
  молча бьёт в несуществующий процесс вместо своей роли;
* роль без процесса проглотится молча вместо `N/A` с причиной;
* argparse уедет на уровень модуля → spawn-дети (переимпорт как __mp_main__)
  начнут разбирать чужой argv.
"""

from __future__ import annotations

import importlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE = "backend_ctl.probes.probe_observability_consumer_acceptance"
SOURCE = PROJECT_ROOT / "backend_ctl" / "probes" / "probe_observability_consumer_acceptance.py"


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    """Импорт зонда с изолированным каталогом логов; env процесса pytest восстанавливается."""
    saved = dict(os.environ)
    os.environ["MULTIPROCESS_LOG_DIR"] = str(tmp_path_factory.mktemp("probe_logs"))
    try:
        mod = importlib.import_module(MODULE)
        yield mod
    finally:
        os.environ.clear()
        os.environ.update(saved)


def test_prototype_profile_equals_old_constants(probe):
    p = probe.profile_for("prototype")
    assert p.port == 8765
    assert set(p.expected_procs) == {
        "ProcessManager",
        "camera_0",
        "gui",
        "inspector",
        "processor",
        "renderer",
        "storage",
    }
    assert p.roles == {
        "camera": "camera_0",
        "neighbor": "processor",
        "fault": "renderer",
        "ring": "inspector",
        "inspector": "inspector",
    }
    assert p.frame_path == ("camera_0", "processor", "inspector")
    # Строки T1 у прототипа нет: иначе число строк без аргументов станет 52.
    assert p.level_writers == ()
    # Глобалы на импорте = прототип (дети spawn получают их без main()).
    assert (probe.PORT, probe.CAM, probe.NB, probe.FLT, probe.RING, probe.INSP) == (
        8765,
        "camera_0",
        "processor",
        "renderer",
        "inspector",
        "inspector",
    )


def test_prototype_roles_cover_every_process_the_old_code_named(probe):
    """Каждое имя процесса, которое прежний код называл в семьях, достижимо через роль или состав."""
    p = probe.profile_for("prototype")
    old_named = {"camera_0", "processor", "renderer", "inspector"}
    assert old_named <= set(p.roles.values())
    assert set(p.roles.values()) <= set(p.expected_procs)


def test_line_sim_profile_literals(probe):
    p = probe.profile_for("line_sim")
    assert p.port == 8766
    # Литерал, не производная от pipeline.yaml: сверка чтения yaml с реальностью.
    assert set(p.expected_procs) == {"ProcessManager", "robot", "camera", "mjpeg"}
    assert p.roles["inspector"] is None
    assert p.na_reason.get("inspector")
    live_roles = {k: v for k, v in p.roles.items() if v is not None}
    assert set(live_roles.values()) <= set(p.expected_procs)
    assert set(p.frame_path) <= set(p.expected_procs)


def test_unknown_app_rejected(probe):
    with pytest.raises(ValueError):
        probe.profile_for("nope")


def test_no_prototype_process_literal_left_in_family_bodies():
    """Имя процесса прототипа как голый литерал в семьях — утечка мимо роли."""
    src = SOURCE.read_text(encoding="utf-8")
    body = src[src.index("def log(msg: str)") : src.index("def parse_args(")]
    # `na(..., "inspector")` — ключ РОЛИ, не имя процесса; такие строки не в счёт.
    code = "\n".join(ln for ln in body.splitlines() if not ln.strip().startswith("na("))
    leaks = re.findall(r'"(camera_0|processor|renderer|inspector|gui|storage)"', code)
    assert leaks == [], f"голые имена процессов прототипа в семьях: {leaks}"


def test_na_row_carries_reason_and_line_sim_gating(probe):
    saved_rows = list(probe.ROWS)
    saved_profile, saved_port = probe.PROFILE, probe.PORT
    try:
        probe.ROWS.clear()
        probe.apply_profile(probe.profile_for("line_sim"))
        assert (probe.PORT, probe.CAM, probe.NB, probe.FLT, probe.INSP) == (8766, "camera", "robot", "mjpeg", None)
        probe.na("K10", "ручки", "регистр", "inspector")
        (r,) = probe.ROWS
        assert r["verdict"] == "N/A"
        assert "inspector" in r["observed"] and len(r["observed"]) > 20
        probe.apply_profile(probe.profile_for("prototype"), port=9999)
        assert probe.PORT == 9999 and probe.INSP == "inspector"
    finally:
        probe.apply_profile(saved_profile, saved_port)
        probe.ROWS[:] = saved_rows


def test_import_with_foreign_argv_does_not_parse_it(tmp_path):
    """Переимпорт как __mp_main__ у spawn-ребёнка: чужой argv на импорте не разбирается."""
    code = f"import sys; sys.argv = ['x', '--definitely-not-a-flag']; import {MODULE}; print('ok')"
    env = dict(os.environ, PYTHONPATH=str(PROJECT_ROOT), MULTIPROCESS_LOG_DIR=str(tmp_path))
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=str(PROJECT_ROOT), env=env, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0 and "ok" in proc.stdout, proc.stderr[-1000:]


def test_register_role_prototype_literals_and_sim_target(probe):
    """K10/L5: прототип — прежние литералы дословно; сим — процесс из своего состава, поле в границах схемы."""
    assert probe.profile_for("prototype").register == ("inspector", "robot_control", "reject_delay_ms", 1, 0)
    sim = probe.profile_for("line_sim")
    proc, reg, fld, v_set, v_back = sim.register
    assert (proc, reg, fld) == ("camera", "camera_service", "gain")
    assert proc in sim.expected_procs
    # L5 пишет v_set и v_set + 1; всё обязано лежать в границах CameraServiceRegisters.gain (0..255).
    from Plugins.sources.camera_service.registers import CameraServiceRegisters

    for v in (v_set, v_set + 1, v_back):
        CameraServiceRegisters(gain=v)  # ValidationError, если вне границ
    assert "регистр" not in sim.na_reason["inspector"], (
        "причина N/A не должна ссылаться на регистры — K10/L5 теперь меряются"
    )


_I4_PIN = r"""
import dataclasses, importlib, sys
probe = importlib.import_module("backend_ctl.probes.probe_observability_consumer_acceptance")
calls = []
probe.port_free = lambda port: (calls.append(port), False)[1]
_orig = probe.profile_for
def _boom(*a, **k):
    raise AssertionError("harness must not be built")
probe.profile_for = lambda app: dataclasses.replace(_orig(app), make_harness=_boom)
out = []
for argv in ([], ["--app", "line_sim"], ["--app", "line_sim", "--port", "9999"], ["--port", "9001"]):
    rc = probe.main(argv)
    out.append((rc, calls[-1]))
print("RESULT", out)
"""


def test_abort_checks_the_resolved_port(tmp_path):
    """I4: абортный порт-чек смотрит на РАЗРЕШЁННЫЙ порт; стенд не строится (офлайн, отдельный процесс)."""
    env = dict(os.environ, PYTHONPATH=str(PROJECT_ROOT), MULTIPROCESS_LOG_DIR=str(tmp_path))
    proc = subprocess.run(
        [sys.executable, "-c", _I4_PIN], cwd=str(PROJECT_ROOT), env=env, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT "))
    assert line == "RESULT [(2, 8765), (2, 8766), (2, 9999), (2, 9001)]", line
