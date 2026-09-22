# -*- coding: utf-8 -*-
"""Авторские hazard-тесты ``MjpegSinkPlugin`` (Task 1.2b плана ``line-sim``).

Опасные места механизма, названные в докстринге ``plugin.py``: (a) занятый
порт — синхронный ``OSError`` конструктора ``ThreadingHTTPServer`` (в отличие
от фонового bind'а ``SimRobotServer`` из Task 1.1) не роняет процесс; (b)
повторный ``start`` при живом сервере — no-op, порт не перебиндится; (c)
``shutdown()`` при живом (ещё читающем) клиенте не виснет — ``server.
shutdown()``/``server_close()`` останавливают только accept-цикл, а не
конкретное уже открытое соединение (докстринг модуля); (d) гонка
``process()`` (штатный поток плагина) против чтения сервером (чужой поток) —
дымовой прогон, пара ``(jpeg, seq)`` одним полем; (e)
``cv2.imencode`` не смог закодировать кадр — ``process()`` не падает и не
публикует мусор.

Харнесс — ``MockProcessServices`` + реальный ``PluginContext`` (тот же
приём, что ``Plugins/sim/robot_host/tests/test_hazards.py``, Task 1.1):
границу процесса подделываем, ``PluginContext`` и плагин — настоящие.
"""

from __future__ import annotations

import http.client
import socket
import threading
import time

import numpy as np
import pytest

from multiprocess_framework.modules.process_module.plugins.base import PluginContext
from multiprocess_framework.modules.process_module.plugins.testing import (
    MockProcessServices,
    MockStatsManager,
)
from Plugins.sim.mjpeg_sink.plugin import MjpegSinkPlugin

pytestmark = pytest.mark.timeout(30)


