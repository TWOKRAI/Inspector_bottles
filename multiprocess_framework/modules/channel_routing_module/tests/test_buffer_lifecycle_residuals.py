# -*- coding: utf-8 -*-
"""Резидуалы F3 и F6 — жизненный цикл буфера перестаёт быть немым.

**F3.** Запись, пришедшая после ``stop()``, оседала в ``pending`` полностью
молча. Воспроизведено до правки: три ``enqueue`` после остановки дали
``pending={'Z': 3}``, ``dropped=0``, ``dropped_at_stop=0`` — ни один счётчик
не шевельнулся. ``dropped_at_stop`` считает только остаток на момент самой
остановки и по построению не может увидеть пришедшее позже.

**F6.** ``_batches`` и ``_last_flush_time`` — словари по имени канала, куда
имя попадает от первого ``enqueue`` и не удаляется никогда. Замер до правки:
500 динамических имён → 500 пустых ``deque`` и 500 отметок времени.

Обе правки — про ВИДИМОСТЬ и уборку, а не про поведение доставки: записи
по-прежнему принимаются, счётчики потерь по каналу по-прежнему переживают
снятие приёмника (урок ревью фазы Ф0).
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..buffers.batch_buffer import BatchBuffer, BatchConfig


def _collecting_buffer(**kw: Any) -> tuple[BatchBuffer, List[Dict[str, Any]]]:
    written: List[Dict[str, Any]] = []

    def _flush(channel: str, batch: List[Dict[str, Any]]) -> int:
        written.extend(batch)
        return len(batch)

    return BatchBuffer(flush_fn=_flush, config=BatchConfig(**kw)), written


# =============================================================================
# F3
# =============================================================================


class TestEnqueueAfterStop:
    def test_counted_not_silent(self) -> None:
        buf, _ = _collecting_buffer(max_size=100)
        buf.start()
        buf.stop()

        for i in range(3):
            buf.enqueue("Z", {"i": i})

        stats = buf.stats
        assert stats["enqueued_after_stop"] == 3, "запись после stop() снова невидима"
        assert stats["stopped"] is True
        assert stats["pending"] == {"Z": 3}

    def test_records_are_still_deliverable(self) -> None:
        """Считаем — не значит выбрасываем: явный flush обязан их доставить."""
        buf, written = _collecting_buffer(max_size=100)
        buf.start()
        buf.stop()
        buf.enqueue("Z", {"i": 1})

        buf.flush()

        assert len(written) == 1
        assert buf.stats["enqueued_after_stop"] == 1

    def test_normal_traffic_before_stop_is_not_counted(self) -> None:
        """Счётчик не должен подниматься на здоровой работе."""
        buf, _ = _collecting_buffer(max_size=100)
        buf.start()
        buf.enqueue("Z", {"i": 1})
        buf.stop()

        assert buf.stats["enqueued_after_stop"] == 0

    def test_fresh_buffer_is_not_stopped(self) -> None:
        """До первого start() буфер не «остановлен» — его просто не запускали.

        Иначе счётчик поднимался бы у любого потребителя, который пользуется
        буфером без фонового таймера (а такие есть).
        """
        buf, _ = _collecting_buffer(max_size=100)
        buf.enqueue("Z", {"i": 1})

        assert buf.stats["stopped"] is False
        assert buf.stats["enqueued_after_stop"] == 0

    def test_restart_clears_the_flag(self) -> None:
        buf, _ = _collecting_buffer(max_size=100)
        buf.start()
        buf.stop()
        buf.start()
        try:
            buf.enqueue("Z", {"i": 1})
            assert buf.stats["enqueued_after_stop"] == 0
            assert buf.stats["stopped"] is False
        finally:
            buf.stop()

    def test_accounting_invariant_still_holds(self) -> None:
        """Инвариант учёта не сломан новым счётчиком (он не про потери)."""
        buf, _ = _collecting_buffer(max_size=100)
        buf.start()
        buf.enqueue("Z", {"i": 0})
        buf.stop()
        buf.enqueue("Z", {"i": 1})

        s = buf.stats
        pending = sum(s["pending"].values())
        assert s["total_enqueued"] == (
            s["total_flushed"] + pending + s["dropped"] + s["flush_failed"] + s["in_flight_records"]
        )


# =============================================================================
# F6
# =============================================================================


class TestForgetChannel:
    def test_dynamic_names_do_not_accumulate(self) -> None:
        buf, _ = _collecting_buffer(max_size=1)
        for i in range(50):
            buf.enqueue(f"module_{i}", {"i": i})

        assert len(buf._batches) == 50, "предусловие: имена накопились"

        forgotten = sum(1 for i in range(50) if buf.forget_channel(f"module_{i}"))

        assert forgotten == 50
        assert buf._batches == {}
        assert buf._last_flush_time == {}
        assert buf.stats["pending"] == {}

    def test_refuses_to_forget_channel_with_pending(self) -> None:
        """Молча выбросить неотправленное нельзя — это был бы новый класс потери."""
        buf, _ = _collecting_buffer(max_size=1000)
        buf.enqueue("busy", {"i": 1})

        assert buf.forget_channel("busy") is False
        assert buf.stats["pending"] == {"busy": 1}

    def test_unknown_channel_is_a_quiet_no_op(self) -> None:
        buf, _ = _collecting_buffer(max_size=10)
        assert buf.forget_channel("никогда-не-было") is False

    def test_manager_forgets_the_channel_it_removed(self, tmp_path) -> None:
        """Уборка подключена к МЕНЕДЖЕРУ, а не только доступна как метод.

        Без этого теста ``forget_channel`` мог бы остаться идеально рабочим и
        никем не вызываемым — ровно тот класс, что ``flush_failed`` в реестре
        счётчиков (F5): запись есть, публикатора нет.
        """
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

        mgr = LoggerManager(
            manager_name="ForgetProbe",
            config={
                "app_name": "forget",
                "log_directory": str(tmp_path),
                "enable_batching": True,
                "modules": {},
                "channels": {
                    "sink": {"type": "file", "enabled": True, "file_path": str(tmp_path / "s.log")},
                },
                "scopes": {"BUSINESS": {"enabled": True, "min_level": "INFO", "channels": ["sink"]}},
            },
        )
        mgr.initialize()
        try:
            mgr.enable_module_logging("ephemeral")
            mgr.info("запись", module="ephemeral")
            assert "module_ephemeral" in mgr._buffer.stats["pending"], "предусловие: имя попало в буфер"

            mgr.flush()
            mgr.disable_module_logging("ephemeral")

            assert "module_ephemeral" not in mgr._buffer.stats["pending"], (
                "имя снятого канала осталось в буфере навсегда"
            )
        finally:
            mgr.shutdown()

    def test_loss_history_survives_forgetting(self) -> None:
        """Счётчики потерь канала переживают его уход — прямой урок ревью Ф0.

        Их обнуление здесь повторило бы дефект «история потерь консоли
        стиралась той самой командой, которую дают при разборе инцидента».
        """
        buf, _ = _collecting_buffer(max_size=1000, max_pending=1)
        # Занять сток, чтобы потолок начал ронять записи (drop_oldest).
        blocked = BatchBuffer(flush_fn=lambda ch, b: len(b), config=BatchConfig(max_size=1000, max_pending=1))
        blocked._in_flight.add("ghost")
        blocked.enqueue("ghost", {"i": 1})
        blocked.enqueue("ghost", {"i": 2})
        assert blocked.stats["dropped_by_channel"] == {"ghost": 1}, "предусловие: потеря случилась"

        blocked._in_flight.discard("ghost")
        blocked.flush("ghost")
        assert blocked.forget_channel("ghost") is True

        assert blocked.stats["dropped_by_channel"] == {"ghost": 1}, "история потерь стёрлась вместе с каналом"
        assert blocked.stats["dropped"] == 1
