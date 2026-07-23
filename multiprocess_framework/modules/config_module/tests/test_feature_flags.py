# -*- coding: utf-8 -*-
"""Contract-тесты реестра feature_flags — читаются как документация.

Каждая Pre/Post-строка docstring'ов модуля имеет хотя бы один given/when/then.
"""

from __future__ import annotations

import pytest

from multiprocess_framework.modules.config_module import feature_flags as ff


# ── Реестр собран корректно ───────────────────────────────────────────────────


def test_registry_has_no_duplicate_or_self_referential_flags():
    # given собранный на импорте реестр
    # then каждый ключ совпадает с .name, requires/aliases не ссылаются на себя
    for name, spec in ff.FLAGS.items():
        assert spec.name == name
        assert name not in spec.requires
        assert name not in spec.aliases


def test_every_requires_target_is_registered():
    # requires-граф замкнут: нет ссылок на неизвестные флаги
    for spec in ff.FLAGS.values():
        for req in spec.requires:
            assert req in ff.FLAGS, f"{spec.name} требует незарегистрированный {req}"


# ── resolve: приоритет ctor > env > default ───────────────────────────────────


def test_resolve_returns_default_when_env_unset(monkeypatch):
    # given флаг с default=False и неустановленной переменной
    monkeypatch.delenv("FW_SHM_SEQLOCK", raising=False)
    # then возвращается default
    assert ff.resolve("FW_SHM_SEQLOCK") is False


def test_resolve_default_true_flag_stays_on_when_unset(monkeypatch):
    # given супервизорный флаг с default=True
    monkeypatch.delenv("FW_AUTORESTART", raising=False)
    # then без env он включён (прежнее поведение)
    assert ff.resolve("FW_AUTORESTART") is True


def test_env_overrides_default(monkeypatch):
    # when env явно задаёт истинное значение
    monkeypatch.setenv("FW_SHM_SEQLOCK", "1")
    # then env побеждает default
    assert ff.resolve("FW_SHM_SEQLOCK") is True


def test_env_zero_overrides_default_true(monkeypatch):
    # ключевое для dark-launch отката: NAME=0 выключает даже default=True
    monkeypatch.setenv("FW_AUTORESTART", "0")
    assert ff.resolve("FW_AUTORESTART") is False


# ── Ф6.1: флип дефолтов гашения gui-шторма (plans/truth-holes-closure.md) ─────


def test_state_storm_flags_are_on_by_default(monkeypatch):
    """Оба флага гашения шторма включены без env.

    Живой замер 2026-07-23: БЕЗ них тот же рецепт за ~45с даёт 1702 безвозвратные
    потери в never-drop очереди gui (`StateStore` put=1871/lost=1687). Дефолт-OFF
    означал бы, что штатный запуск идёт по заведомо худшему пути.
    """
    for name in ("FW_STATE_COALESCE", "FW_STATE_QUEUE"):
        monkeypatch.delenv(name, raising=False)
        assert ff.resolve(name) is True, name


def test_state_storm_flags_rollback_via_env(monkeypatch):
    """Плечо пары: откат через env работает, а не только объявлен в докстринге."""
    for name in ("FW_STATE_COALESCE", "FW_STATE_QUEUE"):
        monkeypatch.setenv(name, "0")
        assert ff.resolve(name) is False, name


def test_ctor_beats_env(monkeypatch):
    # given env говорит off
    monkeypatch.setenv("FW_SHM_SEQLOCK", "0")
    # when ctor явно передаёт True
    # then ctor побеждает env
    assert ff.resolve("FW_SHM_SEQLOCK", explicit=True) is True
    assert ff.resolve("FW_SHM_SEQLOCK", explicit=False) is False


def test_empty_env_falls_back_to_default(monkeypatch):
    # пустая строка трактуется как «не задано» → default
    monkeypatch.setenv("FW_SHM_SEQLOCK", "")
    assert ff.resolve("FW_SHM_SEQLOCK") is False


