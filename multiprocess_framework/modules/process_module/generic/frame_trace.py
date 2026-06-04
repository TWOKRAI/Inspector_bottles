# -*- coding: utf-8 -*-
"""frame_trace — пер-сегментная трассировка кадра через пайплайн (in-band).

Идея: ``item["trace"]`` — список спанов, который едет вместе с кадром через всю
цепочку (в метаданных сообщения, рядом с ссылкой на frame). Каждый узел/плагин
дописывает свой спан → на выходе цепочки читаем полную историю: сколько ушло на
ПЕРЕДАЧУ между процессами (transport) и на ОБРАБОТКУ в каждом плагине (process).

Контракт спана (plain dict — Dict at Boundary, pickle-safe):
    {"kind": "transport", "from": "camera_0", "to": "detector", "ms": 1.8}
    {"kind": "process",   "node": "detector", "plugin": "hsv_mask", "ms": 0.6}

Служебные поля ``_t_send`` / ``_from`` ставятся перед отправкой и снимаются на
приёме (по ним считается transport-спан); они НЕ накапливаются.

Время — ``time.time()`` (wall): кросс-процессно сравнимо на одной машине
(monotonic у каждого процесса свой и несравним). Длительность ОБРАБОТКИ меряем
``perf_counter`` (high-res), длительность ПЕРЕДАЧИ — разностью wall-часов.

Гейтится ``INSPECTOR_FRAME_TRACE=1`` — в проде по умолчанию OFF: stamp/record
становятся no-op (один bool-чек на item на участок, нулевой overhead). Дочерние
процессы (spawn) наследуют env, если флаг выставлен до запуска ``run.py``.
"""

from __future__ import annotations

import functools
import os
import time

# Читается один раз при импорте. Дочерние spawn-процессы наследуют env.
# Тесты могут переопределить: frame_trace._ENABLED = True.
_ENABLED = os.environ.get("INSPECTOR_FRAME_TRACE", "").strip().lower() in ("1", "true", "yes")


def enabled() -> bool:
    """Включена ли трассировка кадра (по env INSPECTOR_FRAME_TRACE)."""
    return _ENABLED


def stamp_send(item: dict, node: str) -> None:
    """Перед отправкой item из узла: запомнить отправителя и wall-время.

    На приёме следующий узел вызовет ``record_transport`` и по ним вычислит
    время передачи. No-op если трассировка выключена.
    """
    if not _ENABLED or not isinstance(item, dict):
        return
    item["_t_send"] = time.time()
    item["_from"] = node


def record_transport(item: dict, node: str) -> None:
    """На приёме: добавить transport-спан ``from -> node`` по _t_send/_from.

    Снимает служебные поля (чтобы не уехали на следующий участок). No-op если
    трассировка выключена или item пришёл без отметки отправки.
    """
    if not _ENABLED or not isinstance(item, dict):
        return
    t_send = item.pop("_t_send", None)
    frm = item.pop("_from", None)
    if not isinstance(t_send, (int, float)):
        return
    item.setdefault("trace", []).append(
        {
            "kind": "transport",
            "from": frm,
            "to": node,
            "ms": round((time.time() - t_send) * 1000.0, 3),
        }
    )


def record_process(item: dict, node: str, plugin: str, ms: float) -> None:
    """Добавить process-спан: обработка ``plugin`` в ``node`` заняла ``ms``."""
    if not _ENABLED or not isinstance(item, dict):
        return
    item.setdefault("trace", []).append({"kind": "process", "node": node, "plugin": plugin, "ms": round(ms, 3)})


def traced(fn):
    """Декоратор: измерить вызов плагинного ``process``/``produce`` и записать
    process-спан в КАЖДЫЙ выходной item.

    Универсален: меряет строго вокруг тела метода (start→end через perf_counter),
    делит длительность на размер батча → честное per-item время (а не общий батч
    на каждый item). Узел берёт из ``self._trace_node`` (ставит оркестратор),
    имя — из ``self.name``. No-op при выключенной трассировке (нулевой overhead,
    кроме одного bool-чека).

    Применяется автоматически в ``ProcessModulePlugin.__init_subclass__`` ко всем
    плагинам — отдельно вешать на каждый плагин не нужно.
    """

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        if not _ENABLED:
            return fn(self, *args, **kwargs)
        t0 = time.perf_counter()
        result = fn(self, *args, **kwargs)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        out = result if isinstance(result, list) else ([] if result is None else [result])
        node = getattr(self, "_trace_node", "")
        name = getattr(self, "name", "?")
        per = dt_ms / len(out) if out else dt_ms
        for it in out:
            record_process(it, node, name, per)
        return result

    wrapper._traced = True  # type: ignore[attr-defined]
    return wrapper
