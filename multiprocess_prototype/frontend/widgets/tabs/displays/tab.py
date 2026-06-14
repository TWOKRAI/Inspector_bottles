# -*- coding: utf-8 -*-
"""DisplaysTab v3 — CRUD-таб управления дисплеями (MVP pattern, recipe-scoped).

Task 5.2 (displays-in-recipe): форма с секциями «Базовые» + «Параметры отображения»,
CRUD с render-полями, persist в активный рецепт, превью с render-параметрами.

Task E.6 + F.3: мигрирован на AppServices DI. Принимает ``services: AppServices``.
DisplayCatalog Protocol (domain) покрывает полный read+write API (Phase F).
Presenter получает ``store=services.displays`` без bridge.

router_manager (превью SHM-канала) — runtime-объект вне AppServices, передаётся
explicit-параметром (паттерн E.2/E.5).

Реализует IDisplaysView через structural subtyping (без явного наследования).
Использует BaseListNavTab: QListWidget слева + content-форма справа.

Форма (правая панель) — две секции (QGroupBox):
  Секция «Базовые»:
    - id (QLineEdit, read-only при выборе существующего)
    - name (QLineEdit)
    - width / height (QSpinBox, 1..7680)
    - format (QComboBox: BGR/RGB/GRAY/RGBA)
    - fps_limit (QDoubleSpinBox, 0.0..240.0)
    - ring_buffer_blocks (QSpinBox, 1..32)
  Секция «Параметры отображения»:
    - position X/Y (QSpinBox, 0..7680)
    - fit (QComboBox: contain/cover/stretch/none)
    - scale (QSpinBox: 10..1000, шаг 10, default 100)
    - rotate (QComboBox: 0/90/180/270)
    - flip (QComboBox: none/horizontal/vertical/both)
    - crop X/Y/W/H (QSpinBox) + галочка «Обрезка включена» (off → crop=None)

Кнопки (action-колонка):
    - «Создать» — всегда активна (при наличии permission)
    - «Удалить» — disabled без выбора
    - «Дублировать» — disabled без выбора
    - «Открыть превью» — disabled без выбора (применяет render-параметры)

Архитектурная заметка:
    BaseListNavTab управляет content_stack через add_item/remove_item.
    DisplaysTab использует одну общую форму (_form_widget) как content для
    всех записей: _create_item_widget возвращает QWidget-заглушку, а
    refresh_list вставляет форму в content_scroll напрямую через
    _tab_layout.set_content_widget — но только один раз (форма singleton).
    Повторная перезапись не нужна, форма остаётся в content_scroll.

Refs: plans/displays-in-recipe/plan.md Task 5.2
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
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
from multiprocess_prototype.frontend.runtime_deps import RuntimeDeps
from multiprocess_prototype.frontend.widgets.primitives.diff_scroll_tab_layout import (
    DiffScrollTabLayout,
)

from .presenter import DisplaysPresenter

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
        image_panel: object | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Инициализировать таб дисплеев.

        Args:
            services: типизированный DI-контейнер AppServices.
            router_manager: RouterManager для превью SHM-канала (runtime-объект вне
                AppServices, по умолчанию None — превью без подписки).
            image_panel: главная панель кадров (ImagePanelWidget) для снимка дисплея
                (grab_frame). None → кнопка «Снимок» даёт понятный статус.
            parent: родительский виджет.
        """
        self._services = services
        self._router_manager = router_manager
        self._image_panel = image_panel
        self._selected_id: str | None = None
        # Индекс формы в content_stack (устанавливается после super().__init__)
        self._form_stack_index: int = 0

        super().__init__(
            title="Дисплеи",
            ctx=None,  # type: ignore[arg-type]  # framework generic-слот, прототип не использует ctx
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

        from multiprocess_prototype.frontend.widgets.displays import PreviewWindowManager

        # Реестр открытых окон превью (PreviewWindowManager):
        # - предотвращает GC (сильные ссылки),
        # - управляет orphan/reconnect при смене рецепта (Task 2.3).
        self._window_manager = PreviewWindowManager()

        # Presenter получает store=services.displays (DisplayCatalog Protocol).
        # event_bus=services.events — для эмита DisplaysChanged (главная панель
        # пересобирает слоты при создании/удалении/toggle дисплея).
        self._presenter = DisplaysPresenter(
            store=services.displays,
            view=self,
            preview_callback=self._open_preview_window,
            event_bus=services.events,
        )

        # Подписка presenter'а на RecipeActivated (Task 2.3):
        # event_bus = services.events, window_manager = наш реестр,
        # router_manager = runtime-параметр (None если не передан).
        self._presenter.bind_event_bus(
            services.events,
            window_manager=self._window_manager,
            router_manager=self._router_manager,
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
    ) -> "DisplaysTab":
        """Фабричный метод для register_all_tabs() / TabFactory.

        Task F.9: принимает AppServices + RuntimeDeps (Q-F1=B).
        image_panel из runtime — для снимка дисплея (кнопка «Снимок»).
        """
        return cls(services, image_panel=runtime.image_panel)

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
        (режим создания нового дисплея). Render-поля сбрасываются к дефолтам.
        При spec!=None — поля заполняются, id становится read-only
        (режим просмотра/редактирования существующего).

        Args:
            spec: спецификация дисплея или None.
        """
        if spec is None:
            # Базовые. ID всегда read-only (генерируется автоматически при создании).
            self._id_edit.clear()
            self._name_edit.clear()
            # blockSignals: программная установка не должна триггерить on_set_enabled
            self._enabled_cb.blockSignals(True)
            self._enabled_cb.setChecked(True)
            self._enabled_cb.blockSignals(False)
            self._width_spin.setValue(1280)
            self._height_spin.setValue(720)
            self._format_combo.setCurrentText("BGR")
            self._fps_spin.setValue(30.0)
            self._ring_spin.setValue(3)
            # Render-дефолты
            self._pos_x_spin.setValue(0)
            self._pos_y_spin.setValue(0)
            self._fit_combo.setCurrentText("contain")
            self._scale_spin.setValue(100)
            self._rotate_combo.setCurrentText("0")
            self._flip_combo.setCurrentText("none")
            self._crop_enabled_cb.setChecked(False)
            self._crop_x_spin.setValue(0)
            self._crop_y_spin.setValue(0)
            self._crop_w_spin.setValue(1280)
            self._crop_h_spin.setValue(720)
        else:
            # Базовые (id всегда read-only)
            self._id_edit.setText(spec.display_id)
            self._name_edit.setText(spec.display_name)
            # blockSignals: программная установка не должна триггерить on_set_enabled
            self._enabled_cb.blockSignals(True)
            self._enabled_cb.setChecked(bool(getattr(spec, "enabled", True)))
            self._enabled_cb.blockSignals(False)
            self._width_spin.setValue(spec.width)
            self._height_spin.setValue(spec.height)
            fmt = spec.format if spec.format in _PIXEL_FORMATS else "BGR"
            self._format_combo.setCurrentText(fmt)
            self._fps_spin.setValue(spec.fps_limit)
            self._ring_spin.setValue(spec.ring_buffer_blocks)
            # Render-поля
            pos = spec.position or {"x": 0, "y": 0}
            self._pos_x_spin.setValue(pos.get("x", 0))
            self._pos_y_spin.setValue(pos.get("y", 0))
            self._fit_combo.setCurrentText(spec.fit or "contain")
            self._scale_spin.setValue(spec.scale if spec.scale else 100)
            self._rotate_combo.setCurrentText(str(spec.rotate or 0))
            self._flip_combo.setCurrentText(spec.flip or "none")
            # Crop
            if spec.crop is not None:
                self._crop_enabled_cb.setChecked(True)
                self._crop_x_spin.setValue(spec.crop.get("x", 0))
                self._crop_y_spin.setValue(spec.crop.get("y", 0))
                self._crop_w_spin.setValue(spec.crop.get("w", 1280))
                self._crop_h_spin.setValue(spec.crop.get("h", 720))
            else:
                self._crop_enabled_cb.setChecked(False)
                self._crop_x_spin.setValue(0)
                self._crop_y_spin.setValue(0)
                self._crop_w_spin.setValue(1280)
                self._crop_h_spin.setValue(720)

    def set_buttons_state(self, has_selection: bool) -> None:
        """Включить/выключить кнопки мутации.

        Args:
            has_selection: True — запись выбрана, кнопки активны.
        """
        self._delete_btn.setEnabled(has_selection)
        self._duplicate_btn.setEnabled(has_selection)
        self._preview_btn.setEnabled(has_selection)
        self._snapshot_btn.setEnabled(has_selection)

    def get_form_data(self) -> dict:
        """Собрать текущие данные формы в словарь.

        Returns:
            dict: базовые + render-поля:
                {id, name, width, height, format, fps_limit, ring_buffer_blocks,
                 position, fit, scale, rotate, flip, crop}
        """
        # Crop: None если галочка выключена
        crop: dict[str, int] | None = None
        if self._crop_enabled_cb.isChecked():
            crop = {
                "x": self._crop_x_spin.value(),
                "y": self._crop_y_spin.value(),
                "w": self._crop_w_spin.value(),
                "h": self._crop_h_spin.value(),
            }

        return {
            "id": self._id_edit.text().strip(),
            "name": self._name_edit.text().strip(),
            "enabled": self._enabled_cb.isChecked(),
            "width": self._width_spin.value(),
            "height": self._height_spin.value(),
            "format": self._format_combo.currentText(),
            "fps_limit": self._fps_spin.value(),
            "ring_buffer_blocks": self._ring_spin.value(),
            # Render-поля
            "position": {
                "x": self._pos_x_spin.value(),
                "y": self._pos_y_spin.value(),
            },
            "fit": self._fit_combo.currentText(),
            "scale": self._scale_spin.value(),
            "rotate": int(self._rotate_combo.currentText()),
            "flip": self._flip_combo.currentText(),
            "crop": crop,
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

        Форма содержит две секции (QGroupBox):
          - «Базовые» — SHM-конфигурация (id, name, width, height, format, fps, ring_buffer).
          - «Параметры отображения» — render-слой (position, fit, scale, rotate, flip, crop).

        Паттерн: SectionedForm (QGroupBox секции), аналог ProcessCard (StyledPanel + header).
        """
        self._form_widget = QWidget()
        form_vbox = QVBoxLayout(self._form_widget)
        form_vbox.setContentsMargins(12, 12, 12, 12)
        form_vbox.setSpacing(10)

        # ============================================================
        # Секция «Базовые»
        # ============================================================
        base_group = QGroupBox("Базовые")
        base_group.setObjectName("DisplaysFormBaseSection")
        base_layout = QFormLayout(base_group)
        base_layout.setContentsMargins(8, 12, 8, 8)
        base_layout.setSpacing(8)

        # ID — генерируется автоматически, всегда read-only (пользователь НЕ вводит).
        # При создании presenter подставит display_<N>; при выборе — id записи.
        self._id_edit = QLineEdit()
        self._id_edit.setReadOnly(True)
        self._id_edit.setPlaceholderText("(генерируется автоматически)")
        base_layout.addRow("ID:", self._id_edit)

        # Название
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Имя дисплея (по умолчанию display_<N>)")
        base_layout.addRow("Название:", self._name_edit)

        # Показывать в главной области (toggle вкл/выкл дисплея).
        # Изменение применяется сразу к выбранному дисплею (persist в рецепт).
        self._enabled_cb = QCheckBox("Показывать в главной области")
        self._enabled_cb.setChecked(True)
        self._enabled_cb.setToolTip("Если включено — дисплей отображается в главной области GUI рядом с другими")
        self._enabled_cb.toggled.connect(self._on_enabled_toggled)
        base_layout.addRow(self._enabled_cb)

        # Ширина
        self._width_spin = QSpinBox()
        self._width_spin.setRange(1, 7680)
        self._width_spin.setValue(1280)
        self._width_spin.setSuffix(" px")
        base_layout.addRow("Ширина:", self._width_spin)

        # Высота
        self._height_spin = QSpinBox()
        self._height_spin.setRange(1, 7680)
        self._height_spin.setValue(720)
        self._height_spin.setSuffix(" px")
        base_layout.addRow("Высота:", self._height_spin)

        # Формат пикселей
        self._format_combo = QComboBox()
        self._format_combo.addItems(_PIXEL_FORMATS)
        base_layout.addRow("Формат:", self._format_combo)

        # FPS limit
        self._fps_spin = QDoubleSpinBox()
        self._fps_spin.setRange(0.0, 240.0)
        self._fps_spin.setSingleStep(0.5)
        self._fps_spin.setDecimals(1)
        self._fps_spin.setValue(30.0)
        self._fps_spin.setSpecialValueText("Без ограничений")
        base_layout.addRow("FPS limit:", self._fps_spin)

        # Ring buffer blocks
        self._ring_spin = QSpinBox()
        self._ring_spin.setRange(1, 32)
        self._ring_spin.setValue(3)
        self._ring_spin.setToolTip("Количество блоков ring-buffer SHM-канала")
        base_layout.addRow("Ring buffer:", self._ring_spin)

        form_vbox.addWidget(base_group)

        # ============================================================
        # Секция «Параметры отображения» (render-слой)
        # ============================================================
        render_group = QGroupBox("Параметры отображения")
        render_group.setObjectName("DisplaysFormRenderSection")
        render_layout = QFormLayout(render_group)
        render_layout.setContentsMargins(8, 12, 8, 8)
        render_layout.setSpacing(8)

        # Позиция X
        self._pos_x_spin = QSpinBox()
        self._pos_x_spin.setRange(0, 7680)
        self._pos_x_spin.setValue(0)
        self._pos_x_spin.setSuffix(" px")
        render_layout.addRow("Позиция X:", self._pos_x_spin)

        # Позиция Y
        self._pos_y_spin = QSpinBox()
        self._pos_y_spin.setRange(0, 7680)
        self._pos_y_spin.setValue(0)
        self._pos_y_spin.setSuffix(" px")
        render_layout.addRow("Позиция Y:", self._pos_y_spin)

        # Fit
        self._fit_combo = QComboBox()
        self._fit_combo.addItems(["contain", "cover", "stretch", "none"])
        render_layout.addRow("Fit:", self._fit_combo)

        # Scale — QSpinBox 10..1000 шаг 10 default 100 (раздел 8 + 9.11 спеки)
        self._scale_spin = QSpinBox()
        self._scale_spin.setObjectName("DisplaysFormScaleSpin")
        self._scale_spin.setRange(10, 1000)
        self._scale_spin.setSingleStep(10)
        self._scale_spin.setValue(100)
        self._scale_spin.setSuffix(" %")
        render_layout.addRow("Scale:", self._scale_spin)

        # Rotate
        self._rotate_combo = QComboBox()
        self._rotate_combo.addItems(["0", "90", "180", "270"])
        render_layout.addRow("Rotate:", self._rotate_combo)

        # Flip
        self._flip_combo = QComboBox()
        self._flip_combo.addItems(["none", "horizontal", "vertical", "both"])
        render_layout.addRow("Flip:", self._flip_combo)

        # Crop — галочка «Обрезка включена» + поля X/Y/W/H
        self._crop_enabled_cb = QCheckBox("Обрезка включена")
        self._crop_enabled_cb.setChecked(False)
        self._crop_enabled_cb.toggled.connect(self._on_crop_toggled)
        render_layout.addRow(self._crop_enabled_cb)

        self._crop_x_spin = QSpinBox()
        self._crop_x_spin.setRange(0, 7680)
        self._crop_x_spin.setValue(0)
        self._crop_x_spin.setSuffix(" px")
        self._crop_x_spin.setEnabled(False)
        render_layout.addRow("Crop X:", self._crop_x_spin)

        self._crop_y_spin = QSpinBox()
        self._crop_y_spin.setRange(0, 7680)
        self._crop_y_spin.setValue(0)
        self._crop_y_spin.setSuffix(" px")
        self._crop_y_spin.setEnabled(False)
        render_layout.addRow("Crop Y:", self._crop_y_spin)

        self._crop_w_spin = QSpinBox()
        self._crop_w_spin.setRange(1, 7680)
        self._crop_w_spin.setValue(1280)
        self._crop_w_spin.setSuffix(" px")
        self._crop_w_spin.setEnabled(False)
        render_layout.addRow("Crop W:", self._crop_w_spin)

        self._crop_h_spin = QSpinBox()
        self._crop_h_spin.setRange(1, 7680)
        self._crop_h_spin.setValue(720)
        self._crop_h_spin.setSuffix(" px")
        self._crop_h_spin.setEnabled(False)
        render_layout.addRow("Crop H:", self._crop_h_spin)

        form_vbox.addWidget(render_group)
        form_vbox.addStretch(1)

    def _on_enabled_toggled(self, enabled: bool) -> None:
        """Применить toggle «Показывать в главной области» к выбранному дисплею.

        Игнорируется при программном заполнении формы (show_entry) — там
        чекбокс обновляется через blockSignals. Срабатывает только на
        пользовательское переключение для уже выбранного дисплея.

        Args:
            enabled: новое состояние чекбокса (True — показывать).
        """
        if self._selected_id is None:
            return
        self._presenter.on_set_enabled(self._selected_id, enabled)

    def _on_crop_toggled(self, enabled: bool) -> None:
        """Включить/выключить поля crop при изменении галочки.

        Args:
            enabled: True — crop поля активны, False — disabled (crop=None).
        """
        self._crop_x_spin.setEnabled(enabled)
        self._crop_y_spin.setEnabled(enabled)
        self._crop_w_spin.setEnabled(enabled)
        self._crop_h_spin.setEnabled(enabled)

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

        # Снимок — сохранить текущий кадр выбранного дисплея в PNG. Read-only вывод,
        # permission не требуется. Disabled без выбора.
        self._snapshot_btn = QPushButton("Снимок")
        self._snapshot_btn.setToolTip("Сохранить текущий кадр выбранного дисплея в PNG (data/snapshots/)")
        self._snapshot_btn.setEnabled(False)
        self._snapshot_btn.clicked.connect(self._on_snapshot_clicked)
        action_layout.addWidget(self._snapshot_btn)

        action_layout.addStretch(1)
        self._tab_layout.set_action_widget(action_widget)

        # Permission gating через AuthFacade Protocol (F.6).
        install_permission_aware_enable(self._create_btn, "tabs.displays.edit", self._services.auth)
        install_permission_aware_enable(self._delete_btn, "tabs.displays.edit", self._services.auth)
        install_permission_aware_enable(self._duplicate_btn, "tabs.displays.edit", self._services.auth)

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

    def _on_snapshot_clicked(self) -> None:
        """Сохранить текущий кадр ВЫБРАННОГО дисплея в PNG (data/snapshots/)."""
        if self._selected_id is None:
            return
        if self._image_panel is None:
            self.show_error("Снимок недоступен: панель кадров не подключена (backend не запущен).")
            return
        frame = self._image_panel.grab_frame(self._selected_id)
        if frame is None:
            self.show_error(
                f"Нет кадра для дисплея '{self._selected_id}'. Запусти процессы и дождись кадра, затем повтори."
            )
            return
        path = self._save_snapshot(self._selected_id, frame)
        if path is not None:
            QMessageBox.information(self, "Снимок сохранён", f"Кадр дисплея «{self._selected_id}» сохранён:\n{path}")

    def _save_snapshot(self, display_id: str, frame) -> "object | None":
        """Сохранить кадр как PNG (как на экране). Возвращает путь или None при ошибке."""
        from datetime import datetime
        from pathlib import Path

        import numpy as np
        from PySide6.QtGui import QImage

        try:
            arr = np.ascontiguousarray(frame)
            if arr.ndim != 3 or arr.shape[2] != 3:
                self.show_error("Кадр не 3-канальный — снимок не поддерживается.")
                return None
            # Дисплей показывает frame[..., ::-1] как RGB888 — повторяем, чтобы PNG совпал с экраном.
            rgb = np.ascontiguousarray(arr[..., ::-1])
            h, w = rgb.shape[:2]
            qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
            out_dir = Path("data/snapshots")
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            path = out_dir / f"{display_id}_{ts}.png"
            # qimg ссылается на буфер rgb — он жив до конца save() (локальная переменная).
            if not qimg.save(str(path), "PNG"):
                self.show_error("Не удалось записать PNG (QImage.save вернул False).")
                return None
            logger.info("DisplaysTab: снимок дисплея '%s' → %s", display_id, path)
            return path
        except Exception as exc:  # noqa: BLE001 — снимок не должен ронять GUI
            logger.error("DisplaysTab: снимок '%s' не удался: %s", display_id, exc, exc_info=True)
            self.show_error(f"Снимок не удался: {exc}")
            return None

    # ------------------------------------------------------------------ #
    #  Preview callback (Task 4.7)                                         #
    # ------------------------------------------------------------------ #

    def _open_preview_window(self, spec: DisplaySpec) -> None:
        """Открыть окно превью SHM-канала для дисплея с render-параметрами.

        Вызывается из presenter через preview_callback.
        router_manager берётся из explicit-параметра конструктора (None -> без подписки).
        Окно регистрируется в ``_window_manager`` (PreviewWindowManager):
          - предотвращает GC (сильная ссылка);
          - включает управление при смене рецепта (orphan close / reconnect).

        open_for_display ожидает DisplayEntry (framework) — конвертируем spec -> entry
        локально (tab — frontend-слой, может импортировать framework для превью).
        Render-параметры (crop/scale/rotate/flip/fit) передаются через render_params (Task 4.1).

        Args:
            spec: спецификация дисплея для превью (включает render-поля).
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

        # Собираем render-параметры из DisplaySpec (Task 4.1 API)
        render_params = {
            "crop": spec.crop,
            "scale": spec.scale,
            "rotate": spec.rotate,
            "flip": spec.flip,
            "fit": spec.fit,
        }

        window = open_for_display(
            entry,
            router_manager=self._router_manager,
            parent=None,
            render_params=render_params,
        )
        # Регистрируем окно в менеджере — это даёт сильную ссылку (GC protection)
        # и включает управление orphan/reconnect при RecipeActivated.
        self._window_manager.register(spec.display_id, window)
        logger.info("DisplaysTab: открыто превью '%s' (render: %s)", spec.display_id, render_params)

    # ------------------------------------------------------------------ #
    #  Qt lifecycle (teardown)                                             #
    # ------------------------------------------------------------------ #

    def closeEvent(self, event) -> None:  # noqa: N802
        """Отписаться от EventBus и закрыть окна превью при закрытии вкладки.

        Args:
            event: QCloseEvent.
        """
        self._presenter.teardown()
        super().closeEvent(event)
