# -*- coding: utf-8 -*-
"""Слепые приёмочные тесты T13: очередь кадров источника камеры (`source_queue_frames`, метрика `overwritten`).

Purpose: закрепить контракт очереди перед реализацией. Вместо одного слота `CameraDevicePlugin` хранит
до K последних кадров (K = register `source_queue_frames`, умолчание 4, 1 = прежнее поведение: только
последний кадр); `produce()` забирает всё накопленное и отдаёт items в порядке `seq_id`; кадр, вытесненный
из полной очереди, считается метрикой `overwritten`, которая публикуется рядом с `frames`; `dropped`
(битые кадры) не меняется.

Написаны ДО кода по вырезке DESIGN/CONTRACT/ACCEPTANCE задачи T13, без чтения реализации. Плагин настоящий
(`PluginContext` над `MockProcessServices`, настоящий `WorkerManager`), порт — фейк (как в `test_plugin_base.py`),
кадр доставляется настоящим `_on_frame(RawFrame)`, забор — настоящим `produce()`. Метрики наблюдаются как в
`test_plugin_observability.py`: подмена `ctx.publish_metric` пишет пары `(имя, значение)`, окно публикации
сжато `_TICK_S = 0.0`. Register задаётся конфигом до `configure()`. Ожидаемые значения — литералы ACCEPTANCE.
Часть пунктов ожидаемо красная до кода (очереди ещё нет); `test_produce_drains_queue_...` — защита прежнего
поведения (зелёная и до кода).
"""

from __future__ import annotations

import threading
import time

import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import MockProcessServices
from multiprocess_framework.modules.worker_module import WorkerManager
from Services.camera_device import plugin_base
from Services.camera_device.interface import RawFrame
from Services.camera_device.plugin_base import CameraDevicePlugin
from Services.camera_device.testing.fake_port import make_port

__all__: list[str] = []

PROCESS_NAME = "cam_queue"
BASE_CFG = {"auto_start": False, "camera_id": 3, "device_select": "serial", "device_serial": "FAKE-0001"}

# Паспорт прогона «25 кадр/с, опрос 25 Гц, 4 с» (секунды).
FRAME_PERIOD_S = 0.04
FRAMES_TOTAL = 100
POLL_PHASE_S = 0.015  # обычный опрос: через 15 мс после кадра j, кадр j+1 ещё не пришёл (до него 25 мс)
POLL_LATE_PHASE_S = 0.065  # запоздавший опрос: после кадра j+1 (он в +40 мс; запас на сон Windows ~16 мс)
POLL_LATE_EVERY = 5  # каждый пятый опрос запаздывает: между опросами оказывается два кадра


# ---------------------------------------------------------------------------------------------- #
# Каркас
# ---------------------------------------------------------------------------------------------- #


def _frame(number: int) -> RawFrame:
    """Кадр 4x2 mono8, все 8 байт равны `number`: по содержимому item видно, чей это кадр."""
    return RawFrame(bytearray([number % 256]) * 8, 4, 2, "mono8", number)


