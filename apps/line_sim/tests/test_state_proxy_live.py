"""Task 2.0 — независимый RED (тестер, worktree на a0edf74a, ДО реализации).

Контракт — из Acceptance criteria/REDS плана (``plans/line-sim/phase-2-belt-truth.md``,
Task 2.0). Фикстура — ``apps/line_sim/tests/fixtures/state_proxy_app/`` (два
процесса на ГОЛОМ ``GenericProcess``, ``writer``/``reader``), не сам
``apps/line_sim`` — камеры в фикстуре нет, см. адаптацию последнего теста ниже.

Образец harness — ``multiprocess_framework/modules/app_module/tests/test_f1_task10_acceptance.py``
(``BackendHarness`` + ``build_app``), тот же приём толерантных хелперов формы
ответа команд.

Сегодня (до Task 2.0): голый ``GenericProcess`` не создаёт ``_state_proxy`` —
``ctx.state_proxy`` в обоих плагинах фикстуры ``None``, писатель/читатель
отвечают ``{"status": "error", "reason": "ctx.state_proxy is None"}`` на
командах, дельты не приходят, лист ``belt_fps`` в дереве не появляется —
все три теста ниже красные.
"""

from __future__ import annotations

import os
import socket
import time
from pathlib import Path
from typing import Any

import pytest

from backend_ctl.harness import BackendHarness

_FIXTURE_APP_YAML = Path(__file__).resolve().parent / "fixtures" / "state_proxy_app" / "app.yaml"

_WRITER = "writer"
_READER = "reader"


