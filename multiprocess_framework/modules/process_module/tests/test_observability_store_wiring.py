# -*- coding: utf-8 -*-
"""Тесты проводки ObservabilityStore в drain-петлю процесса (Ф5.20a)."""

from __future__ import annotations

from multiprocess_framework.modules.channel_routing_module.levels import (
    record_severity,
    threshold_severity,
)
from multiprocess_framework.modules.channel_routing_module.observability import (
    ObservabilityHub,
    ObservabilityStore,
)
from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    STORE_ERROR_TAP,
    STORE_LOGGER_TAP,
    drain_process_observability,
    error_plane_store_warning,
    unwire_observability_store,
    wire_observability_store,
)


class FakeLoggerCore:
    """Мини-LoggerCore: реестр tap'ов + эмиссия записи через них.

    **Порог ``min_level`` фальшивка обязана СОБЛЮДАТЬ (задача 8.5f).** До этой правки
    она принимала аргумент и выбрасывала его, отдавая каждую запись каждому tap'у —
    то есть проверяла ровно ту половину сшивки, которая её не интересовала. Цена
    была измерена инъекцией: подмени ``min_level="ERROR"`` в ``wire_observability_store``
    на ``"DEBUG"`` — и в стор поехал бы весь лог процесса, а не ошибки; ни один тест
    файла не краснел. Дубль, который всегда пропускает, глушит гейт так же надёжно,
    как дубль, который всегда успешен.

    Сравнение уровней берётся у ПРОДАКШН-функций (``record_severity`` /
    ``threshold_severity``), а не пишется здесь заново: своя таблица уровней в
    фальшивке разошлась бы с настоящей молча, и тест продолжал бы быть зелёным,
    доказывая себя.
    """

    def __init__(self):
        #: {имя: (канал, порог)} — порог хранится, потому что он и есть то, что
        #: проверяется: без него реестр tap'ов помнит подписку, но не её условие.
        self._taps = {}

    def add_tap(self, channel, *, min_level="ERROR", name=None):
        key = name or channel.name
        self._taps[key] = (channel, threshold_severity(min_level))
        return key

    def remove_tap(self, name):
        return self._taps.pop(name, None) is not None

    def emit_error(self, message, module="worker_module", level="ERROR"):
        self.emit(message, module=module, level=level)

    def emit(self, message, module="worker_module", level="ERROR"):
        """Эмиссия записи ЛЮБОГО уровня — доедет только до tap'ов, чей порог её пускает."""
        rec = {"timestamp": 1.0, "level": level, "scope": "system", "message": message, "module": module, "extra": {}}
        severity = record_severity(level)
        for channel, threshold in list(self._taps.values()):
            if severity >= threshold:
                channel.write(rec)


class TestWireStore:
    def test_wire_creates_store_and_taps_on_both(self, tmp_path):
        err, log = FakeLoggerCore(), FakeLoggerCore()
        store, taps = wire_observability_store(err, log, db_path=str(tmp_path / "obs.db"))
        assert isinstance(store, ObservabilityStore)
        assert {name for _, name in taps} == {STORE_ERROR_TAP, STORE_LOGGER_TAP}
        assert STORE_ERROR_TAP in err._taps
        assert STORE_LOGGER_TAP in log._taps
        store.close()

    def test_error_via_error_manager_reaches_store(self, tmp_path):
        """Write-through error (error_manager) попадает в стор через tap."""
        err = FakeLoggerCore()
        store, _ = wire_observability_store(err, None, db_path=str(tmp_path / "obs.db"))
        err.emit_error("crash-1")
        err.emit_error("crash-2", level="CRITICAL")
        rows = store.list_records(kind="error")
        assert [r["message"] for r in rows] == ["crash-2", "crash-1"]
        assert rows[0]["severity"] == "critical"
        store.close()

    def test_error_via_logger_manager_reaches_store(self, tmp_path):
        """Live-урок: logger.error/ctx.log_error (logger_manager) тоже в стор."""
        log = FakeLoggerCore()
        store, _ = wire_observability_store(None, log, db_path=str(tmp_path / "obs.db"))
        log.emit_error("camera open failed", module="camera_0")
        rows = store.list_records(kind="error")
        assert len(rows) == 1
        assert rows[0]["message"] == "camera open failed"
        assert rows[0]["module"] == "camera_0"
        store.close()

    def test_store_tap_is_gated_by_error_level(self, tmp_path):
        """8.5f: в стор ошибок едут ОШИБКИ, а не весь журнал процесса.

        Порог ``min_level="ERROR"`` — не украшение подписки: вкладка «Ошибки» читает
        этот стор целиком, и пропусти tap INFO/DEBUG — она превратилась бы во вторую
        вкладку логов, а файл стора рос бы со скоростью всего журнала. До 8.5f
        свойство не было закреплено ничем: фальшивка порог игнорировала, и снятие
        гейта в проде не краснело ни одним тестом.
        """
        log = FakeLoggerCore()
        store, _ = wire_observability_store(None, log, db_path=str(tmp_path / "obs.db"))

        log.emit("рутина кадра", level="DEBUG")
        log.emit("камера открыта", level="INFO")
        log.emit("кадр просрочен", level="WARNING")
        log.emit("камера не открылась", level="ERROR")
        log.emit("процесс умирает", level="CRITICAL")

        rows = store.list_records(kind="error")
        assert [r["message"] for r in rows] == ["процесс умирает", "камера не открылась"], (
            "ниже ERROR в стор попадать не имеет права"
        )
        store.close()

    def test_wire_without_managers(self, tmp_path):
        store, taps = wire_observability_store(None, None, db_path=str(tmp_path / "obs.db"))
        assert isinstance(store, ObservabilityStore)
        assert taps == []
        store.close()

    def test_unwire_removes_all_taps(self, tmp_path):
        err, log = FakeLoggerCore(), FakeLoggerCore()
        store, taps = wire_observability_store(err, log, db_path=str(tmp_path / "obs.db"))
        unwire_observability_store(store, taps)
        assert STORE_ERROR_TAP not in err._taps
        assert STORE_LOGGER_TAP not in log._taps