class _Rig:
    """Плагин над фейковым портом; опубликованные метрики копятся в `published` как `(имя, значение)`."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, cfg: dict) -> None:
        self.port = make_port(frame_period_s=0.02)
        monkeypatch.setattr(plugin_base, "create_port", lambda driver: self.port)
        monkeypatch.setattr(plugin_base, "_TICK_S", 0.0)  # каждый produce() публикует метрики
        config = {**BASE_CFG, **cfg}
        self.published: list[tuple[str, object]] = []
        self.services = MockProcessServices(name=PROCESS_NAME, config=config)
        self.wm = WorkerManager("test_cam_queue")
        self.services.worker_manager = self.wm
        self.ctx = PluginContext(services=self.services, config=config, plugin_name=CameraDevicePlugin.name)
        publish = self.ctx.publish_metric
        self.ctx.publish_metric = lambda name, value: (self.published.append((name, value)), publish(name, value))[0]
        self.plugin = CameraDevicePlugin()
        self.plugin.configure(self.ctx)

    def feed(self, *numbers: int) -> None:
        for number in numbers:
            self.plugin._on_frame(_frame(number))

    def poll(self) -> list[dict]:
        """`produce()` с дедлайном: зависший забор не вешает набор."""
        return _bounded(self.plugin.produce)

    def metric(self, name: str) -> object:
        """Последнее опубликованное значение метрики; метрики нет -> AssertionError с перечнем имён."""
        values = [value for published_name, value in self.published if published_name == name]
        assert values, f"метрика {name!r} не публиковалась; опубликованы: {sorted({n for n, _ in self.published})}"
        return values[-1]

    def close(self) -> None:
        if hasattr(self.plugin, "_session"):  # configure не дошёл до конца — освобождать нечего
            self.plugin.shutdown(self.ctx)
        self.wm.stop_all_workers(2.0)


def _bounded(fn, seconds: float = 10.0):
    """Вызов в daemon-потоке с дедлайном; исключение вызова пробрасывается."""
    box: dict = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — пробрасываем в поток теста как есть
            box["exc"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(seconds)
    assert not thread.is_alive(), f"вызов не вернулся за {seconds} с"
    if "exc" in box:
        raise box["exc"]
    return box.get("value")


@pytest.fixture
def make(monkeypatch):
    rigs: list[_Rig] = []

    def factory(**cfg) -> _Rig:
        rig = _Rig(monkeypatch, cfg)
        rigs.append(rig)
        return rig

    yield factory
    for rig in rigs:
        rig.close()


def _seq(items: list[dict]) -> list[int]:
    return [item["seq_id"] for item in items]


def _fill(items: list[dict]) -> list[int]:
    """Содержимое кадра каждого item (первый пиксель): номер кадра, который туда лёг."""
    return [int(item["frame"][0, 0]) for item in items]


# ---------------------------------------------------------------------------------------------- #
# Доставка нескольких кадров между опросами
# ---------------------------------------------------------------------------------------------- #


def test_three_frames_between_polls_all_delivered(make):
    """3 кадра между опросами при умолчании K=4 -> 3 items с seq_id 1, 2, 3 (до правки один item с seq_id 3).

    Содержимое кадров 1, 2, 3 не склеено: очередь держит три разных буфера, а не один переписанный.
    """
    rig = make()
    rig.feed(1, 2, 3)
    items = rig.poll()
    assert _seq(items) == [1, 2, 3]
    assert [item["device_frame_num"] for item in items] == [1, 2, 3]
    assert _fill(items) == [1, 2, 3]


def test_exactly_k_frames_all_delivered_none_overwritten(make):
    """Граница очереди, нижняя сторона: ровно K=4 кадра -> 4 items, `overwritten == 0` (ничего не вытеснено)."""
    rig = make()
    rig.feed(1, 2, 3, 4)
    items = rig.poll()
    rig.poll()  # второй вызов: тик публикует метрики
    assert _seq(items) == [1, 2, 3, 4]
    assert rig.metric("overwritten") == 0


def test_produce_drains_queue_second_poll_is_empty(make):
    """`produce()` забирает всё: сразу второй вызов даёт пустой список, а новый кадр после него — один item.

    Защита прежнего поведения (зелёная и до кода): забранное не отдаётся повторно.
    """
    rig = make()
    rig.feed(1, 2)
    assert rig.poll() != []  # что именно отдано — проверяют другие тесты; здесь важно, что забрано
    assert rig.poll() == []
    rig.feed(3)
    assert _seq(rig.poll()) == [3]


# ---------------------------------------------------------------------------------------------- #
# Переполнение и метрика overwritten
# ---------------------------------------------------------------------------------------------- #


def test_overflow_counts_overwritten(make):
    """K=4 и 6 кадров -> 4 items с seq_id 3, 4, 5, 6; `overwritten == 2`; `dropped == 0` (вытеснение не брак)."""
    rig = make(source_queue_frames=4)
    rig.feed(1, 2, 3, 4, 5, 6)
    items = rig.poll()
    rig.poll()  # второй вызов: тик публикует метрики
    assert _seq(items) == [3, 4, 5, 6]
    assert _fill(items) == [3, 4, 5, 6]
    assert rig.metric("overwritten") == 2
    assert rig.metric("dropped") == 0


def test_overwritten_metric_published(make):
    """Метрика `overwritten` публикуется рядом с `frames` и `dropped`, значение накопительное.

    Решение: публикуется всегда (как `dropped`), в том числе 0 без вытеснений; значение — счёт с начала работы,
    не приращение за окно. Без вытеснений 2 кадра -> 0; после забора ещё 5 кадров при K=4 (очередь пуста,
    пятый кадр вытесняет первый из них) -> 1.
    """
    rig = make()
    rig.feed(1, 2)
    rig.poll()
    rig.poll()
    names = {name for name, _ in rig.published}
    assert {"frames", "dropped", "overwritten"} <= names
    assert rig.metric("overwritten") == 0
    rig.feed(3, 4, 5, 6, 7)  # очередь пуста после забора: 5 кадров на K=4 -> вытеснен один (кадр 3)
    rig.poll()
    rig.poll()
    assert rig.metric("overwritten") == 1


def test_broken_frame_counts_dropped_not_overwritten(make):
    """Битый кадр (длина буфера 3, нужно 12) -> `dropped == 1`, `overwritten == 0`: счётчики не смешаны."""
    rig = make()
    rig.plugin._on_frame(RawFrame(data=bytearray(3), width=2, height=2, pixel_format="rgb8", frame_num=1, extras={}))
    rig.poll()
    rig.poll()
    assert rig.metric("dropped") == 1
    assert rig.metric("overwritten") == 0


# ---------------------------------------------------------------------------------------------- #
# Порядок
# ---------------------------------------------------------------------------------------------- #


def test_items_in_seq_order(make):
    """Items идут по возрастанию `seq_id`: без переполнения, после переполнения и после повторного забора."""
    rig = make()
    rig.feed(1, 2, 3, 4)
    assert _seq(rig.poll()) == [1, 2, 3, 4]
    rig.feed(5, 6, 7, 8, 9, 10, 11)  # 7 кадров на K=4: остаются 8, 9, 10, 11
    assert _seq(rig.poll()) == [8, 9, 10, 11]
    rig.feed(12, 13)
    assert _seq(rig.poll()) == [12, 13]


# ---------------------------------------------------------------------------------------------- #
# K = 1: прежнее поведение
# ---------------------------------------------------------------------------------------------- #


def test_queue_of_one_keeps_latest_only(make):
    """`source_queue_frames = 1`: 3 кадра -> один item, последний (seq_id 3, содержимое кадра 3); `overwritten == 2`.

    Тот же ввод при умолчании K=4 даёт три items (`test_three_frames_between_polls_all_delivered`): значение
    register'а действительно управляет глубиной.
    """
    rig = make(source_queue_frames=1)
    rig.feed(1, 2, 3)
    items = rig.poll()
    rig.poll()
    assert _seq(items) == [3]
    assert _fill(items) == [3]
    assert rig.metric("overwritten") == 2


# ---------------------------------------------------------------------------------------------- #
# Сквозной прогон: 25 кадр/с, опрос 25 Гц, 4 с
# ---------------------------------------------------------------------------------------------- #


def _sleep_until(deadline: float) -> None:
    remaining = deadline - time.perf_counter()
    if remaining > 0:
        time.sleep(remaining)


def test_paced_25fps_source_25hz_poll_no_loss(make):
    """Источник 25 кадр/с (100 кадров за 4 с) в своём потоке, опрос `produce()` 25 Гц: потеряно 0 (до правки 19 из 100).

    Фаза опроса задана, а не случайна, чтобы тест был красным до кода при любой загрузке машины: опрос j идёт
    через 15 мс после кадра j (на очереди один кадр), а каждый пятый опрос запаздывает на 65 мс и застаёт два
    кадра (j и j+1). До правки слот хранит один кадр: на каждом запоздавшем опросе теряется кадр j (19 потерь).
    Потеря = номер кадра, не дошедший до items; ожидаемый набор — литерал 1..100 с содержимым кадров 1..100.
    """
    rig = make()
    plugin = rig.plugin
    errors: list[BaseException] = []
    start = time.perf_counter() + 0.05

    def source() -> None:
        try:
            for number in range(1, FRAMES_TOTAL + 1):
                _sleep_until(start + number * FRAME_PERIOD_S)
                plugin._on_frame(_frame(number))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    source_thread = threading.Thread(target=source, daemon=True)
    source_thread.start()
    delivered: list[dict] = []
    for poll_no in range(1, FRAMES_TOTAL + 1):
        phase = POLL_LATE_PHASE_S if poll_no % POLL_LATE_EVERY == 0 else POLL_PHASE_S
        _sleep_until(start + poll_no * FRAME_PERIOD_S + phase)
        delivered.extend(rig.poll())
    source_thread.join(10.0)
    assert not source_thread.is_alive(), "поток источника не завершился за 10 с"
    assert errors == []
    delivered.extend(rig.poll())  # остаток после последнего опроса

    assert _seq(delivered) == list(range(1, FRAMES_TOTAL + 1)), (
        f"доставлено {len(delivered)} из {FRAMES_TOTAL}, потеряно {FRAMES_TOTAL - len(delivered)}"
    )
    assert _fill(delivered) == list(range(1, FRAMES_TOTAL + 1))
    rig.poll()
    assert rig.metric("overwritten") == 0
    assert rig.metric("dropped") == 0
