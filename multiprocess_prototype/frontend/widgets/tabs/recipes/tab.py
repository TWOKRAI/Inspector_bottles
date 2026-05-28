# -*- coding: utf-8 -*-
"""RecipesTab — таб управления рецептами (MVP pattern).

Реализует IRecipesView через structural subtyping (runtime_checkable Protocol).
Использует BaseListNavTab: QListWidget (nav) + RecipeFormWidget (content).

Структура колонок (DiffScrollTabLayout):
    Action (160px): кнопки Создать / Дублировать / Удалить / Сделать активным /
                    Открыть в Pipeline (disabled — Task 7a).
    Nav    (230px): динамический список slug'ов рецептов.
    Content       : RecipeFormWidget с метаданными + сводкой blueprint.

Refs: plans/prototype-skeleton-2026-05/phase-5-recipes-manager-v2.md Task 5.7
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from multiprocess_framework.modules.frontend_module.widgets.tabs import BaseListNavTab
from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.frontend.widgets.primitives.diff_scroll_tab_layout import DiffScrollTabLayout

from .presenter import RecipesPresenter
from .recipe_form import RecipeFormWidget

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext


def _layout_factory() -> DiffScrollTabLayout:
    """Фабрика layout для RecipesTab.

    Размеры колонок согласованы с DisplaysTab / SettingsTab.
    """
    return DiffScrollTabLayout(title="Рецепты", action_width=160, nav_width=230)


class RecipesTab(BaseListNavTab):
    """Таб «Рецепты» v2 — BaseListNavTab + MVP (RecipesPresenter + IRecipesView).

    Task E.3: мигрирован на AppServices DI. Принимает ``services: AppServices``.
    RecipeManager берётся через ``services.recipes._rm`` bridge — RecipeStore
    Protocol не покрывает богатый legacy API (read_recipe→dict, duplicate,
    recipes_dir, replace_blueprint). TODO Phase F: расширить RecipeStore Protocol.

    Реализует IRecipesView через structural subtyping:
    ``isinstance(tab, IRecipesView)`` → True без явного наследования.

    Nav-колонка: динамический список slug'ов рецептов из RecipeManager.list().
    Content-колонка: RecipeFormWidget с метаданными + сводкой blueprint.
    Action-колонка: кнопки CRUD + «Открыть в Pipeline» (disabled).
    """

    def __init__(
        self,
        services: AppServices,
        *,
        parent: QWidget | None = None,
    ) -> None:
        """Инициализировать таб рецептов.

        Args:
            services: типизированный DI-контейнер AppServices.
            parent: родительский виджет.
        """
        self._services = services
        self._selected_slug: str | None = None
        self._form_stack_index: int = 0

        super().__init__(
            title="Рецепты",
            ctx=None,  # type: ignore[arg-type]  # BaseListNavTab legacy параметр (Phase F удалит)
            layout_factory=_layout_factory,
            parent=parent,
        )

        # Форма создаётся после super().__init__ (Qt-виджеты готовы)
        self._form_widget = RecipeFormWidget()
        self._form_stack_index = self._content_stack.addWidget(self._form_widget)
        self._content_stack.setCurrentIndex(self._form_stack_index)

        self._setup_actions()

        # Presenter инициализируется после UI (view уже готов).
        # Если recipe_manager недоступен — показываем сообщение и не создаём presenter.
        # TODO Phase F: RecipeStore Protocol не покрывает read_recipe→dict / duplicate /
        # recipes_dir — presenter работает с legacy RecipeManager через _rm bridge.
        recipe_manager = getattr(services.recipes, "_rm", None)
        self._presenter: RecipesPresenter | None = None

        if recipe_manager is None:
            # Показываем информационное сообщение в content-области
            _unavailable_label = QLabel("RecipeManager недоступен")
            _unavailable_label.setStyleSheet("color: gray; font-style: italic;")
            self._content_stack.addWidget(_unavailable_label)
            self._content_stack.setCurrentWidget(_unavailable_label)
            # Все кнопки CRUD остаются disabled (уже по умолчанию disabled кроме «Создать»)
            self._create_btn.setEnabled(False)
        else:
            self._presenter = RecipesPresenter(
                recipe_manager=recipe_manager,
                view=self,
            )
            self._presenter.load()

    # ------------------------------------------------------------------ #
    #  Фабричный метод                                                     #
    # ------------------------------------------------------------------ #

    @classmethod
    def create(cls, ctx: "AppContext") -> "RecipesTab":
        """Адаптер для TabFactory — принимает AppContext, извлекает AppServices.

        Phase F заменит AppContext на AppServices напрямую в register_all_tabs().

        Args:
            ctx: контекст приложения (AppContext).

        Returns:
            Полностью инициализированный RecipesTab с загруженными данными.
        """
        assert ctx.app_services is not None, (
            "AppServices не инициализирован в ctx. Убедитесь что Task D.1 factory вызван в run_gui()."
        )
        return cls(ctx.app_services)

    # ------------------------------------------------------------------ #
    #  BaseListNavTab hooks                                                #
    # ------------------------------------------------------------------ #

    def _create_item_widget(self, key: str) -> QWidget:
        """Создать content-виджет для записи рецепта.

        Все записи используют одну общую форму (_form_widget).
        Заглушка QWidget используется как placeholder в content_stack.
        """
        return QWidget()

    def _on_nav_changed(self, key: str) -> None:
        """Реагировать на смену выбора в nav-списке.

        Args:
            key: slug выбранного рецепта.
        """
        self._selected_slug = key
        # Всегда показываем форму
        self._content_stack.setCurrentIndex(self._form_stack_index)
        self.item_selected.emit(key)
        self.section_changed.emit(key)
        if self._presenter is not None:
            self._presenter.on_select(key)

    # ------------------------------------------------------------------ #
    #  IRecipesView implementation                                         #
    # ------------------------------------------------------------------ #

    def refresh_list(self, slugs: list[str]) -> None:
        """Перестроить nav-список по slug'ам рецептов.

        Очищает nav-список и заглушки в content_stack (не форму!),
        добавляет каждый slug через add_item.

        Args:
            slugs: актуальный список slug'ов из RecipeManager.list().
        """
        assert self._nav_widget is not None

        # Блокируем сигналы nav-виджета на время перестройки
        self._nav_widget.blockSignals(True)
        self._nav_widget.clear()
        self._key_to_item.clear()

        # Удаляем заглушки из content_stack, форму сохраняем
        for key in list(self._key_to_index.keys()):
            idx = self._key_to_index.pop(key, None)
            if idx is None:
                continue
            w = self._content_stack.widget(idx)
            if w is not None and w is not self._form_widget:
                self._content_stack.removeWidget(w)
                w.deleteLater()

        # Восстанавливаем форму как текущую страницу
        self._form_stack_index = self._content_stack.indexOf(self._form_widget)
        if self._form_stack_index < 0:
            self._form_stack_index = self._content_stack.addWidget(self._form_widget)
        self._content_stack.setCurrentIndex(self._form_stack_index)

        self._nav_widget.blockSignals(False)

        for slug in slugs:
            self.add_item(slug, slug)

        self._selected_slug = None

    def show_recipe(self, slug: str | None, data: dict | None) -> None:
        """Заполнить форму данными рецепта или очистить при None.

        Args:
            slug: имя рецепта (для отображения).
            data: dict с YAML-данными рецепта v2 или None для сброса.
        """
        if slug is None or data is None:
            self._form_widget.clear()
        else:
            self._form_widget.populate(slug, data)

    def set_buttons_state(self, has_selection: bool, is_active: bool) -> None:
        """Включить/выключить кнопки мутации.

        Args:
            has_selection: True → Дублировать/Удалить/Активировать активны.
            is_active: True → «Сделать активным» disabled (уже активен).
        """
        self._duplicate_btn.setEnabled(has_selection)
        self._delete_btn.setEnabled(has_selection)
        # «Сделать активным» — enabled если есть выбор И рецепт ещё не активен
        self._activate_btn.setEnabled(has_selection and not is_active)

    def confirm_delete(self, slug: str) -> bool:
        """Показать диалог подтверждения удаления.

        Args:
            slug: имя рецепта для удаления.

        Returns:
            True если пользователь подтвердил.
        """
        reply = QMessageBox.question(
            self,
            "Удаление рецепта",
            f"Удалить рецепт '{slug}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def show_error(self, message: str) -> None:
        """Показать диалог с сообщением об ошибке.

        Args:
            message: текст ошибки.
        """
        QMessageBox.warning(self, "Ошибка", message)

    # ------------------------------------------------------------------ #
    #  Построение UI — action-колонка                                      #
    # ------------------------------------------------------------------ #

    def _setup_actions(self) -> None:
        """Создать action-кнопки в левой колонке layout'а."""
        action_widget = QWidget()
        action_layout = QVBoxLayout(action_widget)
        action_layout.setContentsMargins(4, 4, 4, 4)
        action_layout.setSpacing(6)

        # Создать — всегда активна
        self._create_btn = QPushButton("Создать")
        self._create_btn.setToolTip("Создать новый рецепт")
        self._create_btn.clicked.connect(self._on_create_clicked)
        action_layout.addWidget(self._create_btn)

        # Дублировать — disabled без выбора
        self._duplicate_btn = QPushButton("Дублировать")
        self._duplicate_btn.setToolTip("Дублировать выбранный рецепт")
        self._duplicate_btn.setEnabled(False)
        self._duplicate_btn.clicked.connect(self._on_duplicate_clicked)
        action_layout.addWidget(self._duplicate_btn)

        # Удалить — disabled без выбора
        self._delete_btn = QPushButton("Удалить")
        self._delete_btn.setToolTip("Удалить выбранный рецепт")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        action_layout.addWidget(self._delete_btn)

        # Сделать активным — disabled без выбора
        self._activate_btn = QPushButton("Сделать активным")
        self._activate_btn.setToolTip("Применить рецепт как активный")
        self._activate_btn.setEnabled(False)
        self._activate_btn.clicked.connect(self._on_activate_clicked)
        action_layout.addWidget(self._activate_btn)

        # Открыть в Pipeline — постоянно disabled (Task 7a)
        self._pipeline_btn = QPushButton("Открыть в Pipeline")
        self._pipeline_btn.setToolTip("Task 7a — будет реализовано позже")
        self._pipeline_btn.setEnabled(False)
        action_layout.addWidget(self._pipeline_btn)

        action_layout.addStretch(1)
        self._tab_layout.set_action_widget(action_widget)

    # ------------------------------------------------------------------ #
    #  Button handlers                                                     #
    # ------------------------------------------------------------------ #

    def _on_create_clicked(self) -> None:
        """Обработать нажатие «Создать»."""
        if self._presenter is None:
            return
        form_data = self._form_widget.get_form_data()
        name = form_data.get("name", "").strip()
        description = form_data.get("description", "").strip()
        if not name:
            name = "Новый рецепт"
        self._presenter.on_create(name, description)

    def _on_duplicate_clicked(self) -> None:
        """Обработать нажатие «Дублировать»."""
        if self._presenter is None:
            return
        self._presenter.on_duplicate(self._selected_slug)

    def _on_delete_clicked(self) -> None:
        """Обработать нажатие «Удалить»."""
        if self._presenter is None:
            return
        self._presenter.on_delete(self._selected_slug)

    def _on_activate_clicked(self) -> None:
        """Обработать нажатие «Сделать активным»."""
        if self._presenter is None:
            return
        self._presenter.on_set_active(self._selected_slug)
