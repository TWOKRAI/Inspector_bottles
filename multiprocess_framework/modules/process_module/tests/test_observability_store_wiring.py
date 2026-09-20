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
    reapply_observability_store_level,
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
        store.flush_writers()  # Task 3.3: очередь store-tap'а дожать ДО чтения (write() больше не синхронна)
        rows = store.list_records(kind="error")
        assert [r["message"] for r in rows] == ["crash-2", "crash-1"]
        assert rows[0]["severity"] == "critical"
        store.close()

    def test_error_via_logger_manager_reaches_store(self, tmp_path):
        """Live-урок: logger.error/ctx.log_error (logger_manager) тоже в стор."""
        log = FakeLoggerCore()
        store, _ = wire_observability_store(None, log, db_path=str(tmp_path / "obs.db"))
        log.emit_error("camera open failed", module="camera_0")
        store.flush_writers()  # Task 3.3: очередь store-tap'а дожать ДО чтения (write() больше не синхронна)
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

        store.flush_writers()  # Task 3.3: очередь store-tap'а дожать ДО чтения (write() больше не синхронна)
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

        store.flush_writers()  # Task 3.3: очередь store-tap'а дожать ДО чтения (write() больше не синхронна)
        assert store.count(kind="log") == 1
        store.flush_writers()  # Task 3.3: очередь store-tap'а дожать ДО чтения (write() больше не синхронна)
        assert store.count(kind="stats") == 1
        store.flush_writers()  # Task 3.3: очередь store-tap'а дожать ДО чтения (write() больше не синхронна)
        assert store.count(kind="error") == 0
        store.flush_writers()  # Task 3.3: очередь store-tap'а дожать ДО чтения (write() больше не синхронна)
        assert store.list_records(kind="log")[0]["message"] == "hello"
        store.flush_writers()  # Task 3.3: очередь store-tap'а дожать ДО чтения (write() больше не синхронна)
        assert store.list_records(kind="stats")[0]["message"] == "fps"
        store.close()

    def test_drain_all_called_once_empties_hub(self, tmp_path):
        hub = ObservabilityHub("worker_module")
        hub.info("once")
        store = ObservabilityStore(str(tmp_path / "obs.db"))
        drain_process_observability(hub, None, store)
        # Второй drain — каналы уже осушены, стор не растёт.
        drain_process_observability(hub, None, store)
        store.flush_writers()  # Task 3.3: очередь store-tap'а дожать ДО чтения (write() больше не синхронна)
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
            store.flush_writers()  # Task 3.3: очередь store-tap'а дожать ДО чтения (write() больше не синхронна)
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
            store.flush_writers()  # Task 3.3: очередь store-tap'а дожать ДО чтения (write() больше не синхронна)
            assert store.list_records(process="camera_0") == [], "логгер-tap перестал пропускать маркер — будет дубль"
            for channel, _ in err._taps.values():
                channel.write(self._marked_record())
            store.flush_writers()  # Task 3.3: очередь store-tap'а дожать ДО чтения (write() больше не синхронна)
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


