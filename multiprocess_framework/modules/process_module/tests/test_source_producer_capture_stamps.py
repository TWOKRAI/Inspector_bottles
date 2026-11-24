# -*- coding: utf-8 -*-
"""Слепая приёмка T8: штамп ``capture_ns`` и перенос ``capture_ns``/``group_id`` через цепочку.

Purpose: пригвоздить контракт времени кадра для источника: ``SourceProducer`` ставит
``capture_ns = time.perf_counter_ns()`` (int) на каждый item поштучно, если плагин не поставил
свой; штамп плагина не перезаписывается; ``group_id`` продюсер не назначает; оба поля переживают
``PluginRunner.call_process`` даже когда плагин возвращает СВЕЖИЙ dict.

Тесты написаны по вырезке критериев приёмки, до реализации. Субъект — настоящий
``SourceProducer.run_loop`` (daemon-поток, join-дедлайн) и настоящий ``PluginRunner``.
Ожидаемые значения — литералы (123, 7, 1000), не вычисляются из проверяемого кода. Внутри одной
пачки утверждается только «не меньше»; строгое возрастание — только между отдельными циклами
``produce()``.
"""

from __future__ import annotations

import threading
import time

import pytest

from multiprocess_framework.modules.process_module.generic.plugin_runner import PluginRunner
from multiprocess_framework.modules.process_module.generic.source_producer import SourceProducer

__all__: list[str] = []

#: Страховочный дедлайн выхода потока run_loop (сек): зависание = FAIL, а не зависший набор.
JOIN_DEADLINE_S = 20.0
#: Частота «почти без темпа»: 1000 циклов укладываются в доли секунды.
FAST_FPS = 100_000.0


class _Source:
    """Source-двойник: каждый produce() отдаёт пачку, собранную ``batch_fn(call_no)``."""

    name = "stamp_probe_source"

    def __init__(self, batch_fn) -> None:
        self._batch_fn = batch_fn
        self.calls = 0

    def produce(self) -> list[dict]:
        self.calls += 1
        return self._batch_fn(self.calls)


def _run_until(batch_fn, items_needed: int, target_fps: float = FAST_FPS) -> tuple[list[dict], int, int]:
    """Настоящий run_loop, пока не отправлено ``items_needed`` item-ов.

    Возвращает ``(items_as_sent, n0, n1)``: ``n0`` = perf_counter_ns() до старта потока,
    ``n1`` = после его выхода. Любой штамп, поставленный внутри прогона, лежит в [n0, n1].
    """
    stop = threading.Event()
    pause = threading.Event()
    sent: list[dict] = []

    def send_fn(target: str, msg: dict) -> None:
        sent.append(msg["data"])
        if len(sent) >= items_needed:
            stop.set()

    producer = SourceProducer(
        plugin=_Source(batch_fn),
        shm_middleware=None,
        send_fn=send_fn,
        chain_targets=["sink"],
        target_fps=target_fps,
    )
    thread = threading.Thread(target=producer.run_loop, args=(stop, pause), daemon=True)
    n0 = time.perf_counter_ns()
    thread.start()
    thread.join(JOIN_DEADLINE_S)
    if thread.is_alive():
        stop.set()
        thread.join(2.0)
        pytest.fail(f"run_loop не завершился за {JOIN_DEADLINE_S}s (отправлено {len(sent)} из {items_needed})")
    n1 = time.perf_counter_ns()
    assert len(sent) >= items_needed
    return sent, n0, n1


def test_producer_stamps_capture_ns_when_plugin_did_not() -> None:
    """Плагин не ставил штамп: item уходит с ``capture_ns`` внутри скобки perf_counter_ns() вокруг прогона.

    Убивает: штамп не ставится вовсе; ``time.time_ns()`` вместо ``perf_counter_ns()`` (другая эпоха,
    число далеко за скобкой); штамп из чужих часов.
    """
    sent, n0, n1 = _run_until(lambda call: [{"frame": call}], items_needed=1)
    item = sent[0]
    assert "capture_ns" in item
    assert n0 <= item["capture_ns"] <= n1


def test_plugin_stamp_not_overwritten() -> None:
    """Плагин поставил ``capture_ns`` 123: после SourceProducer остаётся ровно 123.

    Убивает: безусловную перезапись штампа продюсером (вместо «только если нет»).
    """
    sent, _, _ = _run_until(lambda call: [{"frame": call, "capture_ns": 123}], items_needed=3)
    assert [item["capture_ns"] for item in sent[:3]] == [123, 123, 123]


def test_zero_plugin_stamp_is_kept() -> None:
    """Плагин поставил ``capture_ns`` 0 (это int, значит штамп есть): остаётся 0.

    Убивает: проверку «штамп отсутствует» через истинность (``if not item.get("capture_ns")``).
    """
    sent, _, _ = _run_until(lambda call: [{"frame": call, "capture_ns": 0}], items_needed=1)
    assert sent[0]["capture_ns"] == 0


def test_mixed_batch_only_unstamped_items_are_stamped() -> None:
    """Пачка из двух item: первый со штампом 123, второй без. Первый остаётся 123, второму ставится свой.

    Убивает: штамп «на пачку» по первому item; перезапись всей пачки; пропуск item-ов после первого.
    """
    sent, n0, n1 = _run_until(
        lambda call: [{"frame": 1, "capture_ns": 123}, {"frame": 2}],
        items_needed=2,
    )
    stamped, unstamped = sent[0], sent[1]
    assert stamped["capture_ns"] == 123
    assert n0 <= unstamped["capture_ns"] <= n1


