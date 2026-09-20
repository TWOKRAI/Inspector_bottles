"""Приёмочные тесты (RED, Ф1 Task 1.1) для ``apps/line_sim`` — второе приложение на
фреймворке, процесс ``robot`` держит ``SimRobotServer`` через плагин ``sim_robot_host``.

Независимый тестер, БЕЗ реализации (worktree на коммите до неё) — контракт ниже собран
из брифа lead'а, не из кода. Источник форм API — реальные модули: ``backend_ctl.harness``,
``backend_ctl.driver``, ``Services.robot_comm`` (образец — ``examples/minimal_app/tests/
test_ci_smoke.py`` и ``Services/robot_comm/tests/test_sim_e2e.py``).

Контракт (интерфейс, известный СЕЙЧАС — не executable, реализации нет):
  - ``apps/line_sim/app.yaml`` (+ ``pipeline.yaml``, ``run.py``) собирается
    ``multiprocess_framework.modules.app_module.build_app(...)`` как minimal_app;
  - процесс ``robot`` держит плагин ``Plugins.sim.robot_host.plugin.SimRobotHostPlugin``
    (``plugin_name: sim_robot_host``), конфиг ``host=127.0.0.1``, ``port=5021``,
    ``unit_id=2``, ``auto_start=true``;
  - команда ``sim_robot.status`` -> dict ``{running: bool, host, port, unit_id,
    writes_seen: int}``;
  - метрика ``sim_robot.writes``;
  - без ``pymodbus``: процесс ``robot`` живёт, плагин деградирует, "modbus" виден в
    ``errors.log`` процесса ``robot`` (под ``MULTIPROCESS_LOG_DIR``) либо в
    ``system_overview()["anomalies"]``;
  - ``apps/`` и ``Plugins/sim/`` не импортируют ``multiprocess_prototype``.

Сегодня ``apps/line_sim/app.yaml`` не существует -> ожидаем красный на этапе ФИКСТУРЫ
(``build_app`` бросит ``FileNotFoundError``/аналог) для тестов 1-5. Тест 6 не зависит от
живой системы и падает своим ``assert`` (каталога ``Plugins/sim`` нет).

**Форма ``system_overview()`` НЕ зафиксирована брифом** (файл ``backend_ctl/overview.py``
не входил в список разрешённых для чтения) — ``_find_process_entry``/``_entry_is_running``
ниже намеренно терпимы к двум разумным формам (dict-по-имени и list-с-полем ``name``).
Это интерпретация, не факт; см. финальный отчёт тестера.
"""

from __future__ import annotations

import os
import re
import socket
import time
from pathlib import Path

import pytest

from backend_ctl.harness import BackendHarness
from Services.robot_comm.core.client import RobotClient
from Services.robot_comm.core.config import RobotConfig

# .../apps/line_sim/tests/<file> -> parents[1] = apps/line_sim.
_APP_DIR = Path(__file__).resolve().parents[1]
_APP_YAML = _APP_DIR / "app.yaml"

_MODBUS_PORT = 5021  # литерал контракта — НЕ выводить из кода под тестом
_ROBOT_PROCESS = "robot"
_STATUS_COMMAND = "sim_robot.status"
_WRITES_METRIC = "sim_robot.writes"
_ROBOT_HOST = "127.0.0.1"
_ROBOT_UNIT_ID = 2


