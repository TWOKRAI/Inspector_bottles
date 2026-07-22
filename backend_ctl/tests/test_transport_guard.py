# -*- coding: utf-8 -*-
"""Task 1.3 — guard: request() из reader-потока даёт немедленную обучающую ошибку.

Дедлок-конвенция «не звать request() из потока-подписчика» раньше жила только в
докстринге (WatchController.start, backend_ctl/watch.py) — агент узнавал о ней, уже
повиснув на таймауте. Guard в transport.py::request() ловит это по идентичности
потока (``threading.current_thread() is self._reader``) и возвращает error-dict
СРАЗУ, не дожидаясь таймаута.

Два плеча (пара, как требует дисциплина плана):
  * TestCatchesFromReaderThread — подписчик event-hub'а зовёт request() ИЗ
    reader-потока → мгновенная ошибка, доказанная замером времени (<< default_timeout).
  * TestDoesNotCatchFromOtherThread — тот же вызов из постороннего (не reader)
    потока → штатная работа, guard не срабатывает. Явный background-поток (не главный
    поток теста) — тот же класс вызывающего, что и реальные applier-поток
    WatchController (``backend-ctl-resub``) и threading.Timer commit-confirmed
    (``registers.py::RegisterOps._set_register_confirmed``): guard сверяет ИДЕНТИЧНОСТЬ объекта
    потока, а не имя, поэтому любой посторонний поток проходит одинаково.

Оба сервера — сырые TCP-сокеты на localhost (без живого ProcessManager, без
BackendHarness — приём ``harness_smoke`` здесь не нужен и не размечен), по образцу
``test_conn_lost.py::_ToyServer``.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any, Dict, Optional

from backend_ctl.driver import BackendDriver
from backend_ctl.transport import _READER_THREAD_GUARD_ERROR

_HOST = "127.0.0.1"


class _PushServer:
    """TCP-сервер: принимает одно соединение, по команде шлёт одну push-строку.

    Push без совпадающего request_id уходит в ``_dispatch`` как событие → синхронные
    подписчики (``EventHub.emit``) вызываются ИМЕННО в reader-потоке клиента (контракт
    ``events.py``: «Синхронные подписчики получают ОРИГИНАЛЬНОЕ сообщение в
    reader-потоке») — этим тест ловит guard на реальном reader-потоке, поднятом
    настоящим ``connect()``, без живого бэкенда.
    """

    def __init__(self) -> None:
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.bind((_HOST, 0))
        self._srv.listen(1)
        self._srv.settimeout(5.0)
        self.port: int = self._srv.getsockname()[1]
        self._conn: Optional[socket.socket] = None
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    def _accept(self) -> None:
        try:
            conn, _ = self._srv.accept()
        except OSError:
            return
        self._conn = conn

    def wait_connected(self, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while self._conn is None and time.monotonic() < deadline:
            time.sleep(0.01)
        if self._conn is None:
            raise TimeoutError("тестовый сервер не дождался подключения клиента")

    def push(self, message: Dict[str, Any]) -> None:
        assert self._conn is not None, "push() до подключения клиента"
        line = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        self._conn.sendall(line)

    def stop(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except OSError:
                pass
        try:
            self._srv.close()
        except OSError:
            pass


class _EchoServer:
    """TCP-сервер: отвечает {"success": True} эхом request_id на любой запрос.

    Реальный round-trip (не заглушка результата) — доказывает, что «непойманный»
    вызов действительно прошёл штатный путь ``request()`` (отправка + ожидание
    ответа), а не что guard просто не был вызван по случайности.
    """

    def __init__(self) -> None:
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.bind((_HOST, 0))
        self._srv.listen(1)
        self._srv.settimeout(5.0)
        self.port: int = self._srv.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        try:
            conn, _ = self._srv.accept()
        except OSError:
            return
        buf = b""
        try:
            while True:
                try:
                    chunk = conn.recv(4096)
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    if not raw.strip():
                        continue
                    msg = json.loads(raw.decode("utf-8"))
                    reply = {"request_id": msg.get("request_id"), "result": {"success": True}}
                    conn.sendall((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def stop(self) -> None:
        try:
            self._srv.close()
        except OSError:
            pass


class TestCatchesFromReaderThread:
    """Плечо «ловит»: подписчик event-hub'а зовёт request() из reader-потока."""

    def test_request_from_reader_thread_returns_immediate_error(self) -> None:
        # default_timeout нарочно небольшой (2с), а done.wait ждёт заведомо ДОЛЬШЕ (8с):
        # без guard'а вызов из подписчика блокируется в pending.event.wait() ВНУТРИ
        # reader-потока (push-сервер не отвечает на запрос, отправленный ИЗНУТРИ
        # callback'а) ровно на 2с и лишь потом возвращает {"error": "timeout"} — done
        # всё равно будет установлен (8с с запасом хватает), а вот assert elapsed ниже
        # поймает регресс по СУЩЕСТВУ (elapsed≈2с "не мгновенно"), а не по побочному
        # "подписчик не дождались" — так регресс диагностируется точно тем утверждением,
        # которое проверяет приёмку («мгновенно», а не «в принципе завершилось»).
        server = _PushServer()
        drv = BackendDriver(host=_HOST, port=server.port, default_timeout=2.0)
        result: Dict[str, Any] = {}
        done = threading.Event()

        def _on_event(msg: Dict[str, Any]) -> None:
            if msg.get("command") != "trigger":
                return
            t0 = time.monotonic()
            try:
                result["response"] = drv.request({"command": "state.subscribe", "data": {"path": "**"}})
            except Exception as exc:  # noqa: BLE001 — фиксируем факт: контракт требует dict, не исключение
                result["exception"] = exc
            result["elapsed"] = time.monotonic() - t0
            done.set()

        try:
            drv.connect()
            server.wait_connected()
            drv.subscribe(_on_event)
            server.push({"command": "trigger"})
            assert done.wait(timeout=8.0), "подписчик не вызван — push не дошёл до reader-потока"

            assert "exception" not in result, (
                f"guard обязан вернуть error-dict, а не бросить исключение (BCTL-ADR-003): {result.get('exception')!r}"
            )
            response = result["response"]
            assert isinstance(response, dict)
            assert response.get("success") is False

            # СИЛЬНО меньше default_timeout (2с) — иначе это таймаут, а не guard.
            elapsed = result["elapsed"]
            assert elapsed < 0.5, f"guard не мгновенный: {elapsed:.3f}s (default_timeout=2.0s)"

            # Текст называет паттерн (очередь + applier-поток), а не только запрет,
            # и ссылается на живой образец WatchController.
            assert response["error"] == _READER_THREAD_GUARD_ERROR
            error_text = response["error"].lower()
            assert "watchcontroller" in error_text
            assert "watch.py" in error_text
            assert "applier" in error_text
            assert "queue" in error_text or "очеред" in error_text
        finally:
            drv.close()
            server.stop()