def _free_port() -> int:
    """Свободный TCP-порт для backend_ctl (не 8765/8766 — см. TRAPS брифа)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build_fixture_launcher():
    from multiprocess_framework.modules.app_module import build_app

    return build_app(_FIXTURE_APP_YAML)


def _find_process_entry(overview: dict, name: str) -> Any:
    """Найти запись процесса в system_overview() (dict-по-имени, ``overview.py``)."""
    processes = overview.get("processes") if isinstance(overview, dict) else None
    if isinstance(processes, dict):
        return processes.get(name)
    if isinstance(processes, list):
        for entry in processes:
            if isinstance(entry, dict) and entry.get("name") == name:
                return entry
    return None


def _entry_is_running(entry: Any) -> bool:
    """Толерантно: сперва явные boolean-флаги, затем строковый status."""
    if not isinstance(entry, dict):
        return False
    for key in ("running", "is_running", "alive"):
        if key in entry:
            return bool(entry[key])
    status = entry.get("status")
    return isinstance(status, str) and status.lower() in ("running", "ok", "alive")


def _poll_overview_until_running(drv: Any, names: tuple[str, ...], *, deadline_s: float = 15.0) -> dict:
    """Опрос system_overview() по time.monotonic() (не сон) до готовности names."""
    deadline = time.monotonic() + deadline_s
    overview: dict = {}
    while time.monotonic() < deadline:
        overview = drv.system_overview()
        if isinstance(overview, dict) and all(_entry_is_running(_find_process_entry(overview, n)) for n in names):
            return overview
        time.sleep(0.3)
    return overview


def _command_succeeded(res: Any) -> bool:
    """Успех ответа команды — толерантно к {"success": ...} и {"status": "ok"}."""
    if not isinstance(res, dict):
        return False
    if "success" in res:
        return bool(res.get("success"))
    return res.get("status") == "ok"


def _result_field(res: dict, key: str) -> Any:
    """Достать поле ответа, терпимо к одному лишнему уровню ``result`` (backend_ctl/protocol.py::unwrap)."""
    if key in res:
        return res[key]
    nested = res.get("result")
    if isinstance(nested, dict) and key in nested:
        return nested[key]
    return None


@pytest.fixture
def state_proxy_fixture_backend(tmp_path: Path):
    """Headless фикстура: свой порт backend_ctl + свой лог-каталог (образец — test_f1_task10)."""
    prev_log = os.environ.get("MULTIPROCESS_LOG_DIR")
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    os.environ["MULTIPROCESS_LOG_DIR"] = str(log_dir)

    harness = BackendHarness(launcher_factory=_build_fixture_launcher, port=_free_port())
    drv = harness.start()
    try:
        yield harness, drv
    finally:
        harness.stop()
        if prev_log is None:
            os.environ.pop("MULTIPROCESS_LOG_DIR", None)
        else:
            os.environ["MULTIPROCESS_LOG_DIR"] = prev_log


@pytest.mark.timeout(60)
def test_set_in_robot_visible_in_camera_get(state_proxy_fixture_backend) -> None:
    """Acceptance: set() в writer -> get() в reader и state.get на ProcessManager
    видят {"value": 42} не позже 2.0 с. Путь sim.belt.* нигде не посеян."""
    _harness, drv = state_proxy_fixture_backend
    overview = _poll_overview_until_running(drv, (_WRITER, _READER))
    assert _entry_is_running(_find_process_entry(overview, _WRITER)), f"writer не running: {overview!r}"
    assert _entry_is_running(_find_process_entry(overview, _READER)), f"reader не running: {overview!r}"

    trigger_res = drv.send_command(_WRITER, "trigger_set", {}, timeout=5.0)
    assert _command_succeeded(trigger_res), f"trigger_set не удался: {trigger_res!r}"

    deadline = time.monotonic() + 2.0
    got: Any = None
    while time.monotonic() < deadline:
        res = drv.send_command(_READER, "get_belt", {}, timeout=5.0)
        if _command_succeeded(res):
            got = _result_field(res, "value")
            if got == {"value": 42}:
                break
        time.sleep(0.1)
    assert got == {"value": 42}, f"reader.get('sim.belt.encoder') != {{'value': 42}} за 2.0с: {got!r}"

    # backend_ctl той же фикстуры — прямой state.get на ProcessManager (мимо плагина).
    res2 = drv.send_command("ProcessManager", "state.get", {"path": "sim.belt.encoder"}, timeout=5.0)
    assert _command_succeeded(res2), f"state.get('sim.belt.encoder') не удался: {res2!r}"
    assert _result_field(res2, "value") == {"value": 42}, f"state.get вернул {_result_field(res2, 'value')!r}"


@pytest.mark.timeout(60)
def test_subscribe_glob_receives_event_once(state_proxy_fixture_backend) -> None:
    """Acceptance: подписка reader'а на sim.belt.* (оформлена в configure(), ДО
    set) получает РОВНО 1 колбэк с путём sim.belt.encoder за 2.0 с (не 0, не 2)."""
    _harness, drv = state_proxy_fixture_backend
    overview = _poll_overview_until_running(drv, (_WRITER, _READER))
    assert _entry_is_running(_find_process_entry(overview, _WRITER)), f"writer не running: {overview!r}"
    assert _entry_is_running(_find_process_entry(overview, _READER)), f"reader не running: {overview!r}"

    trigger_res = drv.send_command(_WRITER, "trigger_set", {}, timeout=5.0)
    assert _command_succeeded(trigger_res), f"trigger_set не удался: {trigger_res!r}"

    deadline = time.monotonic() + 2.0
    deltas: list = []
    while time.monotonic() < deadline:
        res = drv.send_command(_READER, "received", {}, timeout=5.0)
        if _command_succeeded(res):
            deltas = _result_field(res, "deltas") or []
            if deltas:
                break
        time.sleep(0.1)

    matching = [d for d in deltas if isinstance(d, dict) and d.get("path") == "sim.belt.encoder"]
    assert len(matching) == 1, (
        f"ожидался ровно 1 callback на sim.belt.encoder за 2.0с, получено {len(matching)}: {deltas!r}"
    )


@pytest.mark.timeout(60)
def test_heartbeat_pushes_camera_fps_to_tree(state_proxy_fixture_backend) -> None:
    """Acceptance (адаптация — см. отчёт тестера): heartbeat кладёт уровень
    плагина в дерево, гейт `_state_proxy` снимает ранний выход
    process_heartbeat.py:1355-1357. Фикстура без камеры line_sim — лист
    ``processes.writer.state.plugins.belt_writer.belt_fps`` (ADR-PM-038,
    ctx.publish_metric) вместо ``processes.camera.state.fps``: тот же
    механизм-гейт, другой писатель. Имя теста сохранено = REDS-предсказанию;
    расхождение семантики названо явно."""
    _harness, drv = state_proxy_fixture_backend
    overview = _poll_overview_until_running(drv, (_WRITER, _READER))
    assert _entry_is_running(_find_process_entry(overview, _WRITER)), f"writer не running: {overview!r}"

    deadline = time.monotonic() + 15.0
    value: Any = None
    while time.monotonic() < deadline:
        res = drv.send_command(
            "ProcessManager",
            "state.get",
            {"path": "processes.writer.state.plugins.belt_writer.belt_fps"},
            timeout=5.0,
        )
        if _command_succeeded(res):
            value = _result_field(res, "value")
            if value is not None:
                break
        time.sleep(0.5)

    assert value == 30, (
        f"processes.writer.state.plugins.belt_writer.belt_fps не появился в дереве за 15с "
        f"(гейт _state_proxy не пройден — GenericProcess не создаёт state_proxy): {value!r}"
    )
