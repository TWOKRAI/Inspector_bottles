# -*- coding: utf-8 -*-
"""
domain/topology_session.py — TopologySession: dirty-контур редактора топологии (RS-4).

Единый источник знания о двух независимых расхождениях граф-редактора:

  * **dirty** — «в редакторе есть правки, не сохранённые в рецепт-файл».
    Ставится любой структурной правкой графа (add/remove процесс/провод,
    редактирование конфига ноды) и undo/redo; снимается сохранением в рецепт,
    активацией другого рецепта и загрузкой из файла.

  * **diverged** — «граф редактора расходится с живой системой (backend)».
    Ставится любой правкой (редактор перестал совпадать с тем, что бежит);
    снимается применением графа к backend (Apply) и активацией рецепта.

Два флага — потому что точки сброса РАЗНЫЕ: Save пишет в файл (снимает dirty, но
живая система не тронута → diverged держится), Apply толкает граф в backend
(снимает diverged, но в файл ничего не записано → dirty держится). Activate —
единственная операция, снимающая оба (новый baseline: файл == редактор == live).

Что НЕ считается dirty: перемещение/фиксация нод (layout). Layout — GUI-метаданные,
их точечно авто-сохраняет ``LayoutController._persist_layout_to_recipe`` (пишет
только ``blueprint.metadata`` через ruamel, не трогая processes/wires). Поэтому drag
ноды не поднимает dirty — иначе индикатор «несохранённые правки» горел бы после
каждого косметического сдвига, хотя правка уже на диске.

Границы: чистый Python. Никаких Qt/PySide6 и никакой подписки на EventBus внутри —
класс только хранит состояние и уведомляет callbacks. Проводку (EventBus
TopologyReplaced → mark_edited, RecipeActivated → mark_activated; Save/Apply/Load →
соответствующие mark_*) делает composition root (``app.py``) и презентеры. Это
делает класс тривиально unit-тестируемым и удерживает знание о семантике операций
в тех местах, которые эти операции выполняют.

Целевая архитектура аудита (2026-07-12, раздел C, «RecipeSession — SSOT + dirty»):
полный RecipeSession (свернуть 4 копии топологии в один владелец) — отдельная волна.
TopologySession — первый шаг: честный dirty/diverged без переезда владения топологией.

Refs: plans/2026-07-06_constructor-master/plan.md (RS-4),
      docs/audits/2026-07-12_recipe-lifecycle-audit.md (C-1/C-2/C-3/C-5)
"""

from __future__ import annotations

from typing import Callable


class TopologySession:
    """Состояние сессии редактора топологии: dirty + diverged + уведомления.

    Оба флага стартуют ``False`` (свежая загрузка на старте: редактор == файл ==
    живая система). Каждый ``mark_*`` меняет состояние и, ЕСЛИ оно реально
    изменилось, дёргает зарегистрированные callbacks — GUI обновляет индикаторы
    ровно тогда, когда есть что показать (без лишних перерисовок).

    Thread-safety: НЕ потокобезопасен — как и остальной editor-state, живёт на Qt
    main thread (EventBus публикует синхронно там же).
    """

    __slots__ = ("_dirty", "_diverged", "_callbacks")

    def __init__(self) -> None:
        self._dirty: bool = False
        self._diverged: bool = False
        self._callbacks: list[Callable[[], None]] = []

    # ------------------------------------------------------------------ #
    #  Чтение состояния                                                    #
    # ------------------------------------------------------------------ #

    @property
    def dirty(self) -> bool:
        """Есть несохранённые в рецепт-файл правки графа."""
        return self._dirty

    @property
    def diverged(self) -> bool:
        """Граф редактора расходится с живой системой (backend)."""
        return self._diverged

    # ------------------------------------------------------------------ #
    #  Подписка GUI                                                        #
    # ------------------------------------------------------------------ #

    def add_change_callback(self, cb: Callable[[], None]) -> None:
        """Подписать callback на изменение состояния (dirty/diverged).

        Callback вызывается без аргументов после каждого реального перехода
        состояния — подписчик читает ``dirty``/``diverged`` сам. Дубли не
        отсеиваются (подписчик отвечает за идемпотентность своей реакции).
        """
        self._callbacks.append(cb)

    # ------------------------------------------------------------------ #
    #  Переходы состояния                                                  #
    # ------------------------------------------------------------------ #

    def mark_edited(self) -> None:
        """Правка графа (структура/конфиг ноды) или undo/redo.

        Редактор разошёлся и с сохранённым рецептом, и с живой системой →
        оба флага ``True``.
        """
        self._set(dirty=True, diverged=True)

    def mark_saved(self) -> None:
        """Граф сохранён в рецепт-файл. Снимает только dirty.

        Живая система записью в файл не тронута — ``diverged`` держится (если был).
        """
        self._set(dirty=False)

    def mark_applied(self) -> None:
        """Граф применён к живой системе (Apply / «Перезапустить»). Снимает diverged.

        В файл ничего не записано — ``dirty`` держится (если был).
        """
        self._set(diverged=False)

    def mark_activated(self) -> None:
        """Активирован рецепт: новый baseline (файл == редактор == live). Снимает оба."""
        self._set(dirty=False, diverged=False)

    def mark_loaded(self) -> None:
        """Загрузка топологии из файла в редактор. Снимает dirty, ставит diverged.

        Редактор теперь совпадает с загруженным файлом (dirty=False), но НЕ применён
        к живой системе — до Apply он расходится с backend (``diverged`` = True).
        """
        self._set(dirty=False, diverged=True)

    def reset(self) -> None:
        """Сбросить оба флага (чистый baseline). Использует composition root на старте."""
        self._set(dirty=False, diverged=False)

    # ------------------------------------------------------------------ #
    #  Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _set(self, *, dirty: bool | None = None, diverged: bool | None = None) -> None:
        """Применить частичное обновление флагов; уведомить только при реальном изменении."""
        changed = False
        if dirty is not None and dirty != self._dirty:
            self._dirty = dirty
            changed = True
        if diverged is not None and diverged != self._diverged:
            self._diverged = diverged
            changed = True
        if changed:
            for cb in self._callbacks:
                cb()


__all__ = ["TopologySession"]
