# -*- coding: utf-8 -*-
"""Независимая приёмка контракта ``DeviceHubClient.request()`` — конверт-ответ.

Задача (line-sim, фикс после Task 2.3b): живой ответ процесса на командный
запрос — конверт, который строит ``RouterManager.reply_to_request``:
верхнеуровневый ``success: bool`` и верхнеуровневый ``result: <что вернул
хендлер>`` (БЕЗ ключа ``data``). Сегодня (на этом коммите, ДО фикса) каждое
поле ``result`` теряется — вызывающий получает голый ``{"status": "ok"}``.
Контракт `.request()` — по брифу оркестратора (секция DESIGN), дословно:

- успех, хендлер вернул dict БЕЗ ``status`` -> ``{"status": "ok", **result}``.
- успех, хендлер вернул dict С ``status`` -> тот dict как есть.
- хендлер вернул ``{"status":"error","message":M}`` -> вызывающий получает
  ``status == "error"`` и ``message == M`` (настоящий текст), при любом
  ``success`` конверта.
- транспортный отказ (роутер вернул ``{"success": False, "error": "timeout"}``)
  -> ``{"status":"error","message":"timeout"}``.
- хендлер вернул не-dict (например 42) -> ``{"status":"ok","result":42}``.

ЧЕСТНОЕ РАСКРЫТИЕ УТЕЧКИ (по правилу проекта — раскрывать громко, не молчать):
при подготовке этого файла тестер читал ``Plugins/hub/device_hub/client.py``
инструментом ``Read`` (диапазон строк 1-100), чтобы увидеть ТОЛЬКО сигнатуры
``DeviceHubClient.__init__``/``.request()`` (это разрешено брифом). ``Read``
не умеет резать файл по функциям — в тот же вызов целиком попала запрещённая
``_normalize_response`` (её тело и докстринг, строки 17-46), хотя бриф прямо
называл её форбидден. Тестер это заметил и увидел ТЕКУЩУЮ реализацию: она
читает ``raw.get("data", {})``, а не верхнеуровневый ``result`` — то есть
именно тот баг, что уже был описан словами в DESIGN брифа («сегодня каждое
поле result теряется»). Ни одно ожидаемое значение и ни один сценарий ниже НЕ
подобраны под увиденную реализацию — все взяты дословно из секции REDS брифа
(литералы заданы оркестратором до чтения). Степень вреда независимости —
предмет решения ревьюера/лида, не тестера; подробности — в финальном отчёте.

Конверты для успешных сценариев строит РЕАЛЬНЫЙ
``RouterManager.reply_to_request`` (не hand-written dict) — через
``_FakeSendRouter``, минимальный неинициализированный подкласс
``RouterManager``, у которого ``send()`` эхом возвращает построенный конверт
(вместо реальной отправки). Транспортный таймаут (тест 4) — единственное
исключение по брифу: это НЕ конверт ``reply_to_request``, а то, что сам
``router_manager.request()`` возвращает при отказе транспорта, поэтому он
написан руками.
"""

from __future__ import annotations

import threading
import urllib.request
from types import SimpleNamespace
from typing import Any

import pytest

from multiprocess_framework.modules.router_module.core.router_manager import RouterManager
from Plugins.hub.device_hub.client import DeviceHubClient

pytestmark = pytest.mark.timeout(30)


# ------------------------------------------------------------------ #
# Конверт reply_to_request на минимальном объекте (без тяжёлого __init__)
# ------------------------------------------------------------------ #


class _FakeSendRouter(RouterManager):
    """Подкласс ``RouterManager`` БЕЗ вызова тяжёлого ``__init__`` (AsyncSender и т.п.).

    ``reply_to_request`` (реальный, унаследованный метод) трогает только
    ``self.process``, ``self.router_id``, ``self.send`` и статик-метод
    ``self._extract_correlation_id`` — все они здесь заданы вручную.
    ``send()`` не отправляет ничего — эхом отдаёт построенный конверт, чтобы
    тест мог его забрать как есть.
    """

    def __init__(self) -> None:  # noqa: super().__init__ намеренно не вызван
        self.process = None
        self.router_id = "test-router"

    def send(self, message: dict) -> dict:
        return message


def _reply_envelope(result: Any, success: bool) -> dict:
    """Построить РЕАЛЬНЫЙ конверт-ответ через ``RouterManager.reply_to_request``."""
    router = _FakeSendRouter()
    request_msg = {"request_id": "req-1", "reply_to": "test-caller"}
    envelope = router.reply_to_request(request_msg, result, success=success)
    assert envelope is not None, "reply_to_request вернул None — request_msg без адресата?"
    return envelope


def _client_with_response(response: dict) -> DeviceHubClient:
    """``DeviceHubClient`` на фейковом ctx, чей router_manager.request() отдаёт response."""
    ctx = SimpleNamespace(
        router_manager=SimpleNamespace(request=lambda msg, timeout=None: response),
        process_name="tester",
    )
    return DeviceHubClient(ctx, target_process="robot")


