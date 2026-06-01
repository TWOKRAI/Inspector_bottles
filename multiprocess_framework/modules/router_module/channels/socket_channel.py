# -*- coding: utf-8 -*-
"""
SocketChannel — серверный TCP-канал (сиблинг QueueChannel).

Обычный IMessageChannel: делает ТОЛЬКО байтовый I/O на границе системы.
Регистрируется в RouterManager хоста через register_channel (by-design extension).
Без бизнес-логики — связь с router'ом делает on_inbound-колбэк (см. P2 дизайн §4).

Назначение: внешний тонкий driver (backend_ctl, dev-инструмент) подключается по TCP и
шлёт те же router-сообщения, что GUI по локальной очереди. Граница — ровно Claude↔driver.

Wire-формат: UTF-8, newline-delimited JSON, только dict. Кадры/SHM через сокет НЕ гоняем.

Направления:
  - INBOUND (driver → система): read-loop читает строки, json.loads → on_inbound(msg).
    Это push, не pull → poll() намеренно no-op (receive-цикл router'а канал не опрашивает).
  - OUTBOUND (система → driver): router зовёт send() через _resolve_channels(channel=name);
    JSON+"\n" пишется в клиентские сокеты под Lock.

Гейт/безопасность — на стороне хоста (BACKEND_CTL=1 + bind 127.0.0.1). Канал сам по себе
аутентификацию не делает (localhost dev-tool).
"""

from __future__ import annotations

import json
import socket
import threading
from typing import Any, Callable, Dict, List, Optional

from .base_channel import MessageChannel


