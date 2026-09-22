"""Приёмочные тесты (RED, Ф1 Task 1.0) для дефолтного ``StateBootstrap`` в ``app_module``.

Независимый тестер, БЕЗ реализации (worktree на коммите ``475227c8``, ДО неё) — контракт
ниже собран из брифа lead'а + интерфейс-контракта (``interfaces.py::StateBootstrap``,
``builder.py::AppSpec``/``SystemBuilder._build_generic``), НЕ из будущей реализации.
Образцы — ``examples/minimal_app/tests/test_ci_smoke.py`` (фикстура BackendHarness),
``apps/line_sim/tests/test_f1_task11_acceptance.py`` (стиль толерантных хелперов формы
``system_overview()``).

Сегодня в ``multiprocess_framework.modules.app_module`` НЕТ экспорта
``default_state_bootstrap`` — импорт этого символа бросает ``ImportError`` (тесты 4, 5).
``AppSpec.state_bootstrap`` (Task 1.0 использует существующее поле) применяется
``SystemBuilder._build_generic`` уже сегодня БЕЗ дефолта-конкурента, поэтому
``initial_state`` пуст, если хук не задан явно — ``StateStoreManager`` не создаётся
(``GenericProcessManagerApp._setup_state_store``: пустой ``initial_state`` и пустые
``state_throttle_rules`` -> no-op), у процесса нет команды ``state.get_subtree`` вовсе
(``No handler for key 'state.get_subtree'``) -> ``system_overview()["processes"] == {}``
+ аномалия ``kind == "empty_topology"`` (тесты 1-3).

Форма ``system_overview()["processes"]`` — dict по имени процесса с полем ``status``
(строка) — подтверждена чтением ``backend_ctl/overview.py`` (в разрешённом списке
чтения); толерантный хелпер ``_entry_is_running`` ниже всё равно проверяет запасные
ключи (``running``/``is_running``/``alive``) на случай будущего расхождения формы.
"""

from __future__ import annotations

import os
import socket
import time
from pathlib import Path
from typing import Any

import pytest

from backend_ctl.harness import BackendHarness

# .../app_module/tests/<file> -> parents[4] = корень репо.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_MINIMAL_APP_YAML = _REPO_ROOT / "examples" / "minimal_app" / "app.yaml"
_LINE_SIM_APP_YAML = _REPO_ROOT / "apps" / "line_sim" / "app.yaml"

_TICKER = "ticker"
_CONSOLE_SINK = "console_sink"
_ROBOT_PROCESS = "robot"
_ROBOT_HOST = "127.0.0.1"
_MODBUS_PORT = 5021  # литерал контракта (apps/line_sim/pipeline.yaml) — не выводить из кода


