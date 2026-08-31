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
            "SYSTEM": {"channels": ["a"]},
            "BUSINESS": {"channels": ["a"]},
            "DEBUG": {"channels": ["a"]},
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

    def test_unknown_level_is_refused_instead_of_becoming_a_firehose(self, process_with_tail: Any) -> None:
        """Ф3.1: непонятое имя порога отвергается, а не открывает шлюз.

        До правки такой запрос отвечал ``success=true`` и эхом запрошенного
        уровня, а порог при этом получался «пропускать всё»: подписчик уходил
        уверенным, что подписан на ошибки, и получал каждую запись. Это второй
        путь входа имени уровня (первый — конфиг); чинить один из двух значило
        бы оставить дефект живым на соседней развилке.
        """
        process, _router, _logger = process_with_tail

        res = process.subscribe_observability_tail("backend_ctl.probe", level="ERROR!")

        assert res["success"] is False
        assert "ERROR!" in res["reason"]
        assert not process._observability_forwarders, "отвергнутая подписка не должна оставлять проводку"

    def test_foreign_spelling_of_a_level_is_accepted(self, process_with_tail: Any) -> None:
        """``WARN``/``FATAL`` — каноничные имена OTel, а не опечатки."""
        process, _router, _logger = process_with_tail

        res = process.subscribe_observability_tail("backend_ctl.probe", level="warn")

        assert res["success"] is True
        assert res["min_level"] == "WARNING"


class TestCommandSeamPassesLevel:
    """Шов команды — ЧЕРЕЗ реестр контрактов, а не мимо мидлвари (A1).

    Прежняя версия этих тестов подставляла самодельный ``_Svc``, чья сигнатура
    сама принимала ``level``. Тест был зелёным ровно потому, что дубль
    разошёлся с production-формой: контракт ``level`` запрещал, мидлварь
    отбрасывала бы ключ, а тест этого не видел — он жил НИЖЕ границы. Здесь
    вход сначала проходит контракт команды, и запрет поля убивает тест.
    """

    @staticmethod
    def _through_contract(command: str, payload: dict) -> dict:
        """Пропустить payload через реальную схему команды и вернуть очищенный вход.

        Это и есть граница: то, что схема не объявила, до хендлера не доедет
        (при ``FW_CONTRACTS_STRICT=1`` — вместе со всем сообщением).
        """
        from multiprocess_framework.modules.process_module.commands.command_contracts import (
            BUILTIN_COMMAND_CONTRACTS,
        )

        schema = BUILTIN_COMMAND_CONTRACTS[command]
        return schema(**payload).model_dump(exclude_none=True)

    def test_command_handler_forwards_level_to_the_process(self) -> None:
        from multiprocess_framework.modules.process_module.commands.builtin_commands import (
            BuiltinCommands,
        )

        captured: Dict[str, Any] = {}

        class _Svc:
            name = "proc"

            # Сигнатура — КОПИЯ production-формы ProcessModule.subscribe_observability_tail
            # (level: Optional[str] = None). Разойдётся продовая — тест внизу это поймает.
            def subscribe_observability_tail(self, subscriber: str, level=None, *, wholesale: bool = False) -> dict:
                captured["subscriber"] = subscriber
                captured["level"] = level
                return {"success": True}

        bc = BuiltinCommands.__new__(BuiltinCommands)
        bc._services = _Svc()

        args = self._through_contract(
            "observability.tail.subscribe",
            {"subscriber": "backend_ctl.x", "level": "info"},
        )
        res = bc._cmd_observability_tail_subscribe(args)

        assert res == {"success": True}
        assert captured == {"subscriber": "backend_ctl.x", "level": "INFO"}, (
            "level не пережил границу контракта или не нормализован"
        )

    def test_absent_level_reaches_the_process_as_none_not_as_error(self) -> None:
        """Дефолт живёт в ОДНОЙ позиции — у процесса, а не в хендлере.

        Подставь хендлер свой ``"ERROR"`` — и смена дефолта у процесса молча не
        доехала бы. Совпадение констант замаскировало бы это до первого изменения,
        поэтому проверяется именно ``None``, а не итоговый порог.
        """
        from multiprocess_framework.modules.process_module.commands.builtin_commands import (
            BuiltinCommands,
        )

        captured: Dict[str, Any] = {}

        class _Svc:
            name = "proc"

            def subscribe_observability_tail(self, subscriber: str, level=None, *, wholesale: bool = False) -> dict:
                captured["level"] = level
                return {"success": True}

        bc = BuiltinCommands.__new__(BuiltinCommands)
        bc._services = _Svc()

        args = self._through_contract("observability.tail.subscribe", {"subscriber": "x"})
        bc._cmd_observability_tail_subscribe(args)

        assert captured["level"] is None, "хендлер подставил собственный дефолт — вторая позиция той же константы"

    def test_scope_all_on_the_wire_reaches_the_process_as_wholesale(self) -> None:
        """Задача 5.6: шов «провод → механизм». **Найдено инъекцией K4.**

        Инъекция сняла чтение ``scope`` в хендлере — и НЕ покраснело ничего: сам
        механизм объединения покрыт тестами, брокер-маркер покрыт тестами, а звено
        между ними не сторожил никто. То есть блокер Н2-1 мог вернуться молча, и
        именно так он однажды и появился.
        """
        from multiprocess_framework.modules.process_module.commands.builtin_commands import (
            BuiltinCommands,
        )

        captured: Dict[str, Any] = {}

        class _Svc:
            name = "proc"

            def subscribe_observability_tail(self, subscriber: str, level=None, *, wholesale: bool = False) -> dict:
                captured["wholesale"] = wholesale
                return {"success": True}

            def unsubscribe_observability_tail(self, subscriber=None, *, wholesale: bool = False) -> dict:
                captured["unsub_wholesale"] = wholesale
                return {"success": True}

        bc = BuiltinCommands.__new__(BuiltinCommands)
        bc._services = _Svc()

        bc._cmd_observability_tail_subscribe(
            self._through_contract("observability.tail.subscribe", {"subscriber": "x", "scope": "all"})
        )
        assert captured["wholesale"] is True, "маркер оптовости не доехал до процесса"

        # Пара: без маркера подписка ПРИЦЕЛЬНАЯ — иначе всё стало бы оптовым и
        # защита прицельного порога не срабатывала бы никогда.
        bc._cmd_observability_tail_subscribe(
            self._through_contract("observability.tail.subscribe", {"subscriber": "x"})
        )
        assert captured["wholesale"] is False, "подписка без маркера объявлена оптовой"

        # Тот же шов у снятия — вторая половина симметрии (Н2-2).
        bc._cmd_observability_tail_unsubscribe(
            self._through_contract("observability.tail.unsubscribe", {"subscriber": "x", "scope": "all"})
        )
        assert captured["unsub_wholesale"] is True, "маркер оптовости не доехал до снятия"

    def test_the_fake_signature_still_matches_production(self) -> None:
        """Дубль обязан сверяться с оригиналом, иначе он проверяет сам себя.

        Прецедент: приватная копия фикстуры разошлась с conftest молча, и девять
        красных жили как «не наш» долг. Здесь дубль узкий (одна сигнатура), но
        сверка всё равно явная.
        """
        import inspect

        from multiprocess_framework.modules.process_module.core.process_module import (
            ProcessModule,
        )

        sig = inspect.signature(ProcessModule.subscribe_observability_tail)
        assert list(sig.parameters) == ["self", "subscriber", "level", "wholesale"]
        assert sig.parameters["level"].default is None, (
            "production-дефолт уровня переехал — дубль в тестах выше устарел"
        )
