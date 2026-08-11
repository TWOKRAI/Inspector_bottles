# -*- coding: utf-8 -*-
"""LogStormPlugin — генератор ДОСЛОВНОГО повтора записей по команде (зонд 4.4).

Зачем отдельный плагин, а не «включить DEBUG на живом тракте». Приёмка 4.4
требует чисел «сколько прошло, сколько подавлено», а не «стало меньше». На
естественном шторме роутера число эмитированных записей неизвестно: его задаёт
темп кадров, состав сообщений и попадание в окно замера. Здесь эмитент говорит
точное число сам (``emitted`` в ответе), поэтому подавление считается
арифметикой, а не оценивается на глаз: ``подавлено = emitted − прошло``.

Текст записи — ДОСЛОВНО один и тот же на все повторы: ключ дросселя есть
«уровень + текст», и переменная внутри текста (``… idx=17``) давала бы новый
ключ каждый раз — названный предел механизма, а не его проверка.

Живёт в ``backend_ctl/probes/`` намеренно: это диагностический инструмент стенда,
а не словарь прикладных плагинов (``Plugins/``). Рецепт зовёт его полным путём
``backend_ctl.probes.log_storm_plugin.LogStormPlugin`` — авто-скан каталогов
плагинов его не видит и видеть не должен.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
    register_plugin,
)


@register_plugin("log_storm", category="utility", description="Шторм дословных повторов по команде (зонд 4.4)")
class LogStormPlugin(ProcessModulePlugin):
    """Эмитит ровно ``count`` одинаковых записей заданного уровня по команде."""

    name = "log_storm"
    category = "utility"

    inputs = []
    outputs = []
    commands = {"log_storm.burst": "_cmd_burst"}

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        ctx.log_info("LogStormPlugin: готов принимать log_storm.burst")

    def shutdown(self, ctx: PluginContext) -> None:
        ctx.log_info("LogStormPlugin: остановлен")

    def _emitter(self, level: str) -> Callable[[str], None]:
        """Метод эмиссии по имени уровня. Неизвестный уровень — отказ, не DEBUG молча."""
        table: Dict[str, Callable[..., None]] = {
            "DEBUG": self._ctx.log_debug,
            "INFO": self._ctx.log_info,
            "WARNING": self._ctx.log_warning,
            "ERROR": self._ctx.log_error,
            "CRITICAL": self._ctx.log_critical,
        }
        emit = table.get(level)
        if emit is None:
            raise ValueError(f"неизвестный уровень {level!r}; допустимы {sorted(table)}")
        return emit

    def _cmd_burst(self, data: dict) -> Dict[str, Any]:
        """Выдать ``count`` одинаковых записей уровня ``level`` с текстом ``text``.

        Возвращает ЧИСЛО эмитированных записей — вход арифметики приёмки. Считается
        по фактически сделанным вызовам, а не по запрошенному ``count``: отказ на
        полпути обязан быть виден числом, а не молчаливо выданным «сделано всё».
        """
        count = int(data.get("count", 100))
        level = str(data.get("level", "DEBUG")).upper()
        text = str(data.get("text", "log_storm"))
        try:
            emit = self._emitter(level)
        except ValueError as exc:
            return {"status": "error", "reason": str(exc)}

        emitted = 0
        started = time.perf_counter()
        for _ in range(count):
            emit(text)
            emitted += 1
        elapsed = time.perf_counter() - started
        return {
            "status": "success",
            "emitted": emitted,
            "level": level,
            "text": text,
            "elapsed_sec": round(elapsed, 4),
        }
