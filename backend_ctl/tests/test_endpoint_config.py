# -*- coding: utf-8 -*-
"""Тесты приоритетов резолвера endpoint'а (Task 0.1).

Проверяют единый контракт: явный аргумент > env > дефолт, для host и port
независимо. Дефолт порта = серверный DEFAULT_PORT (единый источник числа).
"""

from __future__ import annotations

import pytest

from backend_ctl.endpoint_config import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    ENV_HOST,
    ENV_PORT,
    resolve_endpoint,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Убрать endpoint-env, чтобы тесты не зависели от окружения запуска."""
    monkeypatch.delenv(ENV_HOST, raising=False)
    monkeypatch.delenv(ENV_PORT, raising=False)


def test_defaults_when_nothing_set():
    assert resolve_endpoint() == (DEFAULT_HOST, DEFAULT_PORT)


def test_explicit_args_win_over_env(monkeypatch):
    monkeypatch.setenv(ENV_HOST, "10.0.0.9")
    monkeypatch.setenv(ENV_PORT, "9999")
    assert resolve_endpoint("192.168.1.1", 8000) == ("192.168.1.1", 8000)


def test_env_wins_over_default(monkeypatch):
    monkeypatch.setenv(ENV_HOST, "10.0.0.9")
    monkeypatch.setenv(ENV_PORT, "9001")
    assert resolve_endpoint() == ("10.0.0.9", 9001)


def test_host_and_port_resolved_independently(monkeypatch):
    # Только порт в env — host падает на дефолт.
    monkeypatch.setenv(ENV_PORT, "9002")
    assert resolve_endpoint() == (DEFAULT_HOST, 9002)
    # Только host явно — порт из env.
    assert resolve_endpoint(host="myhost") == ("myhost", 9002)


def test_explicit_port_zero_is_honored():
    # port=0 (эфемерный) — валидный явный аргумент, не путать с None.
    assert resolve_endpoint(port=0) == (DEFAULT_HOST, 0)


def test_default_port_matches_server_source():
    # Число берётся из серверного backend_ctl_endpoint — один источник.
    from multiprocess_framework.modules.process_manager_module.process.backend_ctl_endpoint import (
        DEFAULT_PORT as SERVER_DEFAULT_PORT,
    )

    assert DEFAULT_PORT == SERVER_DEFAULT_PORT


# --- Task 5.2: валидация BACKEND_CTL_PORT (находка ultra-ревью) ---


@pytest.mark.parametrize("bad_value", ["auto", "0", " ", "70000"])
def test_invalid_env_port_raises_actionable_error(monkeypatch, bad_value):
    """Нечисло/вне диапазона/пробелы — понятная ошибка, не молчаливый fallback на дефолт."""
    monkeypatch.setenv(ENV_PORT, bad_value)
    with pytest.raises(ValueError, match=ENV_PORT):
        resolve_endpoint()


def test_valid_env_port_parsed(monkeypatch):
    monkeypatch.setenv(ENV_PORT, "9142")
    assert resolve_endpoint() == (DEFAULT_HOST, 9142)


def test_unset_env_port_falls_back_to_default(monkeypatch):
    monkeypatch.delenv(ENV_PORT, raising=False)
    assert resolve_endpoint() == (DEFAULT_HOST, DEFAULT_PORT)
