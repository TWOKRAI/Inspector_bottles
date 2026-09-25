# -*- coding: utf-8 -*-
"""Live-приёмка Task 1b.5: команды ``service.*`` на хабе (RED, без implementation).

Сегодня ``service.list``/``service.status``/``service.start``/``service.stop`` неизвестны
``ProcessManager`` — хаб на них ответит unknown-command reply CommandManager'а. Тест бьёт
по живому бэкенду через ``backend_ctl send_command`` (не через GUI), тем же паттерном,
что ``test_recipe_service_live.py`` (Task 1b.1) и ``test_catalog_plugins_live.py``
(Task 1b.2a) — свой уникальный порт, конверт ``{"success", "result": <плоский>}`` (та же
ловушка docs/reviews/2026-09-24_gui-1b.1-green.md, п.2), позитивный acceptance (не
"not success" — то тривиально верно для ЛЮБОЙ незнакомой команды и не пинит контракт).

Утверждаем ПОЗИТИВНЫЙ acceptance из DESIGN-брифинга Task 1b.5:
  - ``service.list`` сразу после boot == множество имён локального
    ``service_module.scanner.discover(Services/)`` (тот же оракул-паттерн, что
    ``test_catalog_plugins_live.py::_local_discover_count`` использует для ``catalog.plugins``,
    но здесь сравниваем множество имён, а не только count).
  - start/status/stop на реальном сервисе из ``Services/`` (по литералу, обоснованному ниже).
  - Неизвестное имя -> {"success": False, "error": "unknown_service", ...}.
  - "Нет нового процесса в дереве" (DESIGN п.4) — проверяем СНИМКОМ ``system_overview()
    ["processes"]`` ДО и ПОСЛЕ всех service.*-вызовов: множества имён процессов равны.
    Снимок "до" — надёжнее ручного литерала полного дерева region_pipeline+base (camera_0/
    preprocessor/сплиттеры/gui/devices/…): он не рассыпется при будущей правке топологии
    рецепта, никак не связанной с Task 1b.5, а инвариант "service.* не спавнит процесс"
    проверяет ровно так же строго.

Открытый вопрос (см. отчёт тестировщика): какое ИМЯ сервиса реально лежит в ``Services/``
на момент GREEN — тест ниже берёт первое имя из локального discover (как
``test_recipe_service_live.py`` берёт ``expected_names[0]`` для рецептов), а не жёстко
зашитое "auth" из DESIGN-примера (DESIGN использует "auth" только как иллюстрацию формы
ответа, не гарантирует, что сервис с таким именем существует в ``Services/`` сегодня).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from backend_ctl.harness import BackendHarness
from backend_ctl.protocol import unwrap

_PORT = 7910  # уникальный порт этого модуля (вне 8860-8910 и 9800+ — заняты другими сессиями)


def _local_expected_names() -> set[str]:
    """Множество имён сервисов, которое найдёт ``scanner.discover(Services/)`` локально.

    Тот же ресолв, который (по DESIGN п.4) обязан использовать хаб при boot — оракул,
    не завязанный на ServiceHost/RemoteServiceManager (это код Task 1b.5, не он сам).
    """
    from multiprocess_framework.modules.service_module import scanner as scanner_module
    from multiprocess_framework.modules.service_module.registry import ServiceRegistry

    repo_root = Path(__file__).resolve().parents[2]
    services_dir = repo_root / "Services"

    registry = ServiceRegistry()
    registry.clear()
    scanner_module.discover(services_dir)
    return {entry.name for entry in registry.list()}


@pytest.fixture(scope="module")
def service_backend():
    """Headless-бэкенд на своём порту — фундамент (``with_base=True``), как в проде."""
    harness = BackendHarness(with_base=True, port=_PORT)
    drv = harness.start()
    try:
        yield drv
    finally:
        harness.stop()


@pytest.mark.harness_smoke
def test_service_commands_on_hub_live(service_backend) -> None:
    drv = service_backend

    expected_names = _local_expected_names()
    assert expected_names, "Services/ должен содержать хотя бы один service.py для этого теста"
    a_name = sorted(expected_names)[0]

    # --- снимок процессов ДО первого service.*-вызова -------------------------------
    overview_before = drv.system_overview(timeout=8.0)
    assert overview_before.get("success") is True, f"system_overview не success: {overview_before}"
    processes_before = set((overview_before.get("processes") or {}).keys())
    assert processes_before, "system_overview не увидел ни одного процесса — бэкенд не прогрет"

    # --- service.list сразу после boot: множество имён == локальный discover -------
    list_res = drv.send_command("ProcessManager", "service.list", {}, timeout=8.0)
    list_body = unwrap(list_res, leaf=True)
    assert list_body.get("success") is True, f"service.list не success: {list_res!r}"
    live_names = {s["name"] for s in list_body.get("services") or []}
    assert live_names == expected_names, (
        f"service.list на хабе вернул {sorted(live_names)}, "
        f"локальный discover(Services/) нашёл {sorted(expected_names)}"
    )

    # --- service.status на существующем имени ----------------------------------------
    status_res = drv.send_command("ProcessManager", "service.status", {"name": a_name}, timeout=8.0)
    status_body = unwrap(status_res, leaf=True)
    assert status_body.get("success") is True, f"service.status не success: {status_res!r}"
    assert status_body.get("name") == a_name, status_body
    assert isinstance(status_body.get("detail"), dict), status_body

    # --- service.start -> lifecycle running, повторный service.stop идемпотентен -----
    start_res = drv.send_command("ProcessManager", "service.start", {"name": a_name}, timeout=8.0)
    start_body = unwrap(start_res, leaf=True)
    assert start_body.get("success") is True, f"service.start не success: {start_res!r}"
    assert start_body.get("lifecycle") == "running", start_body

    stop_res = drv.send_command("ProcessManager", "service.stop", {"name": a_name}, timeout=8.0)
    stop_body = unwrap(stop_res, leaf=True)
    assert stop_body.get("success") is True, f"service.stop не success: {stop_res!r}"
    assert stop_body.get("lifecycle") == "stopped", stop_body

    stop_again_res = drv.send_command("ProcessManager", "service.stop", {"name": a_name}, timeout=8.0)
    stop_again_body = unwrap(stop_again_res, leaf=True)
    assert stop_again_body.get("success") is True, f"повторный service.stop не success: {stop_again_res!r}"
    assert stop_again_body.get("lifecycle") == "stopped", stop_again_body

    # --- неизвестное имя -> unknown_service --------------------------------------------
    unknown_res = drv.send_command(
        "ProcessManager", "service.status", {"name": "definitely-not-a-service"}, timeout=8.0
    )
    unknown_body = unwrap(unknown_res, leaf=True)
    assert unknown_body.get("success") is False, f"service.status с неизвестным именем должен отказать: {unknown_res!r}"
    assert unknown_body.get("error") == "unknown_service", unknown_body

    # --- снимок процессов ПОСЛЕ: ни один service.*-вызов не породил процесс -----------
    overview_after = drv.system_overview(timeout=8.0)
    assert overview_after.get("success") is True, f"system_overview не success: {overview_after}"
    processes_after = set((overview_after.get("processes") or {}).keys())
    assert processes_after == processes_before, (
        f"дерево процессов изменилось после service.*: было {sorted(processes_before)}, "
        f"стало {sorted(processes_after)} — DESIGN п.4 требует 'нет нового процесса'"
    )