def _free_port() -> int:
    """Свободный TCP-порт для backend_ctl (см. Services/robot_comm/tests/test_sim_e2e.py)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _assert_modbus_port_free() -> None:
    """5021 — литерал контракта, другой порт не выбираем при занятости (TEST RULES lead'а):
    падение с внятным сообщением, не тихий skip."""
    with socket.socket() as probe:
        probe.settimeout(0.2)
        try:
            probe.bind((_ROBOT_HOST, _MODBUS_PORT))
        except OSError as exc:
            pytest.fail(f"порт {_MODBUS_PORT} занят — {exc}")


def _result(res: dict) -> dict:
    """Развернуть result-конверт ответа (см. examples/minimal_app/tests/test_ci_smoke.py::_result)."""
    if isinstance(res, dict) and isinstance(res.get("result"), dict):
        return res["result"]
    return res if isinstance(res, dict) else {}


def _port_is_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _find_process_entry(overview: dict, name: str):
    """Найти запись процесса ``name`` в ``system_overview()``.

    Форма НЕ зафиксирована контрактом брифа (см. докстринг модуля) — проверяем два
    разумных варианта: ``{"processes": {name: {...}}}`` и ``{"processes": [{"name": ...}]}``.
    """
    processes = overview.get("processes") if isinstance(overview, dict) else None
    if isinstance(processes, dict):
        return processes.get(name)
    if isinstance(processes, list):
        for entry in processes:
            if isinstance(entry, dict) and entry.get("name") == name:
                return entry
    return None


def _entry_is_running(entry) -> bool:
    if not isinstance(entry, dict):
        return False
    for key in ("running", "is_running", "alive"):
        if key in entry:
            return bool(entry[key])
    status = entry.get("status")
    return isinstance(status, str) and status.lower() in ("running", "ok", "alive")


def _modbus_mentioned(*texts: str) -> bool:
    pattern = re.compile(r"modbus", re.IGNORECASE)
    return any(pattern.search(t) for t in texts if t)


def _errors_log_text(log_dir: Path, process: str) -> str:
    """Текст errors.log процесса под MULTIPROCESS_LOG_DIR. Отсутствие файла -> "" (не отказ:
    вторая проверка — anomalies — реальный якорь существования, см. критерий 5)."""
    path = log_dir / process / "errors.log"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _anomalies_text(overview: dict) -> str:
    anomalies = overview.get("anomalies") if isinstance(overview, dict) else None
    if not isinstance(anomalies, list):
        return ""
    return "\n".join(str(a) for a in anomalies)


def _write_missing_pymodbus_stub(tmp_path: Path) -> Path:
    """Фиктивный пакет ``pymodbus/__init__.py``, бросающий ``ImportError`` при импорте.

    Инъекция ДОЛЖНА доехать до ДОЧЕРНЕГО процесса (spawn): каталог кладём первым в
    PYTHONPATH env ДО сборки launcher'а — spawn-контекст читает env при старте потомка
    (sys.modules-инъекция в родителе до ребёнка НЕ доедет — TRAPS lead'а, п.2).
    """
    stub_root = tmp_path / "no_pymodbus"
    pkg_dir = stub_root / "pymodbus"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text(
        "raise ImportError('pymodbus intentionally unavailable for RED test "
        "(apps/line_sim/tests/test_f1_task11_acceptance.py)')\n",
        encoding="utf-8",
    )
    return stub_root


def _build_line_sim_launcher():
    from multiprocess_framework.modules.app_module import build_app

    return build_app(_APP_YAML)


@pytest.fixture
def line_sim_backend(tmp_path: Path):
    """Headless line_sim: свой порт backend_ctl + свой лог-каталог.

    Образец — ``examples/minimal_app/tests/test_ci_smoke.py::minimal_app_backend``.
    Ловушка (TRAPS lead'а, п.1): без своего ``MULTIPROCESS_LOG_DIR`` логи процесса
    ``robot`` уедут в ``logs/`` репозитория — каталог задаём ЯВНО до сборки launcher'а.

    Отдаёт тройку ``(harness, drv, log_dir)``: критерию 1 нужен сам ``harness`` для
    управляемого ``stop()`` внутри теста (проверка «порт закрылся после остановки»).
    """
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
        harness.stop()  # идемпотентен — тест критерия 1 мог уже сам звать stop()
        if prev_log is None:
            os.environ.pop("MULTIPROCESS_LOG_DIR", None)
        else:
            os.environ["MULTIPROCESS_LOG_DIR"] = prev_log


# --------------------------------------------------------------------------- #
# Критерий 1: приложение поднимается, порт 5021 слушает, закрывается со stop  #
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_app_boots_and_modbus_port_accepts(line_sim_backend) -> None:
    """Пин: SimRobotServer слушает 5021 пока harness жив; после harness.stop() порт закрыт за 5с.

    Провал сегодня: фикстура падает раньше тела (нет apps/line_sim/app.yaml). Провал у
    сломанной реализации: соединение к 5021 не удаётся за 10с ПОКА система поднята, ЛИБО
    порт всё ещё отвечает спустя 5с ПОСЛЕ harness.stop() (сокет/процесс не остановлен).
    """
    harness, _drv, _log_dir = line_sim_backend

    deadline = time.monotonic() + 10.0
    opened = False
    while time.monotonic() < deadline:
        if _port_is_open(_ROBOT_HOST, _MODBUS_PORT):
            opened = True
            break
        time.sleep(0.2)
    assert opened, f"порт {_MODBUS_PORT} не принял соединение за 10с — SimRobotServer не поднялся"

    harness.stop()

    deadline = time.monotonic() + 5.0
    closed = False
    while time.monotonic() < deadline:
        if not _port_is_open(_ROBOT_HOST, _MODBUS_PORT, timeout=0.5):
            closed = True
            break
        time.sleep(0.2)
    assert closed, f"порт {_MODBUS_PORT} всё ещё принимает соединения спустя 5с после harness.stop()"


# --------------------------------------------------------------------------- #
# Критерий 2: RobotClient коннектится и видит растущий энкодер                #
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_robot_client_reads_growing_encoder(line_sim_backend) -> None:
    """Пин: RobotClient.connect() -> True; энкодер строго растёт между двумя чтениями (≥0.5с).

    Провал сегодня: фикстура падает раньше тела. Провал у сломанной симуляции: connect()
    вернул не True, ЛИБО encoder не вырос за паузу (лента стоит/тик не идёт).
    """
    _harness, _drv, _log_dir = line_sim_backend

    client = RobotClient(RobotConfig(host=_ROBOT_HOST, port=_MODBUS_PORT, unit_id=_ROBOT_UNIT_ID))
    try:
        assert client.connect() is True, "RobotClient.connect() вернул не True — Modbus-сервер не отвечает"
        first = client.read_encoder()
        time.sleep(0.5)
        second = client.read_encoder()
        assert second > first, f"энкодер не вырос за 0.5с: first={first}, second={second}"
    finally:
        client.disconnect()


# --------------------------------------------------------------------------- #
# Критерий 3: backend_ctl видит процесс robot и его статус                    #
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_backend_ctl_sees_robot_and_status(line_sim_backend) -> None:
    """Пин: system_overview() видит robot running; sim_robot.status -> running=True, port=5021
    (+host/unit_id по конфигу брифа: 127.0.0.1 / 2).

    Провал сегодня: фикстура падает раньше тела. Провал у сломанной реализации: robot
    отсутствует/не running в overview, ИЛИ sim_robot.status не отдаёт заявленные поля.
    """
    _harness, drv, _log_dir = line_sim_backend

    overview = drv.system_overview()
    entry = _find_process_entry(overview, _ROBOT_PROCESS)
    assert entry is not None, f"процесс {_ROBOT_PROCESS!r} не найден в system_overview(): {overview!r}"
    assert _entry_is_running(entry), f"процесс {_ROBOT_PROCESS!r} не running в system_overview(): {entry!r}"

    status = _result(drv.send_command(_ROBOT_PROCESS, _STATUS_COMMAND))
    assert status.get("running") is True, f"sim_robot.status.running не True: {status!r}"
    assert status.get("port") == _MODBUS_PORT, f"sim_robot.status.port != {_MODBUS_PORT}: {status!r}"
    assert status.get("host") == _ROBOT_HOST, f"sim_robot.status.host != {_ROBOT_HOST!r}: {status!r}"
    assert status.get("unit_id") == _ROBOT_UNIT_ID, f"sim_robot.status.unit_id != {_ROBOT_UNIT_ID}: {status!r}"


# --------------------------------------------------------------------------- #
# Критерий 4: задание считается в статусе и в истории телеметрии              #
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(60)
def test_job_counts_writes_in_status_and_history(line_sim_backend) -> None:
    """Пин: после send_job(...) writes_seen >= 1 в статусе И history_query(metric=...) отдаёт
    >= 1 строку (в пределах 10с — батч записи, TRAPS lead'а п.3).

    Провал сегодня: фикстура падает раньше тела. Провал у сломанной реализации: writes_seen
    остаётся 0 после задания, ЛИБО метрика sim_robot.writes не долетает в history за 10с.
    """
    _harness, drv, _log_dir = line_sim_backend

    client = RobotClient(RobotConfig(host=_ROBOT_HOST, port=_MODBUS_PORT, unit_id=_ROBOT_UNIT_ID))
    try:
        assert client.connect() is True
        sent = client.send_job(75.0, -30.5, client.read_encoder())
        assert sent is True, "RobotClient.send_job(...) вернул не True"
    finally:
        client.disconnect()

    deadline = time.monotonic() + 10.0
    status: dict = {}
    while time.monotonic() < deadline:
        status = _result(drv.send_command(_ROBOT_PROCESS, _STATUS_COMMAND))
        writes_seen = status.get("writes_seen")
        if isinstance(writes_seen, int) and writes_seen >= 1:
            break
        time.sleep(0.5)
    writes_seen = status.get("writes_seen")
    assert isinstance(writes_seen, int) and writes_seen >= 1, (
        f"writes_seen не достиг >=1 за 10с после send_job: {status!r}"
    )

    deadline = time.monotonic() + 10.0
    history: dict = {}
    rows: list = []
    while time.monotonic() < deadline:
        history = drv.history_query(metric=_WRITES_METRIC, limit=50)
        raw_rows = history.get("rows") if isinstance(history, dict) else None
        rows = raw_rows if isinstance(raw_rows, list) else []
        if len(rows) >= 1:
            break
        time.sleep(1.0)
    assert len(rows) >= 1, f"history_query(metric={_WRITES_METRIC!r}) не отдал ни одной строки за 10с: {history!r}"


# --------------------------------------------------------------------------- #
# Критерий 5: без pymodbus плагин деградирует, процесс живёт (+контроль)      #
# --------------------------------------------------------------------------- #


@pytest.mark.timeout(120)
def test_without_pymodbus_plugin_errors_process_lives(tmp_path: Path) -> None:
    """Пин (пара прогонов): С pymodbus — 0 строк со словом "modbus" в плоскости ошибок
    (контроль); БЕЗ pymodbus (инъекция через PYTHONPATH до сборки) — >=1 строка со словом
    "modbus" в errors.log процесса robot либо в system_overview()["anomalies"], И процесс
    robot виден живым (не крашнулся).

    Провал сегодня: сборка line_sim не существует — фикстур здесь нет, харнесс падает прямо
    в теле теста на первом start(). Провал у сломанной деградации: "modbus" не найден нигде
    (плагин упал молча/не задета плоскость ошибок) ЛИБО процесс robot не отвечает.
    """
    # --- контроль: С pymodbus (baseline — модуль реально установлен в окружении теста) ---
    _assert_modbus_port_free()
    prev_log = os.environ.get("MULTIPROCESS_LOG_DIR")
    log_dir_ok = tmp_path / "log_with_pymodbus"
    log_dir_ok.mkdir()
    os.environ["MULTIPROCESS_LOG_DIR"] = str(log_dir_ok)
    harness_ok = BackendHarness(launcher_factory=_build_line_sim_launcher, port=_free_port())
    try:
        harness_ok.start()
        drv_ok = harness_ok.driver
        overview_ok = drv_ok.system_overview()
        errors_text_ok = _errors_log_text(log_dir_ok, _ROBOT_PROCESS)
        assert not _modbus_mentioned(errors_text_ok, _anomalies_text(overview_ok)), (
            f"с установленным pymodbus неожиданно есть упоминание 'modbus' в плоскости ошибок: "
            f"errors.log={errors_text_ok!r}, anomalies={_anomalies_text(overview_ok)!r}"
        )
    finally:
        harness_ok.stop()
        if prev_log is None:
            os.environ.pop("MULTIPROCESS_LOG_DIR", None)
        else:
            os.environ["MULTIPROCESS_LOG_DIR"] = prev_log

    # --- целевой прогон: БЕЗ pymodbus (фиктивный пакет первым в PYTHONPATH) ---
    _assert_modbus_port_free()
    stub_root = _write_missing_pymodbus_stub(tmp_path)
    prev_pythonpath = os.environ.get("PYTHONPATH", "")
    prev_log2 = os.environ.get("MULTIPROCESS_LOG_DIR")
    log_dir_bad = tmp_path / "log_without_pymodbus"
    log_dir_bad.mkdir()
    os.environ["MULTIPROCESS_LOG_DIR"] = str(log_dir_bad)
    os.environ["PYTHONPATH"] = os.pathsep.join([str(stub_root), prev_pythonpath]) if prev_pythonpath else str(stub_root)
    harness_bad = BackendHarness(launcher_factory=_build_line_sim_launcher, port=_free_port())
    try:
        harness_bad.start()
        drv_bad = harness_bad.driver

        deadline = time.monotonic() + 10.0
        overview_bad: dict = {}
        errors_text_bad = ""
        found = False
        while time.monotonic() < deadline and not found:
            overview_bad = drv_bad.system_overview()
            errors_text_bad = _errors_log_text(log_dir_bad, _ROBOT_PROCESS)
            found = _modbus_mentioned(errors_text_bad, _anomalies_text(overview_bad))
            if not found:
                time.sleep(0.5)

        assert found, (
            f"без pymodbus ожидали упоминание 'modbus' в errors.log процесса robot или в "
            f"system_overview()['anomalies'] за 10с — не нашли ни там, ни там: "
            f"errors.log={errors_text_bad!r}, anomalies={_anomalies_text(overview_bad)!r}"
        )

        entry = _find_process_entry(overview_bad, _ROBOT_PROCESS)
        status_res = drv_bad.introspect_status(_ROBOT_PROCESS)
        status_ok = isinstance(status_res, dict) and status_res.get("success") is not False
        assert entry is not None or status_ok, (
            f"процесс {_ROBOT_PROCESS!r} не виден живым без pymodbus: "
            f"overview={overview_bad!r}, introspect_status={status_res!r}"
        )
    finally:
        harness_bad.stop()
        os.environ["PYTHONPATH"] = prev_pythonpath
        if prev_log2 is None:
            os.environ.pop("MULTIPROCESS_LOG_DIR", None)
        else:
            os.environ["MULTIPROCESS_LOG_DIR"] = prev_log2


# --------------------------------------------------------------------------- #
# Критерий 6: apps/ и Plugins/sim/ не импортируют multiprocess_prototype      #
# --------------------------------------------------------------------------- #


def _find_prototype_imports(root: Path) -> list[str]:
    """Просканировать *.py под root на "multiprocess_prototype" построчно (grep-подобно)."""
    hits: list[str] = []
    pattern = re.compile(r"multiprocess_prototype")
    for path in sorted(root.rglob("*.py")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                hits.append(f"{path}:{lineno}: {line.strip()}")
    return hits


def test_no_prototype_imports_in_apps_and_plugins_sim() -> None:
    """Пин: apps/ и Plugins/sim/ не импортируют multiprocess_prototype (слоение зависимостей,
    правило 9 корневого CLAUDE.md).

    Провал сегодня: каталог Plugins/sim/ отсутствует -> КРАСНЫЙ с внятным сообщением, не
    skip (apps/ уже существует — создан этой же задачей как пустой пакет). Провал у
    сломанной реализации: найдена хотя бы одна строка с "multiprocess_prototype".
    """
    repo_root = Path(__file__).resolve().parents[3]
    apps_dir = repo_root / "apps"
    plugins_sim_dir = repo_root / "Plugins" / "sim"

    assert apps_dir.is_dir(), f"каталог {apps_dir} отсутствует — критерий непроверяем, это красный, не skip"
    assert plugins_sim_dir.is_dir(), (
        f"каталог {plugins_sim_dir} отсутствует — критерий непроверяем, это красный, не skip"
    )

    hits = _find_prototype_imports(apps_dir) + _find_prototype_imports(plugins_sim_dir)
    assert hits == [], f"найдены упоминания multiprocess_prototype: {hits}"
