# -*- coding: utf-8 -*-
"""Авторские hazard-тесты механизма «читатель ушёл навсегда» (ADR-SRM-016, L-2 Task 1.2).

Что может сломаться именно в ЭТОМ механизме (метка едет с очередью, владелец взводит
её на системном стопе, писатель на выходе отпускает feeder только маркированных):

  H1. Индивидуальный стоп/рестарт взвёл метку → писатель, выходящий позже, отпустит
      кадр посреди записи в очередь, которую уже читает новое воплощение (очереди
      рестарт переиспользует). Пин: стоп по своему ``stop_event`` метку НЕ ставит.
  H2. Метка не пережила spawn-pickle (``__getstate__`` потерял Event) → сосед видит
      свою копию без метки, писатель ждёт вечно. Пин: метка видна через границу
      процесса в обе стороны.
  H3. Гонка: читатель вышел ПОСЛЕ первого взгляда писателя → разовая проверка
      промахнётся, и писатель повиснет. Пин: писатель выходит вскоре после метки,
      взведённой уже во время его ожидания (здесь же замер задержки реакции).
  H4. Отпуск по таймеру (запрещён ADR-SRM-015) → медленный живой читатель получает
      обрезанный кадр. Пин: без метки feeder ждётся, читатель, пришедший через 1.5 с,
      получает всё целиком.
  H5. Хук вызван дважды → двойной счёт потерь или повторный close/cancel. Пин: второй
      вызов — (0, 0) и возвращается сразу.
  H7. Счёт потерь выдаёт не то число (ревью: «буфер + 1» давал 1 при 0 и 1 при 5
      потерянных). Пин: N сообщений в буфере feeder'а → ровно N, литералом.
  H8. Формат и числа строки итога доходят до stderr настоящей пары spawn-процессов
      (литеральная строка). ВЫБОР КАНАЛА (``emergency_log`` мимо остановленного
      LoggerManager) этот тест НЕ закрепляет: в тестовом ребёнке LoggerManager нет,
      и ``log.warning`` тоже уходит в stderr — инъекция ревью итерации 2 оставила H8
      зелёным. Канал доказан только живым прогоном ведущего 2026-09-24 (33 строки в
      stderr за 10 циклов ``inspection_full``). Вопрос закрыт Task 1.3 (lifecycle-stop-ownership):
      после Ф6.8 ``LoggerManager.shutdown()`` снимает себя с ``_instance``, и вид ``log`` тоже
      падает в stdlib — каналы неразличимы по выходу. Свойство «строка доходит при настоящем
      остановленном менеджере» пинит ``test_exit_loss_line_acceptance.py::test_a4_*`` (красный,
      только если сломать И выбор канала, И снятие менеджера).
  H9. Потеря «в полёте» при ПУСТОМ буфере (один кадр застрял в send) видна в stderr: строка
      итога печатается по ``released``, а не по ``buffered_dropped`` (Task 1.3). Инъекция «печатать
      только при buffered_dropped > 0» оставляла все остальные тесты зелёными.
  H6. Голая ``mp.Queue`` (не из реестра) задета хуком → поведение очередей вне
      реестра изменилось молча. Пин: хук её не закрывает и не отпускает.

Любой блокирующий вызов — в дочернем процессе или daemon-потоке с дедлайном join:
зависание обязано стать падением, а не таймаутом всего прогона.
"""

from __future__ import annotations

import multiprocessing
import os
import subprocess
import sys
import threading
import time

from multiprocess_framework.modules.process_manager_module.runner.process_runner import (
    run_process_function,
)
from multiprocess_framework.modules.shared_resources_module.queues.core.manager import QueueRegistry
from multiprocess_framework.modules.shared_resources_module.queues.core.reader_gone import (
    ReaderGoneQueue,
    release_feeders_at_exit,
)

BIG = b"x" * (1024 * 1024)  # заведомо больше OS pipe buffer


# ---------------------------------------------------------------------------
# Top-level цели дочерних процессов (spawn пиклит по dotted-пути).
# ---------------------------------------------------------------------------


class _IdleOwner:
    """Владелец очереди, ничего не делает, ждёт стопа через lifecycle runner'а."""

    def __init__(self, name, shared_resources, config) -> None:
        self.name = name

    def initialize(self) -> bool:
        return True

    def run(self) -> None:
        pass

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


def _child_report_mark(q, out) -> None:
    out.put(q.is_reader_gone())


def _child_set_mark(q) -> None:
    q.mark_reader_gone()


def _child_put_big_then_exit_hook(q, extra_small: int, done) -> None:
    """Писатель-сосед: кладёт 1 MiB (+N маленьких), затем выходной хук как у runner'а
    на системном стопе (очередь чужая — метку он не ставит, только ждёт/отпускает)."""
    q.put(("big", BIG))
    for i in range(extra_small):
        q.put(("small", i))
    time.sleep(0.2)  # feeder упирается в полный pipe
    released, dropped = release_feeders_at_exit([], [q], system_stop=True)
    done.put((released, dropped, time.monotonic()))


