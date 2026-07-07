"""DeviceHubClient — IPC-клиент для вызова команд процесса devices.

Контракт потока: вызывать ТОЛЬКО из worker-потока, НЕ из приёмного цикла
и НЕ из process() горячего пути. Причина: router_manager.request() блокирует
поток до получения ответа (дедлок в приёмном цикле).

Паттерн: build_command_message + router_manager.request (Р9).
Нормализация ответа: PM-формат {"success": ..., "data": {"result": ...}}
→ {"status": "ok"|"error", ...}.
"""

from __future__ import annotations

from typing import Any


def _normalize_response(raw: dict) -> dict:
    """Привести ответ PM/router к формату {"status": "ok"|"error", ...}.

    router_manager.request возвращает:
        {"success": True,  "data": {"result": <plugin_result>}} — успех
        {"success": False, "error": "timeout"}                  — таймаут
        {"success": False, "error": "..."}                      — ошибка
    Плагин возвращает {"status": "ok", ...} или {"status": "error", ...}.
    """
    if not isinstance(raw, dict):
        return {"status": "error", "message": "некорректный ответ"}

    # Прямой ответ плагина (уже нормализован)
    if "status" in raw:
        return raw

    success = raw.get("success", False)
    if not success:
        error = raw.get("error", "неизвестная ошибка")
        return {"status": "error", "message": str(error)}

    # Вытащить result из PM-обёртки
    data = raw.get("data", {})
    if isinstance(data, dict):
        result = data.get("result", data)
        if isinstance(result, dict) and "status" in result:
            return result
        return {"status": "ok", **result} if isinstance(result, dict) else {"status": "ok", "result": result}
    return {"status": "ok", "data": data}


class DeviceHubClient:
    """IPC-клиент для вызова команд процесса devices.

    Использование (только из worker-потока!)::

        client = DeviceHubClient(ctx)
        result = client.request("robot_send_test_job", {"device_id": "robot_main", "x": 10, "y": 20})
        if result["status"] == "ok":
            ...

    Args:
        ctx:            PluginContext с router_manager.
        target_process: Имя целевого процесса (default: "devices").
        default_timeout: Таймаут по умолчанию (секунды).
    """

    def __init__(
        self,
        ctx: Any,
        target_process: str = "devices",
        default_timeout: float = 2.0,
    ) -> None:
        self._ctx = ctx
        self._target = target_process
        self._timeout = default_timeout

    def request(
        self,
        command: str,
        args: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Отправить команду в devices и дождаться ответа.

        Контракт потока: ТОЛЬКО из worker-потока. Не из приёмного цикла.
        Деградация: нет router_manager → {"status": "error", "message": "..."}.

        Args:
            command: Имя команды (напр. "robot_send_test_job").
            args:    Аргументы команды.
            timeout: Таймаут ожидания ответа (None → default_timeout).

        Returns:
            {"status": "ok"|"error", ...}
        """
        router = getattr(self._ctx, "router_manager", None)
        if router is None:
            return {"status": "error", "message": "router недоступен"}

        from multiprocess_framework.modules.message_module.builders.command_envelopes import (
            build_command_message,
        )

        sender = getattr(self._ctx, "process_name", "unknown")
        msg = build_command_message(
            target=self._target,
            command=command,
            args=args or {},
            sender=sender,
        )

        t = timeout if timeout is not None else self._timeout
        try:
            raw = router.request(msg, timeout=t)
        except Exception as exc:
            # IPC-отказ — операционная ошибка процесса-вызывателя: кормим его health,
            # даже если вызыватель обработает только dict-ответ (getattr — ctx может быть Sub/mock).
            health = getattr(self._ctx, "health", None)
            if health is not None:
                health.report_error(exc, context="device_hub_client.request", throttle=30.0)
            return {"status": "error", "message": f"IPC ошибка: {exc}"}

        return _normalize_response(raw)

    def send_fire_and_forget(
        self,
        command: str,
        args: dict[str, Any] | None = None,
    ) -> bool:
        """Отправить команду в devices БЕЗ ожидания ответа (fire-and-forget).

        Б-3 ревью Fable: безопасно вызывать из приёмного потока
        (message_processor), т.к. НЕ блокирует — использует
        router_manager.send_async (non-blocking enqueue в AsyncSender).

        Returns:
            True если сообщение поставлено в очередь, False при ошибке.
        """
        router = getattr(self._ctx, "router_manager", None)
        if router is None:
            return False

        send_async = getattr(router, "send_async", None)
        if send_async is None:
            return False

        from multiprocess_framework.modules.message_module.builders.command_envelopes import (
            build_command_message,
        )

        sender = getattr(self._ctx, "process_name", "unknown")
        msg = build_command_message(
            target=self._target,
            command=command,
            args=args or {},
            sender=sender,
        )

        try:
            send_async(msg)
            return True
        except Exception as exc:
            # fire-and-forget: сообщение потеряно — учитываем в health вызывателя
            health = getattr(self._ctx, "health", None)
            if health is not None:
                health.report_error(exc, context="device_hub_client.send_async", throttle=30.0)
            return False
