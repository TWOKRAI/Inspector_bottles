# -*- coding: utf-8 -*-
"""Потолок отставания исполнителя: догоняющий буфер вместо накопления.

Основание — живой стенд 2026-08-12 (`webcam_sketch`). Исполнитель `lines` тянет
3.3 к/с, источник даёт 21 к/с. Внутренняя очередь (64) и очередь транспорта (50)
стояли полными, Line-art отставал от реальности примерно на **34 секунды**, и при
этом транспорт всё равно выбросил **1646** кадров (``queue_data_evicted`` у `seg`).
То есть гарантия «не дропаем» уже не действовала — платили за неё только
задержкой. Требование владельца: «несколько кадров, чтобы догнать пробку, а не
задержка в несколько секунд».

Свойства (каждое своим тестом):

1. глубина очереди не превышает потолка — сколько бы ни лили;
2. выживают СВЕЖИЕ, а не первые пришедшие (иначе догоняющий буфер бессмыслен);
3. потеря считается ВСЕГДА, а голос — не чаще раза в окно и с числом;
4. потолок 0 = прежнее поведение (блокировка), ни одной потери;
5. гонка с потребителем не даёт тихой потери: коллекция уходит на прежнюю дорогу.

Часы — зависимость объекта (инъекция ``clock``), а не глобальный патч: троттл
голоса меряется временем, и подмена ``time.monotonic`` на весь процесс делала бы
соседние тесты флейкими.
"""

from __future__ import annotations

import queue
import threading
from typing import List

import pytest

from multiprocess_framework.modules.process_module.generic.data_receiver import DataReceiver


class _FakeClock:
    """Управляемые часы: тест двигает время сам."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _receiver(chain: queue.Queue, max_lag: int, errors: List[str], clock=None) -> DataReceiver:
    return DataReceiver(
        receive_fn=lambda **_: None,
        shm_middleware=None,
        item_collector=object(),  # в этих сценариях не участвует
        chain_queue=chain,
        lag_alert_threshold_sec=0.05,
        log_error=errors.append,
        max_lag_items=max_lag,
        clock=clock,
    )


def _drain(chain: queue.Queue) -> List[str]:
    """Всё содержимое очереди по порядку — судим по данным, а не по qsize."""
    out: List[str] = []
    while True:
        try:
            out.append(chain.get_nowait()[0]["marker"])
        except queue.Empty:
            return out


def _item(marker: str) -> list[dict]:
    return [{"marker": marker}]


# =============================================================================
# 1-2. Глубина ограничена, выживают свежие
# =============================================================================


def test_queue_never_grows_beyond_the_cap() -> None:
    """20 коллекций при потолке 4 → в очереди 4, а не 20."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    receiver = _receiver(chain, max_lag=4, errors=[], clock=_FakeClock())

    for i in range(20):
        receiver.on_items_ready(_item(f"к{i}"))

    assert chain.qsize() == 4, f"глубина {chain.qsize()} при потолке 4"


def test_the_newest_survive_not_the_oldest() -> None:
    """Остаются последние — иначе исполнитель молотит древность.

    Литералы, а не «последние N»: выражение, выведенное из той же формулы, что и
    код, согласилось бы и с обратным порядком.
    """
    chain: queue.Queue = queue.Queue(maxsize=64)
    receiver = _receiver(chain, max_lag=3, errors=[], clock=_FakeClock())

    for i in range(10):
        receiver.on_items_ready(_item(f"к{i}"))

    assert _drain(chain) == ["к7", "к8", "к9"]


def test_cap_of_one_keeps_only_the_freshest() -> None:
    """Потолок 1 — «только самый свежий», крайний случай ручки."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    receiver = _receiver(chain, max_lag=1, errors=[], clock=_FakeClock())

    for i in range(5):
        receiver.on_items_ready(_item(f"к{i}"))

    assert _drain(chain) == ["к4"]


def test_no_drops_while_the_executor_keeps_up() -> None:
    """Успевающий исполнитель не теряет ничего: потолок не трогает здоровый темп."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    receiver = _receiver(chain, max_lag=4, errors=[], clock=_FakeClock())

    for i in range(10):
        receiver.on_items_ready(_item(f"к{i}"))
        chain.get_nowait()  # потребитель забирает сразу

    assert receiver.lag_dropped_total == 0
    assert chain.qsize() == 0


# =============================================================================
# 3. Потеря со счётом и голосом
# =============================================================================


