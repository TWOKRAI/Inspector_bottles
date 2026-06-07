# -*- coding: utf-8 -*-
"""DisplaysPresenter — бизнес-логика таба дисплеев (MVP, recipe-scoped).

Pure Python, без Qt-импортов. Управляет CRUD над DisplayCatalog (domain Protocol):
- load() / on_select() / on_create() / on_delete() / on_duplicate() / on_open_preview()
- bind_event_bus() — подписывается на RecipeActivated → перечитывает реестр,
  управляет окнами превью через PreviewWindowManager (вариант А, раздел 11.4 спеки).

Task 5.2: CRUD работает с render-полями (position, fit, scale, rotate, flip, crop).
on_open_preview собирает render-параметры из DisplaySpec и передаёт в open_for_display.
Персистентность — recipe-scoped через store.persist() (пишет в активный рецепт).

Refs: plans/displays-in-recipe/plan.md Task 2.3, 5.2
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from multiprocess_prototype.domain.protocols.display_catalog import (
    DisplayCatalog,
    DisplaySpec,
)

if TYPE_CHECKING:
    from multiprocess_prototype.domain.event_bus import _Subscription
    from multiprocess_prototype.domain.events import RecipeActivated
    from multiprocess_prototype.frontend.widgets.displays.preview_manager import (
        PreviewWindowManager,
    )

    from .view import IDisplaysView

logger = logging.getLogger(__name__)


class DisplaysPresenter:
    """Presenter для DisplaysTab.

    Содержит всю бизнес-логику работы с реестром дисплеев.
    View получает обновления только через методы IDisplaysView.

    Подписка на RecipeActivated:
        После создания presenter'а вызвать ``bind_event_bus(bus, window_manager)``
        для подключения к событийной шине. Presenter сам отписывается при teardown
        (явный вызов ``teardown()`` или удаление через GC).

    Attributes:
        _store: DisplayCatalog Protocol (read+write store).
        _view: ссылка на view (IDisplaysView protocol).
        _preview_callback: вызывается при on_open_preview.
        _selected_id: текущий выбранный id дисплея.
        _window_manager: реестр окон превью (PreviewWindowManager), может быть None.
        _recipe_sub: подписка на RecipeActivated (для отписки при teardown).
        _router_manager: RouterManager для переподписки окон (runtime-зависимость).
    """

    def __init__(
        self,
        store: DisplayCatalog,
        view: "IDisplaysView",
        preview_callback: Callable[[DisplaySpec], None] | None = None,
    ) -> None:
        """Инициализировать presenter.

        Args:
            store: DisplayCatalog Protocol (read+write).
            view: реализация IDisplaysView.
            preview_callback: опциональный callback для открытия превью.
        """
        self._store = store
        self._view = view
        self._preview_callback = preview_callback
        self._selected_id: str | None = None

        # Подписка на RecipeActivated (устанавливается через bind_event_bus)
        self._recipe_sub: "_Subscription | None" = None
        self._window_manager: "PreviewWindowManager | None" = None
        # RouterManager для переподписки окон при смене рецепта
        self._router_manager: object | None = None

    # ------------------------------------------------------------------ #
    #  Event bus binding (Task 2.3)                                       #
    # ------------------------------------------------------------------ #

    def bind_event_bus(
        self,
        event_bus: object,
        window_manager: "PreviewWindowManager | None" = None,
        router_manager: object | None = None,
    ) -> None:
        """Подписаться на RecipeActivated через EventBus.

        Должен вызываться один раз после создания presenter'а (из tab/фабрики).
        Повторный вызов отписывает предыдущую подписку и создаёт новую.

        Args:
            event_bus:      EventBusProtocol (services.events) — pure Python, без Qt.
            window_manager: реестр открытых окон превью (PreviewWindowManager).
                            None → управление окнами отключено.
            router_manager: RouterManager для переподписки окон при смене рецепта.
                            None → subscribe(None) вызывает graceful no-op в PreviewWindow.
        """
        from multiprocess_prototype.domain.events import RecipeActivated

        # Снять старую подписку при повторном вызове
        if self._recipe_sub is not None:
            try:
                self._recipe_sub.unsubscribe()
            except Exception:
                logger.exception("DisplaysPresenter: ошибка отписки RecipeActivated")
            self._recipe_sub = None

        self._window_manager = window_manager
        self._router_manager = router_manager

        subscribe = getattr(event_bus, "subscribe", None)
        if subscribe is None:
            logger.warning(
                "DisplaysPresenter.bind_event_bus: объект %r не имеет метода subscribe",
                event_bus,
            )
            return

        self._recipe_sub = subscribe(RecipeActivated, self._on_recipe_activated)
        logger.debug("DisplaysPresenter: подписан на RecipeActivated")

    def teardown(self) -> None:
        """Отписаться от EventBus и закрыть все окна превью.

        Вызывается при закрытии вкладки (tab.closeEvent / сборщик мусора).
        Idempotent — повторные вызовы безопасны.
        """
        if self._recipe_sub is not None:
            try:
                self._recipe_sub.unsubscribe()
            except Exception:
                logger.exception("DisplaysPresenter: ошибка отписки RecipeActivated при teardown")
            self._recipe_sub = None

        if self._window_manager is not None:
            try:
                self._window_manager.close_all()
            except Exception:
                logger.exception("DisplaysPresenter: ошибка закрытия окон при teardown")
            self._window_manager = None

        logger.debug("DisplaysPresenter: teardown выполнен")

    # ------------------------------------------------------------------ #
    #  Обработчик RecipeActivated                                         #
    # ------------------------------------------------------------------ #

    def _on_recipe_activated(self, event: "RecipeActivated") -> None:
        """Обработать смену активного рецепта.

        Порядок действий:
          1. Перечитать store через load() → view.refresh_list получает актуальные дисплеи.
          2. Управление окнами превью (вариант А, раздел 11.4 спеки):
             - orphan-окна (id нет в новом реестре) → закрыть;
             - совпадающие id → переподключить (unsubscribe + subscribe с новым RouterManager).

        Args:
            event: RecipeActivated с полем slug (не используется напрямую —
                   store уже наполнен backend'ом в apply_topology).
        """
        logger.info(
            "DisplaysPresenter: RecipeActivated slug='%s', перечитываю реестр",
            event.slug,
        )

        # Шаг 1: перечитать список дисплеев нового рецепта
        self.load()

        # Шаг 2: управление окнами превью (вариант А)
        if self._window_manager is not None:
            # Получаем id дисплеев нового рецепта из store
            new_ids: set[str] = {spec.display_id for spec in self._store.list_displays()}
            self._window_manager.apply_recipe_change(
                new_display_ids=new_ids,
                router_manager=self._router_manager,  # type: ignore[arg-type]
            )

    # ------------------------------------------------------------------ #
    #  Загрузка                                                            #
    # ------------------------------------------------------------------ #

    def load(self) -> None:
        """Загрузить дисплеи из store и обновить список в view.

        Сбрасывает выбор (set_buttons_state -> False).
        """
        specs = list(self._store.list_displays())
        self._view.refresh_list(specs)
        self._view.set_buttons_state(False)
        self._selected_id = None

    # ------------------------------------------------------------------ #
    #  Selection                                                           #
    # ------------------------------------------------------------------ #

    def on_select(self, display_id: str | None) -> None:
        """Обработать выбор записи в nav-списке.

        Args:
            display_id: id выбранного дисплея или None при снятии выбора.
        """
        self._selected_id = display_id
        if display_id is None:
            self._view.show_entry(None)
            self._view.set_buttons_state(False)
            return
        spec = self._store.resolve(display_id)
        self._view.show_entry(spec)
        self._view.set_buttons_state(True)

    # ------------------------------------------------------------------ #
    #  CRUD                                                                #
    # ------------------------------------------------------------------ #

    def on_create(self) -> None:
        """Создать новый дисплей из данных формы.

        Читает view.get_form_data(), строит DisplaySpec (включая render-поля),
        регистрирует через store, сохраняет в рецепт, обновляет список.
        При ValueError — показывает ошибку через view.show_error().
        """
        data = self._view.get_form_data()

        display_id = data.get("id", "").strip()
        if not display_id:
            self._view.show_error("Поле 'ID' не может быть пустым.")
            return

        try:
            spec = DisplaySpec(
                display_id=display_id,
                display_name=data.get("name", display_id),
                width=int(data.get("width", 1280)),
                height=int(data.get("height", 720)),
                format=str(data.get("format", "BGR")),
                fps_limit=float(data.get("fps_limit", 30.0)),
                ring_buffer_blocks=int(data.get("ring_buffer_blocks", 3)),
                # Render-поля (Task 5.2)
                position=data.get("position", {"x": 0, "y": 0}),
                fit=str(data.get("fit", "contain")),
                scale=int(data.get("scale", 100)),
                rotate=int(data.get("rotate", 0)),
                flip=str(data.get("flip", "none")),
                crop=data.get("crop"),
            )
        except (TypeError, ValueError) as exc:
            self._view.show_error(f"Некорректные данные формы: {exc}")
            return

        try:
            self._store.register(spec)
        except ValueError as exc:
            self._view.show_error(str(exc))
            return

        self._persist()
        self._view.refresh_list(list(self._store.list_displays()))
        logger.info("DisplaysPresenter: создан дисплей '%s'", display_id)

    def on_delete(self, display_id: str) -> None:
        """Удалить дисплей из store.

        Args:
            display_id: id дисплея для удаления.
        """
        removed = self._store.unregister(display_id)
        if not removed:
            logger.warning("DisplaysPresenter: дисплей '%s' не найден для удаления", display_id)
            return

        self._persist()
        self._selected_id = None
        self._view.refresh_list(list(self._store.list_displays()))
        self._view.show_entry(None)
        self._view.set_buttons_state(False)
        logger.info("DisplaysPresenter: удалён дисплей '%s'", display_id)

    def on_duplicate(self, display_id: str) -> None:
        """Дублировать дисплей с суффиксом _copy (или _copy2, _copy3 ...).

        Копирует все поля включая render-параметры.
        Если id уже занят — перебирает _copy2, _copy3 и т.д.

        Args:
            display_id: id исходного дисплея.
        """
        source = self._store.resolve(display_id)
        if source is None:
            logger.warning("DisplaysPresenter: дисплей '%s' не найден для дублирования", display_id)
            return

        # Генерируем уникальный id с суффиксом _copy / _copy2 / ...
        new_id = self._generate_copy_id(display_id)

        new_spec = DisplaySpec(
            display_id=new_id,
            display_name=f"{source.display_name} (копия)",
            width=source.width,
            height=source.height,
            format=source.format,
            fps_limit=source.fps_limit,
            ring_buffer_blocks=source.ring_buffer_blocks,
            # Render-поля копируются из source (Task 5.2)
            position=dict(source.position) if source.position else {"x": 0, "y": 0},
            fit=source.fit,
            scale=source.scale,
            rotate=source.rotate,
            flip=source.flip,
            crop=dict(source.crop) if source.crop else None,
        )

        try:
            self._store.register(new_spec)
        except ValueError as exc:
            # Теоретически невозможно — id уже проверен, но на всякий случай
            self._view.show_error(str(exc))
            return

        self._persist()
        self._view.refresh_list(list(self._store.list_displays()))
        logger.info("DisplaysPresenter: дублирован '%s' -> '%s'", display_id, new_id)

    def on_open_preview(self, display_id: str) -> None:
        """Открыть превью канала дисплея.

        Args:
            display_id: id дисплея для превью.
        """
        spec = self._store.resolve(display_id)
        if spec is None:
            logger.warning("DisplaysPresenter: дисплей '%s' не найден для превью", display_id)
            return

        if self._preview_callback is not None:
            self._preview_callback(spec)
        else:
            logger.info("DisplaysPresenter: открыть превью '%s' (заглушка Phase 4)", display_id)

    # ------------------------------------------------------------------ #
    #  Вспомогательные методы                                              #
    # ------------------------------------------------------------------ #

    def _generate_copy_id(self, source_id: str) -> str:
        """Сгенерировать уникальный id-копии для дублирования.

        Перебирает _copy, _copy2, _copy3 ... до нахождения незанятого id.

        Args:
            source_id: id оригинального дисплея.

        Returns:
            Первый свободный id с суффиксом _copy / _copy2 / ...
        """
        candidate = f"{source_id}_copy"
        if not self._store.has(candidate):
            return candidate

        counter = 2
        while True:
            candidate = f"{source_id}_copy{counter}"
            if not self._store.has(candidate):
                return candidate
            counter += 1

    def _persist(self) -> None:
        """Сохранить store в YAML. Логирует ошибку при исключении."""
        try:
            self._store.persist()
        except Exception as exc:
            logger.error("DisplaysPresenter: ошибка сохранения YAML: %s", exc)
