"""apply_env_aliases — MULTIPROCESS_* ↔ INSPECTOR_* back-compat (Ф5.11)."""

from __future__ import annotations

from multiprocess_framework.modules.app_module import ENV_ALIAS_PAIRS, apply_env_aliases


def test_canonical_fills_legacy() -> None:
    env = {"MULTIPROCESS_PID_FILE": "/tmp/a.pids"}
    filled = apply_env_aliases(env)
    assert "INSPECTOR_PID_FILE" in filled
    assert env["INSPECTOR_PID_FILE"] == "/tmp/a.pids"


def test_legacy_fills_canonical() -> None:
    env = {"INSPECTOR_LOG_DIR": "/var/log/x"}
    filled = apply_env_aliases(env)
    assert "MULTIPROCESS_LOG_DIR" in filled
    assert env["MULTIPROCESS_LOG_DIR"] == "/var/log/x"


def test_both_set_untouched() -> None:
    env = {"MULTIPROCESS_MANIFEST": "/a", "INSPECTOR_MANIFEST": "/b"}
    filled = apply_env_aliases(env)
    assert filled == []  # оба заданы — не трогаем (явное приоритетно)
    assert env["MULTIPROCESS_MANIFEST"] == "/a"
    assert env["INSPECTOR_MANIFEST"] == "/b"


def test_idempotent() -> None:
    env = {"MULTIPROCESS_LOG_DIR": "/l"}
    apply_env_aliases(env)
    second = apply_env_aliases(env)
    assert second == []  # повторный вызов ничего не меняет


def test_all_pairs_covered() -> None:
    keys = {c for c, _ in ENV_ALIAS_PAIRS} | {legacy for _, legacy in ENV_ALIAS_PAIRS}
    assert "MULTIPROCESS_PID_FILE" in keys and "INSPECTOR_PID_FILE" in keys
    assert "MULTIPROCESS_LOG_DIR" in keys and "INSPECTOR_LOG_DIR" in keys