def test_every_drop_is_counted_even_when_silent() -> None:
    """Счётчик растёт на КАЖДОЙ потере, независимо от троттла голоса."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    errors: List[str] = []
    clock = _FakeClock()
    receiver = _receiver(chain, max_lag=2, errors=errors, clock=clock)

    for i in range(12):
        receiver.on_items_ready(_item(f"к{i}"))

    # 12 положили, 2 осталось → 10 выброшено.
    assert receiver.lag_dropped_total == 10, receiver.lag_dropped_total


def test_voice_is_throttled_but_carries_the_number() -> None:
    """Голос не чаще раза в окно; после окна печатает, сколько потеряно за окно."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    errors: List[str] = []
    clock = _FakeClock()
    receiver = _receiver(chain, max_lag=1, errors=errors, clock=clock)

    for i in range(6):
        receiver.on_items_ready(_item(f"к{i}"))
    first = len(errors)

    clock.now += 5.001  # окно истекло
    receiver.on_items_ready(_item("после-окна"))

    assert first == 1, f"в одном окне голосов {first}, ожидался 1"
    assert len(errors) == 2, errors
    assert "выброшено" in errors[1] and "всего" in errors[1], errors[1]


def test_voice_never_fires_without_a_loss() -> None:
    """Молчание при отсутствии потерь: голос про потерю, а не про работу."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    errors: List[str] = []
    receiver = _receiver(chain, max_lag=4, errors=errors, clock=_FakeClock())

    for i in range(3):
        receiver.on_items_ready(_item(f"к{i}"))

    assert errors == []


# =============================================================================
# 4. Потолок 0 — прежнее поведение
# =============================================================================


def test_cap_zero_keeps_the_old_blocking_behaviour() -> None:
    """0 = копим до предела очереди и НЕ теряем: дефолт не изменился молча."""
    chain: queue.Queue = queue.Queue(maxsize=5)
    errors: List[str] = []
    receiver = _receiver(chain, max_lag=0, errors=errors, clock=_FakeClock())

    for i in range(5):
        receiver.on_items_ready(_item(f"к{i}"))

    assert chain.qsize() == 5
    assert receiver.lag_dropped_total == 0
    assert _drain(chain) == ["к0", "к1", "к2", "к3", "к4"], "порядок при потолке 0 обязан быть прежним"


def test_cap_zero_still_blocks_until_space_appears() -> None:
    """При потолке 0 полная очередь ЖДЁТ (Q6), а не выбрасывает.

    Вызов в потоке-демоне с дедлайном join: тест, который вместо красноты
    ПОВИСАЕТ, хуже отсутствующего — он прячет регрессию за таймаутом.
    """
    chain: queue.Queue = queue.Queue(maxsize=1)
    receiver = _receiver(chain, max_lag=0, errors=[], clock=_FakeClock())
    receiver.on_items_ready(_item("занял"))

    done = threading.Event()

    def _put() -> None:
        receiver.on_items_ready(_item("ждёт"))
        done.set()

    worker = threading.Thread(target=_put, daemon=True)
    worker.start()
    assert not done.wait(0.3), "при потолке 0 укладка прошла без ожидания — политика изменилась"

    chain.get_nowait()  # освободили место
    assert done.wait(2.0), "укладка не завершилась после освобождения места"
    worker.join(timeout=1.0)


# =============================================================================
# 5. Гонка не даёт тихой потери
# =============================================================================


def test_race_falls_back_to_the_blocking_path_instead_of_losing() -> None:
    """Если место заняли между get и put — идём прежней дорогой, а не теряем.

    Очередь-дубль занимает освободившееся место ровно один раз; после отката на
    блокирующую дорогу коллекция обязана оказаться в очереди.
    """

    class _RacingQueue(queue.Queue):
        def __init__(self) -> None:
            super().__init__(maxsize=2)
            self._stolen = False

        def put_nowait(self, item):  # noqa: ANN001, ANN201 — форма базы
            if not self._stolen:
                self._stolen = True
                raise queue.Full
            return super().put_nowait(item)

    chain = _RacingQueue()
    receiver = _receiver(chain, max_lag=1, errors=[], clock=_FakeClock())
    receiver.on_items_ready(_item("первый"))

    assert _drain(chain) == ["первый"], "коллекция потеряна на гонке"


def test_cap_is_normalised_from_garbage() -> None:
    """Отрицательный/дробный потолок не ломает узел: 0 или целое, без исключения."""
    chain: queue.Queue = queue.Queue(maxsize=8)
    assert _receiver(chain, max_lag=-5, errors=[], clock=_FakeClock())._max_lag_items == 0
    assert _receiver(chain, max_lag=3.7, errors=[], clock=_FakeClock())._max_lag_items == 3


@pytest.mark.parametrize("cap", [1, 2, 4, 8])
def test_cap_holds_for_every_value(cap: int) -> None:
    """Ручка работает во всём диапазоне, а не на одном подобранном числе."""
    chain: queue.Queue = queue.Queue(maxsize=64)
    receiver = _receiver(chain, max_lag=cap, errors=[], clock=_FakeClock())

    for i in range(30):
        receiver.on_items_ready(_item(f"к{i}"))

    assert chain.qsize() == cap
    assert _drain(chain) == [f"к{i}" for i in range(30 - cap, 30)]
