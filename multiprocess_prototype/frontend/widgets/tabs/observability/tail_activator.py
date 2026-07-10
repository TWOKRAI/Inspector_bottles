# -*- coding: utf-8 -*-
"""
ObservabilityTailActivator — активация/переподписка live-хвоста наблюдаемости (Ф5.20b).

Форвардер на каждом backend-процессе «мёртв» без подписчика (как log_tail): GUI
сам инициирует ``observability.tail.subscribe`` по мере обнаружения процессов в
``processes.*`` state-дельтах. Дедуп по имени — одна подписка на процесс.

**Закрытие долга (2026-07-10):** авто-рестарт (Ф3.7) поднимает НОВУЮ инкарнацию
процесса с тем же именем — её форвардер не подписан, а дедуп по имени переподписку
блокировал → после рестарта хвост процесса молча пропадал. Триггер переподписки —
громкое supervisor-событие ``processes.<name>.supervisor.event = "recovered"``
(публикуется по ВОЗВРАТУ heartbeat после рестарта, ADR-PMM-015): на него снимаем
дедуп и подписываем новую инкарнацию заново. Команда subscribe идемпотентна.

Qt-free: принимает callable ``send_command(target, command, args)`` — тестируется
без живого backend.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

SUBSCRIBE_COMMAND = "observability.tail.subscribe"


class ObservabilityTailActivator:
    """Подписывает backend-процессы на live-хвост и переподписывает после рестарта."""

    def __init__(self, send_command: Callable[[str, str, Dict[str, Any]], Any], gui_name: str) -> None:
        """
        Args:
            send_command: отправка команды процессу (обычно CommandSender.send_command).
            gui_name: имя GUI-процесса — и адрес-подписчик (targets), и «себя не подписывать».
        """
        self._send = send_command
        self._gui_name = gui_name
        self._subscribed: set[str] = set()

    def on_state_delta(self, msg_dict: Dict[str, Any]) -> None:
        """Слушатель state-дельт (add_state_listener): подписать/переподписать процесс."""
        if not isinstance(msg_dict, dict) or msg_dict.get("data_type") != "state_delta":
            return
        path = msg_dict.get("path", "")
        if not path.startswith("processes."):
            return
        parts = path.split(".")
        proc = parts[1] if len(parts) >= 2 else ""
        # Себя не подписываем (у GUI нет пилот-hub'а).
        if not proc or proc == self._gui_name:
            return
        # Рестарт: recovered → новая инкарнация, старая подписка потеряна → снять дедуп.
        if path.endswith(".supervisor.event") and msg_dict.get("value") == "recovered":
            self._subscribed.discard(proc)
        if proc in self._subscribed:
            return
        self._subscribed.add(proc)
        try:
            self._send(proc, SUBSCRIBE_COMMAND, {"subscriber": self._gui_name})
        except Exception:  # noqa: BLE001 — активация хвоста best-effort, не рушим GUI
            pass