class TestDrainToStore:
    def test_drain_persists_log_and_stats_not_error(self, tmp_path):
        hub = ObservabilityHub("worker_module")
        hub.info("hello")
        hub.record_metric("fps", 30)
        # error в hub НЕ кладём — он идёт write-through; но проверим, что даже
        # если бы попал, drain его в стор НЕ пишет (источник error — tap).
        store = ObservabilityStore(str(tmp_path / "obs.db"))

        drain_process_observability(hub, None, store)

        assert store.count(kind="log") == 1
        assert store.count(kind="stats") == 1
        assert store.count(kind="error") == 0
        assert store.list_records(kind="log")[0]["message"] == "hello"
        assert store.list_records(kind="stats")[0]["message"] == "fps"
        store.close()

    def test_drain_all_called_once_empties_hub(self, tmp_path):
        hub = ObservabilityHub("worker_module")
        hub.info("once")
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        drain_process_observability(hub, None, store)
        # Второй drain — каналы уже осушены, стор не растёт.
        drain_process_observability(hub, None, store)
        assert store.count(kind="log") == 1
        store.close()

    def test_drain_store_none_is_noop_safe(self, tmp_path):
        hub = ObservabilityHub("worker_module")
        hub.info("x")
        drain_process_observability(hub, None, None)  # без стора — не падает


class TestExactlyOneTapOwnsTheErrorPlane:
    """Владелец маркированных строк — ровно один, и он есть, пока встал хоть один tap.

    Сторож находки Major 1 ревью Task 1.3a на уровне ПРОВОДКИ (сквозной сторож
    числом строк — ``process_module/tests/test_health_incident_reaches_the_store.py``).
    Прежняя редакция раздавала ``owns_error_plane`` константой по роли, и на
    раскладке «есть logger-tap, нет error-tap» маркированную запись не принимал
    НИКТО: замер ревью — контроль 1 строка стора, опыт 0.
    """

    @staticmethod
    def _marked_record(message="инцидент"):
        return {
            "timestamp": 1.0,
            "level": "ERROR",
            "scope": "system",
            "message": message,
            "module": "worker_module",
            "extra": {"origin": "error_manager"},
        }

    def test_the_logger_tap_takes_over_when_the_error_plane_has_no_tap(self, tmp_path):
        """ОПЫТ: ErrorManager'а нет — маркированную запись обязан принять логгер-tap."""
        log = FakeLoggerCore()
        store, taps = wire_observability_store(None, log, db_path=str(tmp_path / "obs.db"), process="camera_0")
        try:
            assert {name for _, name in taps} == {STORE_LOGGER_TAP}
            for channel, _ in log._taps.values():
                channel.write(self._marked_record())
            rows = store.list_records(process="camera_0")
            assert len(rows) == 1, f"маркированную запись не принял никто: {rows}"
        finally:
            unwire_observability_store(store, taps)

    def test_the_logger_tap_still_skips_when_the_error_plane_has_its_own_tap(self, tmp_path):
        """КОНТРОЛЬ: оба менеджера на месте — логгер-tap по-прежнему пропускает маркер.

        Без него «опыт принял» доказывалось бы и починкой, снявшей дедуп путей
        целиком: тогда инцидент давал бы две строки вместо одной.
        """
        err, log = FakeLoggerCore(), FakeLoggerCore()
        store, taps = wire_observability_store(err, log, db_path=str(tmp_path / "obs.db"), process="camera_0")
        try:
            assert {name for _, name in taps} == {STORE_ERROR_TAP, STORE_LOGGER_TAP}
            for channel, _ in log._taps.values():
                channel.write(self._marked_record())
            assert store.list_records(process="camera_0") == [], "логгер-tap перестал пропускать маркер — будет дубль"
            for channel, _ in err._taps.values():
                channel.write(self._marked_record())
            assert len(store.list_records(process="camera_0")) == 1
        finally:
            unwire_observability_store(store, taps)


class TestTheErrorPlaneGapIsAnnounced:
    """Асимметрия tap'ов обязана быть СКАЗАНА, а не пройти молча.

    Ревью Task 1.3a: прежнее предупреждение срабатывало только на НУЛЕ tap'ов,
    а раскладка «есть logger-tap, нет error-tap» — та самая, на которой инцидент
    терялся, — проходила его без единого слова.
    """

    def test_a_healthy_pair_says_nothing(self):
        healthy = [(object(), STORE_ERROR_TAP), (object(), STORE_LOGGER_TAP)]
        assert error_plane_store_warning("camera_0", healthy) is None

    def test_no_taps_at_all_is_announced_as_a_loss(self):
        msg = error_plane_store_warning("camera_0", [])
        assert msg is not None and "camera_0" in msg
        assert "попадать НЕ будут" in msg, msg

    def test_a_logger_only_layout_is_announced_as_a_takeover(self):
        """Именно эта ветка и была находкой: список НЕ пуст, а плоскости ошибок нет."""
        msg = error_plane_store_warning("camera_0", [(object(), STORE_LOGGER_TAP)])
        assert msg is not None, "раскладка «есть logger-tap, нет error-tap» прошла молча"
        assert "ПЛОСКОСТИ ОШИБОК" in msg, msg
        assert "camera_0" in msg, msg

    def test_none_taps_reads_as_no_taps(self):
        """``None`` вместо списка — та же потеря, а не тихий успех."""
        assert error_plane_store_warning("camera_0", None) is not None
