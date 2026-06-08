"""io_peek — наблюдение in/out плагина для отладочной панели карточки ноды (Этап 5).

Два компонента:
- ``summarize_payload`` — O(1) JSON-safe сводка списка items БЕЗ копирования пикселей
  (ndarray → {shape, dtype}, list → {len, head}, кадр → {frame_id, shape}). Безопасна
  для Dict-at-Boundary: уходит в StateProxy → IPC → GUI, поэтому никаких ndarray/bytes.
- ``IoPeekPublisher`` — pre/post-хуки для PluginRunner: снимает сводку входа (в pre-хуке,
  до мутации плагином) и выхода (в post-хуке), публикует в реактивное дерево по пути
  ``processes.{proc}.plugins.{plugin}.io_peek``. Throttle (rate_hz) + opt-in: хуки
  вешаются ТОЛЬКО когда observability.io_peek.enabled — при выключенном io-debug
  оверхед нулевой (PluginRunner без хуков, гарантия Этапа 4).

«Заморозить» — чисто GUI-операция (снапшот подписки), бэкенд продолжает публиковать.
"""

from __future__ import annotations

import time
from typing import Any, Callable

# Глубина рекурсии при сводке dict-значений (защита от больших вложенных структур).
_MAX_DEPTH = 2


def _summarize_value(value: Any, depth: int = 0, head_len: int = 3) -> Any:
    """Свести одно значение к JSON-safe сводке без копирования тяжёлых данных.

    ndarray (duck-typing по shape/dtype) → {shape, dtype}; bytes → {len};
    list/tuple → {len, head из head_len элементов}; dict → сводка по ключам (до глубины);
    скаляры (int/float/str/bool/None) — как есть; прочее — имя типа.
    """
    # ndarray-like (numpy) — НЕ импортируем numpy, ловим по атрибутам. Главное: без пикселей.
    if hasattr(value, "shape") and hasattr(value, "dtype"):
        return {"_type": "ndarray", "shape": list(value.shape), "dtype": str(value.dtype)}

    if value is None or isinstance(value, (bool, int, float)):
        return value

    if isinstance(value, str):
        # Длинные строки усекаем (не раздуваем дерево/IPC).
        return value if len(value) <= 80 else value[:77] + "…"

    if isinstance(value, (bytes, bytearray)):
        return {"_type": "bytes", "len": len(value)}

    if isinstance(value, (list, tuple)):
        head = [_summarize_value(v, depth + 1, head_len) for v in value[:head_len]]
        return {"_type": "list", "len": len(value), "head": head}

    if isinstance(value, dict):
        if depth >= _MAX_DEPTH:
            return {"_type": "dict", "keys": list(value.keys())[:head_len]}
        return {k: _summarize_value(v, depth + 1, head_len) for k, v in list(value.items())[:8]}

    # Прочие типы — только имя класса (JSON-safe, без сериализации объекта).
    return {"_type": type(value).__name__}


def _summarize_item(item: Any, head_len: int = 3) -> Any:
    """Свести один item (обычно dict {frame, ...metadata}) к JSON-safe сводке.

    Кадр получает явный frame_id (если есть) рядом со сводкой — удобно для отладки
    корреляции seq_id ↔ frame_id в Join-узлах.
    """
    if not isinstance(item, dict):
        return _summarize_value(item, head_len=head_len)
    summary = {k: _summarize_value(v, head_len=head_len) for k, v in list(item.items())[:12]}
    return summary


def summarize_payload(items: list[dict] | None, head_len: int = 3) -> dict:
    """O(1) JSON-safe сводка payload (input/output плагина) без копирования пикселей.

    Args:
        items: список items (или None для produce-входа — у источника входа нет).
        head_len: сколько items/элементов списка показывать (хвост усекается).

    Returns:
        {"count": N, "items": [сводка ...]} либо {"count": 0, "items": None} для None.
    """
    if items is None:
        return {"count": 0, "items": None}
    return {
        "count": len(items),
        "items": [_summarize_item(it, head_len) for it in items[:head_len]],
    }


class IoPeekPublisher:
    """pre/post-хуки PluginRunner: публикует сводку in/out плагина в StateProxy.

    Throttle per-plugin (rate_hz): между публикациями оба хука почти бесплатны
    (одно сравнение monotonic). Snapshot входа снимается в pre-хуке (плагины часто
    мутируют item in-place), выхода — в post-хуке.

    Args:
        state_proxy: реактивное дерево (set(path, dict)). None → publisher no-op.
        process_name: имя процесса (для пути processes.{proc}.plugins.{plugin}.io_peek).
        rate_hz: частота публикации (Гц). 0 → каждый вызов.
        head_len: глубина сводки (items/элементы списка).
        log_error: для изоляции (хук не должен ронять pipeline — но PluginRunner и так
            ловит; здесь лог на случай ошибки публикации в merge).
    """

    def __init__(
        self,
        state_proxy: Any,
        process_name: str,
        rate_hz: float = 1.0,
        head_len: int = 3,
        log_error: Callable[[str], None] | None = None,
    ) -> None:
        self._state_proxy = state_proxy
        self._process = process_name
        self._interval = 1.0 / rate_hz if rate_hz > 0 else 0.0
        self._head_len = head_len
        self._log_error = log_error or (lambda msg: None)
        # Per-plugin состояние: когда следующая публикация и отложенная сводка входа.
        self._next_due: dict[str, float] = {}
        self._pending_input: dict[str, dict] = {}

    def attach(self, runner: Any) -> None:
        """Зарегистрировать хуки в PluginRunner (вызывается при opt-in)."""
        runner.add_pre_hook(self.on_pre)
        runner.add_post_hook(self.on_post)

    def on_pre(self, plugin: Any, method: str, inputs: list[dict] | None) -> None:
        """Throttle-gate + снимок входа (до мутации плагином)."""
        if self._state_proxy is None:
            return
        name = plugin.name
        now = time.monotonic()
        if now < self._next_due.get(name, 0.0):
            # Не время публиковать — отметим, чтобы post-хук пропустил (без сводки выхода).
            self._pending_input.pop(name, None)
            return
        self._pending_input[name] = summarize_payload(inputs, self._head_len)

    def on_post(self, plugin: Any, method: str, inputs: list[dict] | None, outputs: list[dict]) -> None:
        """Если pre-хук пропустил throttle — снять сводку выхода и опубликовать."""
        if self._state_proxy is None:
            return
        name = plugin.name
        input_summary = self._pending_input.pop(name, None)
        if input_summary is None:
            return  # throttled — pre-хук не подготовил вход
        now = time.monotonic()
        self._next_due[name] = now + self._interval
        try:
            # set (не merge!) — публикуем снимок io_peek ОДНОЙ дельтой с целым dict.
            # merge рекурсивно флэттенит вложенные dict на листовые дельты (и
            # непоследовательно: первый раз целиком, потом по листьям) — GUI-подписка
            # на узел io_peek тогда не получит снимок целиком. set перезаписывает узел
            # одним значением → одна дельта path=...io_peek, value=весь снимок.
            path = f"processes.{self._process}.plugins.{name}.io_peek"
            self._state_proxy.set(
                path,
                {
                    "method": method,
                    "ts": round(now, 3),
                    "input": input_summary,
                    "output": summarize_payload(outputs, self._head_len),
                },
            )
        except Exception as e:  # noqa: BLE001 — публикация не должна ронять pipeline
            self._log_error(f"IoPeekPublisher set error ({name}): {e}")
