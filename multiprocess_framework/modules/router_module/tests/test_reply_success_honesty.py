# -*- coding: utf-8 -*-
"""Конверт-ответ не должен рапортовать успех на провалившейся команде.

Регресс, пойманный живьём 2026-07-21: авто-reply в ``_dispatch_command`` звал
``reply_to_request(processed, result)``, оставляя ``success=True`` по умолчанию.
В итоге на несуществующую команду приходило::

    {"success": true, "result": {"status": "error",
     "reason": "No handler for key 'introspect.capabilities'"}}

Последствия были не косметические: проба готовности харнесса проверяет ровно
``success`` конверта — и потому объявляла систему готовой за 3.3 с ДО того, как
регистрировались ``introspect.*``. Всё, что спрашивало в этом окне (дамп
контракта, live-тесты backend_ctl), получало «нет хендлера» под видом успеха.

Инвариант: ``success`` конверта = «команда выполнена», а не «сообщение доехало».
"""

from __future__ import annotations

from multiprocess_framework.modules.router_module.core.router_manager import (
    RouterManager,
    _result_is_success,
)


class _FakeQR:
    def send_to_queue(self, process, qtype, msg, timeout: float = 0.0, on_evict=None):
        return True

    def get_queue(self, process, qtype):
        return None


class _CM:
    """CommandManager, отдающий заранее заданный результат."""

    def __init__(self, result):
        self._result = result

    def get_command_info(self, name):
        return None

    def handle_command(self, msg):
        return self._result


class _Process:
    def __init__(self, cm):
        self.name = "seg"
        self.command_manager = cm


class TestResultIsSuccess:
    def test_error_status_is_not_success(self):
        assert _result_is_success({"status": "error", "reason": "No handler for key 'x'"}) is False

    def test_explicit_false_success_is_not_success(self):
        assert _result_is_success({"success": False, "reason": "отказ"}) is False

    def test_ok_payload_is_success(self):
        assert _result_is_success({"success": True, "process": "seg"}) is True

    def test_plain_payload_without_markers_is_success(self):
        assert _result_is_success({"status": "ok", "value": 1}) is True

    def test_non_dict_result_is_success(self):
        """Команда могла вернуть список/строку — это не признак отказа."""
        assert _result_is_success(["a", "b"]) is True
        assert _result_is_success(None) is True


class TestAutoReplyEnvelope:
    """Сквозная проверка: что реально уезжает инициатору."""

    @staticmethod
    def _capture(result):
        rm = RouterManager(manager_name="seg", queue_registry=_FakeQR())
        rm.process = _Process(_CM(result))
        sent: list = []
        rm.send = lambda msg: sent.append(msg)  # type: ignore[assignment]
        rm._dispatch_command(
            {
                "type": "command",
                "command": "introspect.capabilities",
                "sender": "backend_ctl",
                "request_id": "cid-1",
            }
        )
        return sent

    def test_missing_handler_replies_failure(self):
        sent = self._capture({"status": "error", "reason": "No handler for key 'introspect.capabilities'"})

        assert len(sent) == 1, "ответ инициатору обязан уйти (fail-loud, не silent drop)"
        assert sent[0]["success"] is False, "конверт не должен рапортовать успех на отсутствующей команде"
        assert sent[0]["result"]["status"] == "error"

    def test_successful_command_replies_success(self):
        sent = self._capture({"success": True, "process": "seg", "commands": []})

        assert len(sent) == 1
        assert sent[0]["success"] is True

    def test_no_correlation_id_stays_fire_and_forget(self):
        """Без correlation-id ответа нет вовсе — паритет с GUI-трафиком."""
        rm = RouterManager(manager_name="seg", queue_registry=_FakeQR())
        rm.process = _Process(_CM({"status": "error", "reason": "нет"}))
        sent: list = []
        rm.send = lambda msg: sent.append(msg)  # type: ignore[assignment]

        rm._dispatch_command({"type": "command", "command": "x", "sender": "gui"})

        assert sent == []
