# -*- coding: utf-8 -*-
"""Ф7 G.5.c — PipelineExecutor дропает батч на устаревшем zero-copy view.

Между _execute_chain и _send_results: если входной view не пережил обработку
(middleware.frame_view_valid → False), результат НЕ отправляется (построен на
порванных пикселях). На не-view пути (нет _shm_views) — ноль оверхеда.
"""

from __future__ import annotations

import os
import queue
import threading
import time

import pytest

from multiprocess_framework.modules.process_module.generic.pipeline_executor import (
    PipelineExecutor,
)


class _FakeShm:
    """Минимальный middleware: frame_view_valid возвращает заданное, считает вызовы."""

    def __init__(self, valid: bool):
        self._valid = valid
        self.calls: list[tuple[str, int]] = []

    def frame_view_valid(self, ref: dict) -> bool:
        self.calls.append((ref["name"], ref["gen"]))
        return self._valid


def _ref(owner: str, idx: int, gen: int, name: str | None = None) -> dict:
    """Ссылка SHM (Task 4.4): она же билет re-check/release."""
    return {"owner": owner, "slot": "output_frames", "idx": idx, "gen": gen, "name": name or f"v{idx}"}


def _make_executor(shm, sent: list):
    return PipelineExecutor(
        plugins=[],  # пустая цепочка = passthrough (items наружу без изменений)
        chain_targets=["out"],
        shm_middleware=shm,
        send_fn=lambda target, msg: sent.append(msg),  # _send(target, msg)
    )


class TestCollectAndValidate:
    def test_collect_only_view_items(self):
        ex = _make_executor(_FakeShm(True), [])
        ref0, ref1 = _ref("cam0", 0, 4, "seg0"), _ref("cam1", 1, 6, "seg1")
        items = [
            {"_shm_views": [ref0]},
            {"frame": "plain"},  # не view — игнор
            {"_shm_views": [ref1]},
        ]
        assert ex._collect_view_tickets(items) == [ref0, ref1]

    def test_no_middleware_no_checks(self):
        ex = _make_executor(None, [])
        assert ex._collect_view_tickets([{"_shm_views": [_ref("cam0", 0, 2, "x")]}]) == []

    def test_all_valid_true_any_stale_false(self):
        ex_ok = _make_executor(_FakeShm(True), [])
        assert ex_ok._frame_views_valid([_ref("cam0", 0, 4, "seg0")]) is True
        ex_bad = _make_executor(_FakeShm(False), [])
        assert ex_bad._frame_views_valid([_ref("cam0", 0, 4, "seg0")]) is False


class TestRunLoopDrop:
    def _run_one_batch(self, ex, batch):
        q: queue.Queue = queue.Queue()
        q.put(batch)
        ex.bind_queue(q)
        stop = threading.Event()
        pause = threading.Event()
        t = threading.Thread(target=ex.run, args=(stop, pause))
        t.start()
        time.sleep(0.15)
        stop.set()
        t.join(timeout=1)

    def test_stale_view_batch_not_sent(self):
        sent: list = []
        shm = _FakeShm(valid=False)  # view устарел
        ex = _make_executor(shm, sent)
        self._run_one_batch(ex, [{"_shm_views": [_ref("cam0", 0, 2, "seg0")]}])
        assert sent == []  # дропнут, не отправлен
        assert shm.calls  # re-check был вызван

    def test_valid_view_batch_sent(self):
        sent: list = []
        shm = _FakeShm(valid=True)
        ex = _make_executor(shm, sent)
        self._run_one_batch(ex, [{"_shm_views": [_ref("cam0", 0, 2, "seg0")], "marker": 7}])
        assert len(sent) == 1  # валиден → отправлен
        assert sent[0]["data"]["marker"] == 7

    def test_non_view_batch_sent_without_recheck(self):
        sent: list = []
        shm = _FakeShm(valid=False)  # даже если бы дёрнули — False; но не view → не дёргаем
        ex = _make_executor(shm, sent)
        self._run_one_batch(ex, [{"frame": "plain", "camera_id": 1}])
        assert len(sent) == 1  # обычный кадр уходит
        assert shm.calls == []  # re-check НЕ вызывался (ноль оверхеда на не-view пути)


def _view_item(owner, idx, gen):
    return {"_shm_views": [_ref(owner, idx, gen)]}


