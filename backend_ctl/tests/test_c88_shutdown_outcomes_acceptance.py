# -*- coding: utf-8 -*-
"""C-88 — слепая приёмка: «у каждого ребёнка честный итог стопа после ``system_shutdown``».

Написано ДО правки по критериям приёмки брифа (DESIGN и тела реализации PM не читались). Всё — через публичное
наблюдаемое: ``BackendDriver.system_shutdown(wait=True)`` и ``supervision.status`` (``stop_outcome`` процесса).
Обвязка настоящая: ``BackendHarness`` поднимает настоящий ``ProcessManagerProcess`` с настоящими spawn-детьми
(``backend_ctl/tests/fixtures/c88/slow_exit_children.py``), двойников нет.

Словарь итога: ``exited`` — ушёл сам в окне стопа; ``terminated`` — ушёл после SIGTERM (окно кончилось);
``killed`` — после kill (SIGTERM проигнорирован).

Окно стопа ребёнка задаётся ``orchestrator_config["stop_process_timeout"]`` PM (так делает стенд 1.9b:
``docs/reports/2026-10-26_lifecycle-stop-ownership_1.9b-stand/stand_backend.py``): тестовый патч
``assemble_launcher`` кладёт 1.0 с, чтобы «медленный» ребёнок (30 с на закрытии) не ждал дефолтных секунд.

Критерии:
  R1  ``test_r1_*``  — 11 детей (из них один выходит на ~0.5 с позже остальных): итог КАЖДОГО из
      exited|terminated|killed, ни одного ``None``, ``unconfirmed`` пуст, ``timed_out`` False. До правки
      красный вероятностно (прогнан трижды: параметр ``run``).
  R2  ``test_r2_*``  — семантика итога: ``exited`` / ``terminated`` / ``killed`` на наименьшем настоящем дереве.
  R3  ``test_r3_*``  — повторный стоп уже мёртвого ребёнка не затирает итог прежнего стопа в ``None``.
  R4  всё выше идёт на настоящем PM и настоящих детях.

Порты 18765-18779 (бронь C-88). Живые тесты: ``pytest --backend-live``.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from backend_ctl.driver import BackendDriver
from backend_ctl.harness import BackendHarness
from backend_ctl.protocol import unwrap
from backend_ctl.tests.fixtures.c88.slow_exit_children import (
    IGNORE_TERM_CLASS_PATH,
    SLEEP05_CLASS_PATH,
    SLEEP30_CLASS_PATH,
)

pytestmark = pytest.mark.harness_smoke

_PORT_BASE = 18765
_GENERIC = "multiprocess_prototype.generic_process_app.GenericProcessApp"
_HEADLESS_GUI = "multiprocess_prototype.frontend.headless_process.HeadlessGuiProcess"
_STOP_WINDOW_S = 1.0
_VALID_OUTCOMES = {"exited", "terminated", "killed"}
_CALL_DEADLINE_S = 120.0  # потолок любого вызова, который может зависнуть
_PM = "ProcessManager"


# --------------------------------------------------------------------------- #
# Обвязка
# --------------------------------------------------------------------------- #


def _bounded[T](call: Callable[[], T], deadline_s: float = _CALL_DEADLINE_S) -> T:
    """Вызов в daemon-потоке с дедлайном; исключение вызова пробрасывается в поток теста."""
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["value"] = call()
        except BaseException as exc:  # noqa: BLE001 — пробросим в поток теста
            box["error"] = exc

    th = threading.Thread(target=_run, daemon=True, name="c88-bounded-call")
    th.start()
    th.join(deadline_s)
    assert not th.is_alive(), f"вызов не вернулся за {deadline_s} с"
    if "error" in box:
        raise box["error"]
    return box["value"]


def _write_recipe(tmp_path: Path, children: dict[str, str], name: str = "c88") -> Path:
    """Рецепт: headless ``gui`` + дети ``{имя: process_class}`` без плагинов."""
    processes: list[dict[str, Any]] = [
        {"process_name": "gui", "protected": True, "process_class": _HEADLESS_GUI, "plugins": []}
    ]
    for child_name, class_path in children.items():
        processes.append({"process_name": child_name, "process_class": class_path, "priority": "normal", "plugins": []})
    path = tmp_path / f"{name}.yaml"
    path.write_text(
        yaml.safe_dump({"name": name, "description": "C-88 acceptance", "processes": processes}, allow_unicode=True),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def stop_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """Окно стопа ребёнка ``_STOP_WINDOW_S`` с: ключ ``stop_process_timeout`` в ``orchestrator_config`` PM."""
    import multiprocess_framework.modules.process_manager_module.launcher as launcher_pkg

    original = launcher_pkg.assemble_launcher

    def patched(proc_dicts: Any, *args: Any, orchestrator_config: Any = None, **kwargs: Any) -> Any:
        cfg = dict(orchestrator_config or {})
        cfg["stop_process_timeout"] = _STOP_WINDOW_S
        return original(proc_dicts, *args, orchestrator_config=cfg, **kwargs)

    monkeypatch.setattr(launcher_pkg, "assemble_launcher", patched)


def _start(tmp_path: Path, children: dict[str, str], port: int) -> tuple[BackendHarness, BackendDriver]:
    recipe = _write_recipe(tmp_path, children)
    harness = BackendHarness(recipe=recipe, port=port, warmup=1.0, log_dir=tmp_path / "logs")
    driver = _bounded(harness.start)
    return harness, driver


def _stop_outcomes(driver: BackendDriver) -> dict[str, Any]:
    """``{процесс: stop_outcome}`` из ``supervision.status`` (без ``ProcessManager``)."""
    snap = unwrap(driver.supervision_status(pm_name=_PM, timeout=10.0), leaf=True)
    processes = snap.get("processes") or {}
    return {name: entry.get("stop_outcome") for name, entry in processes.items() if name != _PM}


def _shutdown(driver: BackendDriver) -> dict[str, Any]:
    return _bounded(lambda: driver.system_shutdown(wait=True))


# --------------------------------------------------------------------------- #
# R1: 11 детей, один выходит позже остальных
# --------------------------------------------------------------------------- #


def _eleven_children() -> dict[str, str]:
    children = {f"worker_{i}": _GENERIC for i in range(10)}
    children["slow_exit"] = SLEEP05_CLASS_PATH
    return children


@pytest.mark.parametrize("run", [0, 1, 2])
def test_r1_every_child_has_honest_outcome_with_one_slow_exiter(run: int, tmp_path: Path, stop_window: None) -> None:
    """R1: 11 детей, ``slow_exit`` держит выход +0.5 с: ни ``None``, ``unconfirmed`` пуст, ``timed_out`` False."""
    # gui (headless) — тоже ребёнок PM: 12 имён = gui + worker_0..9 + slow_exit.
    names = sorted(["gui", "slow_exit", *(f"worker_{i}" for i in range(10))])
    harness, driver = _start(tmp_path, _eleven_children(), _PORT_BASE + run)
    try:
        result = _shutdown(driver)
    finally:
        harness.stop()

    assert result["accepted"] is True, f"run {run}: стоп не принят: {result}"
    outcomes = result["outcomes"]
    assert outcomes is not None, f"run {run}: опроса итогов не было: {result}"
    assert sorted(outcomes) == names, f"run {run}: набор детей в итогах: {sorted(outcomes)}"
    bad = {name: value for name, value in outcomes.items() if value not in _VALID_OUTCOMES}
    assert not bad, f"run {run}: у детей нет честного итога (ждали exited|terminated|killed): {bad}"
    assert result["unconfirmed"] == [], f"run {run}: unconfirmed не пуст: {result['unconfirmed']}"
    assert result["timed_out"] is False, f"run {run}: ожидание кончилось по сроку: {result}"


def test_r1_control_eleven_fast_children_all_have_honest_outcome(tmp_path: Path, stop_window: None) -> None:
    """R1, вариант без медленного: 11 быстрых детей + gui — то же свойство (контроль: дефект не только у медленного)."""
    harness, driver = _start(tmp_path, {f"worker_{i}": _GENERIC for i in range(11)}, _PORT_BASE + 6)
    try:
        result = _shutdown(driver)
    finally:
        harness.stop()
    assert result["accepted"] is True, f"стоп не принят: {result}"
    outcomes = result["outcomes"]
    assert outcomes is not None, f"опроса итогов не было: {result}"
    bad = {name: value for name, value in outcomes.items() if value not in _VALID_OUTCOMES}
    assert not bad, f"у детей нет честного итога (ждали exited|terminated|killed): {bad}"
    assert result["unconfirmed"] == [], f"unconfirmed не пуст: {result['unconfirmed']}"
    assert result["timed_out"] is False, f"ожидание кончилось по сроку: {result}"


# --------------------------------------------------------------------------- #
# R2: семантика итога на наименьшем настоящем дереве
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def semantics_result(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Одно дерево на три теста R2: ``fast`` (0 с), ``in_window`` (0.5 с), ``late`` (30 с), ``deaf`` (30 с, без TERM).

    Окно стопа 1.0 с. Результат ``system_shutdown(wait=True)`` целиком.
    """
    import multiprocess_framework.modules.process_manager_module.launcher as launcher_pkg

    tmp_path = tmp_path_factory.mktemp("c88_r2")
    original = launcher_pkg.assemble_launcher

    def patched(proc_dicts: Any, *args: Any, orchestrator_config: Any = None, **kwargs: Any) -> Any:
        cfg = dict(orchestrator_config or {})
        cfg["stop_process_timeout"] = _STOP_WINDOW_S
        return original(proc_dicts, *args, orchestrator_config=cfg, **kwargs)

    launcher_pkg.assemble_launcher = patched
    try:
        children = {
            "fast": _GENERIC,
            "in_window": SLEEP05_CLASS_PATH,
            "late": SLEEP30_CLASS_PATH,
            "deaf": IGNORE_TERM_CLASS_PATH,
        }
        harness, driver = _start(tmp_path, children, _PORT_BASE + 3)
        try:
            return _shutdown(driver)
        finally:
            harness.stop()
    finally:
        launcher_pkg.assemble_launcher = original


