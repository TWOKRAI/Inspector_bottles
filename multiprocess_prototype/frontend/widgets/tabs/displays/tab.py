# -*- coding: utf-8 -*-
"""DisplaysTab v2 — CRUD-таб управления дисплеями (MVP pattern).

Task E.6 + F.3: мигрирован на AppServices DI. Принимает ``services: AppServices``.
DisplayCatalog Protocol (domain) покрывает полный read+write API (Phase F).
Presenter получает ``store=services.displays`` без bridge.

router_manager (превью SHM-канала) — runtime-объект вне AppServices, передаётся
explicit-параметром (паттерн E.2/E.5).

Реализует IDisplaysView через structural subtyping (без явного наследования).
Использует BaseListNavTab: QListWidget слева + content-форма справа.

Форма (правая панель):
    - id (QLineEdit, read-only при выборе существующего)
    - name (QLineEdit)
    - width / height (QSpinBox, 1..7680)
    - format (QComboBox: BGR/RGB/GRAY/RGBA)
    - fps_limit (QDoubleSpinBox, 0.0..240.0)
    - ring_buffer_blocks (QSpinBox, 1..32)

Кнопки (action-колонка):
    - «Создать» — всегда активна (при наличии permission)
    - «Удалить» — disabled без выбора
    - «Дублировать» — disabled без выбора
    - «Открыть превью» — disabled без выбора

Архитектурная заметка:
    BaseListNavTab управляет content_stack через add_item/remove_item.
    DisplaysTab использует одну общую форму (_form_widget) как content для
    всех записей: _create_item_widget возвращает QWidget-заглушку, а
    refresh_list вставляет форму в content_scroll напрямую через
    _tab_layout.set_content_widget — но только один раз (форма singleton).
    Повторная перезапись не нужна, форма остаётся в content_scroll.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from multiprocess_framework.modules.frontend_module.widgets.tabs import BaseListNavTab
from multiprocess_prototype.domain.app_services import AppServices
from multiprocess_prototype.domain.protocols.display_catalog import DisplaySpec
from multiprocess_prototype.frontend.widgets.primitives.diff_scroll_tab_layout import (
    DiffScrollTabLayout,
)

from .presenter import DisplaysPresenter

if TYPE_CHECKING:
    from multiprocess_prototype.frontend.app_context import AppContext

logger = logging.getLogger(__name__)

# Допустимые форматы пикселей
_PIXEL_FORMATS = ["BGR", "RGB", "GRAY", "RGBA"]


def _layout_factory() -> DiffScrollTabLayout:
    """Фабрика layout для DisplaysTab.

    Размеры колонок согласованы с Recipes/Processes/Services.
    """
    return DiffScrollTabLayout(title="Дисплеи", action_width=160, nav_width=230)


class DisplaysTab(BaseListNavTab):
    """Таб «Дисплеи» v2 — BaseListNavTab + MVP (DisplaysPresenter + IDisplaysView).

    Реализует IDisplaysView через structural subtyping:
    ``isinstance(tab, IDisplaysView)`` -> True без явного наследования.

    Левая панель: QListWidget с именами дисплеев из DisplayCatalog.
    Правая панель: форма редактирования полей DisplaySpec.
    Action-колонка: кнопки Создать / Удалить / Дублировать / Открыть превью.
    """

    def __init__(
        self,
        services: AppServices,
        *,
        router_manager: object | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Инициализировать таб дисплеев.

        Args:
            services: типизированный DI-контейнер AppServices.
            router_manager: RouterManager для превью SHM-канала (runtime-объект вне
                AppServices, по умолчанию None — превью без подписки).
            parent: родительский виджет.
        """
        self._services = services
        self._router_manager = router_manager
        self._selected_id: str | None = None
        # Индекс формы в content_stack (устанавливается после super().__init__)
        self._form_stack_index: int = 0

        super().__init__(
            title="Дисплеи",
            ctx=None,  # type: ignore[arg-type]  # BaseListNavTab legacy параметр (Phase F удалит)
            layout_factory=_layout_factory,
            parent=parent,
        )

        # Форма создаётся после super().__init__ (Qt-виджеты готовы)
        self._build_form()
        # Добавляем форму в content_stack как страницу с индексом 0
        # Это обеспечивает правильный parent и Qt lifecycle
        self._form_stack_index = self._content_stack.addWidget(self._form_widget)
        self._content_stack.setCurrentIndex(self._form_stack_index)

        self._setup_actions()

        # Список открытых окон превью (PreviewWindow) — предотвращаем GC
        self._preview_windows: list = []

        # Presenter получает store=services.displays (DisplayCatalog Protocol)
        self._presenter = DisplaysPresenter(
            store=services.displays,
            view=self,
            preview_callback=self._open_preview_window,
        )
        self._presenter.load()

    # ------------------------------------------------------------------ #
    #  Фабричный метод                                                     #
    # ------------------------------------------------------------------ #

    @classmethod
    def create(cls, ctx: "AppContext") -> "DisplaysTab":
        """Адаптер для TabFactory — принимает AppContext, извлекает AppServices.

        Phase F заменит AppContext на AppServices напрямую в register_all_tabs().

        Args:
            ctx: контекст приложения (AppContext).

        Returns:
            Полностью инициализированный DisplaysTab с загруженными данными.
        """
        assert ctx.app_services is not None, (
            "AppServices не инициализирован в ctx. Убедитесь что Task D.1 factory вызван в run_gui()."
        )
        return cls(ctx.app_services)

    # ------------------------------------------------------------------ #
    #  BaseListNavTab hooks                                                #
    # ------------------------------------------------------------------ #

    def _create_item_widget(self, key: str) -> QWidget:
        """Создать content-виджет для записи дисплея.

        Все записи используют одну общую форму (_form_widget), которая
        размещена в content_scroll напрямую. Заглушки здесь не отображаются.
        """
        return QWidget()

    def _on_nav_changed(self, key: str) -> None:
        """Реагировать на смену выбора в nav-списке.

        Всегда показывает форму (_form_widget) в content_stack.

        Args:
            key: id выбранного дисплея.
        """
        self._selected_id = key
        # Всегда переключаемся на страницу с формой
        self._content_stack.setCurrentIndex(self._form_stack_index)
        self.item_selected.emit(key)
        self.section_changed.emit(key)
        self._presenter.on_select(key)

    # ------------------------------------------------------------------ #
    #  IDisplaysView implementation                                        #
    # ------------------------------------------------------------------ #

    def refresh_list(self, specs: list[DisplaySpec]) -> None:
        """Перестроить nav-список по текущему состоянию store.

        Очищает nav-список и заглушки в content_stack (не форму!),
        добавляет каждый spec через add_item.

        Args:
            specs: список DisplaySpec из store.
        """
        assert self._nav_widget is not None

        # Блокируем сигналы nav-виджета на время перестройки
        self._nav_widget.blockSignals(True)
        self._nav_widget.clear()
        self._key_to_item.clear()

        # Удаляем только заглушки (QWidget()) из content_stack, форму сохраняем.
        # Форма (_form_widget) имеет parent = content_stack и НЕ удаляется.
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
            # Форма была удалена — добавляем обратно (защитная логика)
            self._form_stack_index = self._content_stack.addWidget(self._form_widget)
        self._content_stack.setCurrentIndex(self._form_stack_index)

        self._nav_widget.blockSignals(False)

        for spec in specs:
            self.add_item(spec.display_id, spec.display_name)

        # Сброс выбора после перестройки
        self._selected_id = None

    def show_entry(self, spec: DisplaySpec | None) -> None:
        """Заполнить форму данными записи или очистить при None.

        При spec=None — поля очищаются, id становится редактируемым
        (режим создания нового дисплея).
        При spec!=None — поля заполняются, id становится read-only
        (режим просмотра/редактирования существующего).

        Args:
            spec: спецификация дисплея или None.
        """
        if spec is None:
            self._id_edit.setReadOnly(False)
            self._id_edit.clear()
            self._name_edit.clear()
            self._width_spin.setValue(1280)
            self._height_spin.setValue(720)
            self._format_combo.setCurrentText("BGR")
            self._fps_spin.setValue(30.0)
            self._ring_spin.setValue(3)
        else:
            self._id_edit.setReadOnly(True)
            self._id_edit.setText(spec.display_id)
            self._name_edit.setText(spec.display_name)
            self._width_spin.setValue(spec.width)
            self._height_spin.setValue(spec.height)
            fmt = spec.format if spec.format in _PIXEL_FORMATS else "BGR"
            self._format_combo.setCurrentText(fmt)
            self._fps_spin.setValue(spec.fps_limit)
            self._ring_spin.setValue(spec.ring_buffer_blocks)

    def set_buttons_state(self, has_selection: bool) -> None:
        """Включить/выключить кнопки мутации.

        Args:
            has_selection: True — запись выбрана, кнопки активны.
        """
        self._delete_btn.setEnabled(has_selection)
        self._duplicate_btn.setEnabled(has_selection)
        self._preview_btn.setEnabled(has_selection)

    def get_form_data(self) -> dict:
        """Собрать текущие данные формы в словарь.

        Returns:
            dict: {id, name, width, height, format, fps_limit, ring_buffer_blocks}
        """
        return {
            "id": self._id_edit.text().strip(),
            "name": self._name_edit.text().strip(),
            "width": self._width_spin.value(),
            "height": self._height_spin.value(),
            "format": self._format_combo.currentText(),
            "fps_limit": self._fps_spin.value(),
            "ring_buffer_blocks": self._ring_spin.value(),
        }

    def show_error(self, message: str) -> None:
        """Показать диалог с сообщением об ошибке.

        Args:
            message: текст ошибки для отображения пользователю.
        """
        QMessageBox.warning(self, "Ошибка", message)

    # ------------------------------------------------------------------ #
    #  Построение UI                                                       #
    # ------------------------------------------------------------------ #

    def _build_form(self) -> None:
        """Создать singleton-форму редактирования полей DisplaySpec.

        Форма размещается в content_scroll через set_content_widget.
        Не привязана к content_stack — один виджет для всех записей.
        """
        self._form_widget = QWidget()
        form_vbox = QVBoxLayout(self._form_widget)
        form_vbox.setContentsMargins(12, 12, 12, 12)
        form_vbox.setSpacing(6)

        form_vbox.addWidget(QLabel("<b>Параметры дисплея</b>"))

        form_layout = QFormLayout()
        form_layout.setContentsMargins(0, 4, 0, 0)
        form_layout.setSpacing(8)

        # ID — read-only при выборе существующего
        self._id_edit = QLineEdit()
        self._id_edit.setPlaceholderText("Уникальный идентификатор")
        form_layout.addRow("ID:", self._id_edit)

        # Название
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Имя дисплея")
        form_layout.addRow("Название:", self._name_edit)

        # Ширина
        self._width_spin = QSpinBox()
        self._width_spin.setRange(1, 7680)
        self._width_spin.setValue(1280)
        self._width_spin.setSuffix(" px")
        form_layout.addRow("Ширина:", self._width_spin)

        # Высота
        self._height_spin = QSpinBox()
        self._height_spin.setRange(1, 7680)
        self._height_spin.setValue(720)
        self._height_spin.setSuffix(" px")
        form_layout.addRow("Высота:", self._height_spin)

        # Формат пикселей
        self._format_combo = QComboBox()
        self._format_combo.addItems(_PIXEL_FORMATS)
        form_layout.addRow("Формат:", self._format_combo)

        # FPS limit
        self._fps_spin = QDoubleSpinBox()
        self._fps_spin.setRange(0.0, 240.0)
        self._fps_spin.setSingleStep(0.5)
        self._fps_spin.setDecimals(1)
        self._fps_spin.setValue(30.0)
        self._fps_spin.setSpecialValueText("Без ограничений")
        form_layout.addRow("FPS limit:", self._fps_spin)

        # Ring buffer blocks
        self._ring_spin = QSpinBox()
        self._ring_spin.setRange(1, 32)
        self._ring_spin.setValue(3)
        self._ring_spin.setToolTip("Количество блоков ring-buffer SHM-канала")
        form_layout.addRow("Ring buffer:", self._ring_spin)

        form_vbox.addLayout(form_layout)
        form_vbox.addStretch(1)

    def _setup_actions(self) -> None:
        """Создать action-кнопки в левой колонке layout'а.

        Подключает permission gating через install_permission_aware_enable.
        """
        from multiprocess_prototype.frontend.widgets.access import (
            install_permission_aware_enable,
        )

        action_widget = QWidget()
        action_layout = QVBoxLayout(action_widget)
        action_layout.setContentsMargins(4, 4, 4, 4)
        action_layout.setSpacing(6)

        # Создать — всегда активна (при наличии permission)
        self._create_btn = QPushButton("Создать")
        self._create_btn.setToolTip("Создать новый дисплей из данных формы")
        self._create_btn.clicked.connect(self._on_create_clicked)
        action_layout.addWidget(self._create_btn)

        # Удалить — disabled без выбора
        self._delete_btn = QPushButton("Удалить")
        self._delete_btn.setToolTip("Удалить выбранный дисплей")
        self._delete_btn.setEnabled(False)
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        action_layout.addWidget(self._delete_btn)

        # Дублировать — disabled без выбора
        self._duplicate_btn = QPushButton("Дублировать")
        self._duplicate_btn.setToolTip("Создать копию выбранного дисплея")
        self._duplicate_btn.setEnabled(False)
        self._duplicate_btn.clicked.connect(self._on_duplicate_clicked)
        action_layout.addWidget(self._duplicate_btn)

        # Открыть превью — disabled без выбора
        self._preview_btn = QPushButton("Открыть превью")
        self._preview_btn.setToolTip("Открыть окно превью SHM-канала (Task 4.7)")
        self._preview_btn.setEnabled(False)
        self._preview_btn.clicked.connect(self._on_preview_clicked)
        action_layout.addWidget(self._preview_btn)

        action_layout.addStretch(1)
        self._tab_layout.set_action_widget(action_widget)

        # Permission gating: services.auth — AuthFacadeFromAuthState, реальный AuthState
        # хранится в _state (паттерн E.4/E.5). Fake/тесты не имеют _state -> None (no-op gate).
        auth_state = getattr(self._services.auth, "_state", None)
        install_permission_aware_enable(self._create_btn, "tabs.displays.edit", auth_state)
        install_permission_aware_enable(self._delete_btn, "tabs.displays.edit", auth_state)
        install_permission_aware_enable(self._duplicate_btn, "tabs.displays.edit", auth_state)

    # ------------------------------------------------------------------ #
    #  Button handlers                                                     #
    # ------------------------------------------------------------------ #

    def _on_create_clicked(self) -> None:
        """Обработать нажатие «Создать»."""
        self._presenter.on_create()

    def _on_delete_clicked(self) -> None:
        """Обработать нажатие «Удалить»."""
        if self._selected_id is not None:
            self._presenter.on_delete(self._selected_id)

    def _on_duplicate_clicked(self) -> None:
        """Обработать нажатие «Дублировать»."""
        if self._selected_id is not None:
            self._presenter.on_duplicate(self._selected_id)

    def _on_preview_clicked(self) -> None:
        """Обработать нажатие «Открыть превью»."""
        if self._selected_id is not None:
            self._presenter.on_open_preview(self._selected_id)

    # ------------------------------------------------------------------ #
    #  Preview callback (Task 4.7)                                         #
    # ------------------------------------------------------------------ #

    def _open_preview_window(self, spec: DisplaySpec) -> None:
        """Открыть окно превью SHM-канала для дисплея.

        Вызывается из presenter через preview_callback.
        router_manager берётся из explicit-параметра конструктора (None -> без подписки).
        Ссылка на окно сохраняется в ``_preview_windows`` для предотвращения GC.

        open_for_display ожидает DisplayEntry (framework) — конвертируем spec -> entry
        локально (tab — frontend-слой, может импортировать framework для превью).

        Args:
            spec: спецификация дисплея для превью.
        """
        from multiprocess_framework.modules.display_module import DisplayEntry
        from multiprocess_prototype.frontend.widgets.displays import open_for_display

        entry = DisplayEntry(
            id=spec.display_id,
            name=spec.display_name,
            width=spec.width,
            height=spec.height,
            format=spec.format,
            fps_limit=spec.fps_limit,
            ring_buffer_blocks=spec.ring_buffer_blocks,
        )

        window = open_for_display(entry, router_manager=self._router_manager, parent=None)
        # Сохраняем ссылку — без неё Qt удалит окно при GC
        self._preview_windows.append(window)
        # Подчищаем закрытые окна из списка
        self._preview_windows = [w for w in self._preview_windows if w.isVisible()]
        logger.info("DisplaysTab: открыто превью '%s'", spec.display_id)
