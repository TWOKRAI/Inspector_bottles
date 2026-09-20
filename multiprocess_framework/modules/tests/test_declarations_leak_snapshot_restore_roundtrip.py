# -*- coding: utf-8 -*-
"""RED (Task 0.1, критерий 4) — публичный снимок/восстановление реестра объявлений.

Независимый приёмочный тест, написанный ДО реализации. Источник — Acceptance
criteria задачи 0.1: «Реестр имеет публичный способ снять снимок и восстановить
его (снимок до теста -> восстановление после), не теряя чужих объявлений».

Сейчас ``snapshot``/``restore`` в `observability_declarations.py` не существует
(`__all__` называет только `declare_log_source`, `declared_sources`,
`declared_rules`, `declare_metric`, `declared_metrics`, `forget_declarations`) —
оба теста ниже обязаны падать `AttributeError` на первом же обращении.
"""

from __future__ import annotations

from multiprocess_framework.modules import observability_declarations as decls


def test_restore_reverts_a_declaration_made_after_the_snapshot() -> None:
    """snapshot() до объявления -> объявление -> restore(snapshot) стирает его."""
    name = "declarations_leak_probe_added_after_snapshot"
    snapshot = decls.snapshot()
    try:
        decls.declare_metric(name, owner=f"{__name__}:after")
        assert name in decls.declared_metrics(), "предпосылка: объявление реально попало в каталог"
        decls.restore(snapshot)
        assert name not in decls.declared_metrics(), (
            "restore(snapshot) не откатил объявление, сделанное ПОСЛЕ snapshot()"
        )
    finally:
        # Гигиена теста: если restore ещё не работает (AttributeError выше уже
        # оборвал бы тест раньше) или отработал не полностью — не оставлять
        # маркерное имя каталогу метрик соседям (страж сессии в
        # test_declarations_leak_session_catalogue_guard.py).
        decls.forget_declarations(names=[name])


def test_restore_preserves_a_declaration_that_existed_before_the_snapshot() -> None:
    """Объявление ДО snapshot() переживает snapshot() -> шум -> restore(snapshot).

    Это и есть «не теряя чужих объявлений»: restore обязан вернуть реестр К
    СОСТОЯНИЮ СНИМКА, а не выполнить сплошную очистку — снимок, взятый ДО
    объявления, что-то чужое просто не видел, но обязан его сохранить, а не
    объявление уничтожить как «шум роста».
    """
    preexisting = "declarations_leak_probe_preexisting_before_snapshot"
    noise = "declarations_leak_probe_noise_after_snapshot"
    decls.declare_metric(preexisting, owner=f"{__name__}:before")
    try:
        snapshot = decls.snapshot()
        decls.declare_metric(noise, owner=f"{__name__}:noise")
        decls.restore(snapshot)
        assert preexisting in decls.declared_metrics(), (
            "restore(snapshot) стёр объявление, существовавшее ДО snapshot() — "
            "восстановление обязано быть возвратом к состоянию снимка, а не "
            "голой очисткой того, что накопилось после него"
        )
    finally:
        decls.forget_declarations(names=[preexisting, noise])
