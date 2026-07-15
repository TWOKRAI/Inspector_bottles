# -*- coding: utf-8 -*-
"""Ф7 G.9(a): GC-дисциплина — gc.freeze за флагом + сборка по расписанию.

Флаг off = штатный GC бит-в-бит (freeze не зовётся). on = freeze после старта;
scheduled — сборка не чаще interval и только при включённом расписании.
"""

from __future__ import annotations

import gc

from multiprocess_framework.modules.process_module.lifecycle.gc_discipline import GcDiscipline


class TestFreeze:
    def test_noop_without_flag(self, monkeypatch):
        monkeypatch.delenv("FW_GC_FREEZE", raising=False)
        d = GcDiscipline()
        assert d.freeze_after_startup() is False

    def test_freezes_with_flag(self, monkeypatch):
        monkeypatch.setenv("FW_GC_FREEZE", "1")
        monkeypatch.delenv("FW_GC_SCHEDULED", raising=False)
        try:
            d = GcDiscipline()
            assert d.freeze_after_startup() is True
            # startup-объекты переехали в permanent-поколение (не сканируются далее).
            assert gc.get_freeze_count() > 0
            assert gc.isenabled() is True  # без FW_GC_SCHEDULED авто-GC остаётся включён
        finally:
            gc.unfreeze()  # не течём между тестами
            gc.enable()

    def test_idempotent(self, monkeypatch):
        monkeypatch.setenv("FW_GC_FREEZE", "1")
        try:
            d = GcDiscipline()
            assert d.freeze_after_startup() is True
            assert d.freeze_after_startup() is False  # второй раз — no-op
        finally:
            gc.unfreeze()
            gc.enable()

    def test_scheduled_disables_auto_gc(self, monkeypatch):
        monkeypatch.setenv("FW_GC_FREEZE", "1")
        monkeypatch.setenv("FW_GC_SCHEDULED", "1")
        try:
            d = GcDiscipline()
            d.freeze_after_startup()
            assert gc.isenabled() is False  # авто-GC отключён → сборка по расписанию
        finally:
            gc.unfreeze()
            gc.enable()

    def test_scheduled_without_freeze_warns_loudly(self, monkeypatch):
        """Ф7 ревью фазы G: FW_GC_SCHEDULED без FW_GC_FREEZE — расписание НЕ применяется,
        и это ГРОМКО (раньше — тихий no-op: оператор включал расписание и не получал
        ничего без единого лога)."""
        monkeypatch.delenv("FW_GC_FREEZE", raising=False)
        monkeypatch.setenv("FW_GC_SCHEDULED", "1")
        logs: list[str] = []
        d = GcDiscipline(log=logs.append)
        assert d.freeze_after_startup() is False
        assert gc.isenabled() is True  # авто-GC не тронут
        assert d.collect_scheduled(now=100.0) is False  # расписание не активно
        assert any("БЕЗ FW_GC_FREEZE" in m for m in logs)  # тихого no-op больше нет


class TestScheduledCollect:
    def test_noop_when_not_scheduled(self, monkeypatch):
        monkeypatch.delenv("FW_GC_SCHEDULED", raising=False)
        d = GcDiscipline()
        # расписание не включено → collect_scheduled ничего не делает (штатный авто-GC).
        assert d.collect_scheduled(now=100.0) is False

    def test_collects_by_deadline(self, monkeypatch):
        monkeypatch.setenv("FW_GC_FREEZE", "1")
        monkeypatch.setenv("FW_GC_SCHEDULED", "1")
        try:
            d = GcDiscipline()
            d.freeze_after_startup()
            # первый вызов собирает (дедлайн 0), затем throttle до now+interval.
            assert d.collect_scheduled(now=100.0, interval_s=2.0) is True
            assert d.collect_scheduled(now=101.0, interval_s=2.0) is False  # рано
            assert d.collect_scheduled(now=102.5, interval_s=2.0) is True  # дедлайн прошёл
        finally:
            gc.unfreeze()
            gc.enable()
