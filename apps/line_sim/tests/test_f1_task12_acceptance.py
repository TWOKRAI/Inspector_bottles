# -*- coding: utf-8 -*-
"""Приёмочные RED-тесты (Task 1.2 плана line-sim) для НОВОГО плагина
``Plugins.sim.mjpeg_sink.plugin.MjpegSinkPlugin`` — критерий 3 брифа lead'а ("живой MJPEG").

Независимый тестер, БЕЗ реализации (worktree на коммите ДО неё). ``Plugins/sim/mjpeg_sink``
СЕГОДНЯ НЕ СУЩЕСТВУЕТ вообще (ни каталога, ни файла) — это ``import`` НОВОГО модуля, форма RED
здесь по конструкции ``ModuleNotFoundError`` на collection, для ВСЕХ тестов файла разом. Это
ожидаемо и корректно (аналог "new-full" NotImplementedError-контракта из dev/tester протокола
для полностью нового модуля), а не поломанный setup теста — см. финальный отчёт тестера.

Контракт (из DESIGN-секции брифа, НЕ из кода — ``interface.py`` для ``mjpeg_sink`` не заведён):
  - плагин ``sink``-категории, вход ``frame`` (``image/bgr``), форма — как у
    ``Plugins/sim/robot_host/plugin.py`` (``configure``/``start``/``shutdown`` + ``ctx.health``);
  - HTTP-сервер stdlib на порту ИЗ КОНФИГА; ``GET /`` отдаёт ПОСЛЕДНИЙ кадр как
    ``multipart/x-mixed-replace``.

Догадки тестера сняты ведущим по фактам кода (2026-09-21) — ниже КОНТРАКТ, не гипотеза:
  - метод приёма кадра — ``process(items: list[dict]) -> list[dict]``: это сигнатура
    базового класса ``ProcessModulePlugin.process`` (``process_module/plugins/base.py:1426``),
    а не обобщение одного прецедента ``modbus_sink``;
  - имя ключа порта в конфиге — ``port``, в ряд с соседом по ``Plugins/sim``
    (``robot_host/plugin.py``, Task 1.1). Хедж ``http_port`` УБРАН: тест, принимающий оба
    имени, сторожит не имя, а собственную терпимость;
  - вход объявляется ``Port(name="frame", dtype="image/bgr", shape="(H, W, 3)")`` — форма
    из ``Plugins/processing/*/plugin.py`` (grayscale, roi_crop, contour_draw);
  - хост — ``127.0.0.1``, порт юнит-тестов свободный, НЕ 8091 (8091 меряет ведущий на
    живом стенде).

Харнесс: ``ctx = MagicMock()`` + реальный ``HealthReporter``/``HealthState`` — тот же приём,
что ``Plugins/sources/camera_service/tests/test_health_fault.py`` и мой файл для Task 1.2
камеры (единообразие в рамках одной задачи).

Все сетевые чтения — с явным дедлайном/таймаутом сокета И в отдельном потоке с
``join(timeout=...)`` (TRAPS брифа: multipart-поток бесконечен, простой ``.read()`` без
границы зависнет навсегда).
"""

from __future__ import annotations

import http.client
import socket
import threading
import time
from unittest.mock import MagicMock

import cv2
import numpy as np
import pytest

from multiprocess_framework.modules.process_module.health import HealthReporter, HealthState

pytestmark = pytest.mark.timeout(45)