class SocketChannel(MessageChannel):
    """Серверный TCP-эндпоинт как IMessageChannel.

    Args:
        name: имя канала (= адрес для channel=-маршрутизации ответа, напр. "backend_ctl").
        host: bind-адрес (по умолчанию 127.0.0.1 — localhost-only).
        port: TCP-порт.
        on_inbound: колбэк(msg: dict) для каждого прочитанного сообщения. None → сообщения
            читаются и отбрасываются (канал работает, но никуда не передаёт).
        log_warning/log_error: инъекция логирования (или от RouterManager при регистрации).
    """

    def __init__(
        self,
        name: str,
        host: str = "127.0.0.1",
        port: int = 8765,
        on_inbound: Optional[Callable[[Dict[str, Any]], None]] = None,
        log_warning: Optional[Callable[[str], None]] = None,
        log_error: Optional[Callable[[str], None]] = None,
    ) -> None:
        super().__init__(log_warning=log_warning, log_error=log_error)
        self._name = name
        self._host = host
        self._port = port
        self._on_inbound = on_inbound

        self._server_sock: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None
        self._running = False
        self._bound = False

        # Клиентские соединения + лок на запись (fan-out ответов всем подключённым).
        self._clients: List[socket.socket] = []
        self._clients_lock = threading.Lock()
        self._write_lock = threading.Lock()

        # Счётчики для get_info (наблюдаемость).
        self._rx = 0
        self._tx = 0

    # ---- IMessageChannel: свойства ----

    @property
    def name(self) -> str:
        return self._name

    @property
    def channel_type(self) -> str:
        return "socket"

    @property
    def port(self) -> int:
        """Фактический порт после bind (актуально при port=0 — авто-выбор ОС)."""
        return self._port

    @property
    def host(self) -> str:
        return self._host

    # ---- Жизненный цикл ----

    def start(self) -> bool:
        """Поднять сервер: socket/bind/listen + accept-loop в daemon-потоке.

        Returns:
            True если поднят; False если уже запущен или bind не удался.
        """
        if self._running:
            return False
        try:
            self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_sock.bind((self._host, self._port))
            # При port=0 ОС выбирает свободный порт — фиксируем фактический.
            self._port = self._server_sock.getsockname()[1]
            self._server_sock.listen(5)
            # Таймаут на accept, чтобы поток мог завершиться по флагу _running.
            self._server_sock.settimeout(0.5)
            self._bound = True
        except OSError as exc:
            self._log_error(f"[SocketChannel:{self._name}] bind/listen failed: {exc}")
            self._bound = False
            if self._server_sock is not None:
                self._server_sock.close()
                self._server_sock = None
            return False

        self._running = True
        self._accept_thread = threading.Thread(
            target=self._accept_loop,
            name=f"socket-ch-accept-{self._name}",
            daemon=True,
        )
        self._accept_thread.start()
        return True

    def close(self) -> None:
        """Остановить accept-loop, закрыть клиентские и серверный сокеты."""
        self._running = False
        # Закрыть клиентов — их read-loop'ы выйдут.
        with self._clients_lock:
            clients = list(self._clients)
            self._clients.clear()
        for c in clients:
            try:
                c.close()
            except OSError:
                pass
        # Закрыть серверный сокет.
        if self._server_sock is not None:
            try:
                self._server_sock.close()
            except OSError:
                pass
            self._server_sock = None
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=1.0)
            self._accept_thread = None
        self._bound = False

    # ---- IMessageChannel: отправка (OUTBOUND система → driver) ----

    def send(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Сериализовать dict в newline-JSON и отправить всем клиентам (под Lock).

        Зовётся ТОЛЬКО router'ом через _resolve_channels(channel=name).

        Returns:
            {"status": "success"|"error", "channel": name, ...}.
        """
        try:
            line = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        except (TypeError, ValueError) as exc:
            self._log_error(f"[SocketChannel:{self._name}] json encode failed: {exc}")
            return {"status": "error", "reason": str(exc), "channel": self._name}

        with self._clients_lock:
            clients = list(self._clients)
        if not clients:
            return {"status": "error", "reason": "no clients connected", "channel": self._name}

        dead: List[socket.socket] = []
        sent = 0
        with self._write_lock:
            for c in clients:
                try:
                    c.sendall(line)
                    sent += 1
                except OSError as exc:
                    self._log_warning(f"[SocketChannel:{self._name}] send to client failed: {exc}")
                    dead.append(c)
        if dead:
            self._drop_clients(dead)
        if sent == 0:
            return {"status": "error", "reason": "all clients dead", "channel": self._name}
        self._tx += sent
        return {"status": "success", "channel": self._name, "clients": sent}

    # ---- IMessageChannel: получение ----

    def poll(self, timeout: float = 0.0) -> List[Dict[str, Any]]:
        """No-op: inbound доставляется push'ем через read-loop → on_inbound, не pull'ом.

        Router опрашивает только каналы процесса (input_channels_only); этот канал
        с именем без префикса процесса не попадает в receive-цикл, и это верно.
        """
        return []

    # ---- Внутреннее: accept + read ----

    def _accept_loop(self) -> None:
        """Принимать соединения; на каждое — отдельный read-поток."""
        while self._running and self._server_sock is not None:
            try:
                client, _addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break  # сокет закрыт в close()
            client.settimeout(0.5)
            with self._clients_lock:
                self._clients.append(client)
            threading.Thread(
                target=self._read_loop,
                args=(client,),
                name=f"socket-ch-read-{self._name}",
                daemon=True,
            ).start()

    def _read_loop(self, client: socket.socket) -> None:
        """Читать newline-JSON из соединения, парсить и передавать в on_inbound.

        Битая строка → лог+skip, не падаем. Закрытие соединения → выход.
        """
        buf = b""
        while self._running:
            try:
                chunk = client.recv(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break  # peer закрыл соединение
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                if not raw.strip():
                    continue
                self._handle_line(raw)
        self._drop_clients([client])

    def _handle_line(self, raw: bytes) -> None:
        """Распарсить одну строку wire и вызвать on_inbound (изоляция ошибок)."""
        try:
            msg = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            self._log_warning(f"[SocketChannel:{self._name}] bad line skipped: {exc}")
            return
        if not isinstance(msg, dict):
            self._log_warning(f"[SocketChannel:{self._name}] non-dict message skipped")
            return
        self._rx += 1
        if self._on_inbound is None:
            return
        try:
            self._on_inbound(msg)
        except Exception as exc:  # noqa: BLE001 — граница: ошибка обработки не должна ронять read-loop
            self._log_error(f"[SocketChannel:{self._name}] on_inbound error: {exc}")

    def _drop_clients(self, clients: List[socket.socket]) -> None:
        """Убрать мёртвые соединения из списка и закрыть их."""
        with self._clients_lock:
            for c in clients:
                if c in self._clients:
                    self._clients.remove(c)
        for c in clients:
            try:
                c.close()
            except OSError:
                pass

    # ---- Мониторинг ----

    def get_info(self) -> Dict[str, Any]:
        with self._clients_lock:
            clients = len(self._clients)
        return {
            "name": self._name,
            "type": self.channel_type,
            "active": self._running,
            "bound": self._bound,
            "host": self._host,
            "port": self._port,
            "clients": clients,
            "rx": self._rx,
            "tx": self._tx,
        }
