# -*- coding: utf-8 -*-
"""Task 0.2 (gui-graceful-close): живая приёмка ``system.shutdown mode=force`` — стадия 1, вслепую.

Контракт — ``plans/2026-10-20_gui-graceful-close/tasks/0.2.md`` (ACCEPTANCE), реализация не читалась.

Тесты:
  * L6  ``test_force_with_hung_child_tree_gone_fast`` — RED. ``inspection_full`` + один ребёнок-зависатель
        (``_hung_child_plugin``: корень спит 8 с на закрытии); ``force`` со сроком 1.0 с; 5 прогонов:
        каждый выход PM < 4.0 с, медиана ≤ 2.5 с, код PM 0, ни ``ВЫЖИЛИ``, ни ``survivors after root close``,
        строка ``Process '<имя>' did not stop in N.Ns, terminating`` у зависшего и INFO
        ``force: срок стопа детей 1.0 с``.
  * L-smoke ``test_driver_system_shutdown_live_smoke`` — RED (``AttributeError``: метода драйвера нет).
  * L7  ``test_force_on_healthy_system_not_slower_than_graceful`` — СТРАЖ (зелёный до и после): 10 пар
        graceful/force по очереди, ``deadline_s=5.0``; медиана(force) ≤ медиана(graceful) + 0.3 с, каждый
        force < 2.5 с, ``did not stop in`` — 0.

Время считается от отправки команды до ВЫХОДА процесса PM (``harness._launcher._spawner.get_process()``,
образец — ``test_system_shutdown_live.py``), а не до закрытия сокета.

Порты 7920–7929 (бронь Task 0.2). Запускать только в окне стенда: ``pytest --backend-live``.
"""

from __future__ import annotations

import re
import statistics
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

from backend_ctl.harness import BackendHarness
from backend_ctl.tests._hung_child_plugin import HUNG_PROCESS_CLASS_PATH

_PORT_BASE = 7920
_PORT_COUNT = 10
_RECIPE = "multiprocess_prototype/backend/topology/inspection_full.yaml"
_HUNG_NAME = "storage"
_PM_EXIT_WAIT_S = 20.0
_REPLY_TIMEOUT_S = 10.0

_TERMINATING_RE_TEMPLATE = r"Process '{name}' did not stop in \d+\.\ds, terminating"


def _port(index: int) -> int:
    return _PORT_BASE + (index % _PORT_COUNT)