def _run_child(target, args, deadline: float):
    ctx = multiprocessing.get_context("spawn")
    p = ctx.Process(target=target, args=args)
    p.start()
    return p


def _kill(p) -> None:
    if p.is_alive():
        p.kill()
        p.join(3.0)


def _in_thread(fn, deadline: float):
    box: dict = {}

    def body():
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 — переносим в тест
            box["error"] = exc

    t = threading.Thread(target=body, daemon=True)
    t.start()
    t.join(deadline)
    assert not t.is_alive(), f"вызов завис дольше {deadline}s"
    assert "error" not in box, box.get("error")
    return box["result"]


def _new_queue() -> ReaderGoneQueue:
    q = QueueRegistry().create_queues({"data": {}})["data"]
    assert isinstance(q, ReaderGoneQueue)
    return q


def _drop(q) -> None:
    try:
        q.cancel_join_thread()
        q.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# H1 — индивидуальный стоп НЕ ставит метку; системный — ставит.
# ---------------------------------------------------------------------------


class TestH1IndividualStopDoesNotMark:
    def _run_owner(self, set_system: bool) -> bool:
        ctx = multiprocessing.get_context("spawn")
        q = _new_queue()
        own_stop, system_stop = ctx.Event(), ctx.Event()
        bundle = {"queues": {"data": q}, "config": {}, "custom": {}}
        p = ctx.Process(
            target=run_process_function, args=(f"{__name__}._IdleOwner", "Owner", own_stop, bundle, system_stop)
        )
        try:
            p.start()
            time.sleep(0.3)
            (system_stop if set_system else own_stop).set()
            p.join(5.0)
            assert not p.is_alive(), "владелец не вышел за 5s"
            return q.is_reader_gone()
        finally:
            _kill(p)
            _drop(q)

    def test_individual_stop_leaves_queue_unmarked(self) -> None:
        assert self._run_owner(set_system=False) is False

    def test_system_stop_marks_own_queue(self) -> None:
        assert self._run_owner(set_system=True) is True


# ---------------------------------------------------------------------------
# H2 — метка переживает spawn-pickle в обе стороны.
# ---------------------------------------------------------------------------


