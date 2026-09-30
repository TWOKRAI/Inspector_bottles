# -*- coding: utf-8 -*-
"""Независимая слепая приёмка R-4 — ``DeviceHubClient.request()`` не теряет поля ошибки.

Дефект: хендлер целевого процесса вернул
``{"status": "error", "code": "conflict", "message": "rev mismatch", "current_rev": 7}``;
роутер завернул это РЕАЛЬНЫМ ``RouterManager.reply_to_request(..., success=False)`` в
``{"type": "response", ..., "success": False, "result": <тот dict>}``; клиент отдаёт
вызывающему только ``{"status": "error", "message": ...}`` — ``code`` и ``current_rev`` пропали.

Критерии (литералы заданы лидом, значения не выводятся из кода под тестом):

- A. conflict-результат + success=False -> status "error", code "conflict", current_rev 7,
  message "rev mismatch".
- B. bad_request + русский message -> code "bad_request", message без искажений.
- C. транспортный отказ ``{"success": False, "error": "timeout"}`` -> РОВНО
  ``{"status": "error", "message": "timeout"}`` (никаких лишних ключей).
- D. success=False всегда даёт status "error", даже если в dict хендлера нет ``status``.
- E. dict ошибки без ``message``, но с ``reason`` -> message == текст ``reason``; ``code`` сохранён.
- H. успешный конверт с результатом ``{"rev": 3}`` -> ``{"status": "ok", "rev": 3}``.

Конверты строит РЕАЛЬНЫЙ ``reply_to_request`` (``_FakeSendRouter`` из соседней приёмки конверта);
единственный руками написанный ответ — транспортный отказ (C): его формирует не
``reply_to_request``, а сам ``router.request()``.

Слепота: тело ``_normalize_response`` в ``client.py`` не читалось (файл читался только с
``request()`` и ниже — ``sed -n 60,135p``).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from Plugins.hub.device_hub.client import DeviceHubClient
from Plugins.hub.device_hub.tests.test_reply_envelope_acceptance import _FakeSendRouter

pytestmark = pytest.mark.timeout(30)


def _reply_envelope(result: Any, success: bool) -> dict:
    """РЕАЛЬНЫЙ конверт-ответ от ``RouterManager.reply_to_request``."""
    envelope = _FakeSendRouter().reply_to_request(
        {"request_id": "req-1", "reply_to": "test-caller"}, result, success=success
    )
    assert envelope is not None, "reply_to_request вернул None — request_msg без адресата?"
    return envelope


def _request_via(response: dict) -> dict:
    """РЕАЛЬНЫЙ ``DeviceHubClient`` над заглушкой роутера, чей ``request()`` отдаёт ``response``."""
    ctx = SimpleNamespace(
        router_manager=SimpleNamespace(request=lambda msg, timeout=None: response),
        process_name="tester",
    )
    return DeviceHubClient(ctx, target_process="scene").request("preset.commit", {})


_CONFLICT = {"status": "error", "code": "conflict", "message": "rev mismatch", "current_rev": 7}


# --- A ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "key, expected",
    [
        pytest.param("status", "error", id="status"),
        pytest.param("code", "conflict", id="code"),
        pytest.param("current_rev", 7, id="current_rev"),
        pytest.param("message", "rev mismatch", id="message"),
    ],
)
def test_a_conflict_error_fields_survive(key: str, expected: Any) -> None:
    """A: каждое поле ответа-конфликта доходит до вызывающего."""
    resp = _request_via(_reply_envelope(dict(_CONFLICT), success=False))

    assert resp.get(key) == expected, f"{key!r}: ждали {expected!r}, получили {resp!r}"


# --- B ---------------------------------------------------------------------


def test_b_bad_request_code_survives() -> None:
    """B: code == "bad_request" не теряется."""
    result = {"status": "error", "code": "bad_request", "message": "preset: ожидался dict"}

    resp = _request_via(_reply_envelope(result, success=False))

    assert resp.get("code") == "bad_request", f"code потерян: {resp!r}"


def test_b_bad_request_message_intact() -> None:
    """B: русский текст message приходит дословно."""
    result = {"status": "error", "code": "bad_request", "message": "preset: ожидался dict"}

    resp = _request_via(_reply_envelope(result, success=False))

    assert resp.get("message") == "preset: ожидался dict", f"message искажён: {resp!r}"


# --- C ---------------------------------------------------------------------


def test_c_transport_failure_is_exactly_status_and_message() -> None:
    """C: транспортный отказ -> РОВНО два ключа, без выдуманных ``code`` и т.п."""
    resp = _request_via({"success": False, "error": "timeout"})

    assert resp == {"status": "error", "message": "timeout"}, f"лишние/недостающие ключи: {resp!r}"


# --- D ---------------------------------------------------------------------


def test_d_success_false_without_status_is_error() -> None:
    """D: dict хендлера без ``status`` при success=False -> status "error"."""
    resp = _request_via(_reply_envelope({"code": "conflict", "message": "x"}, success=False))

    assert resp.get("status") == "error", f"success=False не дал status=error: {resp!r}"


def test_d_success_false_without_status_keeps_code() -> None:
    """D: и при отсутствии ``status`` в dict хендлера ``code`` сохраняется."""
    resp = _request_via(_reply_envelope({"code": "conflict", "message": "x"}, success=False))

    assert resp.get("code") == "conflict", f"code потерян: {resp!r}"


# --- E ---------------------------------------------------------------------


def test_e_reason_becomes_message() -> None:
    """E: нет ``message``, есть ``reason`` -> message == текст reason (действующий контракт)."""
    result = {"status": "error", "code": "io_error", "reason": "disk full"}

    resp = _request_via(_reply_envelope(result, success=False))

    assert resp.get("message") == "disk full", f"reason не стал message: {resp!r}"


def test_e_reason_case_keeps_code() -> None:
    """E: в том же случае (message из reason) ``code`` не теряется."""
    result = {"status": "error", "code": "io_error", "reason": "disk full"}

    resp = _request_via(_reply_envelope(result, success=False))

    assert resp.get("code") == "io_error", f"code потерян: {resp!r}"


# --- H ---------------------------------------------------------------------


def test_h_success_result_gets_status_ok() -> None:
    """H: успех с результатом ``{"rev": 3}`` -> ``{"status": "ok", "rev": 3}``."""
    resp = _request_via(_reply_envelope({"rev": 3}, success=True))

    assert resp == {"status": "ok", "rev": 3}, f"неожиданный ответ: {resp!r}"