def _outcomes_of(result: dict[str, Any]) -> dict[str, Any]:
    assert result["accepted"] is True, f"стоп не принят: {result}"
    assert result["outcomes"] is not None, f"опроса итогов не было: {result}"
    return result["outcomes"]


def test_r2_child_that_leaves_by_itself_in_window_is_exited(semantics_result: dict[str, Any]) -> None:
    outcomes = _outcomes_of(semantics_result)
    assert (outcomes.get("fast"), outcomes.get("in_window")) == ("exited", "exited"), f"итоги: {outcomes}"


def test_r2_child_that_leaves_only_after_sigterm_is_terminated(semantics_result: dict[str, Any]) -> None:
    outcomes = _outcomes_of(semantics_result)
    assert outcomes.get("late") == "terminated", f"итоги: {outcomes}"


def test_r2_child_that_ignores_sigterm_is_killed(semantics_result: dict[str, Any]) -> None:
    outcomes = _outcomes_of(semantics_result)
    assert outcomes.get("deaf") == "killed", f"итоги: {outcomes}"


# --------------------------------------------------------------------------- #
# R3: повторный стоп мёртвого ребёнка не затирает итог
# --------------------------------------------------------------------------- #


def test_r3_repeated_stop_of_dead_child_keeps_previous_outcome(tmp_path: Path, stop_window: None) -> None:
    """``process.stop`` дважды подряд: ``stop_outcome`` в ``supervision.status`` остаётся ``terminated``."""
    harness, driver = _start(tmp_path, {"victim": SLEEP30_CLASS_PATH, "other": _GENERIC}, _PORT_BASE + 4)
    try:
        first = unwrap(
            _bounded(lambda: driver.send_command(_PM, "process.stop", {"process_name": "victim"}, timeout=30.0)),
            leaf=True,
        )
        assert first.get("success") is True, f"первый process.stop: {first}"
        before = _stop_outcomes(driver)["victim"]
        assert before == "terminated", f"после первого стопа итог {before!r}, ждали 'terminated'"

        _bounded(lambda: driver.send_command(_PM, "process.stop", {"process_name": "victim"}, timeout=30.0))
        samples = []
        for _ in range(5):
            samples.append(_stop_outcomes(driver)["victim"])
            time.sleep(0.3)
    finally:
        harness.stop()
    assert samples == ["terminated"] * 5, f"повторный стоп затёр итог: {samples}"


def test_r3_shutdown_after_early_stop_reports_the_earlier_outcome(tmp_path: Path, stop_window: None) -> None:
    """Ребёнок остановлен ДО ``system_shutdown``; общий стоп трогает его повторно, но итог в ответе тот же."""
    harness, driver = _start(tmp_path, {"victim": SLEEP30_CLASS_PATH, "other": _GENERIC}, _PORT_BASE + 5)
    try:
        first = unwrap(
            _bounded(lambda: driver.send_command(_PM, "process.stop", {"process_name": "victim"}, timeout=30.0)),
            leaf=True,
        )
        assert first.get("success") is True, f"process.stop: {first}"
        result = _shutdown(driver)
    finally:
        harness.stop()
    outcomes = _outcomes_of(result)
    # Только victim: итоги соседей — предмет R1, здесь они бы подмешали чужую причину красного.
    assert outcomes.get("victim") == "terminated", f"итоги: {outcomes}; ответ: {result}"
