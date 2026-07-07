# -*- coding: utf-8 -*-
"""Live-тесты Ф1 Task 1.4/1.5: observability control plane через driver.

harness_smoke (headless_backend, session-фикстура):
  - 1.4: config.reload с inline-override меняет уровень логгера процесса на лету;
  - 1.5: подписка log_tail(level=ERROR) → провокация ERROR (команда к несуществующему
    плагину) → LogRecord приходит в driver.events() через мост 1.1b.
"""

from __future__ import annotations

import pytest


@pytest.mark.harness_smoke
def test_config_reload_changes_log_level_live(headless_backend) -> None:
    """1.4: driver.config_reload меняет уровень логгера процесса на лету.

    Inline-override {log_level: DEBUG} идёт через тот же apply_observability_reconfigure,
    что и hot-reload watcher (единый reconfigure — конфликта нет). Ответ содержит
    применённый уровень.
    """
    drv = headless_backend
    res = drv.config_reload("preprocessor", observability={"log_level": "DEBUG"}, timeout=8.0)
    assert res.get("success") is True, f"config.reload не success: {res}"
    assert (res.get("applied") or {}).get("log_level") == "DEBUG", res

    # Вернуть уровень обратно (не влиять на соседние тесты сессии).
    drv.config_reload("preprocessor", observability={"log_level": "INFO"}, timeout=8.0)


@pytest.mark.harness_smoke
def test_log_tail_catches_error_live(headless_backend) -> None:
    """1.5: driver ловит ERROR процесса в events() через мост 1.1b.

    log_tail подписывает router-push sink (level≥ERROR) на logger процесса. Тейлим
    ProcessManager — процесс-ВЛАДЕЛЕЦ SocketChannel: мост 1.1b (_deliver_by_targets)
    доставляет targets=[backend_ctl] во внешний driver именно там, где канал
    зарегистрирован. Провокация ERROR: команда к несуществующему процессу
    (process.restart '__ghost__') → PM.log_error("No saved config") → push → events().

    Граница 1.5 (tail дочернего процесса не доходил до внешнего сокета) закрыта в 1.7
    relay'ем через хаб — см. test_log_tail_child_process_reaches_driver_via_relay ниже.
    """
    drv = headless_backend
    sub = drv.log_tail("ProcessManager", level="ERROR", timeout=8.0)
    assert sub.get("success") is True, f"log_tail подписка не success: {sub}"

    drv.events()  # осушить накопленное до провокации

    # Провокация ERROR в PM: рестарт несуществующего процесса → "No saved config".
    drv.system_command({"cmd": "process.restart", "process_name": "__ghost__"}, timeout=3.0)

    records = []
    for _ in range(5):
        for e in drv.events(timeout=2.0):
            if e.get("command") == "log.record":
                records.append(e)
        if records:
            break
    assert records, "LogRecord (ERROR) не дошёл до driver.events()"
    levels = {(e.get("data") or {}).get("record", {}).get("level") for e in records}
    assert "ERROR" in levels, f"ожидали ERROR среди {levels}"

    drv.log_untail("ProcessManager", timeout=8.0)  # снять подписку (гигиена сессии)


@pytest.mark.harness_smoke
def test_log_tail_child_process_reaches_driver_via_relay(headless_backend) -> None:
    """1.7: tail ДОЧЕРНЕГО процесса доходит до внешнего driver'а через relay (граница 1.5 закрыта).

    Цепочка: log_tail('preprocessor') ставит router-push sink в ребёнке → провокация
    ERROR (register_update с несуществующим полем → log_error PluginOrchestrator) →
    push targets=[backend_ctl] в router'е ребёнка НЕ доставляем (нет ни очереди, ни
    канала) → однократный relay билета хабу (router.relay) → PM доставляет своим
    router'ом через мост 1.1b → SocketChannel → driver.events().
    """
    drv = headless_backend
    sub = drv.log_tail("preprocessor", level="ERROR", timeout=8.0)
    assert sub.get("success") is True, f"log_tail подписка не success: {sub}"

    drv.events()  # осушить накопленное до провокации

    # Провокация ERROR в ребёнке: register_update по несуществующему полю регистра.
    # Команда fire-and-forget (manages_own_reply) — ответа не ждём, таймаут не диагноз.
    drv.send_command(
        "preprocessor",
        "register_update",
        {"register": "resize", "field": "__no_such_field__", "value": 1},
        timeout=2.0,
    )

    records = []
    for _ in range(5):
        for e in drv.events(timeout=2.0):
            if e.get("command") == "log.record" and (e.get("data") or {}).get("process") == "preprocessor":
                records.append(e)
        if records:
            break
    assert records, "LogRecord ребёнка не дошёл до driver.events() (relay через хаб)"
    levels = {(e.get("data") or {}).get("record", {}).get("level") for e in records}
    assert "ERROR" in levels, f"ожидали ERROR среди {levels}"

    drv.log_untail("preprocessor", timeout=8.0)  # гигиена сессии