def _free_port() -> int:
    """Свободный TCP-порт (см. Services/robot_comm/tests/test_sim_e2e.py)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_test_frame(width: int = 64, height: int = 48, value: int = 90) -> np.ndarray:
    return np.full((height, width, 3), value, dtype=np.uint8)


def _make_sink(port: int):
    """Собрать MjpegSinkPlugin + реальный health поверх mock-контекста.

    Импорт — ВНУТРИ функции: если модуля нет, ошибка всплывает на первом вызове (не на
    collection всех тестов через module-level import) — решил оставить module-level import
    ниже тоже (для ясной формы ModuleNotFoundError на collection, см. докстринг файла);
    эта функция просто инкапсулирует сборку.
    """
    from Plugins.sim.mjpeg_sink.plugin import MjpegSinkPlugin  # noqa: PLC0415 — см. докстринг

    state = HealthState(log_only=False)
    ctx = MagicMock()
    # Имя поля порта — РЕШЕНИЕ ведущего (не хедж): ``port``, в ряд с соседом по
    # ``Plugins/sim`` — ``sim_robot_host`` (Task 1.1, ``robot_host/plugin.py:_DEFAULT_PORT``).
    ctx.config = {"host": "127.0.0.1", "port": port}
    ctx.health = HealthReporter(state, source="mjpeg_sink")

    plugin = MjpegSinkPlugin()
    plugin.configure(ctx)
    plugin.start(ctx)
    return plugin, state, ctx


def _read_bounded(port: int, max_bytes: int = 4000, timeout: float = 3.0) -> bytes:
    """Прочитать ОГРАНИЧЕННОЕ число байт ответа с дедлайном (поток multipart бесконечен).

    ДВЕ ПРАВКИ ВЕДУЩЕГО 2026-09-21 — обе найдены, когда модуль плагина появился и перестал
    маскировать хелпер собой (до этого все 4 теста файла падали ``ModuleNotFoundError`` на
    сборке фикстуры, и поломка хелпера была не видна ни в одном прогоне):

    1. Было ``resp.fp._sock.settimeout(timeout)`` — безусловный ``AttributeError`` до
       единого прочитанного байта: ``resp.fp`` это ``_io.BufferedReader``, ``_sock`` живёт
       на ``resp.fp.raw`` (``socket.SocketIO``). Эскалировано разработчиком 1.2b,
       воспроизведено ведущим на голом ``http.server`` вне плагина (Python 3.12.13).
       Строка не подменена на ``raw._sock``, а УДАЛЕНА: таймаут уже задаёт конструктор
       ``HTTPConnection(timeout=...)`` и он реально правит чтением тела — замер на
       молчащем сервере дал ``TimeoutError`` ровно за 2.0 с при ``timeout=2.0``. Лезть в
       приватные потроха ``http.client`` ради гарантии, которая уже есть, незачем.

    2. Было: ЛЮБОЕ исключение → ``pytest.fail``. Но молчание сервера — это не отказ, а
       ровно то поведение, которое пинит ``test_no_frame_yet_server_answers_without_boundary``
       («кадра ещё нет — клиент ждёт»). С прежним хелпером этот тест краснел бы на
       ПРАВИЛЬНОЙ реализации: ``TimeoutError`` при чтении тела → ``pytest.fail``. Неверная
       модель в спеке, а не опечатка. Теперь таймаут ЧТЕНИЯ ТЕЛА — штатное завершение,
       возвращаем накопленное; отказ соединения/ответа по-прежнему валит тест.

    ``read1`` вместо ``read``: ``BufferedReader.read(n)`` блокируется до ровно ``n`` байт
    или EOF, а у бесконечного multipart-потока EOF не наступает никогда — из-за этого и
    понадобился когда-то низкоуровневый ``settimeout``. ``read1`` отдаёт что есть за один
    обход сокета и на частичном кадре не виснет.
    """
    result: dict = {}

    def _read() -> None:
        conn = None
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
            conn.request("GET", "/")
            resp = conn.getresponse()
            result["status"] = resp.status
            result["headers"] = dict(resp.getheaders())
            data = b""
            try:
                while len(data) < max_bytes:
                    chunk = resp.read1(max_bytes - len(data))
                    if not chunk:
                        break
                    data += chunk
            except TimeoutError:
                pass  # сервер молчит — штатное «клиент ждёт», см. докстринг
            result["body"] = data
        except Exception as exc:  # noqa: BLE001 — отчитываем через result, не роняем поток
            result["error"] = exc
        finally:
            if conn is not None:
                conn.close()

    t = threading.Thread(target=_read, daemon=True)
    t.start()
    t.join(timeout=timeout + 2.0)
    assert not t.is_alive(), f"чтение с MJPEG-сервера зависло (>{timeout + 2.0}с)"
    if "error" in result and "body" not in result:
        pytest.fail(f"ошибка при чтении с MJPEG-сервера: {result['error']!r}")
    return result.get("body", b"")


# --------------------------------------------------------------------------- #
# Критерий 3: GET / отдаёт multipart-boundary + Content-Type: image/jpeg      #
# --------------------------------------------------------------------------- #


def test_mjpeg_boundary_and_jpeg_content_type() -> None:
    """Пин: после хотя бы одного кадра GET / содержит multipart-boundary ("--") и
    "Content-Type: image/jpeg" в теле части (в первых 4000 байт ответа).

    Провал сегодня: ``Plugins.sim.mjpeg_sink`` не существует — ModuleNotFoundError на
    сборке фикстуры (ожидаемо для полностью нового модуля, см. докстринг файла).
    """
    port = _free_port()
    plugin, _state, _ctx = _make_sink(port)
    try:
        plugin.process([{"frame": _make_test_frame()}])

        body = _read_bounded(port)
        assert body, "GET / не вернул ни байта тела ответа за отведённое время"
        assert b"--" in body, f"в первых {len(body)} байтах нет multipart-boundary ('--'): {body[:200]!r}"
        assert b"image/jpeg" in body.lower() or b"image/jpeg" in body, (
            f"в первых {len(body)} байтах нет 'Content-Type: image/jpeg': {body[:200]!r}"
        )
    finally:
        plugin.shutdown(_ctx)


# --------------------------------------------------------------------------- #
# Критерий 3: cv2.VideoCapture читает >=5 кадров за 5с при непрерывной подаче #
# --------------------------------------------------------------------------- #


def test_videocapture_reads_five_frames_in_five_seconds() -> None:
    """Пин: пока плагин непрерывно получает кадры, cv2.VideoCapture(url) читает >=5
    успешных (ret=True) кадров за 5с.

    Провал сегодня: ModuleNotFoundError (нового модуля нет).
    """
    port = _free_port()
    plugin, _state, ctx = _make_sink(port)
    stop = threading.Event()

    def _feed() -> None:
        i = 0
        while not stop.is_set():
            plugin.process([{"frame": _make_test_frame(value=(i % 50) + 50)}])
            i += 1
            time.sleep(0.05)

    feeder = threading.Thread(target=_feed, daemon=True)
    feeder.start()
    try:
        # дать первому кадру долететь до сервера
        time.sleep(0.3)

        result: dict = {"count": 0}

        def _capture() -> None:
            cap = cv2.VideoCapture(f"http://127.0.0.1:{port}/")
            try:
                deadline = time.monotonic() + 5.0
                count = 0
                while time.monotonic() < deadline and count < 5:
                    ret, frame = cap.read()
                    if ret and frame is not None:
                        count += 1
                result["count"] = count
            finally:
                cap.release()

        t = threading.Thread(target=_capture, daemon=True)
        t.start()
        t.join(timeout=8.0)
        assert not t.is_alive(), "cv2.VideoCapture завис (>8с) на MJPEG-эндпойнте плагина"
        assert result["count"] >= 5, f"прочитано только {result['count']} успешных кадров за 5с (нужно >=5)"
    finally:
        stop.set()
        feeder.join(timeout=3.0)
        plugin.shutdown(ctx)


# --------------------------------------------------------------------------- #
# Критерий 3: два клиента обслуживаются одновременно                         #
# --------------------------------------------------------------------------- #


def test_two_clients_served_simultaneously() -> None:
    """Пин: ДВА одновременных ``cv2.VideoCapture``-клиента оба получают >=1 успешный кадр.

    Провал сегодня: ModuleNotFoundError.
    """
    port = _free_port()
    plugin, _state, ctx = _make_sink(port)
    stop = threading.Event()

    def _feed() -> None:
        while not stop.is_set():
            plugin.process([{"frame": _make_test_frame()}])
            time.sleep(0.05)

    feeder = threading.Thread(target=_feed, daemon=True)
    feeder.start()
    try:
        time.sleep(0.3)
        results: dict = {}

        def _client(name: str) -> None:
            cap = cv2.VideoCapture(f"http://127.0.0.1:{port}/")
            try:
                deadline = time.monotonic() + 5.0
                ok = False
                while time.monotonic() < deadline and not ok:
                    ret, frame = cap.read()
                    ok = bool(ret and frame is not None)
                results[name] = ok
            finally:
                cap.release()

        t1 = threading.Thread(target=_client, args=("a",), daemon=True)
        t2 = threading.Thread(target=_client, args=("b",), daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=8.0)
        t2.join(timeout=8.0)
        assert not t1.is_alive() and not t2.is_alive(), "один из клиентов завис (>8с)"
        assert results.get("a") is True, "клиент 'a' не получил ни одного кадра за 5с"
        assert results.get("b") is True, "клиент 'b' не получил ни одного кадра за 5с"
    finally:
        stop.set()
        feeder.join(timeout=3.0)
        plugin.shutdown(ctx)


# --------------------------------------------------------------------------- #
# Краевой случай: кадра ещё нет — сервер отвечает, границ не шлёт             #
# --------------------------------------------------------------------------- #


def test_no_frame_yet_server_answers_without_boundary() -> None:
    """Пин: ДО первого ``process()`` GET / не роняет соединение (сервер отвечает) и НЕ
    шлёт multipart-boundary в теле (кадра ещё нет — ждать/пустое тело, не мусор).

    Провал сегодня: ModuleNotFoundError.

    Интерпретация (не факт брифа, см. отчёт): "сервер отвечает" читаю как "TCP-соединение
    принимается и не рвётся сразу же ошибкой" — необязательно HTTP 200 со статус-строкой
    в первые же байты, если реализация решит держать соединение открытым до первого кадра.
    """
    port = _free_port()
    plugin, _state, ctx = _make_sink(port)
    try:
        body = _read_bounded(port, max_bytes=2000, timeout=1.5)
        assert b"--" not in body, (
            f"сервер отдал multipart-boundary ДО первого кадра (кадра ещё не было): {body[:200]!r}"
        )
    finally:
        plugin.shutdown(ctx)
