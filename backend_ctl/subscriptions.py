# -*- coding: utf-8 -*-
"""subscriptions.py — реестр durable-намерений подписки.

Хранит, на ЧТО driver подписался, чтобы реконнект MCP-сервера мог повторить подписки,
а не потерять их молча. Чистая структура данных БЕЗ транспорта: driver наполняет её
через subscribe-обёртки и экспортирует/загружает при реконнекте (replay).

Выделено из ``driver.py`` (Phase C, C.1). Пути пост-codemod —
``tooling/backend_ctl/subscriptions.py``. Публичное переименование
(``_SubscriptionRegistry`` → ``SubscriptionRegistry``) отложено на codemod — здесь
перенос бит-в-бит.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class _SubscriptionRegistry:
    """Реестр durable-намерений подписки (Task 0.3, ежедневная боль №1).

    Хранит, на ЧТО driver подписался (``state.subscribe`` / ``log.tail.subscribe`` /
    ``ui.tap.subscribe``), чтобы при реконнекте MCP-сервера подписки можно было
    повторить, а не потерять молча (события просто переставали приходить — агент
    думал «всё тихо»). Живёт в driver'е.

    Идентичность намерения — ``(command, target, identity)``, где identity = pattern
    (для state) либо subscriber (для log/ui): повторная подписка того же ключа
    перезаписывает, не плодит дубли.
    """

    def __init__(self) -> None:
        self._intents: Dict[tuple, Dict[str, Any]] = {}

    @staticmethod
    def _key(command: str, target: str, args: Dict[str, Any]) -> tuple:
        identity = args.get("pattern") or args.get("subscriber") or ""
        return (command, target, identity)

    def add(self, command: str, target: str, args: Dict[str, Any]) -> None:
        """Запомнить намерение подписки (idempotent по ключу)."""
        self._intents[self._key(command, target, args)] = {
            "command": command,
            "target": target,
            "args": dict(args),
        }

    def remove(self, command: str, target: str, args: Optional[Dict[str, Any]] = None) -> None:
        """Снять намерение. ``args=None`` → снять все с данными command+target
        (напр. ``ui.tap.unsubscribe`` без subscriber снимает tap процесса целиком)."""
        if args is not None:
            self._intents.pop(self._key(command, target, args), None)
            return
        for k in [k for k in self._intents if k[0] == command and k[1] == target]:
            del self._intents[k]

    def remove_by_command(self, command: str) -> None:
        """Снять ВСЕ намерения данной команды по всем target'ам (F2: подчистка watch).

        Используется unwatch'ем как safety-net: полу-durable watch (контур потерян при
        реконнекте) не должен воскресить obs-tail-намерения на любом процессе.
        """
        for k in [k for k in self._intents if k[0] == command]:
            del self._intents[k]

    def export(self) -> List[Dict[str, Any]]:
        """Снимок намерений (для передачи новому driver'у при реконнекте)."""
        return [
            {"command": v["command"], "target": v["target"], "args": dict(v["args"])} for v in self._intents.values()
        ]

    def load(self, intents: List[Dict[str, Any]]) -> None:
        """Загрузить намерения (в новый driver после реконнекта)."""
        for it in intents or []:
            self.add(it["command"], it["target"], it.get("args") or {})


__all__ = ["_SubscriptionRegistry"]
