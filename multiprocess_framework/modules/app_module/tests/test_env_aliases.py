"""apply_env_aliases — MULTIPROCESS_* ↔ INSPECTOR_* back-compat (Ф5.11)."""

from __future__ import annotations

import pytest

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


# ---------------------------------------------------------------------------
# D4: пять ручек из восьми не имели каноничного имени вовсе — де-брендинг Ф5.11
# покрывал только три. Проверяется ПОИМЁННО: сверка по длине таблицы пережила бы
# потерю любой отдельной пары.
# ---------------------------------------------------------------------------

#: Все ручки, у которых обязана быть каноничная форма. Список литеральный —
#: производный от ENV_ALIAS_PAIRS он согласился бы с любым содержимым таблицы.
_EXPECTED_PAIRS_D4 = {
    "MULTIPROCESS_PID_FILE": "INSPECTOR_PID_FILE",
    "MULTIPROCESS_LOG_DIR": "INSPECTOR_LOG_DIR",
    "MULTIPROCESS_MANIFEST": "INSPECTOR_MANIFEST",
    "MULTIPROCESS_LOG_LEVEL": "INSPECTOR_LOG_LEVEL",
    "MULTIPROCESS_FRAME_TRACE": "INSPECTOR_FRAME_TRACE",
    "MULTIPROCESS_HEALTH_LOG_ONLY": "INSPECTOR_HEALTH_LOG_ONLY",
    "MULTIPROCESS_HEALTH_BREAKER_THRESHOLD": "INSPECTOR_HEALTH_BREAKER_THRESHOLD",
    "MULTIPROCESS_HEALTH_BREAKER_COOLDOWN": "INSPECTOR_HEALTH_BREAKER_COOLDOWN",
}


class TestEnvAliasTableD4:
    def test_every_expected_pair_present_by_name(self):
        """Поимённо, а не по количеству: порог-сумма пережил бы потерю пары."""
        table = dict(ENV_ALIAS_PAIRS)
        for canonical, legacy in _EXPECTED_PAIRS_D4.items():
            assert canonical in table, f"нет каноничной ручки {canonical}"
            assert table[canonical] == legacy, f"{canonical} сопоставлена {table[canonical]!r}, ожидалось {legacy!r}"

    def test_no_extra_pairs_sneaked_in(self):
        assert dict(ENV_ALIAS_PAIRS) == _EXPECTED_PAIRS_D4

    @pytest.mark.parametrize("canonical,legacy", sorted(_EXPECTED_PAIRS_D4.items()))
    def test_mirroring_works_in_both_directions(self, canonical, legacy):
        env = {canonical: "value-A"}
        apply_env_aliases(env)
        assert env[legacy] == "value-A"

        env = {legacy: "value-B"}
        apply_env_aliases(env)
        assert env[canonical] == "value-B"

    @pytest.mark.parametrize("canonical,legacy", sorted(_EXPECTED_PAIRS_D4.items()))
    def test_both_set_are_left_alone(self, canonical, legacy):
        """Явное значение уважается — алиас не переписывает заданную пару."""
        env = {canonical: "canon", legacy: "legacy"}
        apply_env_aliases(env)
        assert env == {canonical: "canon", legacy: "legacy"}