def _make_hung_recipe(tmp_path: Path) -> Path:
    """Копия ``inspection_full`` с одним ребёнком (``storage``), чей корень спит 8 с на закрытии."""
    from multiprocess_prototype.backend.launch import load_topology_dict

    blueprint = load_topology_dict(Path(_RECIPE))
    for proc in blueprint.get("processes", []):
        if isinstance(proc, dict) and proc.get("process_name") == _HUNG_NAME:
            proc["process_class"] = HUNG_PROCESS_CLASS_PATH
            break
    else:
        raise AssertionError(f"процесс '{_HUNG_NAME}' не найден в {_RECIPE}")
    path = tmp_path / "inspection_full_hung_child.yaml"
    path.write_text(yaml.safe_dump(blueprint, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _read_all_logs(log_dir: Path) -> str:
    """Все ``*.log`` под каталогом логов прогона (PM пишет INFO туда, а не обязательно в stderr)."""
    parts: list[str] = []
    for path in sorted(log_dir.rglob("*.log")):
        try:
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(parts)


def _shutdown_run(capfd: Any, tmp_path: Path, *, index: int, recipe: Path | str, command: dict) -> dict:
    """Один прогон: старт, 2 с трафика, команда, ожидание ВЫХОДА PM, сбор кода выхода и текста логов."""
    log_dir = tmp_path / f"run_{index}"
    harness = BackendHarness(recipe=recipe, port=_port(index), warmup=1.0, log_dir=log_dir)
    try:
        capfd.readouterr()  # слить хвост предыдущего прогона
        drv = harness.start()
        time.sleep(2.0)  # пайплайн гонит кадры по всем процессам

        pm_process = None
        if harness._launcher is not None and harness._launcher._spawner is not None:
            pm_process = harness._launcher._spawner.get_process()
        assert pm_process is not None, f"run {index}: нет ссылки на PM-процесс до команды"

        start = time.monotonic()
        reply = drv.system_command(command, timeout=_REPLY_TIMEOUT_S)
        pm_process.join(timeout=_PM_EXIT_WAIT_S)
        elapsed = time.monotonic() - start
        exitcode = pm_process.exitcode
        captured = capfd.readouterr()
    finally:
        harness.stop()
    text = captured.out + captured.err + "\n" + _read_all_logs(log_dir)
    return {"index": index, "reply": reply, "elapsed": elapsed, "exitcode": exitcode, "text": text}


def _lines_with(text: str, needle: str) -> list[str]:
    return [line for line in text.splitlines() if needle in line]


@pytest.mark.harness_smoke
def test_force_with_hung_child_tree_gone_fast(capfd, tmp_path) -> None:
    recipe = _make_hung_recipe(tmp_path)
    command = {"cmd": "system.shutdown", "mode": "force", "deadline_s": 1.0}
    runs = [_shutdown_run(capfd, tmp_path, index=i, recipe=recipe, command=command) for i in range(5)]
    elapsed = [round(r["elapsed"], 3) for r in runs]

    for r in runs:
        assert r["reply"].get("success") is True, f"run {r['index']}: ответ на system.shutdown: {r['reply']!r}"
    slow = [(r["index"], round(r["elapsed"], 3)) for r in runs if r["elapsed"] >= 4.0]
    assert not slow, f"выход PM >= 4.0 с (индекс, с): {slow}; все прогоны: {elapsed}"
    assert statistics.median(r["elapsed"] for r in runs) <= 2.5, f"медиана > 2.5 с; прогоны: {elapsed}"

    for r in runs:
        text = r["text"]
        assert r["exitcode"] == 0, f"run {r['index']}: код выхода PM {r['exitcode']} (ждали 0); прогоны: {elapsed}"
        survivors = _lines_with(text, "ВЫЖИЛИ") + _lines_with(text, "survivors after root close")
        assert not survivors, f"run {r['index']}: выжившие после force: {survivors[:3]}"
        assert re.search(_TERMINATING_RE_TEMPLATE.format(name=_HUNG_NAME), text), (
            f"run {r['index']}: нет строки terminate у зависшего '{_HUNG_NAME}'"
        )
        assert "force: срок стопа детей 1.0 с" in text, f"run {r['index']}: нет INFO про срок стопа детей"


@pytest.mark.harness_smoke
def test_driver_system_shutdown_live_smoke(tmp_path) -> None:
    harness = BackendHarness(recipe=_RECIPE, port=_port(9), warmup=1.0, log_dir=tmp_path / "smoke")
    try:
        drv = harness.start()
        time.sleep(2.0)
        pm_process = None
        if harness._launcher is not None and harness._launcher._spawner is not None:
            pm_process = harness._launcher._spawner.get_process()
        assert pm_process is not None, "нет ссылки на PM-процесс до команды"

        res = drv.system_shutdown(mode="force")

        assert res["accepted"] is True, res
        assert res["pm_gone"] is True, res
        assert res["mode"] == "force", res
        assert res["outcomes"] is None, res
        pm_process.join(timeout=_PM_EXIT_WAIT_S)
        assert pm_process.exitcode is not None, f"PM не вышел за {_PM_EXIT_WAIT_S} с после закрытия сокета"
    finally:
        harness.stop()


@pytest.mark.harness_smoke
def test_force_on_healthy_system_not_slower_than_graceful(capfd, tmp_path) -> None:
    """СТРАЖ: здоровая система, ``deadline_s=5.0`` — force не медленнее graceful и не убивает здоровых детей."""
    graceful_cmd = {"cmd": "system.shutdown"}
    force_cmd = {"cmd": "system.shutdown", "mode": "force", "deadline_s": 5.0}
    graceful: list[dict] = []
    force: list[dict] = []
    for pair in range(10):
        graceful.append(_shutdown_run(capfd, tmp_path, index=2 * pair, recipe=_RECIPE, command=graceful_cmd))
        force.append(_shutdown_run(capfd, tmp_path, index=2 * pair + 1, recipe=_RECIPE, command=force_cmd))

    g_times = [round(r["elapsed"], 3) for r in graceful]
    f_times = [round(r["elapsed"], 3) for r in force]
    g_median = statistics.median(g_times)
    f_median = statistics.median(f_times)

    slow = [(r["index"], round(r["elapsed"], 3)) for r in force if r["elapsed"] >= 2.5]
    assert not slow, f"force >= 2.5 с (индекс, с): {slow}; force={f_times}; graceful={g_times}"
    assert f_median <= g_median + 0.3, (
        f"медиана force {f_median:.3f} с > медианы graceful {g_median:.3f} с + 0.3; force={f_times}; graceful={g_times}"
    )
    forced_stops = [(r["index"], line) for r in graceful + force for line in _lines_with(r["text"], "did not stop in")]
    assert not forced_stops, f"здоровый стоп дошёл до terminate: {forced_stops[:3]}"
