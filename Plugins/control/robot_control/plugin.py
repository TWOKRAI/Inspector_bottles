"""RobotControlPlugin — управление отбраковкой по результатам детекции.

Processing-плагин: принимает item с detections (от blob_detector),
фильтрует дефекты по min_defect_area, принимает решение reject/pass.
Ведёт статистику: total_inspected, total_rejected, reject_rate.

V3_MY_PURE: plugin самодостаточен — создаёт локальный register
если RegistersManager недоступен. Все параметры ВСЕГДА через self._reg.
"""

from __future__ import annotations

import time
from typing import Any

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
    for_each,
)
from multiprocess_framework.modules.process_module.plugins import Port
from multiprocess_framework.modules.process_module.plugins import register_plugin

from .registers import RobotControlRegisters


@register_plugin(
    "robot_control",
    category="processing",
    description="Управление отбраковкой по результатам детекции",
)
class RobotControlPlugin(ProcessModulePlugin):
    """Плагин принятия решений об отбраковке.

    Получает список detections от blob_detector, фильтрует дефекты
    по минимальной площади и выдаёт inspection_result с решением reject/pass.
    """

    name = "robot_control"
    category = "processing"

    inputs = [
        Port(
            name="frame",
            dtype="image/bgr",
            shape="(H, W, 3)",
            description="Кадр",
        ),
        Port(
            name="detections",
            dtype="list[dict]",
            shape="N",
            description="Детекции от blob_detector",
        ),
    ]
    outputs = [
        Port(
            name="frame",
            dtype="image/bgr",
            shape="(H, W, 3)",
            description="Кадр (без изменений)",
        ),
        Port(
            name="inspection_result",
            dtype="dict",
            shape="1",
            description="Результат инспекции",
        ),
    ]

    commands = {
        "enable": "cmd_enable",
        "disable": "cmd_disable",
        "set_delay": "cmd_set_delay",
        "reset_counters": "cmd_reset_counters",
        "get_stats": "cmd_get_stats",
    }
    register_class = RobotControlRegisters

    def configure(self, ctx: PluginContext) -> None:
        """Настройка: register managed (GUI) или локальный (defaults)."""
        self._ctx = ctx
        self._reg = self._init_register(ctx)

        # Счётчики статистики (не в register — runtime-only)
        self._total_inspected: int = 0
        self._total_rejected: int = 0

        ctx.log_info(
            f"RobotControlPlugin: enabled={self._reg.enabled}, "
            f"min_defect_area={self._reg.min_defect_area}, "
            f"reject_delay_ms={self._reg.reject_delay_ms}"
        )

    # --- Обработка ---

    @for_each
    def process(self, item: dict) -> dict | None:
        """Принять решение reject/pass по списку detections.

        Алгоритм:
        1. Инкремент total_inspected
        2. Если disabled → pass (reason=disabled)
        3. Фильтрация detections по min_defect_area
        4. Ограничение по max_detections_for_reject (если > 0)
        5. Если есть дефекты → reject + задержка
        6. Запись inspection_result в item
        """
        self._total_inspected += 1

        # Плагин отключён — всегда пропускаем
        if not self._reg.enabled:
            item["inspection_result"] = {
                "action": "pass",
                "reason": "disabled",
            }
            return item

        # Получаем список детекций
        detections: list[dict] = item.get("detections", [])

        # Фильтруем дефекты по минимальной площади
        defects = [
            d for d in detections
            if d.get("area", 0) >= self._reg.min_defect_area
        ]

        # Ограничиваем количество дефектов для анализа (если задано)
        if self._reg.max_detections_for_reject > 0:
            defects = defects[:self._reg.max_detections_for_reject]

        # Принимаем решение
        if len(defects) > 0:
            action = "reject"
            self._total_rejected += 1
            # Задержка перед отбраковкой (например, для синхронизации с механизмом)
            if self._reg.reject_delay_ms > 0:
                time.sleep(self._reg.reject_delay_ms / 1000.0)
        else:
            action = "pass"

        # Вычисляем коэффициент отбраковки
        rate = (
            self._total_rejected / self._total_inspected
            if self._total_inspected > 0
            else 0.0
        )

        item["inspection_result"] = {
            "action": action,
            "defect_count": len(defects),
            "total_inspected": self._total_inspected,
            "total_rejected": self._total_rejected,
            "reject_rate": round(rate, 4),
        }

        return item

    # --- Команды ---

    def cmd_enable(self, data: dict) -> dict:
        """Включить отбраковку."""
        self._reg.enabled = True
        self._ctx.log_info("RobotControlPlugin: отбраковка включена")
        return {"status": "ok", "enabled": True}

    def cmd_disable(self, data: dict) -> dict:
        """Выключить отбраковку."""
        self._reg.enabled = False
        self._ctx.log_info("RobotControlPlugin: отбраковка выключена")
        return {"status": "ok", "enabled": False}

    def cmd_set_delay(self, data: dict) -> dict:
        """Установить задержку отбраковки в миллисекундах."""
        delay_ms = max(0, int(data.get("delay_ms", 0)))
        self._reg.reject_delay_ms = delay_ms
        self._ctx.log_info(f"RobotControlPlugin: задержка установлена {delay_ms} мс")
        return {"status": "ok", "delay_ms": delay_ms}

    def cmd_reset_counters(self, data: dict) -> dict:
        """Обнулить счётчики статистики."""
        self._total_inspected = 0
        self._total_rejected = 0
        self._ctx.log_info("RobotControlPlugin: счётчики сброшены")
        return {"status": "ok"}

    def cmd_get_stats(self, data: dict) -> dict:
        """Вернуть текущую статистику инспекции."""
        rate = (
            self._total_rejected / self._total_inspected
            if self._total_inspected > 0
            else 0.0
        )
        return {
            "status": "ok",
            "total_inspected": self._total_inspected,
            "total_rejected": self._total_rejected,
            "reject_rate": round(rate, 4),
        }
