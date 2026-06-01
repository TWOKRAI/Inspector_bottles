# -*- coding: utf-8 -*-
"""
command_envelopes — построение dict-команд протокола (один источник правды).

Форма сообщений идентична `CommandSender.send_command` / `send_system_command`
(frontend_module), чтобы внешний driver (backend_ctl) и GUI слали байт-в-байт
одинаковые router-сообщения. Reply-поля (`request_id`/`reply_to`) — опциональны:
driver задаёт их для request-response (P0.5), GUI опускает (fire-and-forget).

Dict at Boundary: возвращается чистый dict, без зависимостей от Qt/процессов.
Порядок ключей сохранён как в исходном `CommandSender` (важно для байт-в-байт
сравнения и читабельности wire-формата).
"""

from __future__ import annotations

from typing import Any, Optional


def build_command_message(
    target: str,
    command: str,
    args: Optional[dict[str, Any]] = None,
    *,
    sender: str,
    request_id: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> dict[str, Any]:
    """Прямая команда процессу (форма ``CommandSender.send_command``).

    Args:
        target: имя процесса-получателя (попадает в ``targets=[target]``).
        command: имя команды (дублируется в ``command`` и ``data_type``).
        args: аргументы команды (``data``); None → пустой dict.
        sender: имя отправителя.
        request_id: корреляция request-response (P0.5); опц.
        reply_to: адрес для ответа; опц.

    Returns:
        dict router-сообщения. Reply-поля добавляются только если заданы.
    """
    msg: dict[str, Any] = {
        "type": "command",
        "command": command,
        "data_type": command,
        "sender": sender,
        "targets": [target],
        "data": args or {},
    }
    if request_id is not None:
        msg["request_id"] = request_id
    if reply_to is not None:
        msg["reply_to"] = reply_to
    return msg


def build_system_command_message(
    command: dict[str, Any],
    *,
    sender: str,
    request_id: Optional[str] = None,
    reply_to: Optional[str] = None,
) -> dict[str, Any]:
    """System-команда в ProcessManager (форма ``CommandSender.send_system_command``).

    Оборачивает прикладную команду в ``process.command``-конверт для PM
    (горячее добавление/удаление процессов, управление wire'ами и т.п.).

    Args:
        command: вложенная прикладная команда (попадает в ``data``).
        sender: имя отправителя.
        request_id: корреляция request-response (P0.5); опц.
        reply_to: адрес для ответа; опц.

    Returns:
        dict router-сообщения с ``targets=["ProcessManager"]``.
    """
    msg: dict[str, Any] = {
        "type": "command",
        "command": "process.command",
        "data_type": "process.command",
        "sender": sender,
        "targets": ["ProcessManager"],
        "data": command,
    }
    if request_id is not None:
        msg["request_id"] = request_id
    if reply_to is not None:
        msg["reply_to"] = reply_to
    return msg