class TestReapplyStoreLevel:
    """Ф2 (задача 2.2), добор ADR-PM-047: переустановка ПОРОГА уже поднятого
    store-tap'а на ``config.reload`` — стор не пересоздаётся, канал переустанавливается.

    До этой функции `history.level` менял ТОЛЬКО кэш `svc._observability_history_
    policy` (см. `resolve_history_policy`) — `min_level` уже поднятого
    `StoreTapChannel` выставлялся РОВНО ОДИН РАЗ на `wire_observability_store` и
    `config.reload` его не видел: `config_reload_verified` отвечал `confirmed`
    (readback честно показывал новый уровень политики), а живой стор продолжал
    принимать записи по СТАРОМУ порогу. Пара до/после по счётчику строк — ровно
    та проверка, которой не хватало приёмке.
    """

    def test_raising_the_level_makes_info_stop_landing_pair_before_after(self, tmp_path):
        log = FakeLoggerCore()
        store, taps = wire_observability_store(
            None, log, db_path=str(tmp_path / "obs.db"), process="seg", min_level="INFO"
        )
        try:
            log.emit("до правки: рутина", level="INFO")
            store.flush_writers()  # Task 3.3: очередь store-tap'а дожать ДО чтения (write() больше не синхронна)
            before = store.list_records(process="seg", severity_in=["info"])
            assert len(before) == 1, f"порог INFO обязан пропускать INFO ДО переустановки: {before}"

            taps = reapply_observability_store_level(store, None, log, "seg", "WARNING")

            log.emit("после правки: рутина", level="INFO")
            store.flush_writers()  # Task 3.3: очередь store-tap'а дожать ДО чтения (write() больше не синхронна)
            after_info = store.list_records(process="seg", severity_in=["info"])
            assert len(after_info) == 1, (
                f"порог поднят до WARNING — вторая INFO-запись не имела права лечь в стор: {after_info}"
            )

            log.emit("после правки: тревога", level="WARNING")
            store.flush_writers()  # Task 3.3: очередь store-tap'а дожать ДО чтения (write() больше не синхронна)
            after_warning = store.list_records(process="seg", severity_in=["warning"])
            assert len(after_warning) == 1, f"WARNING обязан лечь в стор при пороге WARNING: {after_warning}"
        finally:
            unwire_observability_store(store, taps)

    def test_lowering_the_level_makes_info_land_again_pair_before_after(self, tmp_path):
        """Контроль в обратную сторону: понижение порога — то же переустройство,
        а не односторонний хак, который умеет только поднимать порог."""
        log = FakeLoggerCore()
        store, taps = wire_observability_store(
            None, log, db_path=str(tmp_path / "obs.db"), process="seg", min_level="WARNING"
        )
        try:
            log.emit("до правки: рутина", level="INFO")
            store.flush_writers()  # Task 3.3: очередь store-tap'а дожать ДО чтения (write() больше не синхронна)
            before = store.list_records(process="seg", severity_in=["info"])
            assert before == [], f"порог WARNING обязан ГЛУШИТЬ INFO ДО переустановки: {before}"

            taps = reapply_observability_store_level(store, None, log, "seg", "INFO")

            log.emit("после правки: рутина", level="INFO")
            store.flush_writers()  # Task 3.3: очередь store-tap'а дожать ДО чтения (write() больше не синхронна)
            after = store.list_records(process="seg", severity_in=["info"])
            assert len(after) == 1, f"порог понижен до INFO — запись обязана лечь: {after}"
        finally:
            unwire_observability_store(store, taps)

    def test_store_is_none_is_a_noop(self):
        """``store=None`` (стор не поднят, `history.enabled=False`) — no-op со
        списком ``[]``, симметрично `wire_observability_store` без менеджеров."""
        assert reapply_observability_store_level(None, None, None, "seg", "WARNING") == []

    def test_reapply_never_calls_remove_tap_no_absence_window(self, tmp_path):
        """Структурное доказательство отсутствия окна «tap отсутствует».

        Потоковая гонка (см. `TestReapplyStoreLevelRace`) не доказывает это
        свойство надёжно: ручная проверка (2000x8 переустановок против 6
        эмиттеров, `sys.setswitchinterval(0.00001)`) НЕ уронила ни одного
        исключения даже на инъекции, воспроизводящей наивный `remove_tap`+
        `add_tap` — похоже, `list(dict.values())` в CPython не отдаёт GIL
        посередине своего C-вызова, и поэтому потоковый стресс не отличает
        безопасную реализацию от отвергнутой альтернативы. Здесь то же
        свойство доказывается СТРУКТУРНО и детерминированно: `remove_tap`
        не вызывается вовсе, значит окна «pop случился, add ещё не случился»
        нет ПО УСТРОЙСТВУ кода, а не по везению таймингов теста.
        """

        class _SpyLoggerCore(FakeLoggerCore):
            def __init__(self) -> None:
                super().__init__()
                self.remove_calls: list = []

            def remove_tap(self, name):
                self.remove_calls.append(name)
                return super().remove_tap(name)

        log = _SpyLoggerCore()
        store, taps = wire_observability_store(None, log, db_path=str(tmp_path / "obs.db"), process="seg")
        try:
            reapply_observability_store_level(store, None, log, "seg", "WARNING")
            assert log.remove_calls == [], (
                f"reapply вызвал remove_tap{log.remove_calls} — значит между ним и следующим "
                "add_tap есть окно, в котором запись, пришедшая ровно в этот момент, "
                "потерялась бы молча (ноль tap'ов у эмиссии)"
            )
        finally:
            unwire_observability_store(store, taps)

    def test_reused_channel_names_stay_the_same_across_reapply(self, tmp_path):
        """Реестр имён tap'ов не разрастается: переустановка — замена ПО ИМЕНИ,
        не добавление второго tap'а рядом (иначе запись задваивалась бы)."""
        err, log = FakeLoggerCore(), FakeLoggerCore()
        store, taps = wire_observability_store(
            err, log, db_path=str(tmp_path / "obs.db"), process="seg", min_level="INFO"
        )
        try:
            new_taps = reapply_observability_store_level(store, err, log, "seg", "WARNING")
            assert {name for _, name in new_taps} == {STORE_ERROR_TAP, STORE_LOGGER_TAP}
            assert len(err._taps) == 1 and len(log._taps) == 1, (
                f"переустановка обязана ЗАМЕНИТЬ запись по имени, а не добавить вторую: "
                f"err={err._taps.keys()} log={log._taps.keys()}"
            )
        finally:
            unwire_observability_store(store, taps)


