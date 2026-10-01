# -*- coding: utf-8 -*-
"""Task 4.4 (transport-single-policy), A6 — «один хоп»: цепочка из ТРЁХ ОС-процессов A -> B -> C.

Независимый тест-автор (tester), от контракта Task 4.4, БЕЗ чтения реализации после 83a9092f.

Контракт: send-middleware кладёт в исходящее сообщение ТОЛЬКО ссылки, чей ``owner`` — сам отправитель;
входные (унаследованные от предыдущего хопа) ссылки не пересылаются никогда. Поэтому C получает
пиксели, которые записал B, а ссылки A до C не доходят.

Сценарий (код детей — ``frame_ref_one_hop_children.py``, spawn, жёсткий дедлайн и kill):
  * A пишет ``frame`` и ``foo`` (кольцо coll=3) и шлёт B;
  * B читает view, плагин пересобирает item ``dict(item)`` (унаследованные ссылки остаются в dict'е),
    подменяет ``frame`` на ``255 - frame_A``, ВЫБРАСЫВАЕТ ``foo``, добавляет новый ключ ``mask``;
  * после пересылки B писатель A ПЕРЕПИСЫВАЕТ оба своих кольца мусором, и только потом C читает.
Любая ссылка A, доехавшая до C, дала бы мусор (или stale) вместо пикселей B.

Проверки (родитель, по результатам детей): на проводе B->C у ВСЕХ ссылок владелец ``B``; C получил
``frame`` == ``255 - frame_A`` и ``mask`` == записанному B; выброшенный B ключ ``foo`` в C не воскрес.
"""

from __future__ import annotations

import multiprocessing
import os
import queue
from typing import Any

import pytest

from multiprocess_framework.modules.process_module.tests import frame_ref_one_hop_children as kids

RESULT_TIMEOUT_S = 90.0  # потолок на весь сценарий трёх процессов
KILL_GRACE_S = 10.0


@pytest.fixture(autouse=True)
def _clean_shm_flags(monkeypatch):
    """Флаги SHM берутся ТОЛЬКО из теста: env разработчика не должен менять поведение детей."""
    for name in [k for k in os.environ if k.startswith("FW_SHM_")]:
        monkeypatch.delenv(name, raising=False)


def _run_chain() -> dict[str, Any]:
    ctx = multiprocessing.get_context("spawn")
    q_ab, q_bc, res_q = ctx.Queue(), ctx.Queue(), ctx.Queue()
    evt_b_forwarded, evt_garbage_done, evt_done = ctx.Event(), ctx.Event(), ctx.Event()
    procs = [
        ctx.Process(target=kids.child_a, args=(q_ab, evt_b_forwarded, evt_garbage_done, evt_done, res_q), daemon=True),
        ctx.Process(target=kids.child_b, args=(q_ab, q_bc, evt_b_forwarded, evt_done, res_q), daemon=True),
        ctx.Process(target=kids.child_c, args=(q_bc, evt_garbage_done, res_q), daemon=True),
    ]
    results: dict[str, tuple[str, Any]] = {}
    try:
        for p in procs:
            p.start()
        # C заканчивает последним из «читающих»; A и B ждут evt_done, чтобы держать SHM живой.
        while "c" not in results:
            try:
                who, status, payload = res_q.get(timeout=RESULT_TIMEOUT_S)
            except queue.Empty:
                pytest.fail(f"цепочка не завершилась за {RESULT_TIMEOUT_S} с; получено от: {sorted(results)}")
            results[who] = (status, payload)
            if status != "ok":
                break
    finally:
        evt_done.set()
        for p in procs:
            p.join(KILL_GRACE_S)
            if p.is_alive():
                p.terminate()
                p.join(5.0)
    for who, (status, payload) in results.items():
        if status != "ok":
            pytest.fail(f"дочерний процесс {who.upper()} упал:\n{payload}")
    return results["c"][1]


@pytest.fixture(scope="module")
def chain_result() -> dict[str, Any]:
    return _run_chain()


def test_a6_three_process_chain_c_gets_b_pixels_not_a_refs(chain_result):
    """A6: на проводе B->C у каждой ссылки владелец ``B`` (ссылок A нет); C получил ``frame`` =
    ``255 - frame_A`` (пиксели B, не A и не мусор после порчи колец A) и ``mask`` (новый ключ B) —
    побайтно, форма и dtype сохранены; счётчики stale/torn у C нулевые."""
    assert chain_result["owners"] == ["B"], (
        f"на проводе B->C владельцы ссылок {chain_result['owners']}, ожидалось ['B']"
    )
    arrays = chain_result["arrays"]
    want_frame = kids.b_frame_from(kids.make_array("frame", 1))
    want_mask = kids.make_array("mask", 3)
    for key, want in (("frame", want_frame), ("mask", want_mask)):
        assert key in arrays, f"C не получил массив {key!r}; есть: {sorted(arrays)}"
        raw, shape, dtype = arrays[key]
        assert (shape, dtype) == (tuple(want.shape), str(want.dtype)), f"{key}: форма/dtype {shape}/{dtype}"
        assert raw == want.tobytes(), f"{key}: пиксели C не равны записанным B"
    assert chain_result["stale"] == 0 and chain_result["torn"] == 0


def test_a6_key_dropped_by_b_does_not_reach_c_via_a_ref(chain_result):
    """A6: ключ ``foo``, который B выбросил из item'а (в dict остались только унаследованные поля),
    в C не воскресает: ссылка A на ``foo`` дальше B не идёт (после порчи колец A она дала бы чужой кадр)."""
    assert "foo" not in chain_result["arrays"], "C получил foo: ссылка A на выброшенный ключ дошла до C"
