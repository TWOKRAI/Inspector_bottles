# -*- coding: utf-8 -*-
"""RunFlag — флаг работы системы без межпроцессного замка (Task 1.10, ADR-PMM-046).

Purpose:
    Однобайтовый флаг в разделяемой памяти для ``ProcessManagerProcess._run_event``. Заменяет
    ``multiprocessing.Event``: у того каждый ``is_set/set/clear`` берёт межпроцессный замок, и ребёнок,
    убитый (SIGKILL/OOM/segfault) внутри обращения, оставляет замок занятым навсегда — PM встаёт под своим
    ``_run_lock`` (``system.run.*``, публикация, такт монитора). У ``RunFlag`` замка нет вовсе.

Public API:
    ``RunFlag(initial: bool = False)``; ``is_set() -> bool``; ``set() -> None``; ``clear() -> None``.
    Имена и смысл те же, что у ``Event``: подмена одной строкой, потребители не меняются.
    Метода ``wait`` НЕТ — контракт «только опрос» (блокирующих потребителей в репозитории нет).

Pre:
    - Один писатель — ProcessManager (``set``/``clear`` зовёт только он, под своим ``_run_lock``);
      читатели (дети: ``reconcile_run_event``, ``SourceProducer``, ``process_module``) зовут только ``is_set()``.
    - Объект уходит ребёнку ТОЛЬКО наследованием при spawn — аргументом ``Process(...)`` (ADR-PMM-034):
      не через bundle ``custom``, очередь или Manager. Вне spawn ``pickle`` падает громко
      (``TypeError: cannot pickle 'mmap.mmap'``), тихой порчи нет.
Post:
    - ``is_set()`` возвращает настоящий ``bool``; ``set()``/``clear()`` возвращают ``None``, идемпотентны.
    - Ни один метод не блокируется и не бросает: смерть любого процесса не влияет на соседей.
    - Читатель видит старое или новое значение — оба допустимы; фронт виден ребёнку за доли секунды.

Memory:
    Запись одиночного байта без замка и барьера: один писатель, а одиночный байт читается/пишется атомарно
    на x86-64 и arm64. Флаг не публикует зависимых данных (читатель по значению ничего больше не читает
    из памяти писателя), поэтому порядок видимости относительно других записей не нужен. Формально Python
    барьера не даёт — безопасность держится на этих двух условиях; добавишь зависимые данные — пересмотри.

Context:
    ``RawValue`` создан в умолчательном контексте ``multiprocessing`` — как ``RawArray("q", 3)`` слота
    отчёта выхода в ``process_registry`` и ``Event`` рядом (``from multiprocessing import Event, Process,
    RawArray``). Контекст ``Process`` в реестре тоже умолчательный, так что объект согласован с остальным
    кодом при spawn (macOS, Windows); под fork ``RawValue`` тоже наследуется.

Stability:
    Public, stable. Расширение API (``wait``, запись из ребёнка) — только отдельным ADR.
"""

from __future__ import annotations

import ctypes
from multiprocessing import RawValue

__all__ = ["RunFlag"]


class RunFlag:
    """Однобайтовый флаг работы в разделяемой памяти, без межпроцессного замка (см. модульный docstring)."""

    def __init__(self, initial: bool = False) -> None:
        self._value = RawValue(ctypes.c_bool, initial)

    def is_set(self) -> bool:
        """Взведён ли флаг. Не блокируется."""
        return bool(self._value.value)

    def set(self) -> None:
        """Взвести флаг (только PM). Идемпотентно."""
        self._value.value = True

    def clear(self) -> None:
        """Снять флаг (только PM). Идемпотентно."""
        self._value.value = False
