# -*- coding: utf-8 -*-
"""Приёмка Task 1.3 (независимый тестер, вслепую): строка потерь на выходе.

Источник контракта — бриф лида (DESIGN/ACCEPTANCE в задаче), не implementation:
``interface.py`` для этого механизма нет, поэтому REDS пиновятся буквально по
литералам из брифа. План (``plans/lifecycle-stop-ownership.md``) и авторские
тесты (``test_reader_gone_hazards.py``) НЕ читались — запрещены заданием.

Проверяемое поведение (``release_feeders_at_exit`` +
``run_process_function``'s ``finally``, ADR-SRM-016):

  A1. Ничего не потеряно (сообщение реально доставлено) -> ``(0, 0)`` и НИ ОДНОЙ
      строки в stderr. Дефект брифа — гонка: feeder жив ещё мгновение между
      ``close()`` (сентинел) и своим выходом, а метка «читатель ушёл» уже
      взведена -> ложное «отпущено» без утраты.
  A2. 5 мелких сообщений застряли в буфере feeder'а за спиной у сообщения
      1 МиБ, читателя нет -> ``(1, 5)`` и литерал ``buffered dropped: 5``.
  A3. Одно сообщение 1 МиБ застряло в ``send``, буфер пуст -> ``(1, 0)`` —
      подлинная потеря "в полёте", молчать об этом нельзя.
  A4. Канальный пин: строка обязана долетать до stderr родителя, даже когда
      собственный LoggerManager процесса уже остановлен к моменту хука выхода
      (тот использует ``emergency_log``, а не вид процесса — ревью Task 1.2).

Прямые (direct) тесты зовут ``release_feeders_at_exit`` в тестовом процессе —
это чистый OS-эффект (блокирующий ``write()`` на переполненном pipe), от
межпроцессности не зависит. "Реальный ребёнок" тесты гоняют настоящий
``run_process_function`` в отдельном OS-процессе через ``python <script>.py``
(НЕ ``multiprocessing.Process`` — очередь создаётся внутри самого скрипта,
поэтому pickle через spawn не нужен) и читают его stderr.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from multiprocess_framework.modules.shared_resources_module.queues.core.reader_gone import (
    ReaderGoneQueue,
    release_feeders_at_exit,
)

# tests/ -> shared_resources_module -> modules -> multiprocess_framework -> корень worktree
_WORKTREE_ROOT = Path(__file__).resolve().parents[4]

_BIG_MESSAGE = b"x" * (1024 * 1024)  # 1 MiB > буфер OS pipe — TRAPS брифа


# =========================================================================
# Классы-процессы для реальных дочерних запусков (top-level, dotted-path).
# =========================================================================


class _BaseChildProcess:
    """Минимальный процесс-контракт runner'а: initialize/run/stop/shutdown."""

    def __init__(self, name, shared_resources, config):
        self.name = name
        self.shared_resources = shared_resources

    def _queue(self):
        return self.shared_resources.queue_registry.get_process_queues(self.name)["out"]

    def initialize(self):
        return True

    def stop(self):
        pass

    def shutdown(self):
        pass


class SelfConsumeProcess(_BaseChildProcess):
    """A1: кладём одно маленькое сообщение и тут же его забираем — потерь быть не должно."""

    def run(self):
        q = self._queue()
        q.put("hello")
        msg = q.get(timeout=5)
        assert msg == "hello"


class StuckBehindBigProcess(_BaseChildProcess):
    """A2: 5 мелких сообщений застряли в буфере feeder'а за сообщением 1 МиБ, читателя нет."""

    def run(self):
        q = self._queue()
        q.put(_BIG_MESSAGE)
        for i in range(5):
            q.put(f"small-{i}")
        # Дать feeder'у реально попытаться отправить первое (крупное) сообщение
        # и упереться в OS pipe — иначе все 6 сообщений всё ещё в _buffer.
        time.sleep(0.5)


class StuckWithRealLoggerProcess(_BaseChildProcess):
    """A4: как A2, но с реальным LoggerManager, остановленным в shutdown() ДО хука выхода."""

    def run(self):
        from multiprocess_framework.modules.logger_module import (
            LoggerChannelSchema,
            LoggerManager,
            LoggerManagerConfig,
        )

        log_dir = tempfile.mkdtemp(prefix="a4log_")
        channel = LoggerChannelSchema(
            name="system_file",
            type="file",
            enabled=True,
            file_path="system.log",
            rotate=False,
        )
        config = LoggerManagerConfig(
            app_name="task13-a4",
            log_directory=log_dir,
            modules={},
            channels={"system_file": channel},
        )
        self._logger_manager = LoggerManager(config=config)

        q = self._queue()
        q.put(_BIG_MESSAGE)
        for i in range(5):
            q.put(f"small-{i}")
        time.sleep(0.5)

    def shutdown(self):
        lm = getattr(self, "_logger_manager", None)
        if lm is not None:
            lm.shutdown()


# =========================================================================
# Драйвер реального дочернего процесса.
# =========================================================================


