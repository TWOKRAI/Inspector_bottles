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


from PySide6.QtWidgets import (
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from multiprocess_framework.modules.frontend_module.widgets.tabs import BaseListNavTab
from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.frontend.runtime_deps import RuntimeDeps
from multiprocess_prototype.frontend.widgets.primitives.diff_scroll_tab_layout import DiffScrollTabLayout

from .presenter import RecipesPresenter
from .recipe_form import RecipeFormWidget


def _layout_factory() -> DiffScrollTabLayout:
    """Фабрика layout для RecipesTab.

    Размеры колонок согласованы с DisplaysTab / SettingsTab.
    """
    return DiffScrollTabLayout(title="Рецепты", action_width=160, nav_width=230)


class RecipesTab(BaseListNavTab):
    """Таб «Рецепты» v2 — BaseListNavTab + MVP (RecipesPresenter + IRecipesView).

    Task E.3: мигрирован на AppServices DI. Принимает ``services: AppServices``.
    Task F.4: presenter работает через RecipeStore Protocol (services.recipes).
    Bridge ``services.recipes._rm`` убран — RecipeStore Protocol покрывает
    read_raw/save_raw/duplicate/deactivate/set_active->bool.

    Реализует IRecipesView через structural subtyping:
    ``isinstance(tab, IRecipesView)`` → True без явного наследования.

    Nav-колонка: динамический список slug'ов рецептов из RecipeStore.list().
    Content-колонка: RecipeFormWidget с метаданными + сводкой blueprint.
    Action-колонка: кнопки CRUD + «Открыть в Pipeline» (disabled).
    """

    def __init__(
        self,
        services: AppServices,
        *,
        process_manager_proxy: object | None = None,
        persist_active_fn: object | None = None,
        command_sender: object | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Инициализировать таб рецептов.

        Args:
            services: типизированный DI-контейнер AppServices.
            process_manager_proxy: IPC-фасад управления живым backend (Этап 1).
                None → активация рецепта только меняет state, без применения к backend.
            persist_active_fn: колбэк persist активного рецепта в манифест (app.yaml).
                None → persist отключён (активация не пишет app.yaml).
            command_sender: CommandSender для IPC-вызовов к процессам (device_upsert_many).
                None → upsert устройств при активации рецепта пропускается.
            parent: родительский виджет.
        """
        self._services = services
        self._pm_proxy = process_manager_proxy
        self._persist_active_fn = persist_active_fn
        self._command_sender = command_sender
        self._selected_slug: str | None = None
        self._form_stack_index: int = 0

        super().__init__(
            title="Рецепты",
            ctx=None,  # type: ignore[arg-type]  # framework generic-слот, прототип не использует ctx
            layout_factory=_layout_factory,
            parent=parent,
        )

        # Форма создаётся после super().__init__ (Qt-виджеты готовы)
        self._form_widget = RecipeFormWidget()
        self._form_stack_index = self._content_stack.addWidget(self._form_widget)
        self._content_stack.setCurrentIndex(self._form_stack_index)

        self._setup_actions()

        # Presenter инициализируется после UI (view уже готов).
        # Task F.4: presenter работает через RecipeStore Protocol (services.recipes).
        self._presenter: RecipesPresenter | None = None

        if services.recipes is None:
            # Защитная проверка (AppServices.recipes не должен быть None, но на всякий случай)
            _unavailable_label = QLabel("RecipeStore недоступен")
            _unavailable_label.setStyleSheet("color: gray; font-style: italic;")
            self._content_stack.addWidget(_unavailable_label)
            self._content_stack.setCurrentWidget(_unavailable_label)
            self._create_btn.setEnabled(False)
        else:
            # Task 2.1 topology-switch-hardening: «Загрузить» применяет рецепт через
            # proxy.apply_topology(source, on_result) — async request/response
            # (command-result-bridge): presenter получает РЕАЛЬНЫЙ результат PM
            # (success/rolled_back/debounced) и откатывает активацию при провале.
            # Прежний fire-and-forget (optimistic-ack) прятал rollback и debounce.
            # None → graceful: только set_active без перезапуска процессов.
            _apply_fn = (
                self._pm_proxy.apply_topology
                if self._pm_proxy is not None and hasattr(self._pm_proxy, "apply_topology")
                else None
            )
            # Фаза 3 device-hub: upsert устройств рецепта ДО apply_topology.
            # send_action_command — fire-and-forget из Qt main-thread (не блокирует UI).
            # Устройства появятся в devices-процессе асинхронно; robot_io переживёт
            # первые секунды через forward-deque до появления соединения.
            _upsert_fn = self._build_upsert_devices_fn() if self._command_sender is not None else None

            self._presenter = RecipesPresenter(
                store=services.recipes,
                view=self,
                apply_topology_fn=_apply_fn,
                commands=services.commands,  # G.6.5: активация → dispatch(ActivateRecipe)
                topology_store=services.topology,  # Этап 1: «Сохранить» (живой граф → рецепт)
                persist_active_fn=self._persist_active_fn,  # persist #1: активный slug → app.yaml
                upsert_devices_fn=_upsert_fn,  # Фаза 3 device-hub: upsert устройств рецепта
            )
            self._presenter.load()

    # ------------------------------------------------------------------ #
    #  Фабричный метод                                                     #
    # ------------------------------------------------------------------ #

    @classmethod
    def create(
        cls,
        services: AppServices,
        runtime: RuntimeDeps = RuntimeDeps(),
    ) -> "RecipesTab":
        """Фабричный метод для register_all_tabs() / TabFactory.

        Task F.9: принимает AppServices + RuntimeDeps (Q-F1=B).
        Этап 1: process_manager_proxy — применение рецепта к живому backend.
        Фаза 3 device-hub: command_sender — upsert устройств рецепта в devices.
        """
        return cls(
            services,
            process_manager_proxy=runtime.process_manager_proxy,
            persist_active_fn=runtime.persist_active_recipe,
            command_sender=runtime.command_sender,
        )

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
        # «Загрузить» и «Сохранить» — enabled при любом выборе. Загрузить можно
        # повторно (re-apply к backend), даже если рецепт уже активен (is_active
        # больше не блокирует — кнопка теперь про runtime-применение, не про метку).
        self._activate_btn.setEnabled(has_selection)
        self._save_btn.setEnabled(has_selection)

    def show_active_recipe(self, slug: str | None) -> None:
        """Показать в шапке action-колонки активный (загруженный) рецепт.

        Args:
            slug: slug активного рецепта или None.
        """
        self._active_label.setText(f"Активен: {slug}" if slug else "Активен: —")

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

    def set_switch_busy(self, busy: bool) -> None:
        """Busy-состояние применения рецепта (IRecipesView).

        На время async topology.apply кнопка «Загрузить» блокируется и
        показывает прогресс — защита от двойного клика (backend дебаунсит
        молча, здесь пользователь видит, что замена идёт).

        Args:
            busy: True — переключение в полёте.
        """
        if busy:
            self._activate_btn.setEnabled(False)
            self._activate_btn.setText("Применяется…")
        else:
            self._activate_btn.setText("Загрузить")
            # enabled восстановит set_buttons_state (load() после результата)

    # ------------------------------------------------------------------ #
    #  Построение UI — action-колонка                                      #
    # ------------------------------------------------------------------ #

    def _setup_actions(self) -> None:
        """Создать action-кнопки в левой колонке layout'а."""
        action_widget = QWidget()
        action_layout = QVBoxLayout(action_widget)
        action_layout.setContentsMargins(4, 4, 4, 4)
        action_layout.setSpacing(6)

        # Индикатор активного рецепта (какой сейчас загружен в систему).
        # Обновляется presenter'ом через show_active_recipe при load/активации.
        self._active_label = QLabel("Активен: —")
        self._active_label.setWordWrap(True)
        self._active_label.setStyleSheet("font-weight: bold; padding: 2px 0;")
        self._active_label.setToolTip("Рецепт, загруженный в работающую систему")
        action_layout.addWidget(self._active_label)

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

        # Загрузить — активировать рецепт И применить к живому backend (Этап 1).
        # Раньше «Сделать активным»; переименовано — кнопка реально грузит рецепт
        # в систему (apply_topology через proxy), а не только метит активным.
        self._activate_btn = QPushButton("Загрузить")
        self._activate_btn.setToolTip("Загрузить рецепт: активировать и применить к работающей системе")
        self._activate_btn.setEnabled(False)
        self._activate_btn.clicked.connect(self._on_activate_clicked)
        action_layout.addWidget(self._activate_btn)

        # Сохранить — записать текущую живую топологию (services.topology) в выбранный рецепт.
        self._save_btn = QPushButton("Сохранить")
        self._save_btn.setToolTip("Сохранить текущий граф системы в выбранный рецепт")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._on_save_clicked)
        action_layout.addWidget(self._save_btn)

        # Открыть в Pipeline — постоянно disabled (Task 7a)
        self._pipeline_btn = QPushButton("Открыть в Pipeline")
        self._pipeline_btn.setToolTip("Task 7a — будет реализовано позже")
        self._pipeline_btn.setEnabled(False)
        action_layout.addWidget(self._pipeline_btn)

        action_layout.addStretch(1)
        self._tab_layout.set_action_widget(action_widget)

    # ------------------------------------------------------------------ #
    #  Device upsert helper (Фаза 3 device-hub)                           #
    # ------------------------------------------------------------------ #

    def _build_upsert_devices_fn(self):
        """Построить callback для upsert устройств рецепта в процесс devices.

        Вызывается из on_set_active (presenter) в Qt main-thread. Использует
        send_action_command — fire-and-forget (не блокирует UI). Команда
        device_sync_set обрабатывается в supervisor-воркере devices-процесса
        асинхронно; connect произойдёт после разбора очереди supervisor'ом.

        Фаза B device-tree-recipe: рецепт — источник истины, поэтому активация
        — полная синхронизация (device_sync_set): upsert набора рецепта +
        remove чужих recipe-устройств от предыдущего рецепта. Manual-устройства
        не трогаются.

        Returns:
            Callable[[list[dict], str], None] — upsert_devices_fn.
        """
        sender = self._command_sender

        def _upsert(devices: list[dict], slug: str) -> None:
            if sender is None:
                return
            sender.send_action_command(
                "devices",
                "device_sync_set",
                {"devices": devices, "origin": f"recipe:{slug}", "connect": True},
            )

        return _upsert

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
        """Обработать нажатие «Загрузить» (активировать + применить к backend)."""
        if self._presenter is None:
            return
        self._presenter.on_set_active(self._selected_slug)

    def _on_save_clicked(self) -> None:
        """Обработать нажатие «Сохранить» (живой граф → выбранный рецепт)."""
        if self._presenter is None:
            return
        if self._presenter.on_save(self._selected_slug):
            QMessageBox.information(self, "Сохранение рецепта", f"Рецепт сохранён: {self._selected_slug}")
