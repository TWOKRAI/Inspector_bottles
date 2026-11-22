# -*- coding: utf-8 -*-
"""
backend_ctl_endpoint — поднятие SocketChannel в ProcessManager (dev-гейт).

Тонкий хелпер: при BACKEND_CTL=1 создаёт SocketChannel (bind 127.0.0.1:порт),
регистрирует его в RouterManager хоста и подключает SocketBridgeAdapter как
обработчик входящих сообщений driver'а. Вся доставка — через RouterManager.

Гейт + localhost-bind + токен (Task 0.12b, ADR-PMM-052): поставка
выключена (`system.yaml` → `backend_ctl.enabled: false`), dev-старт — `BACKEND_CTL=1`.
Порт без токена закрыт: первая строка соединения — `hello` с токеном из файла
`~/.multiprocess_framework/ctl_<порт>.token` (0600, пишется ПОСЛЕ `start()` по
фактическому порту; при остановке удаляется, только если в нём токен этого канала).

Выделено из process_manager_process.py, чтобы PM оставался тонким и endpoint
тестировался изолированно.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from multiprocess_framework.modules.logger_module import get_std_logger

from ...router_module.adapters import SocketBridgeAdapter
from ...router_module.channels import SocketChannel, socket_auth

_log = get_std_logger(__name__)

#: Атрибуты канала: путь файла токена и сам токен (для сверки при удалении).
_ATTR_TOKEN_PATH = "_backend_ctl_token_path"
_ATTR_TOKEN = "_backend_ctl_token"

#: Имя канала = адрес для channel=-маршрутизации ответа driver'у.
BACKEND_CTL_CHANNEL = "backend_ctl"
#: env-флаг включения (строго "1").
ENV_ENABLE = "BACKEND_CTL"
#: env-переопределение порта.
ENV_PORT = "BACKEND_CTL_PORT"
#: env-флаг session-isolation (D.1); строго "1".
ENV_SESSION_ISOLATION = "BACKEND_CTL_SESSION_ISOLATION"
DEFAULT_PORT = 8765


def is_enabled(env: Optional[dict] = None, config: Optional[dict] = None) -> bool:
    """True, если backend-control включён.

    Источников два (OR): конфиг (`system.yaml` → `backend_ctl.enabled`) ИЛИ
    env-флаг `BACKEND_CTL=1`. Поставка выключена (`enabled: false`, Task 0.12b):
    dev-старт, стенды и харнесс включают порт env-флагом без правки yaml.
    """
    source = env if env is not None else os.environ
    if source.get(ENV_ENABLE) == "1":
        return True
    return bool(config and config.get("enabled"))


def _resolve_port(source: dict, config: Optional[dict], port: Optional[int]) -> int:
    """Порт: явный аргумент > env BACKEND_CTL_PORT > config.port > DEFAULT_PORT."""
    if port is not None:
        return port
    if ENV_PORT in source:
        return int(source[ENV_PORT])
    if config and config.get("port"):
        return int(config["port"])
    return DEFAULT_PORT


def _resolve_session_isolation(source: dict, config: Optional[dict]) -> bool:
    """Флаг session-isolation (D.1). **Дефолт ON с задачи 5.5 (находка Н-A приёмки F2).**

    Прежний дефолт был OFF (broadcast) с формулировкой «остаётся дефолтом до
    доказательства (§9)». Доказательство пришло живьём: событие, адресованное
    ОДНОМУ клиенту, доезжало до всех подключённых — два клиента дали в плоскости
    `logs` по 17 событий с чужим `_address`, а в `state` 419/417/417 по трём
    адресам, третий из которых мёртв. Следствие хуже самой протечки: арифметика
    любого потребителя умножалась на число клиентов, а `dropped` считался по
    чужому трафику — то есть числа приёмки measured не свою плоскость.

    Приоритет — **явное над дефолтом**, а не OR: env со значением (``"1"``/``"0"``)
    решает; иначе решает ключ конфига, если он ЕСТЬ (``in``, а не truthiness —
    иначе `session_isolation: false` было бы неотличимо от молчания); иначе ON.
    Прежний OR не умел выключать: ``"0"`` давал False лишь потому, что проваливался
    в пустой конфиг, и с дефолтом ON эта случайность стала бы дырой.
    """
    raw = source.get(ENV_SESSION_ISOLATION)
    if raw is not None and str(raw).strip() != "":
        return str(raw).strip() == "1"
    if config is not None and "session_isolation" in config:
        return bool(config["session_isolation"])
    return True


def setup_backend_ctl_channel(
    router_manager: Any,
    *,
    host: Optional[str] = None,
    port: Optional[int] = None,
    env: Optional[dict] = None,
    config: Optional[dict] = None,
    log_info: Optional[Any] = None,
    log_error: Optional[Any] = None,
    on_session_closed: Optional[Any] = None,
    on_request: Optional[Any] = None,
) -> Optional[SocketChannel]:
    """Поднять SocketChannel и зарегистрировать в router (если гейт открыт).

    Args:
        router_manager: RouterManager хоста (register_channel + request/send).
        host: bind-адрес; None → config.host или 127.0.0.1.
        port: порт; None → env BACKEND_CTL_PORT > config.port > DEFAULT_PORT.
        env: источник переменных окружения (для тестов); None → os.environ.
        on_session_closed: колбэк(session_id) при разрыве соединения — держателю
            подписок нужен сигнал о смерти внешнего подписчика по факту (5.11-R1).
        on_request: наблюдатель ``(msg, sid, result)`` запроса driver'а — уходит в
            ``SocketBridgeAdapter`` (4.4: оркестратор запоминает точечные подписки,
            чтобы доиграть их свежей инкарнации).
        config: секция `backend_ctl` из system.yaml (`enabled`/`port`/`host`).
        log_info/log_error: опц. колбэки логирования.

    Returns:
        Запущенный SocketChannel или None (гейт закрыт / router отсутствует /
        bind не удался / файл токена не записан — открытого сервера не бывает).
    """
    if not is_enabled(env, config):
        return None
    if router_manager is None:
        if log_error:
            log_error("[backend_ctl] router_manager отсутствует — endpoint не поднят")
        return None

    source = env if env is not None else os.environ
    resolved_port = _resolve_port(source, config, port)
    resolved_host = host if host is not None else ((config or {}).get("host") or "127.0.0.1")
    session_isolation = _resolve_session_isolation(source, config)

    adapter = SocketBridgeAdapter(
        router_manager,
        BACKEND_CTL_CHANNEL,
        session_isolation=session_isolation,
        on_request=on_request,
    )
    # Токен держит замыкание: accept-цикл работает уже между start() и записью файла;
    # пока holder пуст, authenticator возвращает False (закрыто по умолчанию).
    holder: dict[str, str] = {}
    channel = SocketChannel(
        BACKEND_CTL_CHANNEL,
        host=resolved_host,
        port=resolved_port,
        on_inbound=adapter.on_inbound,
        session_isolation=session_isolation,
        on_session_closed=on_session_closed,
        authenticator=socket_auth.token_authenticator(lambda: holder.get("token")),
    )
    router_manager.register_channel(channel)
    if not channel.start():
        # Файл токена не тронут: при занятом порту он принадлежит другому ПМ.
        if log_error:
            log_error(f"[backend_ctl] не удалось поднять SocketChannel на {resolved_host}:{resolved_port}")
        _unregister(router_manager)
        return None

    # Имя файла — по ФАКТИЧЕСКОМУ порту (port: 0 → порт выбрала ОС). Залипший файл
    # прошлого ПМ (SIGKILL) перезаписывается атомарно.
    try:
        token_path = socket_auth.resolve_token_path(channel.port, source)
        token = socket_auth.write_token(token_path)
    except Exception as exc:  # noqa: BLE001 — любой сбой записи: открытого сервера не оставляем
        channel.close()
        _unregister(router_manager)
        if log_error:
            log_error(
                f"[backend_ctl] файл токена для порта {channel.port} не записан "
                f"({type(exc).__name__}: {exc}) — endpoint не поднят"
            )
        return None
    holder["token"] = token  # сразу: окно «файл есть, holder пуст» — одна инструкция
    setattr(channel, _ATTR_TOKEN_PATH, token_path)
    setattr(channel, _ATTR_TOKEN, token)

    if log_info:
        log_info(
            f"[backend_ctl] endpoint поднят на {resolved_host}:{channel.port} "
            f"(канал '{BACKEND_CTL_CHANNEL}', session_isolation={'on' if session_isolation else 'off'}, "
            f"файл токена {token_path}) — DEV-инструмент"
        )
    return channel


def teardown_backend_ctl_channel(
    channel: Optional[SocketChannel],
    router_manager: Any = None,
) -> None:
    """Остановить канал и снять регистрацию (PID-specific, без глобального kill).

    Файл токена удаляется ДО ``channel.close()`` и только если в нём токен этого
    канала: файл, перезаписанный другим ПМ (общий ``BACKEND_CTL_TOKEN_FILE``), остаётся.
    Сбой удаления не мешает закрыть порт.
    """
    if channel is None:
        return
    try:
        _remove_own_token(channel)
        channel.close()
    finally:
        if router_manager is not None:
            _unregister(router_manager)


def _unregister(router_manager: Any) -> None:
    try:
        router_manager.unregister_channel(BACKEND_CTL_CHANNEL)
    except Exception:  # noqa: BLE001 — best-effort откат
        pass


def _remove_own_token(channel: SocketChannel) -> None:
    """Удалить файл токена канала, если в нём всё ещё токен этого канала."""
    path: Optional[Path] = getattr(channel, _ATTR_TOKEN_PATH, None)
    token: Optional[str] = getattr(channel, _ATTR_TOKEN, None)
    if path is None or token is None:
        return
    try:
        if socket_auth.read_token(path) == token:
            path.unlink()
    except FileNotFoundError:
        pass
    except Exception as exc:  # noqa: BLE001 — сбой удаления не мешает close() порта
        _log.warning("[backend_ctl] файл токена %s не удалён: %s: %s", path, type(exc).__name__, exc)
