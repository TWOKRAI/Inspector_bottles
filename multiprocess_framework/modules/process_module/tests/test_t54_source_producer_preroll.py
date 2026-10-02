# -*- coding: utf-8 -*-
"""Task 5.4 — preroll в SourceProducer: источник ждёт готовности потребителей.

Независимые acceptance-тесты (слепой тестер, до реализации). Источник контракта —
раздел «Task 5.4» phase-5.md: ``SourceProducer(ready_event=..., log_warning=...)``,
константа ``DEFAULT_PREROLL_TIMEOUT_S = 10.0`` в ``source_producer.py``, ожидание
кусками <= 0.05 с с проверкой ``stop_event``, срок истёк -> ровно одна строка
``log_warning`` с текстом ``preroll`` и старт, стоп во время ожидания -> выход
<= 0.1 с без ``produce()`` и без предупреждения, ``ready_event is None`` -> как раньше.

Решения тестера (зафиксированы в отчёте):

* Срок preroll в тестах укорачиваем патчем модульной константы
  ``source_producer.DEFAULT_PREROLL_TIMEOUT_S`` (в брифе у конструктора нет ключа срока).
  Следствие-контракт: реализация обязана ЧИТАТЬ константу в момент ожидания/создания
  (глобал модуля), а не зашивать её дефолтом параметра при импорте — иначе патч не
  подействует и тесты срока красные. Само значение 10.0 пинится отдельным тестом литералом.
* Сетка Windows 15.6 мс: где спека даёт числа (50 мс, 100 мс, срок 0.2 с), к границе
  добавлен ``GRID_S``. Нижняя граница срока — «не раньше срока минус сетка».
* Источник кадров — счётчик в ``produce()`` (метка ``perf_counter``), ``send`` — заглушка:
  наблюдаем число вызовов produce, а не имя метода.
* Каждый поток — daemon, ожидание — опросом с дедлайном; teardown всегда ставит stop и join.
"""

from __future__ import annotations

import multiprocessing
import threading
import time

import pytest

from multiprocess_framework.modules.process_module.generic import source_producer as sp_mod
from multiprocess_framework.modules.process_module.generic.source_producer import SourceProducer

#: Шаг таймера Windows: границы со спеки (50/100 мс, срок) допускают +1 такт.
GRID_S = 0.0156

#: Кратковременный срок preroll для тестов таймаута.
SHORT_TIMEOUT_S = 0.2


class _CountingSource:
    """Source-плагин: каждый produce() фиксирует метку времени, кадров не отдаёт."""

    is_source = True

    def __init__(self) -> None:
        self.name = "t54_cam"
        self.stamps: list[float] = []

    def produce(self) -> list:
        self.stamps.append(time.perf_counter())
        return []


class _Rig:
    """Один SourceProducer в daemon-потоке + всё, что нужно для наблюдения и уборки."""

    def __init__(self, ready_event, *, with_warning_sink: bool = True, omit_ready_kwarg: bool = False) -> None:
        self.plugin = _CountingSource()
        self.warnings: list[str] = []
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        kwargs: dict = {}
        if not omit_ready_kwarg:
            kwargs["ready_event"] = ready_event
        if with_warning_sink:
            kwargs["log_warning"] = self.warnings.append
        self.producer = SourceProducer(
            plugin=self.plugin,
            shm_middleware=None,
            send_fn=lambda target, msg: None,
            chain_targets=[],
            target_fps=200.0,  # интервал 5 мс — первый кадр после старта не ждёт темпа
            node_name="t54_cam",
            **kwargs,
        )
        self.thread = threading.Thread(
            target=self.producer.run_loop,
            args=(self.stop_event, self.pause_event),
            name="t54-source-producer",
            daemon=True,
        )
        self.t_started = 0.0

    def start(self) -> None:
        self.t_started = time.perf_counter()
        self.thread.start()

    def wait_first_frame(self, deadline_s: float) -> bool:
        end = time.perf_counter() + deadline_s
        while time.perf_counter() < end:
            if self.plugin.stamps:
                return True
            time.sleep(0.002)
        return bool(self.plugin.stamps)

    def close(self) -> None:
        self.stop_event.set()
        self.thread.join(timeout=3.0)