def _free_port() -> int:
    """Свободный TCP-порт для backend_ctl (см. apps/line_sim/tests/test_f1_task11_acceptance.py)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _assert_modbus_port_free() -> None:
    """5021 — литерал контракта line_sim; падение с внятным сообщением, не тихий skip."""
    with socket.socket() as probe:
        probe.settimeout(0.2)
        try:
            probe.bind((_ROBOT_HOST, _MODBUS_PORT))
        except OSError as exc:
            pytest.fail(f"порт {_MODBUS_PORT} занят — {exc}")


def _find_process_entry(overview: dict, name: str) -> Any:
    """Найти запись процесса ``name`` в ``system_overview()`` (dict-по-имени, ``overview.py``)."""
    processes = overview.get("processes") if isinstance(overview, dict) else None
    if isinstance(processes, dict):
        return processes.get(name)
    if isinstance(processes, list):  # запасной вариант формы, не подтверждён для этого модуля
        for entry in processes:
            if isinstance(entry, dict) and entry.get("name") == name:
                return entry
    return None


def _entry_is_running(entry: Any) -> bool:
    """Толерантно: сперва явные boolean-флаги, затем строковый ``status``."""
    if not isinstance(entry, dict):
        return False
    for key in ("running", "is_running", "alive"):
        if key in entry:
            return bool(entry[key])
    status = entry.get("status")
    return isinstance(status, str) and status.lower() in ("running", "ok", "alive")


def _command_succeeded(res: Any) -> bool:
    """Успех ответа команды — толерантно к двум формам конверта.

    Расхождение с брифом (см. отчёт тестера): ``handle_state_get_subtree``
    (``state_store_module/manager/state_store_manager.py``) отвечает ``{"status": "ok"/
    "error", ...}``, а НЕ ``{"success": ...}``; при отсутствии обработчика
    ``dispatch_module/core/base_dispatcher.py`` тоже отвечает ``{"status": "error",
    "reason": "No handler for key '...'"}`` — тоже без ``success``. Толерантная проверка
    обеих форм не даёт брифовому "success is True" сделать тест ложно-красным ПОСЛЕ
    реализации (реальный контракт станет status=="ok").
    """
    if not isinstance(res, dict):
        return False
    if "success" in res:
        return bool(res.get("success"))
    return res.get("status") == "ok"


def _subtree_value(res: dict) -> Any:
    """Достать ``value`` из ответа ``state.get_subtree`` — терпимо к одному лишнему уровню
    ``result`` (та же осторожность, что у ``backend_ctl/protocol.py::unwrap``)."""
    if isinstance(res.get("value"), dict):
        return res["value"]
    nested = res.get("result")
    if isinstance(nested, dict) and isinstance(nested.get("value"), dict):
        return nested["value"]
    return None


def _all_logs_text(log_dir: Path) -> str:
    """Конкатенация текста всех ``*.log`` под ``log_dir`` (рекурсивно)."""
    chunks: list[str] = []
    for path in log_dir.rglob("*.log"):
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(chunks)


def _build_minimal_app_launcher():
    from multiprocess_framework.modules.app_module import build_app

    return build_app(_MINIMAL_APP_YAML)


def _build_line_sim_launcher():
    from multiprocess_framework.modules.app_module import build_app

    return build_app(_LINE_SIM_APP_YAML)


@pytest.fixture
def minimal_app_backend(tmp_path: Path):
    """Headless minimal_app: свой порт backend_ctl + свой лог-каталог.

    Образец — ``examples/minimal_app/tests/test_ci_smoke.py::minimal_app_backend``.
    Ловушка lead'а п.1: ``MULTIPROCESS_LOG_DIR`` выставляется ДО сборки launcher'а
    (до ``harness.start()``, который зовёт ``launcher_factory`` лениво).
    """
    prev_log = os.environ.get("MULTIPROCESS_LOG_DIR")
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    os.environ["MULTIPROCESS_LOG_DIR"] = str(log_dir)

    harness = BackendHarness(launcher_factory=_build_minimal_app_launcher, port=_free_port())
    drv = harness.start()
    try:
        yield harness, drv, log_dir
    finally:
        harness.stop()
        if prev_log is None:
            os.environ.pop("MULTIPROCESS_LOG_DIR", None)
        else:
            os.environ["MULTIPROCESS_LOG_DIR"] = prev_log


@pytest.fixture
def line_sim_backend(tmp_path: Path):
    """Headless line_sim: свой порт backend_ctl + свой лог-каталог + порт 5021 свободен."""
    _assert_modbus_port_free()
    prev_log = os.environ.get("MULTIPROCESS_LOG_DIR")
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    os.environ["MULTIPROCESS_LOG_DIR"] = str(log_dir)

    harness = BackendHarness(launcher_factory=_build_line_sim_launcher, port=_free_port())
    drv = harness.start()
    try:
        yield harness, drv, log_dir
    finally:
        harness.stop()
        if prev_log is None:
            os.environ.pop("MULTIPROCESS_LOG_DIR", None)
        else:
            os.environ["MULTIPROCESS_LOG_DIR"] = prev_log


def _poll_overview_until_running(drv: Any, names: tuple[str, ...], *, deadline_s: float = 15.0) -> dict:
    """Опрос ``system_overview()`` по ``time.monotonic()`` (не сон) до готовности ``names``."""
    deadline = time.monotonic() + deadline_s
    overview: dict = {}
    while time.monotonic() < deadline:
        overview = drv.system_overview()
        if isinstance(overview, dict) and all(_entry_is_running(_find_process_entry(overview, n)) for n in names):
            break
        time.sleep(0.5)
    return overview


# --------------------------------------------------------------------------- #
# Критерий 1: generic-приложение (minimal_app) сеет state-топологию —         #
# system_overview() видит ticker и console_sink                               #
# --------------------------------------------------------------------------- #


@pytest.mark.harness_smoke
@pytest.mark.timeout(60)
def test_minimal_app_overview_lists_processes(minimal_app_backend) -> None:
    """Пин: system_overview()["processes"] содержит ticker и console_sink (running),
    и в anomalies нет kind == "empty_topology".

    Провал сегодня: initial_state пуст (нет default_state_bootstrap) -> StateStoreManager
    не создаётся -> processes == {} -> оба процесса "не найдены" (AssertionError).
    """
    _harness, drv, _log_dir = minimal_app_backend

    overview = _poll_overview_until_running(drv, (_TICKER, _CONSOLE_SINK))

    for name in (_TICKER, _CONSOLE_SINK):
        entry = _find_process_entry(overview, name)
        assert entry is not None, f"процесс {name!r} не найден в system_overview(): {overview!r}"
        assert _entry_is_running(entry), f"процесс {name!r} не running в system_overview(): {entry!r}"

    anomalies = overview.get("anomalies") if isinstance(overview, dict) else None
    kinds = [a.get("kind") for a in (anomalies or []) if isinstance(a, dict)]
    assert "empty_topology" not in kinds, f"anomalies содержит empty_topology: {anomalies!r}"


# --------------------------------------------------------------------------- #
# Критерий 1 (второе приложение): line_sim сеет топологию — overview видит    #
# robot                                                                        #
# --------------------------------------------------------------------------- #


@pytest.mark.harness_smoke
@pytest.mark.timeout(60)
def test_line_sim_overview_lists_robot(line_sim_backend) -> None:
    """Пин: system_overview()["processes"] содержит robot (running) для второго,
    независимого от minimal_app приложения на том же дефолтном bootstrap-хуке.

    Провал сегодня: та же причина, что и в критерии 1 (initial_state пуст) -> robot
    "не найден" в overview (AssertionError). Порт 5021 проверяется свободным фикстурой
    ДО старта (падение с сообщением, если занят — не skip).
    """
    _harness, drv, _log_dir = line_sim_backend

    overview = _poll_overview_until_running(drv, (_ROBOT_PROCESS,))

    entry = _find_process_entry(overview, _ROBOT_PROCESS)
    assert entry is not None, f"процесс {_ROBOT_PROCESS!r} не найден в system_overview(): {overview!r}"
    assert _entry_is_running(entry), f"процесс {_ROBOT_PROCESS!r} не running в system_overview(): {entry!r}"


# --------------------------------------------------------------------------- #
# Критерий: state.get_subtree отвечает (не "No handler for key ...")          #
# --------------------------------------------------------------------------- #


@pytest.mark.harness_smoke
@pytest.mark.timeout(60)
def test_state_get_subtree_answers_without_handler_errors(minimal_app_backend) -> None:
    """Пин: send_command("ProcessManager", "state.get_subtree", {"path": "processes"})
    успешен и содержит ticker/console_sink; ни в одном *.log под MULTIPROCESS_LOG_DIR
    нет строки "No handler for key 'state.get_subtree'".

    Провал сегодня: без StateStoreManager команда state.get_subtree НЕ зарегистрирована
    в CommandManager -> dispatch_module отвечает {"status": "error", "reason": "No
    handler for key 'state.get_subtree'"} -> _command_succeeded() == False (AssertionError
    на первом assert, до сравнения содержимого).
    """
    _harness, drv, log_dir = minimal_app_backend

    deadline = time.monotonic() + 15.0
    res: dict = {}
    while time.monotonic() < deadline:
        res = drv.send_command("ProcessManager", "state.get_subtree", {"path": "processes"}, timeout=5.0)
        if _command_succeeded(res):
            break
        time.sleep(0.5)

    assert _command_succeeded(res), f"state.get_subtree не успешен: {res!r}"
    subtree = _subtree_value(res)
    assert isinstance(subtree, dict), f"state.get_subtree не отдал dict в value: {res!r}"
    assert _TICKER in subtree, f"{_TICKER!r} отсутствует в поддереве processes: {subtree!r}"
    assert _CONSOLE_SINK in subtree, f"{_CONSOLE_SINK!r} отсутствует в поддереве processes: {subtree!r}"

    logs_text = _all_logs_text(log_dir)
    assert "No handler for key 'state.get_subtree'" not in logs_text, (
        "в логах есть \"No handler for key 'state.get_subtree'\" — команда не зарегистрирована"
    )


# --------------------------------------------------------------------------- #
# Критерий: default_state_bootstrap строит ТОЛЬКО топологию (чистая функция)  #
# --------------------------------------------------------------------------- #


def test_default_bootstrap_builds_topology_only() -> None:
    """Пин: default_state_bootstrap(blueprint) -> {"processes": {name: {"config": {...},
    "state": {"status": "stopped", "pid": None, ...}}}} — единственный верхнеуровневый
    ключ "processes", ни одного из system/wires/services/displays/recipes/plugins;
    результат пиклится (уходит в orchestrator_config через spawn).

    Провал сегодня: default_state_bootstrap ещё не экспортирован app_module -> ImportError.
    """
    from multiprocess_framework.modules.app_module import default_state_bootstrap

    blueprint = {
        "name": "synthetic",
        "processes": [
            {
                "process_name": "a",
                "plugins": [{"plugin_class": "dummy.pkg.PluginA", "plugin_name": "pa"}],
                "chain_targets": ["b"],
                "priority": "normal",
            },
            {
                "process_name": "b",
                "plugins": [{"plugin_class": "dummy.pkg.PluginB", "plugin_name": "pb"}],
                "chain_targets": [],
                "priority": "high",
            },
        ],
        "wires": [],
    }

    result = default_state_bootstrap(blueprint)

    assert isinstance(result, dict), f"результат не dict: {result!r}"
    assert set(result.keys()) == {"processes"}, f"верхний уровень не только 'processes': {result!r}"

    processes = result["processes"]
    assert set(processes.keys()) == {"a", "b"}, f"ожидали ровно {{'a', 'b'}}: {set(processes.keys())!r}"
    for name in ("a", "b"):
        entry = processes[name]
        assert entry["state"]["status"] == "stopped", f"{name}: state.status != 'stopped': {entry!r}"
        assert entry["state"]["pid"] is None, f"{name}: state.pid не None: {entry!r}"

    for forbidden in ("system", "wires", "services", "displays", "recipes", "plugins"):
        assert forbidden not in result, f"неожиданный верхнеуровневый ключ {forbidden!r}: {result!r}"

    import pickle

    pickle.dumps(result)  # не бросает — результат пиклябелен (spawn-граница)


# --------------------------------------------------------------------------- #
# Критерий: явный AppSpec.state_bootstrap выигрывает у дефолта                #
# --------------------------------------------------------------------------- #


def test_explicit_state_bootstrap_wins_over_default() -> None:
    """Пин: явный AppSpec.state_bootstrap уходит в orchestrator_config["initial_state"]
    собранного (НЕ запущенного) launcher'а КАК ЕСТЬ, дефолт (topology с ticker) не
    примешивается.

    Критерий по смыслу ("выигрывает у дефолта") непроверяем без факта, что дефолт СВОЁ
    что-то реально произвёл бы — отдельно зовём default_state_bootstrap на РЕАЛЬНОМ
    blueprint minimal_app и проверяем, что там ЕСТЬ ticker (иначе "выигрывает" было бы
    вакуумной проверкой — победа над пустотой). Это интерпретация теста, а не буквальный
    текст брифа — см. отчёт тестера.

    Провал сегодня: default_state_bootstrap не существует -> ImportError (на первой строке
    импорта, до сборки launcher'а).
    """
    from multiprocess_framework.modules.app_module import (
        AppSpec,
        ManifestStore,
        build_app,
        default_blueprint_loader,
        default_state_bootstrap,
    )

    # Факт "дефолт реально сеет ticker" — иначе "явный выигрывает у дефолта" ничего не
    # доказывает (дефолт мог быть пустышкой). Использует default_state_bootstrap САМ ПО
    # СЕБЕ, не как источник ожидаемого значения ниже (то — литерал).
    manifest = ManifestStore(_MINIMAL_APP_YAML).load()
    blueprint = default_blueprint_loader(manifest)
    default_topology = default_state_bootstrap(blueprint)
    assert _TICKER in default_topology.get("processes", {}), (
        f"default_state_bootstrap(minimal_app) не содержит {_TICKER!r} — критерий "
        f"'явный хук выигрывает у дефолта' непроверяем без этого факта: {default_topology!r}"
    )

    def _marker_hook(_blueprint: dict) -> dict:
        return {"processes": {"marker": {"config": {}, "state": {"status": "stopped"}}}}

    spec = AppSpec(manifest_path=_MINIMAL_APP_YAML, state_bootstrap=_marker_hook)
    launcher = build_app(spec)  # build_app, не run_app — без запуска процессов (TRAPS п.2)

    # Приватный атрибут SystemLauncher — единственное место, где посев виден ДО spawn
    # (builder.py:283-293 кладёт initial_state в orchestrator_config; потребитель —
    # child-side GenericProcessManagerApp._setup_state_store через self.get_config,
    # недоступно без запуска). Подтверждено живым вызовом build_app() с этим же spec —
    # см. отчёт тестера, "что интерпретировал".
    orchestrator_config = getattr(launcher, "_orchestrator_config", None)
    assert isinstance(orchestrator_config, dict), f"нет _orchestrator_config на launcher'е: {launcher!r}"
    seeded = orchestrator_config.get("initial_state")

    assert seeded == {"processes": {"marker": {"config": {}, "state": {"status": "stopped"}}}}, (
        f"посев не равен результату явного хука: {seeded!r}"
    )
    assert _TICKER not in (seeded or {}).get("processes", {}), (
        f"посев неожиданно содержит {_TICKER!r} (топология дефолта просочилась мимо явного хука): {seeded!r}"
    )
