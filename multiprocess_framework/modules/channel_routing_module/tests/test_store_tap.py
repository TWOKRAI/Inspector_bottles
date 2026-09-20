# -*- coding: utf-8 -*-
"""Тесты StoreTapChannel (Ф5.20a): LogRecord-dict → ObservabilityStore."""

from __future__ import annotations

from multiprocess_framework.modules.channel_routing_module.observability import (
    ObservabilityStore,
    StoreTapChannel,
)


def _log_record_dict(level="ERROR", message="boom", module="worker_module", **extra):
    # Форма LogRecord.to_dict()
    return {
        "timestamp": 12.5,
        "level": level,
        "scope": "system",
        "message": message,
        "module": module,
        "extra": dict(extra),
    }


class TestStoreTapChannel:
    def test_write_normalizes_to_error_row(self, tmp_path):
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        tap = StoreTapChannel(store)  # kind считает важность записи (Ф5.2, Б-4)

        tap.write(_log_record_dict(level="ERROR", message="boom", error_type="ValueError"))
        # Task 3.3: между write() и стором встала очередь с фоновым дренажем.
        # Кто читает СВОИ ЖЕ записи, обязан их дожать — иначе сверка идёт с
        # пустым стором и любой ассерт об ОТСУТСТВИИ строк становится вакуумным.
        tap.flush(timeout=2.0)

        rows = store.list_records(kind="error")
        assert len(rows) == 1
        r = rows[0]
        assert r["kind"] == "error"
        assert r["severity"] == "error"  # 'ERROR' → lower
        assert r["message"] == "boom"
        assert r["module"] == "worker_module"
        assert r["ts"] == 12.5
        assert r["extra"]["context"] == {"error_type": "ValueError"}
        store.close()

    def test_write_critical_lowercased(self, tmp_path):
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        tap = StoreTapChannel(store)
        tap.write(_log_record_dict(level="CRITICAL", message="dead"))
        tap.flush(timeout=2.0)  # Task 3.3: дожать очередь перед чтением своих же строк
        assert store.list_records(kind="error")[0]["severity"] == "critical"
        store.close()

    def test_write_failure_does_not_raise(self, tmp_path):
        """Сбой стора не роняет вызывающего — и НАЗЫВАЕТСЯ, а не исчезает.

        Task 3.3 сменила контракт возврата: ``write()`` больше не знает, приняла
        ли строку БД (между ними очередь), поэтому прежний ``status == "error"``
        стал недостижим — он означал бы «стор бросил», а бросить он теперь может
        только в потоке дренажа. Свойство «не роняем» проверяется тем же входом,
        а судьба записи спрашивается там, где она известна: у ``flush()``.
        """
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        store.close()  # закрыли → append бросит внутри, воркер глушит
        tap = StoreTapChannel(store)
        result = tap.write(_log_record_dict())
        assert result["status"] == "success", "постановка в очередь удалась — отказа тут быть не может"
        written, lost = tap.flush(timeout=2.0)
        assert (written, lost) == (0, 1), (
            f"недоступный стор обязан дать честную потерю, а не тишину: written={written} lost={lost}"
        )

    def test_name_and_close(self, tmp_path):
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        tap = StoreTapChannel(store, name="my_tap")
        assert tap.name == "my_tap"
        tap.close()  # no-op, не бросает
        store.close()