@pytest.fixture
def rigs():
    made: list[_Rig] = []

    def _make(ready_event, **kw) -> _Rig:
        rig = _Rig(ready_event, **kw)
        made.append(rig)
        return rig

    yield _make
    for rig in made:
        rig.close()
    leaked = [r.thread.name for r in made if r.thread.is_alive()]
    assert not leaked, f"поток SourceProducer не вышел после stop_event: {leaked}"


@pytest.fixture
def short_preroll(monkeypatch):
    monkeypatch.setattr(sp_mod, "DEFAULT_PREROLL_TIMEOUT_S", SHORT_TIMEOUT_S, raising=False)


_EVENT_FACTORIES = [
    pytest.param(threading.Event, id="threading.Event"),
    pytest.param(multiprocessing.Event, id="multiprocessing.Event"),
]


# ---------------------------------------------------------------------------
# Константа срока
# ---------------------------------------------------------------------------


def test_default_preroll_timeout_constant_is_ten_seconds() -> None:
    # Литерал из спеки; значение не пересчитывается из кода.
    assert sp_mod.DEFAULT_PREROLL_TIMEOUT_S == 10.0


# ---------------------------------------------------------------------------
# Ожидание: невзведённое событие держит источник, взведённое — отпускает
# ---------------------------------------------------------------------------


@pytest.mark.timeout(15)
@pytest.mark.parametrize("make_event", _EVENT_FACTORIES)
def test_unset_event_blocks_all_frames_for_200ms(rigs, make_event) -> None:
    rig = rigs(make_event())
    rig.start()
    time.sleep(0.2)
    assert rig.plugin.stamps == [], f"produce() вызван {len(rig.plugin.stamps)} раз при невзведённом событии"
    assert rig.warnings == []  # срок 10 с далеко: за 200 мс предупреждения быть не может


@pytest.mark.timeout(15)
@pytest.mark.parametrize("make_event", _EVENT_FACTORIES)
def test_first_frame_within_50ms_after_event_set(rigs, make_event) -> None:
    ev = make_event()
    rig = rigs(ev)
    rig.start()
    time.sleep(0.15)  # поток гарантированно внутри ожидания
    assert rig.plugin.stamps == []
    t_set = time.perf_counter()
    ev.set()
    assert rig.wait_first_frame(1.0), "после set() кадров нет за секунду"
    latency = rig.plugin.stamps[0] - t_set
    assert latency <= 0.050 + GRID_S, f"первый кадр через {latency * 1000:.1f} мс после set()"


@pytest.mark.timeout(15)
def test_pre_set_event_means_no_wait_at_all(rigs) -> None:
    """Рестарт процесса: событие уже взведено -> ожидания нет, предупреждения нет."""
    ev = threading.Event()
    ev.set()
    rig = rigs(ev)
    rig.start()
    assert rig.wait_first_frame(1.0)
    assert rig.plugin.stamps[0] - rig.t_started <= 0.050 + GRID_S
    assert rig.warnings == []


# ---------------------------------------------------------------------------
# Срок: истёк -> старт и ровно одно предупреждение
# ---------------------------------------------------------------------------


@pytest.mark.timeout(15)
def test_timeout_starts_frames_not_before_the_deadline(rigs, short_preroll) -> None:
    rig = rigs(threading.Event())  # никто не взведёт
    rig.start()
    assert rig.wait_first_frame(2.0), "срок 0.2 с истёк, а источник так и не стартовал"
    waited = rig.plugin.stamps[0] - rig.t_started
    assert waited >= SHORT_TIMEOUT_S - GRID_S, f"старт через {waited * 1000:.0f} мс — раньше срока 200 мс"
    assert waited <= SHORT_TIMEOUT_S + 0.5, f"старт через {waited * 1000:.0f} мс — срок не соблюдён"


