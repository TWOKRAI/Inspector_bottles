# -*- coding: utf-8 -*-
"""Авторские hazard-тесты ПРОВОДКИ процессных хуков (Task 1.1, C3).

Приёмка (``test_process_hooks_acceptance.py``, A7) сторожит счастливый путь:
``initialize()`` ставит, ``shutdown()`` снимает. Здесь — три опасности самой
проводки, которых у счастливого пути нет:

* ``initialize()`` НЕ зовёт ``shutdown()`` на своём провале — он возвращает
  ``False``. Значит хуки, поставленные в ``_apply_managers_bundle``, пережили бы
  непонявшийся процесс, а слот интерпретатора переживает объект;
* ``shutdown()`` зовут дважды (сам процесс, супервизор, тестовая уборка) — снятие
  обязано быть идемпотентным, иначе второй проход вернул бы в слот значение
  позапрошлой эпохи;
* ``report_error(**fields)`` процесса обязан довезти адрес потока до записи в
  сторе на РЕАЛЬНЫХ менеджерах: фейк тестера держит эту дорогу сам
  (``error_manager.track_error`` напрямую), и на нём проводка
  ``HealthState.report_error(**fields)`` не проверяется вовсе.
"""

from __future__ import annotations

import sys
import threading
import uuid
import warnings
from unittest.mock import Mock

import pytest

from multiprocess_framework.modules.error_module.core.error_manager import ErrorManager
from multiprocess_framework.modules.process_module.core.process_module import ProcessModule
from multiprocess_framework.modules.process_module.managers.observability_wiring import wire_observability_store


@pytest.fixture(autouse=True)
def _restore_global_hooks():
    """Страховка поверх штатного снятия: слоты возвращаются независимо от исхода."""
    prev_threading = threading.excepthook
    prev_sys = sys.excepthook
    prev_warn = warnings.showwarning
    yield
    threading.excepthook = prev_threading
    sys.excepthook = prev_sys
    warnings.showwarning = prev_warn


def _mock_shared_resources():
    """Тот же мок, что в test_process_lifecycle.py / приёмке A7."""
    sr = Mock()
    sr.get_process_data = Mock(return_value=None)
    sr.queue_registry = None
    sr.memory_manager = None
    sr.event_manager = Mock()
    sr.event_manager.set_router_manager = Mock()
    sr.process_state_registry = Mock()
    sr.process_state_registry.get_process_names = Mock(return_value=[])
    sr.process_state_registry.register_process = Mock(return_value=True)
    sr.process_state_registry.update_state = Mock(return_value=True)
    return sr


class TestFailedInitializeDoesNotLeakHooks:
    def test_hooks_are_removed_when_initialize_fails_after_managers(self, monkeypatch) -> None:
        """Провал подъёма ПОСЛЕ установки хуков не оставляет слоты занятыми.

        Слом ставится в ``_init_communication`` — первый шаг ПОСЛЕ
        ``_init_managers`` (то есть после установки). Ветка ``except`` в
        ``initialize()`` возвращает False и никого больше не зовёт: без явного
        снятия три слота процесса, который не поднялся, остались бы занятыми
        объектом с полуразобранным адресатом доставки.
        """
        prev_threading = threading.excepthook
        prev_sys = sys.excepthook
        prev_warn = warnings.showwarning

        def _boom(self) -> None:
            raise RuntimeError("слом проводки после подъёма менеджеров")

        monkeypatch.setattr(ProcessModule, "_init_communication", _boom)

        process = ProcessModule("hook_leak_probe", shared_resources=_mock_shared_resources(), config={})
        assert process.initialize() is False

        assert threading.excepthook is prev_threading, "хуки пережили провалившийся initialize()"
        assert sys.excepthook is prev_sys
        assert warnings.showwarning is prev_warn
        assert process._process_hooks is None


class TestDoubleShutdown:
    def test_second_shutdown_is_a_no_op_for_hooks(self) -> None:
        """Второй ``shutdown()`` не трогает слоты.

        Опасность конкретная: снятие «вслепую» (присвоить сохранённое значение,
        не спросив, наше ли в слоте) на втором проходе вернуло бы значение
        позапрошлой эпохи. Проверяется тем, что между проходами слот занимает
        посторонний объект — и он обязан уцелеть.
        """
        prev_threading = threading.excepthook

        process = ProcessModule("hook_double_shutdown", shared_resources=_mock_shared_resources(), config={})
        assert process.initialize() is True
        assert process.shutdown() is True
        assert threading.excepthook is prev_threading

        def _foreign(args) -> None:
            return None

        threading.excepthook = _foreign
        assert process.shutdown() is True
        assert threading.excepthook is _foreign, "повторный останов снёс чужой хук"


class TestProcessReportErrorCarriesFields:
    def test_fields_reach_the_store_record_through_real_managers(self, tmp_path) -> None:
        """``ProcessModule.report_error(**fields)`` довозит адрес потока до записи.

        Дорога длинная и вся из чужих звеньев: ``report_error`` →
        ``HealthState.report_error(**fields)`` → ``_safe_track`` →
        ``ObservableMixin._track_error`` → ``ErrorManager.track_error`` →
        ``log_exception`` → tap → стор. Приёмка A1 её НЕ проверяет: фейк тестера
        зовёт ``track_error`` сам, минуя health. Порвись любое звено — запись
        осталась бы, потеряв ровно то, ради чего задача заведена: где именно
        упало.
        """
        config = {
            "app_name": "wiring_error",
            "log_directory": str(tmp_path),
            "enable_batching": False,
            "modules": {},
            "channels": {"a": {"type": "file", "enabled": True, "file_path": str(tmp_path / "wiring.log")}},
            "scopes": {
                "SYSTEM": {"channels": ["a"]},
                "BUSINESS": {"channels": ["a"]},
                "DEBUG": {"channels": ["a"]},
            },
        }
        error_mgr = ErrorManager(manager_name="wiring-error", config=config)
        error_mgr.initialize()
        store, _taps = wire_observability_store(
            error_mgr, None, db_path=str(tmp_path / "obs_wiring.db"), process="wiring"
        )
        process = ProcessModule("wiring_probe", shared_resources=None, config={})
        process.register_manager("error", error_mgr, enabled=True)
        try:
            message = f"wiring-{uuid.uuid4().hex}"
            process.report_error(
                RuntimeError(message),
                context="thread:wiring-worker",
                thread="wiring-worker",
                traceback="Traceback (most recent call last):\n  _probe\n",
                hook="threading.excepthook",
            )

            rows = [r for r in store.list_records(kind="error") if message in r["message"]]
            assert len(rows) == 1, f"ожидалась одна запись с {message!r}, получено {len(rows)}"
            inner = rows[0]["extra"].get("context", {})
            assert inner.get("thread") == "wiring-worker", f"extra.context = {inner}"
            assert inner.get("hook") == "threading.excepthook", f"extra.context = {inner}"
            assert "_probe" in (inner.get("traceback") or ""), f"extra.context = {inner}"
        finally:
            store.close()
            error_mgr.shutdown()