class TestReleaseAccumulation:
    """G.5.d-2: executor копит release-тикеты и флашит пачкой владельцу (не на per-frame)."""

    @staticmethod
    def _executor(sent):
        shm = _FakeShm(valid=True)
        shm.loan_protocol_enabled = True  # публичный контракт (ревью-фикс 13)
        shm.ring_depth = 10  # ревью-фикс 6: порог = min(threshold, ring_depth)
        return PipelineExecutor(
            plugins=[],
            chain_targets=["out"],
            shm_middleware=shm,
            send_fn=lambda target, msg: sent.append((target, msg)),
        )

    def test_accumulate_then_flush_on_threshold(self):
        sent: list = []
        ex = self._executor(sent)
        ex._release_batch_threshold = 3
        ex._accumulate_releases([_ticket("cam0", 0, 2), _ticket("cam0", 1, 2)])
        assert sent == []  # < порога — не флашим
        ex._accumulate_releases([_ticket("cam0", 2, 2)])
        assert len(sent) == 1  # порог 3 достигнут → флаш
        target, msg = sent[0]
        assert target == "cam0"
        # ревью-фикс 16: queue_type="system" (не channel) — иначе уходит в data-очередь.
        assert msg["type"] == "shm_release" and msg["queue_type"] == "system"
        assert len(msg["data"]["releases"]) == 3
        assert msg["data"]["releases"][0]["reader"] == ex._node

    def test_threshold_capped_by_ring_depth(self):
        """Ревью-фикс 6: порог не выше глубины кольца (иначе тикеты голодают)."""
        sent: list = []
        ex = self._executor(sent)
        ex._shm.ring_depth = 3  # мелкое кольцо
        ex._release_batch_threshold = 8  # хотели 8, но кольцо 3
        ex._accumulate_releases([_ticket("cam0", i, 2) for i in range(3)])
        assert len(sent) == 1  # флаш на 3 (=ring_depth), не ждём 8

    def test_no_accumulate_without_loan_protocol(self):
        sent: list = []
        shm = _FakeShm(valid=True)  # loan_protocol_enabled не выставлен → getattr False
        ex = PipelineExecutor(
            plugins=[], chain_targets=["out"], shm_middleware=shm, send_fn=lambda t, m: sent.append((t, m))
        )
        ex._accumulate_releases([_ticket("cam0", 0, 2)])
        assert ex._pending_release_count == 0

    def test_run_loop_flushes_residual_on_stop(self):
        sent: list = []
        ex = self._executor(sent)
        ex._release_batch_threshold = 100  # не флашить по порогу — только на стопе
        TestRunLoopDrop()._run_one_batch(ex, [_view_item("cam0", 0, 5)])
        releases = [m for _, m in sent if m.get("type") == "shm_release"]
        assert len(releases) == 1  # хвост флашнут на остановке воркера
        assert releases[0]["data"]["releases"][0]["index"] == 0


def _ticket(owner, idx, gen):
    return _ref(owner, idx, gen)


# ===================== Task 4.4 итерация 2 (часть A): дверь отправки видит каждый вход =====================
# Реальный PipelineExecutor + реальный FrameShmMiddleware (стенд из test_frame_ref_gen): проверяются
# два свойства, которые фейк-middleware выше доказать не может.
from multiprocess_framework.modules.router_module.tests import test_frame_ref_gen as _T  # noqa: E402


@pytest.fixture
def rig(monkeypatch):
    for name in [k for k in os.environ if k.startswith("FW_SHM_")]:
        monkeypatch.delenv(name, raising=False)  # флаги SHM берутся только из теста
    r = _T._Rig()
    yield r
    r.close()


class _Rebuild(_T._Probe):
    """Плагин, пересобирающий dict (как center_crop): свежий dict на выходе, ``_shm_views`` теряется."""

    def process(self, items):
        super().process(items)
        return [{"frame": it["frame"], "n": it.get("n")} for it in items]


class _FanOut(_T._Probe):
    """Плагин, из одного входа делающий три выхода (свежие dict'ы) — батч из трёх сообщений."""

    def process(self, items):
        super().process(items)
        return [{"frame": items[0]["frame"], "n": i} for i in range(3)]


