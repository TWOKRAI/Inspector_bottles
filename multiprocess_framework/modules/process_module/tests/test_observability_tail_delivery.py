# -*- coding: utf-8 -*-
"""Ф6.х.5 — доставка ``observability.tail`` доказана, а не заявлена подпиской.

Корневая причина З-1 (три живых прогона: подписка «успешна», событий ноль):
порог forward-tap'ов был захардкожен ``"ERROR"`` без ручки — аудит-записи (INFO)
не проходили никогда; batch-путь пуст структурно (hub без владельцев-эмитентов).
Ни один прежний тест ДОСТАВКУ не проверял: batch-тесты набивали hub руками,
fake-тест выбрасывал ``min_level``, e2e не существовало.

Харнес: настоящий ``LoggerManager`` + настоящая проводка
``subscribe_observability_tail`` → ``wire_observability_forward`` →
``RecordForwardChannel``; фейковый только router (граница процесса) — по
образцу ``test_send_error_visibility``.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import Mock

import pytest

from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule


class _CapturingRouter:
    """Граница процесса: фиксирует send_async-пуши вместо отправки."""

    def __init__(self) -> None:
        self.pushed: List[Dict[str, Any]] = []

    def send_async(self, message: Dict[str, Any], priority: str = "normal") -> None:
        self.pushed.append(message)


def _real_logger(tmp_path) -> LoggerManager:
    config: Dict[str, Any] = {
        "app_name": "tail",
        "log_directory": str(tmp_path),
        "enable_batching": False,
        "modules": {},
        "channels": {"a": {"type": "file", "enabled": True, "file_path": str(tmp_path / "a.log")}},
        "scopes": {
            "SYSTEM": {"enabled": True, "min_level": "DEBUG", "channels": ["a"]},
            "BUSINESS": {"enabled": True, "min_level": "DEBUG", "channels": ["a"]},
            "DEBUG": {"enabled": True, "min_level": "DEBUG", "channels": ["a"]},
        },
    }
    mgr = LoggerManager(manager_name="TailProbe", config=config)
    mgr.initialize()
    return mgr


@pytest.fixture
def process_with_tail(tmp_path):
    """ProcessModule с реальным логгером, фейковым router'ом и живым hub-заглушкой."""
    process = ProcessModule("tail_process")
    router = _CapturingRouter()
    process.router_manager = router
    process.logger_manager = _real_logger(tmp_path)
    process.error_manager = None
    # Хаб нужен только как признак «подписка возможна» — batch-путь пуст
    # структурно (см. шапку record_forward_channel), проверяется tap-путь.
    process._observability_hub = Mock()
    try:
        yield process, router, process.logger_manager
    finally:
        process.unsubscribe_observability_tail(None)
        process.logger_manager.shutdown()


def _tail_pushes(router: _CapturingRouter) -> List[Dict[str, Any]]:
    return [m for m in router.pushed if m.get("command") == "observability.record"]


class TestLevelOpensTheTail:
    def test_info_record_is_delivered_when_subscriber_asks_info(self, process_with_tail) -> None:
        """Ф6.х.5: level=INFO — INFO-запись реального менеджера доезжает до пуша.

        Ровно сценарий живой приёмки 6.6: аудит-запись сегодняшнего стенда шла
        на INFO и вымирала на захардкоженном пороге ERROR.
        """
        process, router, logger = process_with_tail

        res = process.subscribe_observability_tail("backend_ctl.probe", level="INFO")
        assert res["success"] is True
        logger.info("аудит: sink console выключен", module="observability")

        pushes = _tail_pushes(router)
        assert pushes, "INFO-запись не доехала до подписчика — хвост снова молчит (З-1)"
        assert pushes[0]["targets"] == ["backend_ctl.probe"]

    def test_default_level_stays_error(self, process_with_tail) -> None:
        """Пара: дефолт БЕЗ level — прежнее поведение, INFO отсечён, ERROR проходит."""
        process, router, logger = process_with_tail

        res = process.subscribe_observability_tail("backend_ctl.probe")
        assert res["min_level"] == "ERROR"
        logger.info("рутина", module="unit")
        assert _tail_pushes(router) == [], "дефолтный порог перестал фильтровать INFO"

        logger.error("настоящая беда", module="unit")
        assert _tail_pushes(router), "ERROR обязан проходить и на дефолтном пороге"

    def test_subscription_answer_is_loud(self, process_with_tail) -> None:
        """Ф6.х.5б: ответ называет tap'ы, менеджеры и порог — как у log.tail.

        Молча-пустой ответ и был лицом З-1: «success» без единого слушателя.
        """
        process, _router, _logger = process_with_tail

        res = process.subscribe_observability_tail("backend_ctl.probe", level="INFO")

        assert res["min_level"] == "INFO"
        assert res["taps"], "в ответе нет tap'ов — подписчику нечем понять, слушает ли кто-то"
        assert res["managers"], "в ответе нет менеджеров-носителей tap'ов"


class TestCommandSeamPassesLevel:
    def test_command_handler_forwards_level_to_the_process(self) -> None:
        """Шов команды: observability.tail.subscribe прокидывает level в svc.

        Отдельно от доставки: обработчик — 2 строки, и потерять kwargs здесь
        значило бы вернуть захардкоженный дефолт при живой проводке ниже.
        """
        from multiprocess_framework.modules.process_module.commands.builtin_commands import (
            BuiltinCommands,
        )

        captured: Dict[str, Any] = {}

        class _Svc:
            name = "proc"

            def subscribe_observability_tail(self, subscriber: str, level: str = "ERROR") -> dict:
                captured["subscriber"] = subscriber
                captured["level"] = level
                return {"success": True}

        bc = BuiltinCommands.__new__(BuiltinCommands)
        bc._services = _Svc()

        res = bc._cmd_observability_tail_subscribe({"subscriber": "backend_ctl.x", "level": "info"})

        assert res == {"success": True}
        assert captured == {"subscriber": "backend_ctl.x", "level": "INFO"}, (
            "level не доехал до процесса или не нормализован"
        )
