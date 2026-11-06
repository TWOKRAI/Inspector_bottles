# -*- coding: utf-8 -*-
"""
domain/topology_session.py — TopologySession: dirty-контур редактора топологии (RS-4).

Единый источник знания о двух независимых расхождениях граф-редактора:

  * **dirty** — «в редакторе есть правки, не сохранённые в рецепт-файл».
    Ставится любой структурной правкой графа (add/remove процесс/провод,
    редактирование конфига ноды), undo/redo И загрузкой графа из внешнего файла
    (загруженное содержимое не существует ни в одном рецепте — это несохранённые
    данные); снимается сохранением в рецепт и активацией другого рецепта.

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

from collections.abc import Iterable
from typing import Callable


class TopologySession:
    """Состояние сессии редактора топологии: dirty + diverged + уведомления.

    Оба флага стартуют ``False`` (свежая загрузка на старте: редактор == файл ==
    живая система). Каждый ``mark_*`` меняет состояние и, ЕСЛИ оно реально
    изменилось, дёргает зарегистрированные callbacks — GUI обновляет индикаторы
    ровно тогда, когда есть что показать (без лишних перерисовок).

    ИНВАРИАНТ (осознанная архитектурная цена, RS-4 #7): dirty/diverged держатся на
    РУЧНОЙ проводке ``mark_*`` в точках операций (правка→mark_edited через EventBus,
    Save→mark_saved, Apply→mark_applied, Activate→mark_activated, load-from-file→
    mark_edited, выход/рестарт→confirm). Это НЕ вычисляемое сравнение «редактор vs
    файл vs live» — поэтому ЛЮБОЙ новый путь мутации графа или выхода из приложения
    ОБЯЗАН явно звать соответствующий ``mark_*`` (иначе флаг рассинхронизируется с
    реальностью). Системное решение (SSOT-топология с производными dirty/diverged) —
    RecipeSession (целевая архитектура аудита 2026-07-12, раздел C), отложено в
    отдельную волну; TopologySession — первый, намеренно частичный шаг.

    Третий флаг, **layout_unsaved** (C-30, Task 1.12), — отдельный от ``dirty``:
    «позиции узлов не сохранены, потому что автосейв раскладки наткнулся на
    конфликт (рецепт в файле изменён после загрузки)». ``dirty`` гасит индикаторы
    и «несохранённое» в UI структуры; раскладка с живой системой не расходится,
    поэтому флаг не трогает ``diverged``, индикаторы и Save-путь, а только заставляет
    диалог закрытия/рестарта спросить пользователя. Ставит ``mark_layout_unsaved``;
    снимают ``mark_saved`` / ``mark_activated`` / ``reset``; ``mark_edited`` и
    ``mark_applied`` его не трогают.

    Четвёртое — **foundation_names** (C-30, Task 1.14b): имена процессов фундамента (фрагменты ``manifest.base``),
    которые GUI подмешивает к рецепту при старте. Save их в рецепт не пишет. Это не флаг, а статичный набор на
    жизнь приложения: ставит ``capture_foundation`` composition root один раз; ``mark_*``/``reset``/``rebase``
    его не трогают, callbacks не уведомляются.

    Thread-safety: НЕ потокобезопасен — как и остальной editor-state, живёт на Qt
    main thread (EventBus публикует синхронно там же).
    """

    __slots__ = ("_dirty", "_diverged", "_layout_unsaved", "_callbacks", "_base", "_foundation_names")

    def __init__(self) -> None:
        self._dirty: bool = False
        self._diverged: bool = False
        self._layout_unsaved: bool = False
        self._callbacks: list[Callable[[], None]] = []
        # База правок редактора: (slug рецепта, rev его файла на момент загрузки в редактор).
        # None — базы нет (рецепт загружен не из каталога рецептов / активации ещё не было).
        self._base: tuple[str, str | None] | None = None
        # Имена процессов фундамента (manifest.base); пусто — правило «Save не пишет фундамент» ничего не делает.
        self._foundation_names: frozenset[str] = frozenset()

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

    @property
    def layout_unsaved(self) -> bool:
        """Позиции узлов не сохранены: автосейв раскладки упёрся в конфликт рецепта."""
        return self._layout_unsaved

    @property
    def foundation_names(self) -> frozenset[str]:
        """Имена процессов фундамента (``manifest.base``): Save их в рецепт не пишет."""
        return self._foundation_names

    # ------------------------------------------------------------------ #
    #  База правок (C-30, Task 1.8)                                        #
    # ------------------------------------------------------------------ #

    def capture_base(self, slug: str, rev: str | None) -> None:
        """Запомнить базу: редактор загрузил рецепт ``slug`` с файла ревизии ``rev``.

        Зовут composition root на старте (рецепт, прочитанный один раз) и на активации
        (``RecipeActivated``). Заменяет прежнюю базу целиком.
        """
        self._base = (slug, rev)

    def capture_foundation(self, names: Iterable[str]) -> None:
        """Запомнить имена процессов фундамента (Task 1.14b). Зовёт composition root один раз на старте."""
        self._foundation_names = frozenset(names)

    def base_rev_for(self, slug: str) -> str | None:
        """``rev`` базы, если она относится к ``slug``; иначе ``None`` (стор возьмёт rev своего чтения).

        Save в ДРУГОЙ рецепт не должен сверяться с ревизией чужого файла: сверка по slug.
        """
        if self._base is None or self._base[0] != slug:
            return None
        return self._base[1]

    def rebase(self, slug: str, rev: str | None) -> None:
        """После успешной записи ``slug``: база = ревизия, которую вернула запись.

        Запись в рецепт, не являющийся базой редактора, базу не меняет: редактор по-прежнему
        построен на файле базового рецепта.

        Предусловие: ``rebase`` допустим только после записи, сделанной с ``expected_rev == base_rev_for(slug)``,
        и только если её сделал сам редактор из своей модели (Save) либо она лежит вне секций, из которых
        построена модель (``blueprint.processes`` / ``wires`` / ``displays``). Другая вкладка меняет эти секции
        через модель редактора (dispatch), а не в файл: rebase после её записи туда откатил бы правку при
        следующем Save (Р7 design.md).
        """
        if self._base is not None and self._base[0] == slug:
            self._base = (slug, rev)

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
        Снимает и ``layout_unsaved``.
        """
        self._set(dirty=False, layout_unsaved=False)

    def mark_applied(self) -> None:
        """Граф применён к живой системе (Apply / «Перезапустить»). Снимает diverged.

        В файл ничего не записано — ``dirty`` держится (если был).
        """
        self._set(diverged=False)

    def mark_activated(self) -> None:
        """Активирован рецепт: новый baseline (файл == редактор == live). Снимает все флаги."""
        self._set(dirty=False, diverged=False, layout_unsaved=False)

    def mark_layout_unsaved(self) -> None:
        """Автосейв раскладки не записал позиции (конфликт рецепта). ``dirty``/``diverged`` не трогает."""
        self._set(layout_unsaved=True)

    def mark_layout_saved(self) -> None:
        """Автосейв раскладки записал позиции (C-30, 1.15). Снимает только ``layout_unsaved``.

        ``dirty``/``diverged`` не трогает (``mark_saved`` гасит ``dirty`` — здесь не подходит).
        """
        self._set(layout_unsaved=False)

    def reset(self) -> None:
        """Сбросить все флаги (чистый baseline). Использует composition root на старте."""
        self._set(dirty=False, diverged=False, layout_unsaved=False)

    # ------------------------------------------------------------------ #
    #  Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _set(
        self,
        *,
        dirty: bool | None = None,
        diverged: bool | None = None,
        layout_unsaved: bool | None = None,
    ) -> None:
        """Применить частичное обновление флагов; уведомить только при реальном изменении."""
        changed = False
        if layout_unsaved is not None and layout_unsaved != self._layout_unsaved:
            self._layout_unsaved = layout_unsaved
            changed = True
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