class TestH2MarkSurvivesSpawnPickle:
    def test_parent_mark_visible_in_child(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        q, out = _new_queue(), ctx.Queue()
        q.mark_reader_gone()
        p = _run_child(_child_report_mark, (q, out), 5.0)
        try:
            assert out.get(timeout=5.0) is True
        finally:
            _kill(p)
            _drop(q)

    def test_child_mark_visible_in_parent(self) -> None:
        q = _new_queue()
        assert q.is_reader_gone() is False
        p = _run_child(_child_set_mark, (q,), 5.0)
        try:
            p.join(5.0)
            assert q.is_reader_gone() is True
        finally:
            _kill(p)
            _drop(q)


# ---------------------------------------------------------------------------
# H3 — метка появилась ПОСЛЕ первого взгляда писателя (гонка) + задержка реакции.
# ---------------------------------------------------------------------------


class TestH3MarkAfterWriterLooked:
    def test_writer_exits_soon_after_late_mark(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        q, done = _new_queue(), ctx.Queue()
        p = _run_child(_child_put_big_then_exit_hook, (q, 0, done), 10.0)
        try:
            time.sleep(2.0)  # писатель уже в хуке ≥1 с: смотрит на немаркированную очередь
            assert p.is_alive(), "писатель вышел без метки — значит отпустил по таймеру"
            marked_at = time.monotonic()
            q.mark_reader_gone()
            p.join(2.0)
            assert not p.is_alive(), "писатель не заметил позднюю метку за 2s"
            released, dropped, finished_at = done.get(timeout=2.0)
            latency = finished_at - marked_at
            assert (released, dropped) == (1, 0)  # BIG уже снят feeder'ом — в буфере пусто
            assert latency < 0.5, f"реакция на метку {latency:.3f}s"
        finally:
            _kill(p)
            _drop(q)


# ---------------------------------------------------------------------------
# H4 — без метки медленный живой читатель получает всё целиком (нет таймера).
# ---------------------------------------------------------------------------


class TestH4UnmarkedSlowReaderGetsEverything:
    def test_slow_reader_after_1_5s_gets_all(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        q, done = _new_queue(), ctx.Queue()
        p = _run_child(_child_put_big_then_exit_hook, (q, 5, done), 10.0)
        try:
            time.sleep(1.5)
            assert p.is_alive(), "писатель вышел без читателя и без метки — отпуск по таймеру"
            got = _in_thread(lambda: [q.get(timeout=5.0) for _ in range(6)], 10.0)
            assert got[0] == ("big", BIG)
            assert got[1:] == [("small", i) for i in range(5)]
            p.join(5.0)
            assert not p.is_alive(), "писатель не вышел после слива"
            assert done.get(timeout=2.0)[:2] == (0, 0)
        finally:
            _kill(p)
            _drop(q)


# ---------------------------------------------------------------------------
# H5 — повторный вызов хука; H6 — голая mp.Queue не задета.
# ---------------------------------------------------------------------------


class TestH5H6HookIdempotentAndPlainQueueUntouched:
    def test_second_call_is_noop(self) -> None:
        q = _new_queue()
        try:
            q.put(BIG)
            q.put(b"tail")
            time.sleep(0.2)
            q.mark_reader_gone()
            first = _in_thread(lambda: release_feeders_at_exit([], [q], system_stop=False), 3.0)
            second = _in_thread(lambda: release_feeders_at_exit([q], [q, q], system_stop=True), 3.0)
            assert first == (1, 1)  # BIG застрял в send (не считается), tail — в буфере
            assert second == (0, 0)
        finally:
            _drop(q)

    def test_plain_mp_queue_is_not_touched(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        q = ctx.Queue()
        try:
            q.put(BIG)
            time.sleep(0.2)
            res = _in_thread(lambda: release_feeders_at_exit([q], [q], system_stop=True), 3.0)
            assert res == (0, 0)
            assert q._closed is False and q._joincancelled is False
            assert _in_thread(lambda: q.get(timeout=5.0), 10.0) == BIG
        finally:
            _drop(q)


# ---------------------------------------------------------------------------
# H7 — буферизованные сообщения считаются ровно; H8 — строка итога доходит до stderr.
# ---------------------------------------------------------------------------


class TestH7BufferedCountIsExact:
    def test_n_buffered_items_give_n(self) -> None:
        q = _new_queue()
        try:
            q.put(BIG)  # feeder снимет его и застрянет в send на полном pipe
            for i in range(5):
                q.put(i)
            time.sleep(0.3)
            q.mark_reader_gone()
            assert _in_thread(lambda: release_feeders_at_exit([], [q], system_stop=False), 3.0) == (1, 5)
        finally:
            _drop(q)


class _SendBigPlusThree:
    """Писатель для H8: 1 MiB + 3 маленьких соседу 'Reader' продовым путём."""

    def __init__(self, name, shared_resources, config) -> None:
        self.shared_resources = shared_resources

    def initialize(self) -> bool:
        return True

    def run(self) -> None:
        reg = self.shared_resources.queue_registry
        reg.send_to_queue("Reader", "data", BIG)
        for i in range(3):
            reg.send_to_queue("Reader", "data", i)

    def should_stop(self) -> bool:
        return False

    def stop(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


_H8_SCRIPT = f"""
import multiprocessing, time
from multiprocess_framework.modules.process_manager_module.runner.process_runner import run_process_function
from multiprocess_framework.modules.shared_resources_module.queues.core.manager import QueueRegistry
ctx = multiprocessing.get_context("spawn")
q = QueueRegistry().create_queues({{"data": {{}}}})["data"]
stop = ctx.Event()
r = ctx.Process(target=run_process_function, args=("{__name__}._IdleOwner", "Reader", None,
    {{"queues": {{"data": q}}, "config": {{}}, "custom": {{}}}}, stop))
w = ctx.Process(target=run_process_function, args=("{__name__}._SendBigPlusThree", "Writer", None,
    {{"queues": {{}}, "config": {{}}, "custom": {{}}, "routing_map": {{"Reader": {{"data": q}}}}}}, stop))
r.start(); w.start(); time.sleep(1.5); stop.set()
r.join(10); w.join(10)
print("EXITCODES", r.exitcode, w.exitcode, flush=True)
q.cancel_join_thread()
"""


class TestH8ExitLineReachesStderr:
    def test_real_pair_prints_literal_line(self) -> None:
        env = dict(os.environ, PYTHONPATH=os.getcwd())
        proc = subprocess.run([sys.executable, "-c", _H8_SCRIPT], capture_output=True, text=True, timeout=40, env=env)
        assert "EXITCODES 0 0" in proc.stdout, (proc.stdout, proc.stderr[-2000:])
        lines = [ln for ln in proc.stderr.splitlines() if "queues released to gone readers" in ln]
        # Писатель: 1 очередь отпущена, 3 маленьких остались в буфере (BIG застрял в send).
        # Читатель отпускать нечего — молчит.
        assert lines == ["Writer: queues released to gone readers: 1, buffered dropped: 3"], proc.stderr[-2000:]


class _SendBigOnly(_SendBigPlusThree):
    """Писатель для H9: один 1 MiB — застрянет в send, буфер feeder'а пуст."""

    def run(self) -> None:
        self.shared_resources.queue_registry.send_to_queue("Reader", "data", BIG)


class TestH9InFlightLossWithEmptyBufferIsPrinted:
    def test_single_stuck_frame_prints_line_with_zero_buffered(self) -> None:
        env = dict(os.environ, PYTHONPATH=os.getcwd())
        script = _H8_SCRIPT.replace("._SendBigPlusThree", "._SendBigOnly")
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=40, env=env)
        assert "EXITCODES 0 0" in proc.stdout, (proc.stdout, proc.stderr[-2000:])
        lines = [ln for ln in proc.stderr.splitlines() if "queues released to gone readers" in ln]
        # «buffered dropped: 0» здесь — не ложная тревога: кадр в полёте потерян без счёта.
        assert lines == ["Writer: queues released to gone readers: 1, buffered dropped: 0"], proc.stderr[-2000:]