class TestDoesNotCatchFromOtherThread:
    """Плечо «не ловит»: вызов из постороннего потока — штатная работа."""

    def test_request_from_background_thread_behaves_normally(self) -> None:
        # Отдельный background-поток (не главный поток теста, не reader) — тот же
        # класс вызывающего, что и applier-поток WatchController/таймер
        # commit-confirmed: легитимные вызовы request() из НЕ-reader потоков.
        server = _EchoServer()
        drv = BackendDriver(host=_HOST, port=server.port, default_timeout=5.0)
        result: Dict[str, Any] = {}

        def _caller() -> None:
            result["response"] = drv.request({"command": "introspect.status"})

        try:
            drv.connect()
            caller_thread = threading.Thread(target=_caller, name="test-background-caller", daemon=True)
            caller_thread.start()
            caller_thread.join(timeout=5.0)

            assert not caller_thread.is_alive(), "фоновый вызов request() не завершился вовремя"
            response = result.get("response")
            assert response is not None, "request() не вернул результат"
            assert response.get("success") is True, f"guard ошибочно сработал на постороннем потоке: {response}"
        finally:
            drv.close()
            server.stop()

    def test_request_from_main_thread_behaves_normally(self) -> None:
        """Главный поток теста тоже не reader — контрольный случай без доп. потока."""
        server = _EchoServer()
        drv = BackendDriver(host=_HOST, port=server.port, default_timeout=5.0)
        try:
            drv.connect()
            response = drv.request({"command": "introspect.status"})
            assert response.get("success") is True, f"guard ошибочно сработал в главном потоке: {response}"
        finally:
            drv.close()
            server.stop()
