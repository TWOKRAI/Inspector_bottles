# -*- coding: utf-8 -*-
"""Команды ``ui.tap.*`` — управление UiEventTap'ом gui-процесса через driver/MCP.

Зеркалят механику ``log.tail.subscribe`` (Ф1.5, BuiltinCommands): подписчик
(обычно внешний ``backend_ctl``) получает пуши ``ui.event`` через
RouterPushChannel — targets=[subscriber] + queue_type=system → мост 1.1b,
для дочернего gui-процесса — relay 1.7 через хаб.

Регистрируются НЕ в BuiltinCommands (те — generic для всех процессов), а
явным вызовом из процесса с Qt (GuiProcess прототипа / любого приложения
конструктора): ``register_ui_tap_commands(services, get_tap)``.

``ui.tap.ping`` — синтетическое событие через ТОТ ЖЕ путь доставки: агент
может проверить всю цепочку (команда → tap → push → relay → driver.events)
без физического клика по кнопке.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from .ui_event_tap import UiEventTap

# Getter тапа: GUI может быть ещё не поднят (tap=None) — команды отвечают честно.
TapGetter = Callable[[], Optional[UiEventTap]]


def register_ui_tap_commands(services: Any, get_tap: TapGetter) -> bool:
    """Зарегистрировать ui.tap.subscribe/unsubscribe/ping в CommandManager процесса.

    Args:
        services: сервисы процесса (command_manager, router_manager, name).
        get_tap: getter установленного UiEventTap (None → GUI ещё не поднят).

    Returns:
        True, если команды зарегистрированы (есть CommandManager).
    """
    cm = getattr(services, "command_manager", None)
    if cm is None:
        return False

    handlers = _UiTapCommands(services, get_tap)
    specs = [
        (
            "ui.tap.subscribe",
            handlers.cmd_subscribe,
            "Подписать адрес на UI-события gui (кнопки/табы) — router-push ui.event",
        ),
        (
            "ui.tap.unsubscribe",
            handlers.cmd_unsubscribe,
            "Снять подписку на UI-события gui",
        ),
        (
            "ui.tap.ping",
            handlers.cmd_ping,
            "Синтетическое ui.event по пути доставки тапа (проверка цепочки без клика)",
        ),
    ]
    for name, handler, desc in specs:
        cm.register_command(name, handler, metadata={"description": desc}, tags=["system"])
    return True


class _UiTapCommands:
    """Обработчики ui.tap.* (инстанс держит services + getter тапа)."""

    def __init__(self, services: Any, get_tap: TapGetter) -> None:
        self._services = services
        self._get_tap = get_tap

    @staticmethod
    def _merge_args(data: Any, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Аргументы команды: data-словарь (generic command-путь) + kwargs."""
        args = dict(data) if isinstance(data, dict) else {}
        args.update(kwargs or {})
        return args

    def _tap_or_error(self) -> tuple[Optional[UiEventTap], Optional[dict]]:
        tap = self._get_tap()
        if tap is None:
            return None, {"success": False, "reason": "UI ещё не поднят (UiEventTap не установлен)"}
        return tap, None

    def cmd_subscribe(self, data=None, **kwargs) -> dict:
        """Включить тап: ui.event едут router-пушем на subscriber (идемпотентно).

        Параметры (data): ``subscriber`` (адрес получателя, обяз.),
        ``command`` (поле command пуша, по умолчанию "ui.event").
        """
        args = self._merge_args(data, kwargs)
        svc = self._services
        tap, err = self._tap_or_error()
        if err:
            return err

        subscriber = str(args.get("subscriber") or "").strip()
        if not subscriber:
            return {"success": False, "reason": "subscriber (адрес получателя) обязателен"}
        command = str(args.get("command") or "ui.event")

        router = getattr(svc, "router_manager", None)
        if router is None:
            return {"success": False, "reason": "router_manager недоступен"}

        # Тот же канал доставки, что у log-tail (Ф1.5): пуш targets+queue_type,
        # data = {"process": <gui>, "record": <ui-событие>}.
        from multiprocess_framework.modules.logger_module import RouterPushChannel

        channel = RouterPushChannel(
            f"ui_tap::{subscriber}",
            router=router,
            subscriber=subscriber,
            sender=svc.name,
            command=command,
        )
        tap.enable(subscriber, channel.write)
        return {
            "success": True,
            "process": svc.name,
            "subscriber": subscriber,
            "command": command,
            "events_sent": tap.events_sent,
        }

    def cmd_unsubscribe(self, data=None, **kwargs) -> dict:
        """Выключить тап (фильтр остаётся установленным — no-op до новой подписки)."""
        tap, err = self._tap_or_error()
        if err:
            return err
        was = tap.subscriber
        tap.disable()
        return {"success": True, "process": self._services.name, "was_subscriber": was}

    def cmd_ping(self, data=None, **kwargs) -> dict:
        """Синтетическое ui.event тем же путём доставки — smoke цепочки без клика."""
        args = self._merge_args(data, kwargs)
        tap, err = self._tap_or_error()
        if err:
            return err
        if not tap.enabled:
            return {"success": False, "reason": "тап не включён (сначала ui.tap.subscribe)"}
        note = str(args.get("note") or "ping")
        sent = tap.emit_event({"kind": "ping", "note": note})
        return {
            "success": bool(sent),
            "process": self._services.name,
            "subscriber": tap.subscriber,
            "events_sent": tap.events_sent,
            "send_errors": tap.send_errors,
        }