@pytest.mark.timeout(15)
def test_timeout_emits_exactly_one_preroll_warning(rigs, short_preroll) -> None:
    rig = rigs(threading.Event())
    rig.start()
    assert rig.wait_first_frame(2.0)
    time.sleep(0.3)  # кадры идут дальше — повторного предупреждения быть не должно
    assert len(rig.plugin.stamps) >= 3, "после срока источник должен продолжать крутиться"
    assert len(rig.warnings) == 1, rig.warnings
    assert "preroll" in rig.warnings[0].lower(), rig.warnings[0]


@pytest.mark.timeout(15)
def test_event_set_before_deadline_gives_no_warning(rigs, monkeypatch) -> None:
    monkeypatch.setattr(sp_mod, "DEFAULT_PREROLL_TIMEOUT_S", 0.6, raising=False)
    ev = threading.Event()
    rig = rigs(ev)
    rig.start()
    time.sleep(0.15)
    ev.set()
    assert rig.wait_first_frame(1.0)
    time.sleep(0.8)  # перекрываем исходный срок 0.6 с — предупреждение не должно прийти позже
    assert rig.warnings == []


@pytest.mark.timeout(15)
def test_timeout_without_warning_sink_still_starts_and_does_not_crash(rigs, short_preroll) -> None:
    rig = rigs(threading.Event(), with_warning_sink=False)
    rig.start()
    assert rig.wait_first_frame(2.0), "log_warning=None не должен ломать старт по сроку"
    assert rig.thread.is_alive()


# ---------------------------------------------------------------------------
# Стоп во время preroll
# ---------------------------------------------------------------------------


# Задержки стопа разведены по фазе: ожидание кусками, большими 0.1 с, пропустило бы стоп,
# пришедший сразу после границы куска (0.21 с — сразу после границы куска 0.2 с).
@pytest.mark.timeout(15)
@pytest.mark.parametrize("stop_delay_s", [0.06, 0.15, 0.21])
@pytest.mark.parametrize("make_event", _EVENT_FACTORIES)
def test_stop_during_preroll_exits_within_100ms_without_produce_or_warning(rigs, make_event, stop_delay_s) -> None:
    rig = rigs(make_event())  # срок по умолчанию 10 с — стоп приходит заведомо раньше
    rig.start()
    time.sleep(stop_delay_s)
    assert rig.thread.is_alive()
    t_stop = time.perf_counter()
    rig.stop_event.set()
    rig.thread.join(timeout=1.0)
    exit_after = time.perf_counter() - t_stop
    assert not rig.thread.is_alive(), "поток не вышел за 1 с после stop_event во время preroll"
    assert exit_after <= 0.100 + GRID_S, f"выход через {exit_after * 1000:.1f} мс после stop_event"
    assert rig.plugin.stamps == [], "produce() вызван во время/после стопа в preroll"
    assert rig.warnings == [], rig.warnings


@pytest.mark.timeout(15)
def test_stop_set_before_start_never_produces(rigs) -> None:
    """Стоп взведён ДО входа в ожидание: ни produce(), ни ожидания 10 с."""
    rig = rigs(threading.Event())
    rig.stop_event.set()
    rig.start()
    rig.thread.join(timeout=1.0)
    assert not rig.thread.is_alive()
    assert rig.plugin.stamps == []
    assert rig.warnings == []


# ---------------------------------------------------------------------------
# ready_event is None -> прежнее поведение
# ---------------------------------------------------------------------------


@pytest.mark.timeout(15)
def test_ready_event_omitted_frames_immediately_control(rigs) -> None:
    """КОНТРОЛЬ: без ready_event поведение прежнее (проходит и до реализации)."""
    rig = rigs(None, omit_ready_kwarg=True, with_warning_sink=False)
    rig.start()
    assert rig.wait_first_frame(1.0)
    assert rig.plugin.stamps[0] - rig.t_started <= 0.2


@pytest.mark.timeout(15)
def test_ready_event_none_frames_immediately_without_warning(rigs) -> None:
    rig = rigs(None)
    rig.start()
    assert rig.wait_first_frame(1.0)
    assert rig.plugin.stamps[0] - rig.t_started <= 0.2
    time.sleep(0.3)
    assert rig.warnings == []
