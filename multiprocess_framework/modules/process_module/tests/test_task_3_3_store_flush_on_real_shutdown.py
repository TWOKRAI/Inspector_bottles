# -*- coding: utf-8 -*-
"""Task 3.3, критерий 7 на ЖИВОЙ ПРОВОДКЕ: строку об исходе выпускает ОСТАНОВ.

**Почему этот файл существует отдельно от приёмочного набора.** Приёмочный тест
критерия 7 зовёт ``StoreTapChannel.close()`` рукой — и был бы зелёным даже если
бы этот метод в проде не звал НИКТО. А до Task 3.3 его действительно не звал
никто: ``LoggerCore.shutdown`` закрывает только ``_channel_registry``
(``logger_core.py``), а tap живёт в ОТДЕЛЬНОМ механизме
(``ChannelRoutingManager.add_tap``/``remove_tap``) и в реестр каналов не
попадает намеренно — чтобы пережить ``reconfigure``. Пока ``close()`` у tap'а
был no-op, это было безвредно; с очередью внутри стало дырой: накопленное
исчезало бы молча, а строка ``store flush: N записано, M потеряно`` не
появилась бы в проде НИКОГДА.

Правило проекта: где поверхность проверена на подделках, нужен один тест на
живой проводке. Здесь поднимаются НАСТОЯЩИЕ ``LoggerManager``,
``wire_observability_store`` и ``ObservabilityStore``, а останов зовётся тем же
методом, каким его зовёт процесс, — ``shutdown()``. Объект tap'а тесту
недоступен вовсе: он живёт внутри менеджера.

Свидетельство берётся из ФАЙЛА журнала, а не из ``caplog``: на живой проводке
``get_std_logger`` связывается с поднятым ``LoggerManager`` и строка уходит в
его канал, а не в stdlib. ``caplog`` увидел бы её только в вырожденном режиме
«менеджера нет» — то есть доказывал бы обратное тому, что нужно.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest

from multiprocess_framework.modules.channel_routing_module.observability import ObservabilityStore
from multiprocess_framework.modules.channel_routing_module.observability.store_tap import (
    DEFAULT_STORE_QUEUE_CAPACITY,
)
from multiprocess_framework.modules.logger_module.core.logger_manager import LoggerManager
from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    DEFAULT_HISTORY_QUEUE_CAPACITY,
    STORE_LOGGER_TAP,
    resolve_history_policy,
    wire_observability_store,
)

FLUSH_LINE = re.compile(r"store flush: (\d+) записано, (\d+) потеряно")


def _live_logger_with_store(
    tmp_path: Path, queue_capacity: int = DEFAULT_HISTORY_QUEUE_CAPACITY
) -> tuple[LoggerManager, ObservabilityStore]:
    """Настоящий LoggerManager + настоящая проводка стора (та же, что у процесса)."""
    log_mgr = LoggerManager(
        manager_name="ShutdownProbe",
        config={
            "app_name": "probe",
            "log_directory": str(tmp_path),
            "enable_batching": False,
            "channels": {"a": {"type": "file", "enabled": True, "file_path": str(tmp_path / "a.log")}},
            "scopes": {scope: {"channels": ["a"]} for scope in ("BUSINESS", "SYSTEM", "DEBUG", "PERFORMANCE")},
        },
    )
    log_mgr.initialize()
    store, _taps = wire_observability_store(
        None,
        log_mgr,
        db_path=str(tmp_path / "obs.db"),
        process="probe",
        min_level="INFO",
        queue_capacity=queue_capacity,
    )
    return log_mgr, store


class TestTheRealShutdownDrainsAndNamesTheOutcome:
    def test_shutdown_flushes_the_tap_queue_and_logs_the_literal_line(self, tmp_path: Path) -> None:
        """Останов процесса (``shutdown()``) — и только он — дожимает очередь и называет исход."""
        log_mgr, store = _live_logger_with_store(tmp_path)
        journal = tmp_path / "a.log"
        n = 30

        for i in range(n):
            log_mgr.info(f"строка останова {i}", module="probe")

        assert log_mgr.has_tap(STORE_LOGGER_TAP), "предусловие: store-tap обязан стоять"
        assert not FLUSH_LINE.search(journal.read_text(encoding="utf-8")), (
            "строка об исходе прозвучала ДО останова — значит она не про останов"
        )

        # ЕДИНСТВЕННЫЙ вызов — штатный останов менеджера. Ни close(), ни flush()
        # у tap'а тест не зовёт (и не может: объекта у него нет).
        assert log_mgr.shutdown() is True

        assert not log_mgr.has_tap(STORE_LOGGER_TAP), "останов обязан СНЯТЬ tap, а не только дожать"

        matches = FLUSH_LINE.findall(journal.read_text(encoding="utf-8"))
        assert matches, (
            "после НАСТОЯЩЕГО останова в журнале ожидалась строка "
            "'store flush: N записано, M потеряно'; её там нет — значит проводки останова у tap'а "
            "нет, и в проде она не появится никогда"
        )
        written = sum(int(w) for w, _ in matches)
        lost = sum(int(lost_in_line) for _, lost_in_line in matches)

        rows = store.list_records(limit=200)
        mine = [r for r in rows if "строка останова" in str(r["message"])]
        store.close()

        assert lost == 0, f"на спокойном останове потерь быть не должно, названо потеряно={lost}"
        assert len(mine) == n, f"в сторе {len(mine)} моих строк из {n} принятых"
        # Число в строке — про ВСЕ записи очереди, включая собственную «shutting
        # down» менеджера, поэтому сверяется с итогом стора, а не с n.
        assert written == len(rows), (
            f"строка сообщила записано={written}, а в сторе {len(rows)} — счёт и содержимое разошлись"
        )

    def test_records_wait_in_the_queue_instead_of_landing_synchronously(self, tmp_path: Path) -> None:
        """Контроль достижимости первой половины: строки доезжают ДРЕНАЖЕМ, а не записью.

        Без него зелёный тест выше согласился бы и с прежней (синхронной)
        реализацией: строки в сторе были бы, строка об исходе — тоже, и
        очередь была бы ни при чём.

        Проверка привязана ко ВРЕМЕНИ (такт дренажа 100 мс), поэтому она честно
        отказывается судить, если цикл записи сам занял сравнимое время:
        молчаливое «зелено» на занятой машине означало бы «не проверил», а не
        «проверил и сошлось».
        """
        log_mgr, store = _live_logger_with_store(tmp_path)
        try:
            t0 = time.perf_counter()
            for i in range(30):
                log_mgr.info(f"строка без останова {i}", module="probe")
            immediate = [r for r in store.list_records(limit=200) if "без останова" in str(r["message"])]
            elapsed = time.perf_counter() - t0
            if elapsed > 0.05:  # половина такта дренажа — окно наблюдения закрылось
                pytest.skip(f"цикл записи занял {elapsed * 1000:.0f} мс при такте дренажа 100 мс — не сужу")
            assert immediate == [], (
                f"запись доехала до стора БЕЗ дренажа за {elapsed * 1000:.1f} мс — "
                f"значит write() всё ещё синхронна: {len(immediate)} строк"
            )
            # И вторая половина того же факта: дожатие ДОВОДИТ их до БД.
            store.flush_writers(timeout=2.0)
            after = [r for r in store.list_records(limit=200) if "без останова" in str(r["message"])]
            assert len(after) == 30, f"после дожатия ожидались все 30 строк, получено {len(after)}"
        finally:
            log_mgr.shutdown()
            store.close()


class TestTheQueueCapacityKnobActuallyReachesTheQueue:
    """``observability.history.queue_capacity`` — ручка, а не ключ, который ничего не значит.

    Класс дефекта назван в докстринге самой схемы: до задачи 2.2 ``enabled`` и
    ``db_path`` существовали в конфиге и не влияли ни на что. Ручка без сторожа
    на ДОРОГЕ «схема → политика → проводка → очередь» повторила бы это ровно.
    """

    def test_a_non_default_capacity_travels_from_the_policy_into_the_tap_queue(self, tmp_path: Path) -> None:
        """Литерал НЕ дефолтный: с дефолтом тест согласился бы и с оборванной дорогой."""
        log_mgr, store = _live_logger_with_store(tmp_path, queue_capacity=17)
        try:
            tap = log_mgr._tap_sinks[STORE_LOGGER_TAP][0]  # белый ящик: объекта tap'а наружу нет
            assert tap._worker.capacity == 17, (
                f"ёмкость очереди {tap._worker.capacity} вместо переданных 17 — ручка не доехала "
                f"до очереди (дефолт {DEFAULT_STORE_QUEUE_CAPACITY})"
            )
        finally:
            log_mgr.shutdown()
            store.close()

    def test_the_policy_carries_the_key_and_falls_back_loudly_on_a_bad_value(self) -> None:
        """Политика отдаёт ключ; «0» — не «без потолка», а громкий откат на дефолт.

        У ретеншена ноль означает «предела нет» (объявленный отказ от защиты), и
        скопировать это правило на очередь значило бы либо неограниченный рост
        памяти, либо отказ ``BoundedChannel`` на подъёме процесса.
        """

        class _Svc:
            """Форма фейка взята у ``test_observability_history_policy._Svc`` — читающая
            дорога резолвера (``get_config("observability_app")["history"]``), а не своя."""

            name = "probe"

            def __init__(self, section):
                self._section = section
                self.warnings: list = []

            def get_config(self, key, default=None):
                return {"history": self._section} if key == "observability_app" else default

            def _log_warning(self, message, module=None) -> None:
                self.warnings.append(str(message))

            def _log_info(self, *a, **k) -> None: ...
            def _log_debug(self, *a, **k) -> None: ...

        assert resolve_history_policy(_Svc({}))["queue_capacity"] == DEFAULT_HISTORY_QUEUE_CAPACITY
        assert resolve_history_policy(_Svc({"queue_capacity": 64}))["queue_capacity"] == 64
        zero = _Svc({"queue_capacity": 0})
        assert resolve_history_policy(zero)["queue_capacity"] == DEFAULT_HISTORY_QUEUE_CAPACITY
        assert any("queue_capacity" in w for w in zero.warnings), (
            f"откат на дефолт обязан быть ГРОМКИМ, предупреждений нет: {zero.warnings}"
        )
        junk = _Svc({"queue_capacity": "мусор"})
        assert resolve_history_policy(junk)["queue_capacity"] == DEFAULT_HISTORY_QUEUE_CAPACITY
        assert any("queue_capacity" in w for w in junk.warnings), junk.warnings
