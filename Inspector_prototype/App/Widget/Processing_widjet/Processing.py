from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QGroupBox, QPushButton, QFormLayout, QDialog, QDialogButtonBox
)
from PyQt5.QtCore import Qt
from App.Components.slider import SliderControl
from App.Components.table_with_toolbar import TableWithToolbar


class ProcessingWidget(QWidget):
    def __init__(self, window_manager=None, ui_elements=None, controls_processing=None, callback=None,
                 data_manager=None, controls_post_processing=None, callback_post_processing=None):
        super().__init__()
        self.window_manager = window_manager
        self.ui_elements = ui_elements
        self.controls_processing = controls_processing
        self.callback = callback
        self.data_manager = data_manager
        self.controls_post_processing = controls_post_processing or {}
        self.callback_post_processing = callback_post_processing
        self._current_camera_id = None
        self._current_region_name = None
        self._current_processor_params_widget = None
        self._chain_step_clipboard = None  # для копирования звена цепочки
        if self.data_manager:
            self.data_manager.camera_changed.connect(self._on_data_camera_changed)
            self.data_manager.region_changed.connect(self._on_data_region_changed)
            self.data_manager.chain_changed.connect(self._on_data_chain_changed)
        self.init_ui()

    def _on_data_camera_changed(self, camera_id):
        if camera_id == self._current_camera_id:
            self._refresh_region_combo()
            self._refresh_chains_table()

    def _on_data_region_changed(self, camera_id, region_name):
        if camera_id == self._current_camera_id:
            self._refresh_region_combo()
            self._refresh_chains_table()

    def _on_data_chain_changed(self, camera_id, region_name):
        if camera_id == self._current_camera_id and region_name == self._current_region_name:
            self._refresh_chains_table()

    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Строка выбора: Камера и Регион
        if self.data_manager:
            row_sel = QHBoxLayout()
            row_sel.addWidget(QLabel("Камера:"))
            self.camera_combo = QComboBox()
            self.camera_combo.currentIndexChanged.connect(self._on_camera_combo_changed)
            row_sel.addWidget(self.camera_combo, 1)
            row_sel.addWidget(QLabel("Регион:"))
            self.region_combo = QComboBox()
            self.region_combo.currentIndexChanged.connect(self._on_region_combo_changed)
            row_sel.addWidget(self.region_combo, 1)
            layout.addLayout(row_sel)

            chain_grp = QGroupBox("Цепочки обработки")
            chain_lo = QVBoxLayout()
            self.chains_table = TableWithToolbar(
                columns=[
                    {"key": "name", "label": "Название", "type": "text"},
                    {"key": "enabled", "label": "Включено", "type": "checkbox"},
                    {"key": "info", "label": "Информация", "type": "text"},
                ],
                parent=self,
                show_add_delete=True, show_move=True, show_copy_paste=True
            )
            self.chains_table.row_selected.connect(self._on_chain_row_selected)
            self.chains_table.cell_changed.connect(self._on_chain_cell_changed)
            self.chains_table.add_clicked.connect(self._add_chain_step)
            self.chains_table.delete_clicked.connect(self._delete_chain_step)
            self.chains_table.move_up_clicked.connect(lambda: self._move_chain_step(-1))
            self.chains_table.move_down_clicked.connect(lambda: self._move_chain_step(1))
            self.chains_table.copy_clicked.connect(self._copy_chain_step)
            self.chains_table.paste_clicked.connect(self._paste_chain_step)
            chain_lo.addWidget(self.chains_table)
            chain_grp.setLayout(chain_lo)
            layout.addWidget(chain_grp)
            # Убрана группа "Параметры обработки" - она была пустой
            # Три кнопки в один ряд с такими же размерами и отступами как в цепочке обработки
            buttons_layout = QHBoxLayout()
            buttons_layout.setSpacing(30)  # Отступы между кнопками как в цепочке обработки
            buttons_layout.setContentsMargins(0, 10, 0, 10)  # Отступы сверху и снизу по 10px
            btn_before = QPushButton("До обработки")
            btn_before.setMinimumHeight(60)  # Высота как в цепочке обработки
            btn_before.setMinimumWidth(200)  # Ширина как в цепочке обработки
            btn_before.clicked.connect(self._show_before_processing)
            buttons_layout.addWidget(btn_before, 1)  # Растягиваем по горизонтали
            btn_show = QPushButton("Показать после обработки")
            btn_show.setMinimumHeight(60)
            btn_show.setMinimumWidth(200)
            btn_show.clicked.connect(self._show_frame)
            buttons_layout.addWidget(btn_show, 1)
            btn_back = QPushButton("Вернуться к основному изображению")
            btn_back.setMinimumHeight(60)
            btn_back.setMinimumWidth(200)
            btn_back.clicked.connect(self._back_to_main)
            buttons_layout.addWidget(btn_back, 1)
            layout.addLayout(buttons_layout)
        
        # Регуляторы размера окна изображения
        slider_control = SliderControl(
            "image_width", 
            200, 
            2000, 
            1024,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(slider_control)
        
        slider_control = SliderControl(
            "image_height", 
            200, 
            2000, 
            780,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(slider_control)
        
        # Регуляторы обрезки изображения (максимальные значения будут обновляться при получении размера)
        self.crop_top_slider = SliderControl(
            "crop_top", 
            0, 
            2160, 
            0,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(self.crop_top_slider)
        
        self.crop_bottom_slider = SliderControl(
            "crop_bottom", 
            0, 
            2160, 
            2160,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(self.crop_bottom_slider)
        
        self.crop_left_slider = SliderControl(
            "crop_left", 
            0, 
            3840, 
            0,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(self.crop_left_slider)
        
        self.crop_right_slider = SliderControl(
            "crop_right", 
            0, 
            3840, 
            3840,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(self.crop_right_slider)
        
        # Регуляторы HSV нижней границы
        slider_control = SliderControl(
            "hl", 
            0, 
            179, 
            0,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(slider_control)
        
        slider_control = SliderControl(
            "sl", 
            0, 
            255, 
            0,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(slider_control)
        
        slider_control = SliderControl(
            "vl", 
            0, 
            255, 
            0,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(slider_control)
        
        # Регуляторы HSV верхней границы
        slider_control = SliderControl(
            "hm", 
            0, 
            179, 
            179,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(slider_control)
        
        slider_control = SliderControl(
            "sm", 
            0, 
            255, 
            255,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(slider_control)
        
        slider_control = SliderControl(
            "vm", 
            0, 
            255, 
            255,
            ui_elements=self.ui_elements,
            controls=self.controls_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(slider_control)
    
    def _on_camera_combo_changed(self, index):
        if not self.data_manager or index < 0:
            return
        cameras = self.data_manager.get_cameras()
        if 0 <= index < len(cameras):
            self._current_camera_id = cameras[index]
            self.data_manager.set_current_camera(self._current_camera_id)
            self._refresh_region_combo()
            self._refresh_chains_table()
            self._clear_processor_params()

    def _on_region_combo_changed(self, index):
        if not self.data_manager or index < 0:
            return
        regions = self.data_manager.get_regions(self._current_camera_id or "")
        if 0 <= index < len(regions):
            self._current_region_name = regions[index]
            self._refresh_chains_table()
            self._clear_processor_params()

    def _refresh_region_combo(self):
        if not self.data_manager or not self._current_camera_id:
            if hasattr(self, 'region_combo'):
                self.region_combo.blockSignals(True)
                self.region_combo.clear()
                self.region_combo.blockSignals(False)
            return
        regions = self.data_manager.get_regions(self._current_camera_id)
        prev = self._current_region_name
        self.region_combo.blockSignals(True)
        self.region_combo.clear()
        for r in regions:
            self.region_combo.addItem(r)
        idx = regions.index(prev) if prev in regions else 0
        self.region_combo.setCurrentIndex(idx)
        self.region_combo.blockSignals(False)
        if regions:
            self._current_region_name = regions[idx]

    def _refresh_chains_table(self):
        if not self.data_manager or not self._current_camera_id or not self._current_region_name:
            if hasattr(self, 'chains_table'):
                self.chains_table.set_data([])
            return
        try:
            from Services.Operation_crop.registry import REGISTRY
        except Exception:
            REGISTRY = {}
        chain = self.data_manager.get_chains(self._current_camera_id, self._current_region_name)
        rows = []
        for step in chain:
            pid = step.get("processor_id", "?")
            pcls = REGISTRY.get(pid)
            name = pcls().get_name() if pcls else str(pid)
            rows.append({"name": name, "enabled": step.get("enabled", True), "info": step.get("info", "")})
        self.chains_table.set_data(rows)

    def _add_chain_step(self):
        if not self.data_manager or not self._current_camera_id or not self._current_region_name:
            return
        try:
            from Services.Operation_crop.registry import REGISTRY
        except Exception:
            REGISTRY = {}
        processors = list(REGISTRY.items()) if REGISTRY else []
        if not processors:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Выбор процессора")
        dialog_layout = QVBoxLayout()
        dialog.setLayout(dialog_layout)
        dialog_layout.addWidget(QLabel("Выберите процессор:"))
        processor_combo = QComboBox()
        for pid, pcls in processors:
            processor_combo.addItem(pcls().get_name(), pid)
        dialog_layout.addWidget(processor_combo)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        dialog_layout.addWidget(buttons)
        if dialog.exec_() != QDialog.Accepted:
            return
        pid = processor_combo.currentData()
        if pid and self.data_manager.add_chain_step(
            self._current_camera_id, self._current_region_name, pid, params={}, enabled=True
        ):
            self._refresh_chains_table()
            if self.callback:
                self.callback()

    def _delete_chain_step(self):
        row = self.chains_table.currentRow()
        if row < 0 or not self._current_region_name or not self.data_manager or not self._current_camera_id:
            return
        self.data_manager.delete_chain_step(self._current_camera_id, self._current_region_name, row)
        self._refresh_chains_table()
        self._clear_processor_params()
        if self.callback:
            self.callback()

    def _move_chain_step(self, direction):
        row = self.chains_table.currentRow()
        if row < 0 or not self._current_region_name or not self.data_manager or not self._current_camera_id:
            return
        if self.data_manager.move_chain_step(self._current_camera_id, self._current_region_name, row, direction):
            self._refresh_chains_table()
            new_row = max(0, min(row + direction, self.chains_table.table.rowCount() - 1))
            self.chains_table.table.setCurrentCell(new_row, 0)
            if self.callback:
                self.callback()

    def _copy_chain_step(self):
        row = self.chains_table.currentRow()
        if row < 0 or not self._current_region_name or not self.data_manager or not self._current_camera_id:
            return
        chain = self.data_manager.get_chains(self._current_camera_id, self._current_region_name)
        if 0 <= row < len(chain):
            step = chain[row]
            self._chain_step_clipboard = {
                "processor_id": step.get("processor_id"),
                "params": dict(step.get("params", {})),
                "enabled": step.get("enabled", True),
            }

    def _paste_chain_step(self):
        if not self._chain_step_clipboard or not self.data_manager or not self._current_camera_id or not self._current_region_name:
            return
        pid = self._chain_step_clipboard.get("processor_id")
        if not pid:
            return
        self.data_manager.add_chain_step(
            self._current_camera_id, self._current_region_name,
            pid, params=self._chain_step_clipboard.get("params", {}),
            enabled=self._chain_step_clipboard.get("enabled", True)
        )
        self._refresh_chains_table()
        if self.callback:
            self.callback()

    def _on_chain_row_selected(self, row_index):
        if row_index < 0 or not self._current_region_name:
            self._clear_processor_params()
            return
        chain = self.data_manager.get_chains(self._current_camera_id, self._current_region_name)
        if 0 <= row_index < len(chain):
            step = chain[row_index]
            self._show_processor_params(step.get("processor_id"), step.get("params", {}))

    def _on_chain_cell_changed(self, row_index, column_key, value):
        if not self._current_region_name or column_key != "enabled":
            return
        if self.data_manager and self._current_camera_id:
            self.data_manager.update_chain_step(
                self._current_camera_id, self._current_region_name, row_index, enabled=value
            )
        if self.callback:
            self.callback()

    def _show_processor_params(self, processor_id, params):
        self._clear_processor_params()
        # Параметры обработки больше не отображаются, так как группа была удалена
        if not hasattr(self, 'params_layout'):
            return
        try:
            from Services.Operation_crop.registry import REGISTRY
            from PyQt5.QtWidgets import QSpinBox
        except Exception:
            REGISTRY = {}
            return
        pcls = REGISTRY.get(processor_id)
        if not pcls:
            return
        proc = pcls()
        schema = proc.get_params_schema()
        w = QWidget()
        fl = QFormLayout()
        w.setLayout(fl)
        for param in schema:
            key = param.get("key")
            typ = param.get("type")
            default = param.get("default")
            cur = params.get(key, default)
            if typ == "int":
                sp = QSpinBox()
                sp.setRange(param.get("min", 0), param.get("max", 255))
                sp.setValue(int(cur))
                sp.valueChanged.connect(lambda v, k=key: self._update_processor_param(k, v))
                fl.addRow(key + ":", sp)
            elif typ == "combo":
                from PyQt5.QtWidgets import QComboBox
                cb = QComboBox()
                cb.addItems(param.get("options", []))
                cb.setCurrentText(str(cur))
                cb.currentTextChanged.connect(lambda v, k=key: self._update_processor_param(k, v))
                fl.addRow(key + ":", cb)
        self.params_layout.addWidget(w)
        self._current_processor_params_widget = w

    def _clear_processor_params(self):
        if not hasattr(self, 'params_layout'):
            return
        while self.params_layout.count():
            child = self.params_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._current_processor_params_widget = None

    def _update_processor_param(self, param_key, value):
        if not self._current_region_name or not self.data_manager or not self._current_camera_id:
            return
        row = self.chains_table.currentRow()
        if row < 0:
            return
        chain = self.data_manager.get_chains(self._current_camera_id, self._current_region_name)
        if 0 <= row < len(chain):
            params = dict(chain[row].get("params", {}))
            params[param_key] = value
            self.data_manager.update_chain_step(
                self._current_camera_id, self._current_region_name, row, params=params
            )
        if self.callback:
            self.callback()

    def _show_before_processing(self):
        """Показать изображение до обработки"""
        if not self._current_region_name or not self.controls_post_processing:
            return
        self.controls_post_processing["view_mode"] = "region"
        self.controls_post_processing["selected_region"] = self._current_region_name
        self.controls_post_processing["show_region_processed"] = False
        if self.callback_post_processing:
            self.callback_post_processing()
        if self.callback:
            self.callback()

    def _show_frame(self):
        if not self._current_region_name or not self.controls_post_processing:
            return
        self.controls_post_processing["view_mode"] = "region"
        self.controls_post_processing["selected_region"] = self._current_region_name
        self.controls_post_processing["show_region_processed"] = True
        if self.callback_post_processing:
            self.callback_post_processing()
        if self.callback:
            self.callback()

    def _back_to_main(self):
        if not self.controls_post_processing:
            return
        self.controls_post_processing["view_mode"] = "main"
        self.controls_post_processing["selected_region"] = None
        self.controls_post_processing["show_region_processed"] = False
        if self.callback_post_processing:
            self.callback_post_processing()
        if self.callback:
            self.callback()

    def showEvent(self, event):
        super().showEvent(event)
        if self.data_manager:
            cameras = self.data_manager.get_cameras()
            self.camera_combo.clear()
            for cid in cameras:
                c = self.data_manager.get_camera(cid)
                self.camera_combo.addItem(c.get("name", cid), cid)
            if cameras and not self._current_camera_id:
                self._current_camera_id = cameras[0]
                self.data_manager.set_current_camera(self._current_camera_id)
                self.camera_combo.setCurrentIndex(0)
            elif self._current_camera_id and self._current_camera_id in cameras:
                self.camera_combo.setCurrentIndex(cameras.index(self._current_camera_id))
            self._refresh_region_combo()
            self._refresh_chains_table()
    
    def update_image_size(self, width, height):
        """Обновляет максимальные значения слайдеров обрезки при получении размера изображения"""
        if hasattr(self, 'crop_top_slider') and height > 0:
            self.crop_top_slider.slider.setMaximum(height)
        if hasattr(self, 'crop_bottom_slider') and height > 0:
            self.crop_bottom_slider.slider.setMaximum(height)
            if self.controls_processing.get('crop_bottom', 0) == 0 or self.controls_processing.get('crop_bottom', 0) > height:
                self.controls_processing['crop_bottom'] = height
                self.crop_bottom_slider.slider.setValue(height)
        if hasattr(self, 'crop_left_slider') and width > 0:
            self.crop_left_slider.slider.setMaximum(width)
        if hasattr(self, 'crop_right_slider') and width > 0:
            self.crop_right_slider.slider.setMaximum(width)
            if self.controls_processing.get('crop_right', 0) == 0 or self.controls_processing.get('crop_right', 0) > width:
                self.controls_processing['crop_right'] = width
                self.crop_right_slider.slider.setValue(width)
    
    def get_params(self):
        """Возвращает словарь всех параметров этого виджета для сохранения/загрузки рецептов"""
        return dict(self.controls_processing) if self.controls_processing else {}
    
    def apply_params(self, params_dict):
        """Применяет параметры из словаря к элементам UI виджета"""
        if not params_dict or not self.ui_elements:
            return
        
        for param_name, param_value in params_dict.items():
            if param_name in self.ui_elements:
                element_data = self.ui_elements[param_name]
                element = element_data['element']
                transfer_k = element_data.get('transfer_k', 1)
                
                try:
                    from PyQt5.QtWidgets import QSlider, QCheckBox
                    if isinstance(element, QSlider):
                        value = float(param_value)
                        value = value / transfer_k
                        element.setValue(int(round(value)))
                    elif isinstance(element, QCheckBox):
                        value = str(param_value).lower() in ['true', '1', 'yes']
                        element.setChecked(value)
                except Exception as e:
                    print(f"Ошибка установки значения для {param_name}: {e}")