def _spawn_child(class_name: str, timeout: float = 30.0) -> subprocess.CompletedProcess:
    """Запустить ``run_process_function`` в НАСТОЯЩЕМ отдельном OS-процессе.

    Очередь создаётся ВНУТРИ самого скрипта (не в тестовом процессе) — поэтому
    это plain ``subprocess``, а не ``multiprocessing.Process``: живой
    ``ReaderGoneQueue`` с feeder-потоком через pickle обычного ``subprocess``
    не провезти, а через spawn-inheritance его и не нужно — сценарий не
    требует межпроцессной маршрутизации, только «владелец = сам процесс».

    ``system_stop_event`` взведён ДО спавна: тогда ``_run_lifecycle`` выходит
    из цикла сразу после первой проверки, и хук выхода зовётся с
    ``system_stop=True`` — как при настоящем системном стопе.
    """
    class_path = (
        f"multiprocess_framework.modules.shared_resources_module.tests.test_exit_loss_line_acceptance.{class_name}"
    )
    script = f"""
import multiprocessing as mp
from multiprocess_framework.modules.process_manager_module.runner.process_runner import run_process_function
from multiprocess_framework.modules.shared_resources_module.queues.core.reader_gone import ReaderGoneQueue

q = ReaderGoneQueue()
bundle = {{"queues": {{"out": q}}, "config": {{}}, "custom": {{}}, "routing_map": {{}}}}
evt = mp.Event()
evt.set()
run_process_function({class_path!r}, "childproc", None, bundle, evt)
"""
    fd, script_path = tempfile.mkstemp(suffix=".py", text=True)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(script)
        env = dict(os.environ)
        env["PYTHONPATH"] = str(_WORKTREE_ROOT)
        # subprocess.run(timeout=...) — зависание падает TimeoutExpired'ом,
        # а не вешает раннер навсегда (TEST RULES брифа).
        return subprocess.run(
            [sys.executable, script_path],
            cwd=str(_WORKTREE_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    finally:
        os.unlink(script_path)


# =========================================================================
# A1 — ничего не потеряно.
# =========================================================================


def test_a1_nothing_lost_returns_zero_zero():
    """Прямой вызов: доставленное сообщение никогда не должно посчитаться потерей.

    Гонка (докстринг ``reader_gone.py``): feeder ещё "alive" в момент между
    ``close()`` (сентинел) и своим фактическим выходом. Повтор >= 20 раз —
    одного прогона для гоночного дефекта недостаточно; ниже — наблюдаемая
    частота ложных срабатываний (red rate).
    """
    total = 30
    red = 0
    red_examples = []
    for i in range(total):
        q = ReaderGoneQueue()
        q.put("msg")
        got = q.get(timeout=5)
        assert got == "msg"
        result = release_feeders_at_exit([q], [q], system_stop=True)
        if result != (0, 0):
            red += 1
            if len(red_examples) < 3:
                red_examples.append(result)
        try:
            q.close()
        except Exception:
            pass
        q.cancel_join_thread()
    assert red == 0, (
        f"ложная потеря для доставленного сообщения в {red}/{total} прогонах "
        f"(ожидание всегда (0, 0)); примеры: {red_examples}"
    )


def test_a1_nothing_lost_real_child_prints_no_line():
    """Реальный ребёнок: доставленное сообщение — НИ ОДНОЙ строки о потере в stderr.

    Один прогон (не серия — spawn дорог); гоночная природа A1 означает, что
    единичный green здесь НЕ доказывает отсутствие дефекта — см. отчёт.
    """
    result = _spawn_child("SelfConsumeProcess")
    assert "queues released to gone readers" not in result.stderr, result.stderr


# =========================================================================
# A2 — N застрявших в буфере за крупным сообщением.
# =========================================================================


def test_a2_buffered_n_reported_literal():
    """A2: (1, 5) прямым вызовом + литерал ``buffered dropped: 5`` в stderr реального ребёнка."""
    # Белый ящик: сама функция.
    q = ReaderGoneQueue()
    q.put(_BIG_MESSAGE)
    for i in range(5):
        q.put(f"small-{i}")
    time.sleep(0.5)
    q.mark_reader_gone()
    released, buffered_dropped = release_feeders_at_exit([q], [q], system_stop=False)
    assert (released, buffered_dropped) == (1, 5)
    q.cancel_join_thread()

    # Чёрный ящик: настоящий дочерний процесс, тот же сценарий через runner.
    result = _spawn_child("StuckBehindBigProcess")
    assert "buffered dropped: 5" in result.stderr, result.stderr


# =========================================================================
# A3 — подлинная потеря "в полёте", буфер пуст.
# =========================================================================


def test_a3_in_flight_with_empty_buffer_still_released():
    """A3: одно сообщение застряло в send(), буфер пуст -> (1, 0) — потеря не молчит."""
    q = ReaderGoneQueue()
    q.put(_BIG_MESSAGE)
    time.sleep(0.5)
    q.mark_reader_gone()
    released, buffered_dropped = release_feeders_at_exit([q], [q], system_stop=False)
    assert (released, buffered_dropped) == (1, 0)
    q.cancel_join_thread()


# =========================================================================
# A4 — канальный пин: доезжает даже с остановленным LoggerManager.
# =========================================================================


def test_a4_line_reaches_stderr_with_real_stopped_logger_manager():
    """A4: A2-сценарий + процесс держит РЕАЛЬНЫЙ LoggerManager, остановленный до хука.

    ``shutdown()`` процесса (останавливает LoggerManager) зовётся runner'ом
    ДО хука отпуска очередей (порядок в ``process_runner.py``'s ``finally``) —
    ровно то окно, которое проверяет A4.
    """
    result = _spawn_child("StuckWithRealLoggerProcess")
    assert "buffered dropped: 5" in result.stderr, result.stderr