def _free_port() -> int:
    """Свободный TCP-порт (см. Services/robot_comm/tests/test_sim_e2e.py)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_plugin(port: int) -> tuple[MjpegSinkPlugin, PluginContext, MockProcessServices]:
    """Собрать плагин + PluginContext на MockProcessServices (не сконфигуренный старт)."""
    stats = MockStatsManager()
    services = MockProcessServices(name="camera", stats_manager=stats)
    ctx = PluginContext(services=services, config={"host": "127.0.0.1", "port": port})
    plugin = MjpegSinkPlugin()
    plugin.configure(ctx)
    return plugin, ctx, services


def _frame(value: int = 90) -> np.ndarray:
    return np.full((48, 64, 3), value, dtype=np.uint8)


# --------------------------------------------------------------------------- #
# (a) Порт занят -> report_error, состояние error, процесс живёт (не бросает) #
# --------------------------------------------------------------------------- #


def test_port_busy_reports_error_not_crash() -> None:
    """Порт занят СВОИМ сокетом -> ``start()`` не бросает, health получил ошибку.

    В отличие от ``SimRobotHostPlugin`` (Task 1.1), здесь НЕТ отдельного
    пробного bind'а — ``ThreadingHTTPServer.__init__`` сам биндит синхронно
    (``socketserver.TCPServer.__init__``, проверено чтением stdlib, см.
    докстринг модуля) и бросает ``OSError`` прямо в вызывающем потоке.
    """
    port = _free_port()
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", port))
    occupied.listen(1)
    try:
        plugin, ctx, services = _make_plugin(port)

        plugin.start(ctx)  # не должно бросить

        assert plugin._state == "error", f"ожидали state='error', получили {plugin._state!r}"
        assert plugin._server is None, "сервер не должен быть создан при занятом порту"

        health_state = getattr(services, "_health_state", None)
        assert health_state is not None, "ctx.health.report_error должен был создать HealthState на services"
        assert health_state.error_count >= 1, f"report_error не учтён: error_count={health_state.error_count}"
    finally:
        occupied.close()


# --------------------------------------------------------------------------- #
# (b) Повторный start при живом сервере — no-op (порт не перебиндится)        #
# --------------------------------------------------------------------------- #


def test_double_start_is_noop() -> None:
    """Второй ``start()`` не пересоздаёт сервер — иначе второй bind того же
    порта тем же процессом упал бы ``OSError`` и ошибочно перевёл бы running
    плагин в ``state='error'``."""
    port = _free_port()
    plugin, ctx, _services = _make_plugin(port)
    try:
        plugin.start(ctx)
        assert plugin._state == "running", f"первый start не поднял сервер: reason={plugin._reason!r}"
        first_server = plugin._server
        assert first_server is not None

        plugin.start(ctx)
        assert plugin._server is first_server, "повторный start пересоздал сервер — должен быть no-op"
        assert plugin._state == "running"
    finally:
        plugin.shutdown(ctx)


# --------------------------------------------------------------------------- #
# (c) shutdown() при живом клиенте не виснет                                  #
# --------------------------------------------------------------------------- #


def test_shutdown_does_not_hang_with_live_client() -> None:
    """Клиент держит открытое соединение и читает поток -> ``shutdown()``
    всё равно возвращается за разумное время.

    См. докстринг модуля: ``server.shutdown()``/``server_close()`` тушат
    только accept-цикл и слушающий сокет, поток уже открытого соединения
    они не закрывают — это ИЗВЕСТНОЕ ограничение (см. STATUS.md), а не
    гарантия его закрытия. Тест сторожит именно то, что ``shutdown()`` сам
    по себе не виснет, а не то, что клиент немедленно обрывается.
    """
    port = _free_port()
    plugin, ctx, _services = _make_plugin(port)
    plugin.start(ctx)
    assert plugin._state == "running", f"сервер не поднялся: {plugin._reason!r}"

    stop_feed = threading.Event()

    def _feed() -> None:
        while not stop_feed.is_set():
            plugin.process([{"frame": _frame()}])
            time.sleep(0.02)

    feeder = threading.Thread(target=_feed, daemon=True)
    feeder.start()
    time.sleep(0.2)  # дать первому кадру появиться до подключения клиента

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3.0)
    conn.request("GET", "/")
    resp = conn.getresponse()
    resp.read1(200)  # прочитать хоть что-то — клиент точно "живой"

    def _do_shutdown() -> None:
        plugin.shutdown(ctx)

    t = threading.Thread(target=_do_shutdown, daemon=True)
    t.start()
    t.join(timeout=8.0)
    assert not t.is_alive(), "shutdown() завис (>8с) при живом подключённом клиенте"
    assert plugin._server is None

    stop_feed.set()
    feeder.join(timeout=3.0)
    conn.close()


# --------------------------------------------------------------------------- #
# (d) Гонка process() <-> чтение сервером: целостность последнего кадра       #
# --------------------------------------------------------------------------- #


def test_concurrent_process_and_read_smoke() -> None:
    """НЕ сторожит гонку — это дымовой тест: `process()` и чтение с потока сервера
    работают одновременно, ничего не падает и байты остаются валидным JPEG.

    **Переименовать бы, но важнее сказать правду словами (ведущий, инъекция L7,
    2026-09-21).** Инъекция «снять оба `with self._frame_lock`» не убила ни одного
    теста — 95 passed. Этот тест проверяет SOI-маркер, а структурная целостность
    байтов под GIL не нарушается в принципе: `self._last_frame_jpeg = jpeg_bytes`
    это перепривязка ОДНОЙ ссылки, она атомарна и с локом, и без. Автор записал
    сомнение честно («не уверен, достаточно ли SOI-маркера») — оно подтвердилось.

    Настоящее свойство лока — атомарность ПАРЫ (`_last_frame_jpeg`, `_frame_seq`):
    читатель не должен увидеть новый номер со старыми байтами. Ведущий написал
    тест ровно на это (байты несли свой номер) и **не смог заставить его умереть**:
    без лока 0 рассогласованных пар на 60000 записей × 6 читателей при
    `sys.setswitchinterval(1e-9)`. Похоже, в CPython 3.12 eval breaker не вклинивается
    между двумя соседними `LOAD_ATTR` одного кадра. Тот тест УДАЛЁН, а не оставлен
    зелёным: тест, переживающий свою поломку, не существует.

    Лок СНЯТ (2026-09-21, предложение ревьюера Task 1.2): пара теперь живёт одним
    полем `_latest = (jpeg, seq)`, читатель берёт одну ссылку — рассогласовать нечего
    по построению, спорить о локе больше не о чем. Этот тест остаётся дымовым.
    """
    port = _free_port()
    plugin, ctx, _services = _make_plugin(port)
    plugin.start(ctx)
    assert plugin._state == "running"

    stop = threading.Event()
    errors: list[Exception] = []

    def _writer() -> None:
        sizes = [(48, 64), (96, 128), (32, 32)]
        i = 0
        while not stop.is_set():
            h, w = sizes[i % len(sizes)]
            plugin.process([{"frame": np.full((h, w, 3), (i % 250) + 1, dtype=np.uint8)}])
            i += 1

    def _reader() -> None:
        try:
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline:
                frame, seq = plugin._get_frame()
                if frame is not None:
                    # Валидный JPEG начинается с SOI-маркера 0xFFD8 — целостность
                    # структуры (не половина буфера, не мусор из другого кадра).
                    assert frame[:2] == b"\xff\xd8", f"кадр повреждён на seq={seq}: {frame[:8]!r}"
        except Exception as exc:  # noqa: BLE001 — отчитываем через список, не роняем поток
            errors.append(exc)

    writer = threading.Thread(target=_writer, daemon=True)
    reader = threading.Thread(target=_reader, daemon=True)
    writer.start()
    reader.start()
    reader.join(timeout=5.0)
    stop.set()
    writer.join(timeout=3.0)

    assert not errors, f"гонка обнаружена: {errors!r}"
    plugin.shutdown(ctx)


# --------------------------------------------------------------------------- #
# (e) cv2.imencode не смог закодировать кадр — process() не падает           #
# --------------------------------------------------------------------------- #


def test_encode_failure_does_not_crash_process() -> None:
    """Пустой кадр (``shape=(0, 0, 3)``) не даёт ``cv2.imencode`` уронить
    процесс целиком: замерено отдельно (не в докстринге без repro) — на этой
    форме ``cv2.imencode`` не возвращает ``ok=False``, а БРОСАЕТ ``cv2.error``
    (``OpenCV 4.13.0 ... Assertion failed) !_img.empty()``). ``process()``
    обязан пробросить items дальше как обычно, последний ВАЛИДНЫЙ кадр (если
    был) остаётся раздаваемым, а не затирается мусором/исключением."""
    port = _free_port()
    plugin, ctx, _services = _make_plugin(port)
    try:
        good = _frame(value=42)
        out1 = plugin.process([{"frame": good}])
        assert out1 == [{"frame": good}], "process() обязан пробросить items дальше (pass-through)"
        frame_bytes_before, seq_before = plugin._get_frame()
        assert frame_bytes_before is not None

        broken = np.zeros((0, 0, 3), dtype=np.uint8)
        out2 = plugin.process([{"frame": broken}])
        assert out2 == [{"frame": broken}], "process() обязан пробросить items дальше даже при сбое кодирования"

        frame_bytes_after, seq_after = plugin._get_frame()
        assert seq_after == seq_before, "битый кадр не должен был обновить последний валидный кадр"
        assert frame_bytes_after == frame_bytes_before
    finally:
        plugin.shutdown(ctx)
