# -*- coding: utf-8 -*-
"""Unit-тесты TopologySession (RS-4): переходы dirty/diverged + callbacks.

Чистая логика без Qt/EventBus. Проверяет семантику каждого mark_* и уведомление
подписчиков только при реальном изменении состояния.

Refs: plans/2026-07-06_constructor-master/plan.md (RS-4)
"""

from __future__ import annotations

from multiprocess_prototype.domain.topology_session import TopologySession


def test_initial_state_clean() -> None:
    s = TopologySession()
    assert s.dirty is False
    assert s.diverged is False


def test_mark_edited_sets_both() -> None:
    """Правка графа: редактор разошёлся и с файлом, и с живой системой."""
    s = TopologySession()
    s.mark_edited()
    assert s.dirty is True
    assert s.diverged is True


def test_mark_saved_clears_dirty_keeps_diverged() -> None:
    """Save пишет в файл: dirty снят, но живая система не тронута → diverged держится."""
    s = TopologySession()
    s.mark_edited()
    s.mark_saved()
    assert s.dirty is False
    assert s.diverged is True


def test_mark_applied_clears_diverged_keeps_dirty() -> None:
    """Apply толкает граф в backend: diverged снят, в файл ничего не записано → dirty держится."""
    s = TopologySession()
    s.mark_edited()
    s.mark_applied()
    assert s.dirty is True
    assert s.diverged is False


def test_mark_activated_clears_both() -> None:
    """Активация рецепта — новый baseline: файл == редактор == live."""
    s = TopologySession()
    s.mark_edited()
    s.mark_activated()
    assert s.dirty is False
    assert s.diverged is False


def test_mark_loaded_clears_dirty_sets_diverged() -> None:
    """Загрузка из файла: редактор == файл (dirty=False), но не применён (diverged=True)."""
    s = TopologySession()
    s.mark_loaded()
    assert s.dirty is False
    assert s.diverged is True


def test_save_then_apply_clears_both() -> None:
    """Полный цикл правка → save → apply снимает оба флага."""
    s = TopologySession()
    s.mark_edited()
    s.mark_saved()
    s.mark_applied()
    assert s.dirty is False
    assert s.diverged is False


def test_undo_after_apply_reraises_diverged() -> None:
    """C-3-индикатор: apply снял diverged, последующая правка (undo) снова его ставит."""
    s = TopologySession()
    s.mark_edited()
    s.mark_applied()  # граф == live
    assert s.diverged is False
    s.mark_edited()  # undo/правка после apply → редактор разошёлся с live
    assert s.diverged is True


def test_callback_fires_on_change() -> None:
    s = TopologySession()
    seen: list[tuple[bool, bool]] = []
    s.add_change_callback(lambda: seen.append((s.dirty, s.diverged)))
    s.mark_edited()
    s.mark_saved()
    assert seen == [(True, True), (False, True)]


def test_callback_not_fired_when_state_unchanged() -> None:
    """Повторный mark без смены состояния не дёргает callbacks (нет лишних перерисовок)."""
    s = TopologySession()
    calls = 0

    def _cb() -> None:
        nonlocal calls
        calls += 1

    s.add_change_callback(_cb)
    s.mark_saved()  # уже clean → без изменения
    assert calls == 0
    s.mark_edited()  # изменение
    assert calls == 1
    s.mark_edited()  # состояние то же → без уведомления
    assert calls == 1


def test_reset_clears_both_and_notifies() -> None:
    s = TopologySession()
    seen: list[tuple[bool, bool]] = []
    s.mark_edited()
    s.add_change_callback(lambda: seen.append((s.dirty, s.diverged)))
    s.reset()
    assert s.dirty is False and s.diverged is False
    assert seen == [(False, False)]
