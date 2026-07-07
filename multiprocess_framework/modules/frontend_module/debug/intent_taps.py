# -*- coding: utf-8 -*-
"""Тапы уровня «намерение» (debug-plane v1): что GUI отправил в бэкенд.

Жест (клик, UiEventTap) говорит «пользователь ткнул сюда»; намерение говорит
«GUI отправил команду X процессу Y». Единственная дверь GUI→бэкенд —
``CommandSender.send_command``/``send_system_command`` (field/action/flush-пути
сходятся в send_command) — поэтому ОДИН перехват двери ловит намерение полностью:
любой виджет, клавиатура, программный вызов.

События уходят через ``UiEventTap.emit_event`` — общий seq/ts/счётчики/доставка
с жестами: агент упорядочивает «клик(seq=41) → команда(seq=42)» без гонок ts.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

# Обрезка значений аргументов команды: в отладочный поток не едут большие blobs.
_MAX_ARG_LEN = 200


def _safe_args(args: Any) -> Any:
    """Плоская безопасная копия аргументов команды для отладочного события.

    Скаляры — как есть; строки/repr длиннее лимита — обрезаются; вложенные
    структуры — repr с обрезкой. Dict at Boundary: наружу только простые типы.
    """
    if args is None:
        return None
    if not isinstance(args, dict):
        text = repr(args)
        return text if len(text) <= _MAX_ARG_LEN else text[:_MAX_ARG_LEN] + "…"
    safe: Dict[str, Any] = {}
    for k, v in args.items():
        if isinstance(v, (int, float, bool)) or v is None:
            safe[str(k)] = v
        else:
            text = v if isinstance(v, str) else repr(v)
            safe[str(k)] = text if len(text) <= _MAX_ARG_LEN else text[:_MAX_ARG_LEN] + "…"
    return safe


class CommandSenderTap:
    """Обратимый перехват двери GUI→бэкенд (инстанс CommandSender).

    ``install()`` оборачивает ``send_command`` и ``send_system_command`` на
    ИНСТАНСЕ (класс не трогается), ``remove()`` восстанавливает оригиналы.
    Идемпотентно. Ошибки эмиссии глотаются — команда уходит в бэкенд в любом
    случае, отладка не имеет права ломать прод-путь.
    """

    def __init__(self, sender: Any, emit: Callable[[Dict[str, Any]], Any]) -> None:
        """
        Args:
            sender: живой CommandSender GUI.
            emit: колбэк события (обычно ``UiEventTap.emit_event``).
        """
        self._sender = sender
        self._emit = emit
        self._originals: Optional[Dict[str, Callable[..., Any]]] = None

    @property
    def installed(self) -> bool:
        return self._originals is not None

    def install(self) -> None:
        """Обернуть дверь (идемпотентно)."""
        if self._originals is not None:
            return
        sender, emit = self._sender, self._emit
        orig_cmd = sender.send_command
        orig_sys = sender.send_system_command

        def tapped_send_command(target_process: str, command: str, args: Any = None, *a: Any, **kw: Any) -> Any:
            try:
                emit(
                    {
                        "kind": "command",
                        "target": target_process,
                        "command": command,
                        "args": _safe_args(args),
                    }
                )
            except Exception:  # noqa: BLE001 — отладка не ломает прод-путь
                pass
            return orig_cmd(target_process, command, args, *a, **kw)

        def tapped_send_system_command(command: Any, *a: Any, **kw: Any) -> Any:
            try:
                emit({"kind": "system_command", "command": _safe_args(command)})
            except Exception:  # noqa: BLE001
                pass
            return orig_sys(command, *a, **kw)

        self._originals = {"send_command": orig_cmd, "send_system_command": orig_sys}
        sender.send_command = tapped_send_command
        sender.send_system_command = tapped_send_system_command

    def remove(self) -> None:
        """Восстановить оригинальные методы (идемпотентно)."""
        if self._originals is None:
            return
        self._sender.send_command = self._originals["send_command"]
        self._sender.send_system_command = self._originals["send_system_command"]
        self._originals = None