def test_truthy_parsing_is_canonical(monkeypatch):
    # канонический truthy-набор (F9): 1/true/yes/on регистронезависимо
    for raw in ("1", "true", "TRUE", "Yes", "on"):
        monkeypatch.setenv("FW_SHM_SEQLOCK", raw)
        assert ff.resolve("FW_SHM_SEQLOCK") is True, raw
    for raw in ("0", "false", "no", "off", "garbage"):
        monkeypatch.setenv("FW_SHM_SEQLOCK", raw)
        assert ff.resolve("FW_SHM_SEQLOCK") is False, raw


# ── typo-guard: неизвестное имя громко падает ─────────────────────────────────


def test_unknown_flag_raises_loudly():
    # опечатка в имени → KeyError, а не тихий default=False
    with pytest.raises(KeyError):
        ff.resolve("FW_SHM_SQELOCK")  # опечатка
    with pytest.raises(KeyError):
        ff.is_enabled("FW_TOTALLY_MADE_UP")


# ── aliases: историческое не-FW имя ───────────────────────────────────────────


def test_alias_env_name_is_honoured(monkeypatch):
    # given старое имя MULTIPROCESS_USE_KIND_CHANNELS задано, каноническое — нет
    monkeypatch.delenv("FW_USE_KIND_CHANNELS", raising=False)
    monkeypatch.setenv("MULTIPROCESS_USE_KIND_CHANNELS", "1")
    # then значение читается через alias
    st = ff.state_of("FW_USE_KIND_CHANNELS")
    assert st.value is True
    assert st.source == "alias"


def test_canonical_name_wins_over_alias(monkeypatch):
    # каноническое имя приоритетнее алиаса
    monkeypatch.setenv("FW_USE_KIND_CHANNELS", "0")
    monkeypatch.setenv("MULTIPROCESS_USE_KIND_CHANNELS", "1")
    assert ff.resolve("FW_USE_KIND_CHANNELS") is False


# ── state_of / list_flags: источник значения виден ────────────────────────────


def test_state_of_reports_source(monkeypatch):
    monkeypatch.delenv("FW_SHM_SEQLOCK", raising=False)
    assert ff.state_of("FW_SHM_SEQLOCK").source == "default"
    monkeypatch.setenv("FW_SHM_SEQLOCK", "1")
    assert ff.state_of("FW_SHM_SEQLOCK").source == "env"
    assert ff.state_of("FW_SHM_SEQLOCK", explicit=False).source == "ctor"


def test_list_flags_covers_whole_registry():
    # снимок покрывает весь реестр, по одному состоянию на флаг
    states = ff.list_flags()
    assert {s.name for s in states} == set(ff.FLAGS)
    assert len(states) == len(ff.FLAGS)


# ── validate: requires-граф (advisory) ────────────────────────────────────────


def test_validate_flags_missing_dependency():
    # zero-copy включён без handle-cache/owner-incarnation → нарушения
    snapshot = {name: False for name in ff.FLAGS}
    snapshot["FW_SHM_ZERO_COPY"] = True
    problems = ff.validate(snapshot)
    assert any("FW_SHM_ZERO_COPY" in p and "FW_SHM_HANDLE_CACHE" in p for p in problems)


def test_validate_passes_when_dependencies_satisfied():
    # согласованный набор → пустой список
    snapshot = {name: False for name in ff.FLAGS}
    snapshot.update(
        FW_SHM_OWNER_INCARNATION=True,
        FW_SHM_HANDLE_CACHE=True,
        FW_SHM_ZERO_COPY=True,
    )
    assert ff.validate(snapshot) == []


def test_validate_ignores_disabled_flags():
    # выключенный флаг не проверяет свои requires
    snapshot = {name: False for name in ff.FLAGS}
    assert ff.validate(snapshot) == []


def test_validate_rejects_unknown_name_in_snapshot():
    with pytest.raises(KeyError):
        ff.validate({"FW_MADE_UP": True})


def test_default_snapshot_is_self_consistent(monkeypatch):
    # реестр в дефолтах (всё env снято) не содержит нарушений requires
    for name in ff.FLAGS:
        monkeypatch.delenv(name, raising=False)
        for alias in ff.FLAGS[name].aliases:
            monkeypatch.delenv(alias, raising=False)
    assert ff.validate() == []