def _race_logger_config(tmp_path, name: str) -> dict:
    return {
        "app_name": name,
        "log_directory": str(tmp_path),
        "enable_batching": False,
        "modules": {},
        "channels": {"a": {"type": "file", "enabled": True, "file_path": str(tmp_path / f"{name}.log")}},
        "scopes": {"SYSTEM": {"channels": ["a"]}, "BUSINESS": {"channels": ["a"]}, "DEBUG": {"channels": ["a"]}},
    }


class TestReapplyStoreLevelRace:
    """Опасность, названная ADR-PM-047 и НЕ проверенная задачей 2.2: «что если
    два ``config.reload`` подряд гонятся за одним и тем же tap'ом».

    Харнес — РЕАЛЬНЫЙ ``LoggerManager`` (не ``FakeLoggerCore``): гонка живёт в
    `ChannelRoutingManager._tap_sinks` настоящего менеджера и его реальном пути
    записи (`_emit_to_taps`, `list(self._tap_sinks.values())` — снимок ПЕРЕД
    итерацией), а фальшивка своего снимка не делает и могла бы скрыть проблему
    по совпадению, а не по факту её отсутствия.

    Предсказание ДО прогона: поток-эмиттер и потоки-переустановщики не должны
    уронить друг друга исключением (`RuntimeError` на изменение словаря во время
    итерации — ровно тот класс гонки, которого автор 2.2 испугался), а реестр
    ``_tap_sinks`` после шторма обязан содержать ОБА tap'а с порогом, равным
    ОДНОМУ из двух гонящихся значений (last-write-wins), а не мусором и не
    отсутствующим ключом.
    """

    def test_concurrent_reapply_and_concurrent_emit_never_crash_and_leave_a_valid_threshold(self, tmp_path):
        import threading

        from multiprocess_framework.modules.channel_routing_module.levels import threshold_severity
        from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager

        logger = LoggerManager(manager_name="RaceLogger", config=_race_logger_config(tmp_path, "race"))
        logger.initialize()
        store, taps = wire_observability_store(
            None, logger, db_path=str(tmp_path / "race.db"), process="seg", min_level="INFO"
        )
        errors: list[BaseException] = []
        stop = threading.Event()

        def hammer_reapply(level: str) -> None:
            try:
                for _ in range(200):
                    reapply_observability_store_level(store, None, logger, "seg", level)
            except BaseException as exc:  # noqa: BLE001 — стресс-поток обязан донести исключение наверх
                errors.append(exc)

        def hammer_emit() -> None:
            try:
                i = 0
                while not stop.is_set():
                    logger.info(f"race-{i}")
                    i += 1
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        emitters = [threading.Thread(target=hammer_emit) for _ in range(3)]
        reapplyers = [
            threading.Thread(target=hammer_reapply, args=(lvl,)) for lvl in ("WARNING", "INFO", "WARNING", "INFO")
        ]
        try:
            for t in emitters + reapplyers:
                t.start()
            for t in reapplyers:
                t.join(timeout=30)
                assert not t.is_alive(), "переустановщик не завершился за 30с — подозрение на deadlock"
            stop.set()
            for t in emitters:
                t.join(timeout=5)
                assert not t.is_alive(), "эмиттер не завершился за 5с после stop — подозрение на deadlock"

            assert errors == [], f"гонку уронило исключением в потоке: {errors!r}"

            sinks = logger._tap_sinks  # noqa: SLF001 — тест сознательно инспектирует внутренний реестр
            assert STORE_LOGGER_TAP in sinks, "tap логгера пропал под гонкой переустановки"
            _, threshold = sinks[STORE_LOGGER_TAP]
            assert threshold in (threshold_severity("INFO"), threshold_severity("WARNING")), (
                f"порог после гонки обязан быть ОДНИМ ИЗ ДВУХ валидных значений "
                f"(last-write-wins), а не мусором: {threshold}"
            )
        finally:
            stop.set()
            unwire_observability_store(store, taps)
            logger.shutdown()
