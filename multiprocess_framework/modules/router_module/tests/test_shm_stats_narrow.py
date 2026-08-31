# -*- coding: utf-8 -*-
"""Узкий `get_shm_stats()` не расходится с полным `get_stats()` (ADR-PM-035, блокер 1).

Опрос уровней и push-тик heartbeat'а звали ради тринадцати int'ов полный `get_stats()`,
который строит `channel_routes` / `message_handler_list` / `channels`. Мерка на живом
стенде: опрос 56.25 мс против 11.05 мс у процесса без опроса при поле транспорта 11 мс —
весь прирост был ценой `get_stats()`. Появился узкий аксессор.

**Что может сломаться именно здесь.** Узкий и полный пути — два ИМЕНИ одной величины, и
классический способ их развести это добавить счётчик в одно место. Разойдутся они молча:
`get_stats()` продолжит отвечать, телеметрия продолжит публиковать, просто числа станут
разными — а заметить это можно только сверив два ответа руками. Поэтому:

- вычисление физически одно (`get_stats` splice'ит `**self.get_shm_stats()`), и
- этот файл сторожит, что splice на месте: ключи узкого ответа обязаны присутствовать в
  полном И совпадать по значению, в том числе на НЕнулевых счётчиках (на нулях совпало бы
  и у двух разных реализаций — урок «совпадение констант прячет противоположные реализации»).
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.heartbeat.telemetry import (
    build_router_shm_telemetry,
)
from multiprocess_framework.modules.router_module.core.router_manager import RouterManager


class _FakeFrameMiddleware:
    """Frame-middleware с ненулевыми счётчиками (нули не различают реализации)."""

    def __init__(self) -> None:
        self.frame_pickle_fallbacks = 11
        self.frame_torn_reads = 22
        self.frame_boundary_crossings = 33
        self.frame_stale_drops = 44
        self.frame_loan_exhausted = 55
        self.frame_slots_released = 66
        self.frame_slots_reclaimed = 77
        self.frame_handle_cache_size = 88
        self.frame_loans_released_on_evict = 99
        self.loan_protocol_enabled = True


NARROW_KEYS = (
    "frame_pickle_fallbacks",
    "frame_torn_reads",
    "frame_boundary_crossings",
    "frame_stale_drops",
    "frame_loan_exhausted",
    "frame_slots_released",
    "frame_slots_reclaimed",
    "frame_handle_cache_size",
    "queue_data_evicted",
    "queue_system_evict_blocked",
    "queue_observability_evicted",
    "queue_observability_send_failed",
    "observability_delivery_failed",
)


def _router() -> RouterManager:
    return RouterManager(manager_name="narrow_stats_router")


class TestNarrowAgreesWithFull:
    def test_all_narrow_keys_present_in_full_stats(self) -> None:
        r = _router()
        full = r.get_stats()["router"]
        missing = [k for k in NARROW_KEYS if k not in full]
        assert not missing, missing

    def test_values_identical_on_a_clean_router(self) -> None:
        r = _router()
        narrow = r.get_shm_stats()
        full = r.get_stats()["router"]
        assert {k: full[k] for k in narrow} == narrow

    def test_values_identical_with_nonzero_counters(self) -> None:
        """Ненулевые значения: на нулях согласились бы и две разные реализации.

        Значения прибиты ЛИТЕРАЛОМ по ВСЕМ восьми middleware-счётчикам, а не тремя
        точечными assert'ами. Чего стоила выборка — измерено ревью Task 3.2 прогоном:
        порча `frame_stale_drops`, `frame_loan_exhausted` или `frame_slots_released`
        (`+= 1000` внутри :meth:`RouterManager.get_shm_stats`) оставляла весь корпус
        из 2420 тестов зелёным. Ни один из двух соседних сторожей эту дыру закрыть не
        может по устройству: сверка `narrow == full` слепа, потому что полный путь
        **splice'ит узкий** и оба расходятся согласованно; а поимённый
        `test_every_summand_can_open_the_gate_alone` ходит фейковым router'ом, то есть
        фолбэком, которого в проде нет. Литерал здесь — единственное место, где
        перепутанный атрибут-источник краснеет на настоящем объекте.
        """
        r = _router()
        r._frame_middlewares.append(_FakeFrameMiddleware())

        narrow = r.get_shm_stats()
        full = r.get_stats()["router"]

        # Числа фикстуры намеренно различимы между собой (11/22/…/88): совпади они —
        # и перестановка двух источников прошла бы молча.
        expected_mw = {
            "frame_pickle_fallbacks": 11,
            "frame_torn_reads": 22,
            "frame_boundary_crossings": 33,
            "frame_stale_drops": 44,
            "frame_loan_exhausted": 55,
            "frame_slots_released": 66,
            "frame_slots_reclaimed": 77,
            "frame_handle_cache_size": 88,
        }
        assert {k: narrow[k] for k in expected_mw} == expected_mw
        assert {k: full[k] for k in narrow} == narrow

    def test_two_middlewares_are_summed_not_overwritten(self) -> None:
        r = _router()
        r._frame_middlewares.append(_FakeFrameMiddleware())
        r._frame_middlewares.append(_FakeFrameMiddleware())

        narrow = r.get_shm_stats()

        assert narrow["frame_torn_reads"] == 44
        assert narrow["frame_slots_reclaimed"] == 154

    def test_keys_that_are_NOT_narrow_still_live_in_full_stats(self) -> None:
        """Splice не должен был съесть соседей: они считаются вне узкого аксессора."""
        r = _router()
        r._frame_middlewares.append(_FakeFrameMiddleware())
        full = r.get_stats()["router"]

        assert full["frame_loans_released_on_evict"] == 99
        assert full["frame_loan_pools"] == 1
        for key in ("queue_never_drop_loss_total", "queue_senders", "channel_put_timeouts", "channels"):
            assert key in full, key


class TestCollectorPrefersTheNarrowPath:
    def test_real_router_goes_through_get_shm_stats(self) -> None:
        """Сборщик телеметрии обязан брать узкий путь у настоящего router'а."""
        r = _router()
        r._frame_middlewares.append(_FakeFrameMiddleware())
        calls = {"narrow": 0, "full": 0}
        real_narrow, real_full = r.get_shm_stats, r.get_stats

        def _narrow():
            calls["narrow"] += 1
            return real_narrow()

        def _full():
            calls["full"] += 1
            return real_full()

        r.get_shm_stats, r.get_stats = _narrow, _full

        payload = build_router_shm_telemetry(r)

        assert calls == {"narrow": 1, "full": 0}, calls
        assert payload["torn_reads"] == 22
        assert payload["boundary_crossings"] == 33

    def test_router_without_narrow_accessor_falls_back(self) -> None:
        """Duck-typed router без узкого аксессора обязан остаться рабочим."""

        class _OldRouter:
            def get_stats(self):
                return {"router": {"frame_torn_reads": 5, "queue_data_evicted": 6}}

        payload = build_router_shm_telemetry(_OldRouter())

        assert payload["torn_reads"] == 5
        assert payload["queue_data_evicted"] == 6
        assert payload["pickle_fallbacks"] == 0

    def test_narrow_path_does_not_build_routes_or_channels(self) -> None:
        """Смысл правки: узкий путь не трогает реестры каналов/хендлеров.

        Наблюдаемый эффект: подменяем дорогие сборщики на взрывающиеся — узкий
        аксессор проходит, полный `get_stats()` на них падает.
        """
        r = _router()

        def _boom(*a, **k):
            raise AssertionError("узкий путь полез в дорогую сборку")

        r.channel_dispatcher.get_all_handlers = _boom
        r.event_dispatcher.get_all_handlers = _boom
        r._channel_registry.get_info = _boom

        assert set(r.get_shm_stats()) == set(NARROW_KEYS)