def test_rebuilt_item_blocked_by_send_door(rig, monkeypatch):
    """Свойство: плагин вернул СВЕЖИЙ dict (``_shm_views`` потерян) — executor всё равно передаёт двери
    билеты входного батча, и вход, перезаписанный ПОСЛЕ re-check executor'а и ДО копии в кольцо
    отправителя, дропается: ни к одной цели не уходит, ``frame_stale_drops`` == 1 (один раз на item).
    Красный revert: убрать в ``_run_batch`` слияние ``item[SHM_VIEWS_KEY]`` -> ушло к t1, t2, stale 0."""
    writer = rig.make("A")
    mm_b = _T.MemoryManager()
    sender = rig.make("B", view=True, mm=mm_b)
    fired: list[int] = []
    real_write = mm_b.write_images

    def write_after_overwrite(*args, **kwargs):
        if not fired:
            fired.append(1)
            _T._overwrite(writer, "frame")  # писатель переписывает входную ячейку прямо перед копией
        return real_write(*args, **kwargs)

    monkeypatch.setattr(mm_b, "write_images", write_after_overwrite)
    sent: list[str] = []

    def send_like_router(target, msg):
        if sender.strip_data_frame_on_send(msg) is not None:
            sent.append(target)

    probe = _Rebuild("frame")

    def scenario():
        item = _T._receive_as_pipeline(sender, _T._wire(_T._send(writer, {"frame": _T._arr("frame", 1), "n": 1})))
        ex = PipelineExecutor(
            plugins=[probe], chain_targets=["t1", "t2"], shm_middleware=sender, send_fn=send_like_router, node_name="B"
        )
        _T._run_executor(ex, [item], probe.done)

    _T._bounded(scenario)
    assert fired, "стенд неисправен: перехват write_images отправителя не сработал"
    assert sent == [], f"пересобранный item ушёл к целям {sent} с пикселями перезаписанного входа"
    assert sender.frame_stale_drops == 1, f"frame_stale_drops = {sender.frame_stale_drops}, ожидалось 1"


def test_batch_drop_counts_one_per_input_item(rig):
    """Свойство: единица счётчика — ВХОДНОЕ сообщение (с 4.7d-2b; раньше считались выходы цепочки).
    Вход перезаписан во время цепочки, плагин вернул три выхода -> дропнут один вход,
    ``frame_stale_drops`` == 1 (reader посчитал 1 на первой провалившейся ссылке, ``n_in - 1`` == 0
    доначислять нечего), ничего не отправлено."""
    writer, reader = rig.make("A"), rig.make("B", view=True)
    sent: list[str] = []
    probe = _FanOut("frame", lambda: _T._overwrite(writer, "frame"))

    def scenario():
        item = _T._receive_as_pipeline(reader, _T._wire(_T._send(writer, {"frame": _T._arr("frame", 1), "n": 1})))
        ex = PipelineExecutor(
            plugins=[probe],
            chain_targets=["out"],
            shm_middleware=reader,
            send_fn=lambda target, msg: sent.append(target),
            node_name="B",
        )
        _T._run_executor(ex, [item], probe.done)

    _T._bounded(scenario)
    assert sent == [], "батч ушёл дальше, хотя входной view был перезаписан во время обработки"
    assert reader.frame_stale_drops == 1, f"frame_stale_drops = {reader.frame_stale_drops}, ожидалось 1"


def test_output_views_are_own_plus_batch_tickets_deduped_in_new_list():
    """Свойство: не-view батч не получает ключа ``_shm_views`` вовсе (ноль работы на не-view пути); у
    view-батча каждый выход несёт СВОИ views + билеты батча без дублей по (name, gen), в НОВОМ списке
    (список входа не мутируется). Красный revert: убрать слияние в ``_run_batch`` -> у item 1 только own."""
    sent: list = []
    ex = _make_executor(_FakeShm(valid=True), sent)
    TestRunLoopDrop()._run_one_batch(ex, [{"frame": "plain"}])
    assert "_shm_views" not in sent[0]["data"]

    sent.clear()
    own, other = _ref("cam0", 0, 2, "seg0"), _ref("cam1", 1, 4, "seg1")
    own_list = [own]
    TestRunLoopDrop()._run_one_batch(ex, [{"_shm_views": own_list, "marker": 1}, {"_shm_views": [other], "marker": 2}])
    views_by_marker = {m["data"]["marker"]: m["data"]["_shm_views"] for m in sent}
    assert views_by_marker[1] == [own, other]  # своя ссылка + билет соседа, own не задвоена
    assert views_by_marker[2] == [other, own]
    assert own_list == [own], "список views входа мутирован на месте"
