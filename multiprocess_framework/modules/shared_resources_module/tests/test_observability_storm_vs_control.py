"""Шторм хвоста против управляющего трафика — пара «до/после» Ф7.3.

Живой прогон Б-6 (`webcam_sketch`, ~25 мин) намерил, во что обходится общий сосуд:
97 066 отказов доставки, 21 903 потерянных записи логгера, 303 016 строк в сторе.
Синтетические стенды g1/dualcam шторма НЕ воспроизводят (проверено прогоном
2026-08-06: 0 ошибок, очереди пусты) — поэтому пара воспроизводится здесь, на
настоящих объектах: настоящая ``QueueRegistry``, настоящие очереди с прод-глубинами
(system=100 из ``DEFAULT_QUEUES``, observability=256).

Стенд один, различается ТОЛЬКО класс груза у записей:

  * **до Ф7.3** — записи едут ``queue_type="system"``, в тот же сосуд, что heartbeat;
  * **после** — своим классом.

Сторожатся ровно два обещания приёмки:
  1. шторм записей не отнимает мест у управления (heartbeat доезжает);
  2. отказ доставки хвоста НЕ порождает новой записи (петля разорвана).
"""

from __future__ import annotations

import queue as _queue

import pytest

from ..queues import QueueRegistry
from ..queues.core import manager as manager_module
from ..state.process_data import ProcessDataKeys
from ..state.process_state_registry import ProcessStateRegistry

OBS = ProcessDataKeys.QUEUE_OBSERVABILITY

#: Глубины — прод (``DEFAULT_QUEUES``), не удобные для теста. Сотня мест у system —
#: та самая, в которую упирался живой шторм.
SYSTEM_DEPTH = 100
OBS_DEPTH = 256
#: Записей в шторме: заведомо больше обеих глубин, чтобы переполнение случилось
#: наверняка, но достаточно мало для мгновенного теста.
STORM = 2_000
#: Тактов управления, пущенных ПОСЛЕ шторма — как heartbeat после всплеска логов.
HEARTBEATS = 20


class _Probe:
    """Счётчик записей: любая запись под штормом — звено петли самоусиления."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def __getattr__(self, level):
        def _write(msg, *args, **kwargs):
            self.records.append((level.upper(), msg % args if args else msg))

        return _write


@pytest.fixture
def probe(monkeypatch):
    p = _Probe()
    monkeypatch.setattr(manager_module, "_loss_logger", p)
    return p


def _stand() -> tuple[QueueRegistry, dict[str, _queue.Queue]]:
    """Подписчик 'gui', который НИЧЕГО не дренирует — модель отставшего потребителя."""
    psr = ProcessStateRegistry()
    psr.register_process("gui")
    queues = {
        "system": _queue.Queue(maxsize=SYSTEM_DEPTH),
        OBS: _queue.Queue(maxsize=OBS_DEPTH),
    }
    for qtype, q in queues.items():
        psr.add_queue("gui", qtype, q)
    reg = QueueRegistry(process_state_registry=psr)
    reg.initialize()
    return reg, queues


def _storm(reg: QueueRegistry, qtype: str) -> None:
    for i in range(STORM):
        reg.send_to_queue("gui", qtype, {"command": "log.record", "sender": "camera_0", "i": i})


def _heartbeats(reg: QueueRegistry) -> int:
    """Сколько управляющих тактов доехало (system-почта, never-drop)."""
    return sum(
        1
        for i in range(HEARTBEATS)
        if reg.send_to_queue("gui", "system", {"type": "system", "command": "heartbeat", "i": i})
    )


class TestStormOfRecordsVersusControlPlane:
    def test_before_split_storm_starves_the_control_plane(self, probe):
        """ДО Ф7.3 (воспроизведение): записи в system-почте забивают её целиком,
        и ни один последующий heartbeat не доезжает — never-drop не вытесняет."""
        reg, queues = _stand()

        _storm(reg, "system")
        delivered = _heartbeats(reg)

        assert queues["system"].qsize() == SYSTEM_DEPTH  # сотня мест занята записями
        assert delivered == 0, "весь control-plane потерян — это и есть беда Б-6"
        assert reg.system_evict_blocked > 0
        assert reg.never_drop_loss_total > 0
        # И каждая потеря говорила: записи, порождённые отказом доставки записей.
        assert probe.records, "на system-пути потеря пишет в лог — звено петли"

    def test_after_split_control_plane_survives_the_same_storm(self, probe):
        """ПОСЛЕ Ф7.3: тот же шторм в свой класс груза — управление не задето."""
        reg, queues = _stand()

        _storm(reg, OBS)
        delivered = _heartbeats(reg)

        assert delivered == HEARTBEATS, "heartbeat обязан доезжать при любом объёме диагностики"
        assert queues["system"].qsize() == HEARTBEATS
        assert reg.system_evict_blocked == 0
        assert reg.never_drop_loss_total == 0
        # Хвост при этом ЧЕСТНО потерял старейшее — и потеря видна счётчиком.
        assert reg.observability_evicted == STORM - OBS_DEPTH
        assert queues[OBS].qsize() == OBS_DEPTH

    def test_after_split_the_storm_writes_no_records(self, probe):
        """Пара на самоусиление: шторм на 2 000 записей не порождает НИ ОДНОЙ новой
        записи. До расщепления тот же шторм писал их сотнями (тест выше)."""
        reg, _queues = _stand()
        probe.records.clear()

        _storm(reg, OBS)

        assert probe.records == []

    def test_loss_is_visible_where_it_is_supposed_to_be(self, probe):
        """«Терять можно, молчать нельзя»: молчат ЛОГИ, а не система. Потеря
        доступна интроспекции пер-жертвенно — «где», а не только «сколько»."""
        reg, _queues = _stand()

        _storm(reg, OBS)

        stats = reg.get_stats()["queues"]
        assert stats["observability_evicted"] == STORM - OBS_DEPTH
        assert stats[f"observability_evicted.gui.{OBS}"] == STORM - OBS_DEPTH
        # И «чей груз» — тоже: отправитель назван.
        assert stats["senders"][f"gui_{OBS}"]["camera_0"]["put"] == STORM