# ------------------------------------------------------------------ #
# REDS 1-5 — контракт .request()
# ------------------------------------------------------------------ #


def test_belt_status_like_result_preserves_fields_without_status_key():
    """REDS 1: результат belt.status (без ``status``) -> все поля сохранены, status=ok."""
    result = {"ok": True, "run": True, "freq_hz": 50.0, "mm_s": 101.1311, "encoder": 3899403}
    envelope = _reply_envelope(result, success=True)
    client = _client_with_response(envelope)

    resp = client.request("belt.status", {})

    assert resp["status"] == "ok"
    assert resp["encoder"] == 3899403
    assert resp["run"] is True
    assert resp["freq_hz"] == pytest.approx(50.0)
    assert resp["mm_s"] == pytest.approx(101.1311)


def test_result_with_status_ok_and_payload_preserves_payload():
    """REDS 2: результат уже с ``status: ok`` + полезная нагрузка -> нагрузка сохранена."""
    result = {"status": "ok", "jobs": 3}
    envelope = _reply_envelope(result, success=True)
    client = _client_with_response(envelope)

    resp = client.request("robot.jobs", {})

    assert resp["status"] == "ok"
    assert resp["jobs"] == 3


def test_handler_error_message_is_preserved_verbatim():
    """REDS 3: хендлер вернул error-статус -> вызывающий получает НАСТОЯЩИЙ текст message."""
    result = {"status": "error", "message": "robot_main not connected"}
    envelope = _reply_envelope(result, success=False)
    client = _client_with_response(envelope)

    resp = client.request("robot.jobs", {})

    assert resp["status"] == "error"
    assert resp["message"] == "robot_main not connected"


def test_transport_timeout_becomes_error_with_literal_message():
    """REDS 4: транспортный таймаут роутера -> {"status":"error","message":"timeout"}.

    Hand-written по брифу: это НЕ конверт reply_to_request, а собственный
    возврат ``router_manager.request()`` при отказе транспорта.
    """
    transport_failure = {"success": False, "error": "timeout"}
    client = _client_with_response(transport_failure)

    resp = client.request("belt.status", {})

    assert resp["status"] == "error"
    assert resp["message"] == "timeout"


def test_non_dict_result_is_wrapped_under_result_key():
    """REDS 5: хендлер вернул не-dict (42) -> {"status":"ok","result":42}."""
    envelope = _reply_envelope(42, success=True)
    client = _client_with_response(envelope)

    resp = client.request("robot.raw_value", {})

    assert resp["status"] == "ok"
    assert resp["result"] == 42


# ------------------------------------------------------------------ #
# REDS 6 — сквозная проводка пульта (реальные объекты, HTTP)
# ------------------------------------------------------------------ #


def test_pult_web_api_status_exposes_encoder_via_real_client():
    """REDS 6: реальный PultWebPlugin + реальный DeviceHubClient -> GET /api/status.

    Никакого monkeypatch DeviceHubClient — фейковый только router_manager.request()
    на уровне ctx (единственный внешний шов у DeviceHubClient). Порт 0 —
    ОС выдаёт свободный, живой стенд (8091/8092/8766/5021) не трогаем.
    """
    from Plugins.sim.pult_web.plugin import PultWebPlugin

    encoder_value = 3899403
    result = {"ok": True, "run": True, "freq_hz": 50.0, "mm_s": 101.1311, "encoder": encoder_value}
    envelope = _reply_envelope(result, success=True)

    ctx = SimpleNamespace(
        config={"host": "127.0.0.1", "port": 0, "timeout_s": 2.0},
        process_name="test_pult",
        router_manager=SimpleNamespace(request=lambda msg, timeout=None: envelope),
        health=SimpleNamespace(report_error=lambda *a, **k: None),
        log_info=lambda *a, **k: None,
    )

    plugin = PultWebPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    try:
        assert plugin._server is not None, "сервер не поднялся на свободном порту"
        port = plugin._server.server_address[1]

        body_holder: dict[str, Any] = {}
        error_holder: dict[str, Exception] = {}

        def _do_request() -> None:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5) as resp:
                    body_holder["status"] = resp.status
                    body_holder["json"] = resp.read()
            except Exception as exc:  # noqa: BLE001 - под join-дедлайном ниже
                error_holder["exc"] = exc

        thread = threading.Thread(target=_do_request, daemon=True)
        thread.start()
        thread.join(timeout=10.0)

        assert not thread.is_alive(), "GET /api/status завис — daemon-поток не завершился за 10с"
        assert "exc" not in error_holder, f"HTTP-запрос упал: {error_holder.get('exc')}"
        assert body_holder.get("status") == 200

        import json

        payload = json.loads(body_holder["json"])
        assert payload.get("encoder") == encoder_value
    finally:
        plugin.shutdown(ctx)
