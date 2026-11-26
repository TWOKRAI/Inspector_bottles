"""presence_watch — проходной индикатор «нет изделия» / «слабое распознавание».

Purpose:
    Items проходят без изменений. Пока плагин «в работе», ``readiness()`` отдаёт не более одной
    причины ``out_of_spec``: изделия нет ``absent_after_s`` секунд, или последнее изделие
    распознано слабо. Это не авария: START и STOP не блокируются. О конкретном продукте плагин
    не знает: ключи item и тексты задаёт регистр (рецепт).

Public API:
    PresenceWatchPlugin — плагин; параметры — PresenceWatchRegisters.

Stability: lite

Pre:
    ``configure(ctx)`` вызван до ``process``; ``items`` — список, может быть пуст.
Post:
    ``process`` возвращает тот же список; item не изменены, не скопированы, не убраны.
    ``readiness`` не бросает; вне работы и у выключенного узла — ``[]``.
Invariants:
    Причина одна; «нет изделия» старше «слабого». Пустой текст выключает свою причину.
    «В работе» задают хуки: ``start``/``resume`` открывают (прошлая работа забыта), ``pause`` закрывает.
    Регистр читается на каждом вызове. Лог — одна строка ERROR на (место, тип исключения),
    значений item в нём нет. State и команд нет.
"""

from __future__ import annotations

import time

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    ProcessModulePlugin,
    register_plugin,
)

from .registers import PresenceWatchRegisters

__all__ = ["PresenceWatchPlugin"]

_clock = time.monotonic  # тесты подменяют атрибут модуля


def _resolve(item: object, path: str) -> object | None:
    """Значение по пути «a.b» через dict; нет звена — None."""
    cur = item
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


@register_plugin(
    "presence_watch",
    category="processing",
    description="Проходной индикатор: нет изделия / слабое распознавание (out_of_spec, только в работе)",
)
class PresenceWatchPlugin(ProcessModulePlugin):
    """Наблюдает поток items и сообщает причины ``out_of_spec``, не меняя поток."""

    name = "presence_watch"
    category = "processing"
    thread_safe = True

    inputs = []
    outputs = []

    commands: dict[str, str] = {}
    register_class = PresenceWatchRegisters

    # Пишут run_watch (start/pause/resume) и конвейер (process); читает поток снимка. Одна ссылка, без замков.
    _run_since: float | None = None  # None — не в работе
    _last_seen: tuple[float, bool] | None = None  # (момент, слабое ли) последнего изделия

    @classmethod
    def config_class(cls) -> type | None:
        from .config import PresenceWatchPluginConfig

        return PresenceWatchPluginConfig

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._logged: set[tuple[str, str]] = set()
        self._reg: PresenceWatchRegisters = self._init_register(ctx)

    def start(self, ctx: PluginContext) -> None:
        """Поднят в «готов» — сразу придёт pause(); поднят в работе (рестарт) — нет."""
        self._begin_run()

    def resume(self, ctx: PluginContext) -> None:
        self._begin_run()

    def pause(self, ctx: PluginContext) -> None:
        self._run_since = None

    def _begin_run(self) -> None:
        self._last_seen = None  # сначала забыть прошлую работу,
        self._run_since = _clock()  # потом открыть новую

    def _log_once(self, place: str, exc: Exception) -> None:
        """Одна строка ERROR на (место, тип исключения); значений item нет."""
        logged, ctx = getattr(self, "_logged", None), getattr(self, "_ctx", None)
        key = (place, type(exc).__name__)
        if logged is None or ctx is None or key in logged:
            return
        logged.add(key)
        ctx.log_error(f"presence_watch: {place}: {key[1]}")

    def process(self, items: list[dict]) -> list[dict]:
        """Pre: items — список, может быть пуст. Post: тот же список items; item не изменены,
        не скопированы, не убраны, порядок прежний."""
        for item in items:
            self._observe(item)
        return items

    def _observe(self, item: object) -> None:
        seen_at = _clock()  # момент ДО разбора
        try:
            keys = [k.strip() for k in self._reg.presence_keys.split(",") if k.strip()]
            if not any(_resolve(item, k) is not None for k in keys):
                return  # не изделие
        except Exception as exc:  # noqa: BLE001 — наблюдение не ломает поток кадров
            self._log_once("ключи изделия", exc)
            return
        try:
            weak = self._is_weak(item)
        except Exception as exc:  # noqa: BLE001 — негодное предсказание = слабое
            self._log_once("распознавание", exc)
            weak = True
        self._last_seen = (seen_at, weak)

    def _is_weak(self, item: object) -> bool:
        reg = self._reg
        preds = _resolve(item, reg.predictions_key)
        if not isinstance(preds, list) or not preds:
            return True  # нет топ-K или он пуст
        top = preds[0]
        if not isinstance(top, dict):
            return True
        if reg.label_key and top.get(reg.label_key) in (None, ""):
            return True  # метка 0 — метка
        if reg.below_threshold_key and top.get(reg.below_threshold_key):
            return True
        threshold = float(reg.min_confidence)
        return threshold > 0.0 and not (float(top.get(reg.confidence_key, 1.0)) >= threshold)  # NaN — слабое

    def readiness(self, ctx: PluginContext) -> list[dict]:
        """Post: причины независимых проверок; сейчас одна. Новая проверка — своя строка extend под своим try;
        «только в работе» — внутри проверки, не ранний return метода. Исключение = failure = авария в работе."""
        reasons: list[dict] = []
        try:
            reasons.extend(self._presence_reasons())
        except Exception as exc:  # noqa: BLE001
            self._log_once("readiness", exc)
        return reasons

    def _presence_reasons(self) -> list[dict]:
        since = self._run_since  # каждое поле читается один раз
        if since is None or not getattr(self, "enabled", True):
            return []  # не в работе или узел выключен (process() не идёт)
        last = self._last_seen
        if last is not None and last[0] < since:
            last = None  # запись прошлой работы: process() пересёк pause/resume
        reg = self._reg
        ref = since if last is None else last[0]
        if _clock() - ref >= float(reg.absent_after_s):
            return [{"severity": "out_of_spec", "reason": reg.text_absent}] if reg.text_absent else []
        if last is not None and last[1] and reg.text_weak:
            return [{"severity": "out_of_spec", "reason": reg.text_weak}]
        return []