@pytest.mark.parametrize("absent_value", [None, 1.5, "123"], ids=["none", "float", "str"])
def test_none_or_non_int_capture_ns_counts_as_absent(absent_value) -> None:
    """``capture_ns`` равный None или не int = штампа нет: продюсер ставит свой int в скобке.

    Убивает: ``setdefault``-подобную защиту, принимающую любое присутствие ключа за штамп.
    """
    sent, n0, n1 = _run_until(lambda call: [{"frame": call, "capture_ns": absent_value}], items_needed=1)
    stamp = sent[0]["capture_ns"]
    assert type(stamp) is int
    assert n0 <= stamp <= n1


def test_capture_ns_non_decreasing_within_one_batch() -> None:
    """Пачка из трёх item от одного produce(): штампы не убывают (строгости внутри пачки не требуем).

    Убивает: штамп, убывающий внутри пачки (обратный порядок, случайное значение).
    """
    sent, n0, n1 = _run_until(lambda call: [{"frame": 1}, {"frame": 2}, {"frame": 3}], items_needed=3)
    stamps = [item["capture_ns"] for item in sent[:3]]
    assert stamps[0] <= stamps[1] <= stamps[2]
    assert n0 <= stamps[0] and stamps[2] <= n1


def test_capture_ns_strictly_increasing_1000_items() -> None:
    """1000 отдельных циклов produce() через настоящий run_loop (target_fps 100000): штампы строго растут.

    Убивает: одно значение на весь прогон (штамп в конструкторе/первый кадр); штамп на часах с
    грубым шагом, дающим равные значения у соседних циклов.
    """
    sent, _, _ = _run_until(lambda call: [{"frame": call}], items_needed=1000)
    stamps = [item["capture_ns"] for item in sent[:1000]]
    assert len(stamps) == 1000
    assert all(later > earlier for earlier, later in zip(stamps, stamps[1:]))


def test_capture_ns_is_int() -> None:
    """``capture_ns`` — настоящий ``int`` (не float, не None, не bool).

    Убивает: ``perf_counter()`` (float) вместо ``perf_counter_ns()``; float-округление наносекунд.
    """
    sent, _, _ = _run_until(lambda call: [{"frame": call}], items_needed=1)
    assert type(sent[0]["capture_ns"]) is int


def test_producer_does_not_assign_group_id() -> None:
    """Продюсер ``group_id`` не назначает: у item без ``group_id`` значение ``None``/отсутствует.

    Убивает: назначение group_id в продюсере (счётчик, 0, capture_ns). Формулировка контракта
    допускает и отсутствие ключа, и None, поэтому читаем через ``.get``.
    """
    sent, _, _ = _run_until(lambda call: [{"frame": call}], items_needed=1)
    assert sent[0].get("group_id") is None


def test_plugin_group_id_passes_through_producer_untouched() -> None:
    """Плагин поставил ``group_id`` 7: продюсер его не меняет.

    Убивает: продюсер затирает/обнуляет ``group_id``.
    """
    sent, _, _ = _run_until(lambda call: [{"frame": call, "group_id": 7}], items_needed=1)
    assert sent[0]["group_id"] == 7


class _FreshDictPlugin:
    """Process-плагин, который строит СВЕЖИЙ dict вместо мутации входного (как stitcher/compositor)."""

    name = "fresh_dict_plugin"

    def process(self, items: list[dict]) -> list[dict]:
        return [{"frame": item["frame"], "processed": True} for item in items]


def test_capture_ns_and_group_id_survive_real_producer_and_fresh_dict_plugin() -> None:
    """Настоящий run_loop: плагин-источник ставит capture_ns 123 и group_id 7; msg["data"] идёт в
    ``PluginRunner.call_process`` с плагином, возвращающим СВЕЖИЙ dict; на выходе 123 и 7.

    Убивает: ключи не переносятся через плагин (нет в списке переносимых системных полей);
    перенос только одного из двух полей; потеря поля продюсером до плагина.
    """
    sent, _, _ = _run_until(lambda call: [{"frame": call, "capture_ns": 123, "group_id": 7}], items_needed=1)
    message = {"target": "next", "type": "data", "channel": "data", "data": sent[0]}

    outputs = PluginRunner().call_process(_FreshDictPlugin(), [message["data"]])

    assert len(outputs) == 1
    assert outputs[0]["processed"] is True  # плагин действительно вернул свежий dict, а не мутировал вход
    assert outputs[0]["capture_ns"] == 123
    assert outputs[0]["group_id"] == 7


def test_fallback_capture_ns_survives_fresh_dict_plugin() -> None:
    """Запасной штамп продюсера (плагин-источник своего не ставил) переживает свежий dict плагина.

    Убивает: перенос, работающий только для штампа плагина-источника; потерю int-штампа на process().
    """
    sent, n0, n1 = _run_until(lambda call: [{"frame": call}], items_needed=1)
    outputs = PluginRunner().call_process(_FreshDictPlugin(), [sent[0]])

    assert type(outputs[0]["capture_ns"]) is int
    assert n0 <= outputs[0]["capture_ns"] <= n1
