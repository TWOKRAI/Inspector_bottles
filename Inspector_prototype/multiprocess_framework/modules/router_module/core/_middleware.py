# -*- coding: utf-8 -*-
"""
MiddlewarePipeline — конвейер функций обработки сообщений.

Используется как для исходящих (send middleware), так и для входящих
(receive middleware) сообщений.

Поведение:
  - fn(msg) → dict   — сообщение обновлено, pipeline продолжается
  - fn(msg) → None   — сообщение дропается (pipeline прерывается)
  - fn() raises      — исключение логируется, pipeline продолжается

Пример:
    send_pipeline = MiddlewarePipeline(log_warning=router._log_warning)
    send_pipeline.add(lambda msg: {**msg, "_ts": time.time()})
    send_pipeline.add(lambda msg: msg if msg.get("auth") else None)

    result = send_pipeline.apply(my_message)
    if result is not None:
        channel.send(result)
"""
from typing import Callable, Dict, List, Optional


class MiddlewarePipeline:
    """Последовательный конвейер fn(msg) → dict | None.

    Каждая функция получает сообщение и возвращает изменённое сообщение
    или None чтобы отбросить его. Исключения внутри fn не ломают pipeline —
    некорректный middleware не должен останавливать маршрутизацию.
    """

    def __init__(
        self,
        name: str = "pipeline",
        log_warning: Optional[Callable] = None,
    ) -> None:
        self._name = name
        self._pipeline: List[Callable] = []
        self._log_warning = log_warning or (lambda msg: None)

    # ------------------------------------------------------------------
    # Management
    # ------------------------------------------------------------------

    def add(self, fn: Callable[[Dict], Optional[Dict]]) -> None:
        """Добавить функцию в конец pipeline."""
        self._pipeline.append(fn)

    def clear(self) -> None:
        """Удалить все функции из pipeline."""
        self._pipeline.clear()

    def __len__(self) -> int:
        return len(self._pipeline)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def apply(self, msg: Dict) -> Optional[Dict]:
        """Прогнать сообщение через весь pipeline.

        Returns:
            Обработанное сообщение или None если какой-либо fn вернула None.
        """
        current = msg
        for fn in self._pipeline:
            try:
                result = fn(current)
                if result is None:
                    return None
                current = result
            except Exception as e:
                fn_name = getattr(fn, "__name__", repr(fn))
                self._log_warning(
                    f"[MiddlewarePipeline:{self._name}] '{fn_name}' raised: {e} "
                    f"— skipped, pipeline continues"
                )
        return current
