# -*- coding: utf-8 -*-
"""Unit-тесты формы вердикта I3 (Task 0.3): ``backend_ctl.verdict.judge`` / ``is_refusal``.

Ожидаемые значения — литералы из Task 0.3, не выводятся из кода под тестом.
"""

from __future__ import annotations

from backend_ctl.registers import RegisterOps
from backend_ctl.verdict import is_refusal, judge

REFUSED = {"success": False, "error": "x"}
TIMEOUT = {"success": False, "error": "timeout"}
OK = {"success": True}


def _raising_eq(a, b):
    raise RuntimeError("eq blew up")


def test_rejected_ack_equal_pre_is_failed_and_vacuous():
    res = judge(10, REFUSED, 10, 10)
    assert res["verdict"] == "failed"
    assert res["vacuous"] is True
    assert res["success"] is False


def test_accepted_from_other_value_is_confirmed():
    res = judge(5, OK, 10, 10)
    assert res["verdict"] == "confirmed"
    assert res["vacuous"] is False
    assert res["success"] is True
    assert res["pre"] == 5
    assert res["post"] == 10
    assert res["ack"] == {"success": True}
    assert res["unverifiable"] == []


def test_applied_equal_value_is_vacuous():
    res = judge(10, OK, 10, 10)
    assert res["verdict"] == "vacuous"
    assert res["vacuous"] is True
    assert res["success"] is True


def test_rejected_ack_other_value_is_failed_not_vacuous():
    res = judge(5, REFUSED, 5, 10)
    assert res["verdict"] == "failed"
    assert res["vacuous"] is False
    assert res["success"] is False


def test_post_not_target_is_failed_even_if_ack_ok():
    res = judge(5, OK, 7, 10)
    assert res["verdict"] == "failed"
    assert res["vacuous"] is False
    assert res["success"] is False


def test_status_error_ack_is_refusal():
    res = judge(10, {"status": "error"}, 10, 10)
    assert res["verdict"] == "failed"
    assert res["vacuous"] is True
    assert res["success"] is False


def test_timeout_ack_applied_is_confirmed():
    res = judge(5, TIMEOUT, 10, 10)
    assert res["verdict"] == "confirmed"
    assert res["success"] is True


def test_timeout_ack_not_applied_is_failed():
    res = judge(5, TIMEOUT, 5, 10)
    assert res["verdict"] == "failed"
    assert res["success"] is False


def test_ack_none_decided_by_post():
    assert judge(5, None, 10, 10)["verdict"] == "confirmed"
    assert judge(5, None, 5, 10)["verdict"] == "failed"


def test_ack_without_success_or_status_decided_by_post():
    assert judge(5, {"error": "timeout"}, 10, 10)["verdict"] == "confirmed"
    assert judge(5, {"error": "timeout"}, 5, 10)["verdict"] == "failed"


def test_ack_string_decided_by_post():
    assert judge(5, "error", 10, 10)["verdict"] == "confirmed"
    assert judge(5, "error", 5, 10)["verdict"] == "failed"


def test_default_eq_does_not_coerce_strings():
    res = judge(5, OK, "10", 10)
    assert res["verdict"] == "failed"
    assert res["success"] is False


def test_coerced_string_target_is_confirmed():
    res = judge(5, OK, "10", 10, eq=RegisterOps._values_match)
    assert res["verdict"] == "confirmed"
    assert res["success"] is True


def test_unreadable_post_is_unverifiable():
    res = judge(5, OK, None, 10, unreadable=("post",))
    assert res["verdict"] == "unverifiable"
    assert res["unverifiable"] == ["post"]
    assert res["success"] is False


def test_unreadable_pre_is_unverifiable_not_vacuous():
    res = judge(None, OK, 10, 10, unreadable=("pre",))
    assert res["verdict"] == "unverifiable"
    assert res["vacuous"] is False
    assert res["success"] is False


def test_refused_ack_wins_over_unreadable():
    res = judge(10, REFUSED, None, 10, unreadable=("post",))
    assert res["verdict"] == "failed"
    assert res["vacuous"] is True
    assert res["success"] is False


def test_unreadable_post_keeps_vacuous_flag():
    res = judge(10, OK, None, 10, unreadable=("post",))
    assert res["verdict"] == "unverifiable"
    assert res["vacuous"] is True


def test_eq_that_raises_is_not_equal():
    res = judge(5, OK, 10, 10, eq=_raising_eq)
    assert res["verdict"] == "failed"
    assert res["vacuous"] is False
    assert res["success"] is False


def test_float_int_equal():
    assert judge(5, OK, 10.0, 10)["verdict"] == "confirmed"
    assert judge(10.0, OK, 10, 10)["verdict"] == "vacuous"


def test_is_refusal_matches_definition():
    assert is_refusal({"success": False, "error": "x"}) is True
    assert is_refusal({"status": "error"}) is True
    assert is_refusal({"success": False, "error": "timeout"}) is False
    assert is_refusal(None) is False
    assert is_refusal({"error": "timeout"}) is False
