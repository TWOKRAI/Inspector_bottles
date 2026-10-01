# -*- coding: utf-8 -*-
"""Task 4.7c rework — слепой RED-тест условия C4 вердикта CTO.

C4: исполнитель проверяет поколение входного view ДО прогона цепочки (чтение gen — микросекунды), а не
только после. Кадр, порванный уже на входе, до цепочки не доходит и считается.

Стенд — настоящие ``FrameShmMiddleware`` + ``MemoryManager`` и настоящий ``PipelineExecutor.run`` (как в
test_frame_ref_gen / test_g5c_executor_drop; фейк middleware счёта stale-дропов не даёт). Сценарий:
  1. писатель A шлёт кадр 1, читатель B (view) принимает его — на приёме поколение ещё совпадает;
  2. писатель прогоняет кольцо (``_overwrite``) -> вход item1 теперь stale ДО того, как исполнитель его увидел;
  3. писатель шлёт кадр 2 -> item2 свежий;
  4. в очередь исполнителя кладутся два батча [item1], [item2]; воркер один, порядок FIFO.
Свойства: плагин цепочки видит ТОЛЬКО кадр 2 (item1 в цепочку не попал), наружу ушёл один выход (n == 2),
дроп item1 посчитан ровно один раз (``frame_stale_drops`` == 1 — единица счёта сообщение).

Сегодня исполнитель сначала гонит цепочку и лишь потом сверяет поколение: плагин видит кадр 1 (пиксели
порваны), счёт тот же — отсюда красное по ``seen``. Сигнал «плагин вызван на stale-входе» — наблюдаемое
(пиксели, которые увидел плагин), а не имя приватного метода.

Зависший тест хуже отсутствующего: весь сценарий — в daemon-потоке с дедлайном join (``_T._bounded``),
исполнитель останавливается по событию «плагин обработал кадр 2».
"""

from __future__ import annotations

import os
import queue
import threading

import pytest

from multiprocess_framework.modules.process_module.generic.pipeline_executor import PipelineExecutor
from multiprocess_framework.modules.router_module.tests import test_frame_ref_gen as _T


@pytest.fixture
def rig(monkeypatch):
    for name in [k for k in os.environ if k.startswith("FW_SHM_")]:
        monkeypatch.delenv(name, raising=False)  # флаги SHM берутся только из теста
    r = _T._Rig()
    yield r
    r.close()


class _SeenPlugin:
    """Плагин цепочки: запоминает ``n`` и пиксели каждого item, который ему дали; сигналит на кадре 2."""

    name = "seen"
    enabled = True
    inputs: list = []
    outputs: list = []

    def __init__(self) -> None:
        self.seen: list[tuple[int, bytes]] = []
        self.got_frame_2 = threading.Event()

    def process(self, items: list[dict]) -> list[dict]:
        for item in items:
            arr = item.get("frame")
            self.seen.append((item.get("n"), arr.tobytes() if hasattr(arr, "tobytes") else b""))
            if item.get("n") == 2:
                self.got_frame_2.set()
        return items


@pytest.mark.xfail(strict=True, reason="4.7c rework: C4")
def test_stale_input_never_reaches_chain(rig):
    """Вход, порванный ДО исполнителя, не доходит до цепочки: плагин видит только свежий кадр 2,
    наружу уходит один выход (n == 2), дроп stale-входа посчитан один раз."""
    writer, reader = rig.make("A"), rig.make("B", view=True)
    arr1, arr2 = _T._arr("frame", 1), _T._arr("frame", 2)
    plugin = _SeenPlugin()
    sent: list[dict] = []

    def scenario() -> None:
        item1 = _T._receive_as_pipeline(reader, _T._wire(_T._send(writer, {"frame": arr1, "n": 1})))
        _T._overwrite(writer, "frame")  # ячейка кадра 1 переписана ДО того, как исполнитель взял батч
        item2 = _T._receive_as_pipeline(reader, _T._wire(_T._send(writer, {"frame": arr2, "n": 2})))

        ex = PipelineExecutor(
            plugins=[plugin],
            chain_targets=["out"],
            shm_middleware=reader,
            send_fn=lambda target, msg: sent.append(msg),
            node_name="B",
        )
        q: queue.Queue = queue.Queue()
        q.put([item1])
        q.put([item2])
        ex.bind_queue(q)
        stop, pause = threading.Event(), threading.Event()
        worker = threading.Thread(target=ex.run, args=(stop, pause), daemon=True)
        worker.start()
        if not plugin.got_frame_2.wait(15.0):
            stop.set()
            pytest.fail("плагин не получил свежий кадр 2 за 15 с (исполнитель завис или потерял батч)")
        stop.set()
        worker.join(10.0)
        if worker.is_alive():
            pytest.fail("PipelineExecutor не завершил такт за 10 с")

    _T._bounded(scenario)

    assert plugin.seen == [(2, arr2.tobytes())], (
        f"цепочка увидела не только свежий кадр 2: {[(n, len(px)) for n, px in plugin.seen]}"
    )
    assert [m["data"]["n"] for m in sent] == [2], "наружу должен уйти ровно один выход — кадр 2"
    assert reader.frame_stale_drops == 1, f"frame_stale_drops = {reader.frame_stale_drops}, ожидалось 1"
