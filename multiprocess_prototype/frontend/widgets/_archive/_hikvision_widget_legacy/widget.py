# multiprocess_prototype/frontend/widgets/hikvision_widget/widget.py
"""
HikvisionWidget — виджет управления камерой Hikvision (BaseWidget + MVP).

Структура компонентов (порядок создания в BaseWidget.__init__):
  1. _coerce_callbacks  — нормализация колбэков
  2. _coerce_ui         — конфигурация UI (HikvisionUiConfig)
  3. _create_model      — HikvisionModel (регистры, колбэки)
  4. _init_ui           — построение Qt-дерева (View)
  5. _create_presenter   — HikvisionPresenter(view=self, model)
  6. _connect_signals   — привязка сигналов кнопок к Model/Presenter
  7. _on_presenter_ready — post-init (пусто)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Union

from multiprocess_framework.modules.frontend_module.widgets.base_widget import BaseWidget
from multiprocess_framework.modules.frontend_module.widgets.tabs import RegisterBindingContext, callback_no_args
from multiprocess_framework.modules.frontend_module.widgets.tabs.numeric_bind_or_lineedit import (
    append_spinbox_numeric_or_line_fallback,
)
from multiprocess_framework.modules.frontend_module.core.qt_imports import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from multiprocess_framework.modules.frontend_module.core.schema_config import coerce_schema_config

from multiprocess_prototype.frontend.touch_keyboard_bind import merge_touch_keyboard_dicts
from multiprocess_prototype.registers.schemas.camera_tab import CAMERA_REGISTER

from .callbacks import HikvisionWidgetCallbacks
from .line_params import apply_params_to_line_edits, parse_triple_from_line_edits
from .model import HikvisionModel
from .presenter import HikvisionPresenter
from .schemas import HikvisionUiConfig


@dataclass
class HikvisionParamsRefs:
    """Ссылки на line edits (fallback) или None при bind к регистру."""

    line_edits: List[Optional[QLineEdit]]


class HikvisionWidget(BaseWidget[HikvisionModel]):
    """Виджет Hikvision: устройство, Open/Close, Grabbing, параметры."""

    def __init__(
        self,
        *,
        registers_manager=None,
        callbacks: Optional[HikvisionWidgetCallbacks] = None,
        ui: Optional[Union[HikvisionUiConfig, dict]] = None,
        touch_keyboard: Any | None = None,
        parent=None,
    ) -> None:
        self._touch_keyboard_parent = touch_keyboard
        super().__init__(
            registers_manager=registers_manager,
            callbacks=callbacks,
            ui=ui,
            parent=parent,
        )

    # ========================================================================
    # [1/7] _coerce_callbacks — нормализация колбэков (dict → HikvisionWidgetCallbacks)
    # ========================================================================

    def _coerce_callbacks(self, callbacks: Optional[object]) -> HikvisionWidgetCallbacks:
        return callbacks or HikvisionWidgetCallbacks()

    # ========================================================================
    # [2/7] _coerce_ui — конфигурация UI (dict/None → HikvisionUiConfig)
    # ========================================================================

    def _coerce_ui(self, ui: Optional[object]) -> HikvisionUiConfig:
        return coerce_schema_config(ui, HikvisionUiConfig)

    # ========================================================================
    # [3/7] _create_model — MODEL: слой данных (регистры + делегирование в колбэки)
    # ========================================================================

    def _create_model(self) -> HikvisionModel:
        return HikvisionModel(
            rm=self._registers_manager,
            callbacks=self._callbacks,
            ui=self._ui,
        )

    # ========================================================================
    # [4/7] _init_ui — VIEW: построение Qt-дерева (без привязки сигналов)
    # ========================================================================

    def _init_ui(self) -> None:
        u = self._ui
        binding = RegisterBindingContext(rm=self._registers_manager)

        page = QWidget()
        layout = QVBoxLayout(page)

        # ---- Секция «Устройство»: hint, list_devices, btn_enum, btn_open/close ----
        dev_group = QGroupBox(u.group_device)
        dev_layout = QVBoxLayout(dev_group)
        hint = QLabel(u.device_list_hint)
        hint.setWordWrap(True)
        dev_layout.addWidget(hint)
        # ---- Секция «Устройство»: hint, list_devices, btn_enum, btn_open/close ----
        self._list_devices = QListWidget()
        self._list_devices.setMinimumHeight(u.device_list_min_height)
        self._list_devices.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        dev_layout.addWidget(self._list_devices)

        self._btn_enum = QPushButton(u.btn_enum_devices)
        dev_layout.addWidget(self._btn_enum)
        row_open = QHBoxLayout()
        self._btn_open = QPushButton(u.btn_open)
        self._btn_close = QPushButton(u.btn_close)
        row_open.addWidget(self._btn_open)
        row_open.addWidget(self._btn_close)
        dev_layout.addLayout(row_open)
        layout.addWidget(dev_group)

        # ---- Секция «Grabbing»: btn_start_grabbing, btn_stop_grabbing ----
        grab_group = QGroupBox(u.group_grabbing)
        grab_layout = QVBoxLayout(grab_group)
        self._btn_start_grabbing = QPushButton(u.btn_start_grabbing)
        self._btn_stop_grabbing = QPushButton(u.btn_stop_grabbing)
        grab_layout.addWidget(self._btn_start_grabbing)
        grab_layout.addWidget(self._btn_stop_grabbing)
        layout.addWidget(grab_group)

        # ---- Секция «Параметры» (NumericControl или QLineEdit fallback) ----
        params_group, self._hik_params = self._build_params_group(binding)
        layout.addWidget(params_group)

        self._devices: list = []
        root_layout = QVBoxLayout(self)
        root_layout.addWidget(page)

    # ---- Фабрика секции параметров (используется в _init_ui) ----

    def _build_params_group(self, binding: RegisterBindingContext) -> tuple:
        """Собрать QGroupBox параметров: NumericControl (bind) или QLineEdit (fallback)."""
        u = self._ui
        group = QGroupBox(u.group_params)
        layout = QVBoxLayout(group)
        placeholders = (u.placeholder_fps, u.placeholder_exposure, u.placeholder_gain)
        tk = merge_touch_keyboard_dicts(
            self._touch_keyboard_parent,
            getattr(self._ui, "touch_keyboard", None),
        )
        line_edits = append_spinbox_numeric_or_line_fallback(
            layout,
            binding=binding,
            register_name=CAMERA_REGISTER,
            row_specs=u.hikvision_spinbox_rows,
            label_for_row=u.spinbox_label_for_row,
            placeholders=placeholders,
            line_edit_max_width=u.hikvision_line_edit_max_width,
            touch_keyboard=tk,
            host_widget=group,
        )

        row_btns = QHBoxLayout()
        self._btn_get_params = QPushButton(u.btn_get_parameters)
        self._btn_set_params = QPushButton(u.btn_set_parameters)
        row_btns.addWidget(self._btn_get_params)
        row_btns.addWidget(self._btn_set_params)
        layout.addLayout(row_btns)

        return group, HikvisionParamsRefs(line_edits=line_edits)

    # ========================================================================
    # [5/7] _create_presenter — PRESENTER: связывает Model и View (self)
    # ========================================================================

    def _create_presenter(self, model: Optional[HikvisionModel]) -> HikvisionPresenter:
        assert model is not None
        return HikvisionPresenter(view=self, model=model, ui=self._ui)

    # ========================================================================
    # [6/7] _connect_signals — привязка UI → Model / UI → Presenter (пассивный View)
    # ========================================================================

    def _connect_signals(self) -> None:
        """Привязка: кнопки → Model (прямо) или Presenter (через слоты View)."""
        # clicked передаёт bool в слот; без обёртки методы Model получили бы лишний аргумент.
        _btn = callback_no_args
        m = self._model

        # ---- Кнопки, идущие напрямую в Model (без данных из View) ----
        self._btn_enum.clicked.connect(_btn(m.enum_devices))
        self._btn_close.clicked.connect(_btn(m.close_camera))
        self._btn_stop_grabbing.clicked.connect(_btn(m.stop_grabbing))
        self._btn_get_params.clicked.connect(_btn(m.get_parameters))

        # ---- Кнопки → слоты View → Presenter (пассивный View: View передаёт данные) ----
        self._btn_open.clicked.connect(self._on_open_clicked)
        self._btn_start_grabbing.clicked.connect(self._on_start_grabbing_clicked)
        self._btn_set_params.clicked.connect(self._on_set_params_clicked)

    # ========================================================================
    # Слоты View: извлекают данные из UI и передают в Presenter (пассивный View)
    # ========================================================================

    def _get_selected_camera_index(self) -> int:
        """Текущий индекс выбранной камеры (из _list_devices). Для слотов Open/Start."""
        if not self._devices:
            return 0
        row = self._list_devices.currentRow()
        if row < 0 or row >= len(self._devices):
            return int(self._devices[0].get("index", 0))
        return int(self._devices[row].get("index", 0))

    def _on_open_clicked(self) -> None:
        idx = self._get_selected_camera_index()
        self._presenter.on_open_clicked(idx)

    def _on_start_grabbing_clicked(self) -> None:
        idx = self._get_selected_camera_index()
        self._presenter.on_start_grabbing_clicked(idx)

    def _on_set_params_clicked(self) -> None:
        fr, exp, gain = self._model.get_params_for_set(self._get_params_from_lines)
        self._presenter.on_set_parameters_clicked(fr, exp, gain)

    def _get_params_from_lines(self) -> tuple[float, float, float]:
        """Fallback для модели: тройка из QLineEdit (см. line_params.parse_triple_from_line_edits)."""
        hp = self._hik_params
        if not hp:
            return (25.0, 10000.0, 0.0)
        return parse_triple_from_line_edits(self._ui, hp.line_edits)

    # ========================================================================
    # HikvisionView protocol — методы, которые Presenter вызывает для обновления UI
    # ========================================================================

    def set_devices_list(self, devices: list) -> None:
        self._devices = devices or []
        if not hasattr(self, "_list_devices") or self._list_devices is None:
            return
        lst = self._list_devices
        lst.clear()
        for dev in self._devices:
            display = dev.get("display_name", f"[{dev.get('index', '?')}]")
            lst.addItem(display)
        if self._devices:
            lst.setCurrentRow(0)

    def set_hikvision_params_lines(self, params: dict) -> None:
        if not hasattr(self, "_hik_params") or not self._hik_params:
            return
        apply_params_to_line_edits(self._ui, self._hik_params.line_edits, params)

    # ---- Публичные методы (внешние вызовы: CameraTab, IPC) ----

    def update_camera_devices(self, devices: list) -> None:
        self._presenter.update_camera_devices(devices)

    def update_camera_parameters(self, params: dict) -> None:
        self._presenter.update_camera_parameters(params)
