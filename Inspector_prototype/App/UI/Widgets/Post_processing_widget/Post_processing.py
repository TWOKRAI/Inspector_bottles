from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QComboBox, QGroupBox, QFormLayout,
                             QLineEdit, QSpinBox, QListWidget, QListWidgetItem,
                             QTableWidget, QTableWidgetItem, QCheckBox, QHeaderView,
                             QMessageBox, QSplitter)
from PyQt5.QtCore import Qt
from App.Components.checkbox import CheckboxControl
from App.Components.table_with_toolbar import TableWithToolbar


class PostProcessingWidget(QWidget):
    def __init__(self, window_manager=None, ui_elements=None, controls_post_processing=None, callback=None, data_manager=None):
        super().__init__()
        self.window_manager = window_manager
        self.ui_elements = ui_elements
        self.controls_post_processing = controls_post_processing
        self.callback = callback
        self.data_manager = data_manager  # DataManager для работы с многоуровневой структурой
        self._selected_region_edit_idx = -1
        self._selected_chain_step_idx = -1
        self._current_processor_params_widget = None
        self._current_camera_id = None
        self._current_region_name = None
        self._chain_step_clipboard = None  # буфер для копирования звена цепочки

        # Подключаем сигналы DataManager если он есть
        if self.data_manager:
            self.data_manager.camera_changed.connect(self._on_camera_changed)
            self.data_manager.region_changed.connect(self._on_region_changed_in_manager)
            self.data_manager.chain_changed.connect(self._on_chain_changed_in_manager)
        
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Убран чекбокс enable_post_processing - он не нужен здесь

        # Режим просмотра объединен с таблицей регионов - при выборе региона автоматически показывается

        # Убрана правая часть с цепочками обработки - она есть во вкладке "Обработка"
        # Левая часть: список камер и регионов
        left_widget = QWidget()
        left_layout = QVBoxLayout()
        left_widget.setLayout(left_layout)
        
        # Выпадающий список камер вверху (камеры создаются в HikvisionWidget)
        if self.data_manager:
            camera_select_row = QHBoxLayout()
            camera_select_row.addWidget(QLabel("Камера:"))
            self.camera_combo = QComboBox()
            self.camera_combo.currentIndexChanged.connect(self._on_camera_combo_changed)
            camera_select_row.addWidget(self.camera_combo, 1)
            left_layout.addLayout(camera_select_row)
            self._refresh_camera_combo()

        self._copied_region = None

        # Таблица регионов с тулбаром: Добавить, Удалить, Вверх, Вниз, Копировать, Вставить
        regions_group = QGroupBox("Регионы / Изображения")
        regions_layout = QVBoxLayout()
        self.regions_table = TableWithToolbar(
            columns=[
                {"key": "name", "label": "Название", "type": "text"},
                {"key": "enabled", "label": "Вкл.", "type": "checkbox"},
                {"key": "is_main", "label": "Главный", "type": "checkbox"},
                {"key": "processing_enabled", "label": "Обработка", "type": "checkbox"},
                {"key": "coords", "label": "Координаты", "type": "text"},
            ],
            parent=self,
            show_add_delete=True, show_move=True, show_copy_paste=True
        )
        self.regions_table.set_row_key("name")
        self.regions_table.table.cell_changed.connect(self._on_region_table_cell_changed)
        self.regions_table.row_selected.connect(self._on_region_table_row_selected)
        self.regions_table.add_clicked.connect(self._create_region)
        self.regions_table.delete_clicked.connect(self._delete_region)
        self.regions_table.move_up_clicked.connect(lambda: self._move_region(-1))
        self.regions_table.move_down_clicked.connect(lambda: self._move_region(1))
        self.regions_table.copy_clicked.connect(self._copy_region)
        self.regions_table.paste_clicked.connect(self._paste_region)
        regions_layout.addWidget(self.regions_table)
        
        # Кнопки "Показать" и "Вернуться к основному" на одном уровне как кнопки тулбара
        view_buttons_layout = QHBoxLayout()
        view_buttons_layout.setSpacing(30)  # Отступы между кнопками как в тулбаре
        view_buttons_layout.setContentsMargins(0, 10, 0, 10)  # Отступы сверху и снизу по 10px
        btn_show_region = QPushButton("Показать")
        btn_show_region.setMinimumHeight(60)  # Высота как в тулбаре
        btn_show_region.setMinimumWidth(200)  # Ширина как в тулбаре
        btn_show_region.clicked.connect(self._show_region)
        view_buttons_layout.addWidget(btn_show_region, 1)  # Растягиваем по горизонтали
        
        btn_back_to_main = QPushButton("Вернуться к основному")
        btn_back_to_main.setMinimumHeight(60)
        btn_back_to_main.setMinimumWidth(200)
        btn_back_to_main.clicked.connect(self._back_to_main)
        view_buttons_layout.addWidget(btn_back_to_main, 1)
        view_buttons_layout.addStretch()
        regions_layout.addLayout(view_buttons_layout)
        
        regions_group.setLayout(regions_layout)
        left_layout.addWidget(regions_group)
        
        # Форма редактирования региона
        edit_group = QGroupBox("Редактирование региона")
        edit_layout = QFormLayout()
        self.region_name_edit = QLineEdit()
        self.region_name_edit.setPlaceholderText("Имя региона")
        edit_layout.addRow("Имя:", self.region_name_edit)
        
        self.region_x1 = QSpinBox()
        self.region_x1.setRange(0, 10000)
        self.region_x1.valueChanged.connect(self._update_region_coords_from_spinboxes)
        edit_layout.addRow("x1:", self.region_x1)
        
        self.region_y1 = QSpinBox()
        self.region_y1.setRange(0, 10000)
        self.region_y1.valueChanged.connect(self._update_region_coords_from_spinboxes)
        edit_layout.addRow("y1:", self.region_y1)
        
        self.region_x2 = QSpinBox()
        self.region_x2.setRange(0, 10000)
        self.region_x2.valueChanged.connect(self._update_region_coords_from_spinboxes)
        edit_layout.addRow("x2:", self.region_x2)
        
        self.region_y2 = QSpinBox()
        self.region_y2.setRange(0, 10000)
        self.region_y2.valueChanged.connect(self._update_region_coords_from_spinboxes)
        edit_layout.addRow("y2:", self.region_y2)
        
        # Чекбоксы региона
        self.region_enabled_checkbox = QCheckBox("Включен")
        self.region_enabled_checkbox.stateChanged.connect(self._on_region_enabled_changed)
        edit_layout.addRow("", self.region_enabled_checkbox)
        
        self.region_is_main_checkbox = QCheckBox("Основное изображение")
        self.region_is_main_checkbox.stateChanged.connect(self._on_region_is_main_changed)
        edit_layout.addRow("", self.region_is_main_checkbox)
        
        self.region_processing_enabled_checkbox = QCheckBox("Включить обработку")
        self.region_processing_enabled_checkbox.stateChanged.connect(self._on_region_processing_enabled_changed)
        edit_layout.addRow("", self.region_processing_enabled_checkbox)
        
        edit_group.setLayout(edit_layout)
        left_layout.addWidget(edit_group)
        
        # Убрана правая часть с цепочками обработки - она есть во вкладке "Обработка"
        layout.addWidget(left_widget)
        self._refresh_regions_ui()
    
    # Метод _on_view_image_changed удален - режим просмотра объединен с таблицей регионов
    
    def _create_region(self):
        """Создать новый регион (копировать текущий если выбран)"""
        if self.data_manager and self._current_camera_id:
            row = self.regions_table.currentRow()
            if row >= 0:
                rd = self.regions_table.get_row_data(row)
                if rd:
                    src = self.data_manager.get_region(self._current_camera_id, rd.get("name"))
                    if src:
                        name = f"{rd.get('name', 'region')}_copy"
                        self.data_manager.add_region(
                            self._current_camera_id, name,
                            x1=src.get("x1", 100), y1=src.get("y1", 50),
                            x2=src.get("x2", 300), y2=src.get("y2", 200),
                            enabled=src.get("enabled", True),
                            processing_enabled=src.get("processing_enabled", True),
                        )
                        self._refresh_regions_ui()
                        idx = self.data_manager.get_regions(self._current_camera_id).index(name)
                        self.regions_table.table.setCurrentCell(idx, 0)
                        if self.callback:
                            self.callback()
                        return
            name = f"region_{len(self.data_manager.get_regions(self._current_camera_id)) + 1}"
            self.data_manager.add_region(self._current_camera_id, name, x1=100, y1=50, x2=300, y2=200)
            self._refresh_regions_ui()
            idx = self.data_manager.get_regions(self._current_camera_id).index(name)
            self.regions_table.table.setCurrentCell(idx, 0)
            if self.callback:
                self.callback()
            return
        if not self.controls_post_processing:
            return
        row = self.regions_table.currentRow()
        source_region = None
        if row >= 0:
            regions = self.controls_post_processing.get("regions", [])
            if 0 <= row < len(regions):
                source_region = self._region_to_dict(regions[row]).copy()
                source_region["name"] = f"{source_region['name']}_copy"
        new_region = source_region or {
            "name": f"region_{len(self.controls_post_processing.get('regions', [])) + 1}",
            "x1": 100, "y1": 50, "x2": 300, "y2": 200,
            "enabled": True, "processor_id": 1
        }
        self.controls_post_processing.setdefault("regions", []).append(new_region)
        self.controls_post_processing.setdefault("region_chains", {})[new_region["name"]] = []
        self._refresh_regions_ui()
        last_row = len(self.controls_post_processing["regions"]) - 1
        if last_row >= 0:
            self.regions_table.table.setCurrentCell(last_row, 0)
        if self.callback:
            self.callback()
    
    def _save_current_region(self):
        """Сохранить текущий регион (удален - данные сохраняются автоматически при изменении)"""
        # Данные сохраняются автоматически через DataManager при изменении полей
        pass
    
    def _delete_region(self):
        """Удалить выбранный регион с подтверждением"""
        row = self.regions_table.currentRow()
        if row < 0:
            return
        if self.data_manager and self._current_camera_id:
            rd = self.regions_table.get_row_data(row)
            if not rd:
                return
            name = rd.get("name")
            if not name or name == "main_image":
                QMessageBox.warning(self, "Ошибка", "Нельзя удалить основной регион.")
                return
            reply = QMessageBox.question(
                self, "Подтверждение удаления",
                f"Вы уверены, что хотите удалить регион '{name}'?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.data_manager.delete_region(self._current_camera_id, name)
                self._refresh_regions_ui()
                if self.callback:
                    self.callback()
            return
        if not self.controls_post_processing:
            return
        regions = self.controls_post_processing.get("regions", [])
        if 0 <= row < len(regions):
            region = self._region_to_dict(regions[row])
            name = region["name"]
            reply = QMessageBox.question(
                self, "Подтверждение удаления",
                f"Вы уверены, что хотите удалить регион '{name}'?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                regions.pop(row)
                self.controls_post_processing.get("region_chains", {}).pop(name, None)
                self._refresh_regions_ui()
                if self.callback:
                    self.callback()

    def _move_region(self, direction):
        """Переместить выбранный регион вверх (direction=-1) или вниз (direction=1)."""
        if not self.data_manager or not self._current_camera_id:
            return
        row = self.regions_table.currentRow()
        if row < 0:
            return
        rd = self.regions_table.get_row_data(row)
        if not rd:
            return
        name = rd.get("name")
        if not name:
            return
        if self.data_manager.move_region(self._current_camera_id, name, direction):
            self._refresh_regions_ui()
            regions = self.data_manager.get_regions(self._current_camera_id)
            new_idx = regions.index(name) if name in regions else row
            self.regions_table.table.setCurrentCell(new_idx, 0)
            if self.callback:
                self.callback()

    def _on_region_table_cell_changed(self, row_index, column_key, value):
        """Изменение ячейки в таблице регионов (чекбоксы Вкл./Главный/Обработка)."""
        if not self.data_manager or not self._current_camera_id:
            return
        row = self.regions_table.get_row_data(row_index)
        if not row:
            return
        region_name = row.get("name")
        if not region_name:
            return
        self.data_manager.update_region(
            self._current_camera_id, region_name, **{column_key: value}
        )
        
        # Если изменился чекбокс "Обработка" и регион сейчас показан, обновляем отображение
        if column_key == "processing_enabled" and self._current_region_name == region_name:
            if self.controls_post_processing and self.controls_post_processing.get("view_mode") == "region":
                self._show_region(show_processed=value)
        
        if self.callback:
            self.callback()

    def _on_region_table_row_selected(self, row_index):
        """При выборе строки региона — загрузить форму, цепочки и автоматически показать регион."""
        if self.data_manager and self._current_camera_id:
            row = self.regions_table.get_row_data(row_index)
            if row:
                self._current_region_name = row.get("name")
                self._refresh_chains_table(self._current_region_name)
                self._load_region_to_form(self._current_region_name)
                # Автоматически показываем регион при выборе
                self._auto_show_region()
            return
        self._on_region_selected_legacy()

    def _on_region_selected_legacy(self):
        """Выбор региона при работе без DataManager."""
        if not self.controls_post_processing:
            return
        row = self.regions_table.currentRow()
        if row < 0:
            return
        regions = self.controls_post_processing.get("regions", [])
        if 0 <= row < len(regions):
            r = self._region_to_dict(regions[row])
            self.region_name_edit.setText(r.get("name", ""))
            self.region_x1.setValue(r.get("x1", 0))
            self.region_y1.setValue(r.get("y1", 0))
            self.region_x2.setValue(r.get("x2", 0))
            self.region_y2.setValue(r.get("y2", 0))
            self.region_enabled_checkbox.setChecked(r.get("enabled", True))
            self._refresh_chains_table(r.get("name", ""))
    
    def _on_region_selected(self):
        """При выборе региона - загрузить данные и обновить цепочки"""
        if not self.controls_post_processing:
            return
        
        row = self.regions_table.currentRow()
        self._selected_region_edit_idx = row
        
        if row < 0:
            return
        
        if self.data_manager and self._current_camera_id:
            rd = self.regions_table.get_row_data(row)
            if rd:
                self._current_region_name = rd.get("name")
                self._refresh_chains_table(self._current_region_name)
                self._load_region_to_form(self._current_region_name)
            return
        
        regions = self.controls_post_processing.get("regions", [])
        if 0 <= row < len(regions):
            r = self._region_to_dict(regions[row])
            
            # Загружаем данные региона в форму
            self.region_name_edit.blockSignals(True)
            self.region_x1.blockSignals(True)
            self.region_y1.blockSignals(True)
            self.region_x2.blockSignals(True)
            self.region_y2.blockSignals(True)
            self.region_enabled_checkbox.blockSignals(True)
            
            self.region_name_edit.setText(r.get("name", ""))
            self.region_x1.setValue(r.get("x1", 0))
            self.region_y1.setValue(r.get("y1", 0))
            self.region_x2.setValue(r.get("x2", 0))
            self.region_y2.setValue(r.get("y2", 0))
            self.region_enabled_checkbox.setChecked(r.get("enabled", True))
            
            self.region_name_edit.blockSignals(False)
            self.region_x1.blockSignals(False)
            self.region_y1.blockSignals(False)
            self.region_x2.blockSignals(False)
            self.region_y2.blockSignals(False)
            self.region_enabled_checkbox.blockSignals(False)
            
            # Обновляем таблицу цепочек для выбранного региона
            self._refresh_chains_table(r.get("name", ""))
    
    def _refresh_chains_table(self, region_name):
        """Обновить таблицу цепочек для выбранного региона (универсальная таблица)."""
        # Таблица цепочек удалена - она есть во вкладке "Обработка"
        pass
    
    def _on_chain_table_cell_changed(self, row_index, column_key, value):
        """Изменение ячейки в таблице цепочек (чекбокс Включено)."""
        if not self._current_region_name:
            return
        if self.data_manager and self._current_camera_id:
            self.data_manager.update_chain_step(
                self._current_camera_id, self._current_region_name, row_index, enabled=value
            )
        else:
            chain = self.controls_post_processing.get("region_chains", {}).get(self._current_region_name, [])
            if 0 <= row_index < len(chain):
                chain[row_index]["enabled"] = value
        if self.callback:
            self.callback()

    def _on_chain_step_selected_from_table(self, row_index):
        """При выборе звена цепочки — показать параметры (вызов из таблицы)."""
        self._on_chain_step_selected_impl(row_index)

    def _on_chain_step_selected(self):
        """При выборе звена цепочки — показать его параметры (совместимость)."""
        # Таблица цепочек удалена - она есть во вкладке "Обработка"
        pass

    def _on_chain_step_selected_impl(self, row):
        """Показать параметры выбранного шага цепочки."""
        if row < 0:
            self._clear_processor_params()
            return
        region_name = self._current_region_name
        if not region_name:
            rd = self.regions_table.get_current_row_data()
            if rd:
                region_name = rd.get("name")
        if not region_name:
            return
        if self.data_manager and self._current_camera_id:
            chain = self.data_manager.get_chains(self._current_camera_id, region_name)
        else:
            chain = self.controls_post_processing.get("region_chains", {}).get(region_name, [])
        if 0 <= row < len(chain):
            step = chain[row]
            self._show_processor_params(step.get("processor_id"), step.get("params", {}))
    
    def _show_processor_params(self, processor_id, params):
        """Показать параметры процессора"""
        self._clear_processor_params()
        
        from Services.Operation_crop.registry import REGISTRY
        processor_class = REGISTRY.get(processor_id)
        
        if not processor_class:
            return
        
        processor = processor_class()
        schema = processor.get_params_schema()
        
        # Создаем виджет для параметров
        params_widget = QWidget()
        params_layout = QFormLayout()
        params_widget.setLayout(params_layout)
        
        # Заполняем параметры из схемы
        for param in schema:
            param_key = param.get("key")
            param_type = param.get("type")
            param_default = param.get("default")
            current_value = params.get(param_key, param_default)
            
            if param_type == "int":
                spinbox = QSpinBox()
                spinbox.setRange(param.get("min", 0), param.get("max", 255))
                spinbox.setValue(int(current_value))
                spinbox.valueChanged.connect(lambda val, key=param_key: self._update_processor_param(key, val))
                params_layout.addRow(param_key + ":", spinbox)
            elif param_type == "combo":
                combo = QComboBox()
                combo.addItems(param.get("options", []))
                combo.setCurrentText(str(current_value))
                combo.currentTextChanged.connect(lambda val, key=param_key: self._update_processor_param(key, val))
                params_layout.addRow(param_key + ":", combo)
        
        self.params_layout.addWidget(params_widget)
        self._current_processor_params_widget = params_widget
    
    def _clear_processor_params(self):
        """Очистить виджет параметров"""
        while self.params_layout.count():
            child = self.params_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._current_processor_params_widget = None
    
    def _update_processor_param(self, param_key, value):
        """Обновить параметр процессора в цепочке"""
        # Таблица цепочек удалена - она есть во вкладке "Обработка"
        return
        region_name = self._current_region_name
        if not region_name:
            rd = self.regions_table.get_current_row_data()
            region_name = rd.get("name") if rd else None
        if not region_name:
            return
        if self.data_manager and self._current_camera_id:
            chain = self.data_manager.get_chains(self._current_camera_id, region_name)
            if 0 <= row < len(chain):
                params = dict(chain[row].get("params", {}))
                params[param_key] = value
                self.data_manager.update_chain_step(
                    self._current_camera_id, region_name, row, params=params
                )
                if self.callback:
                    self.callback()
            return
        chain = self.controls_post_processing.get("region_chains", {}).get(region_name, [])
        if 0 <= row < len(chain):
            if "params" not in chain[row]:
                chain[row]["params"] = {}
            chain[row]["params"][param_key] = value
            if self.callback:
                self.callback()
    
    def _on_chain_enabled_changed(self, row, state):
        """Обработчик изменения состояния чекбокса включения звена"""
        region_row = self.regions_table.currentRow()
        if region_row < 0:
            return
        
        regions = self.controls_post_processing.get("regions", [])
        if 0 <= region_row < len(regions):
            region = self._region_to_dict(regions[region_row])
            region_name = region.get("name", "")
            chain = self.controls_post_processing.get("region_chains", {}).get(region_name, [])
            
            if 0 <= row < len(chain):
                chain[row]["enabled"] = (state == Qt.Checked)
                if self.callback:
                    self.callback()
    
    def _on_chain_table_changed(self, row, column):
        """Обработчик изменения таблицы цепочек"""
        pass
    
    def _add_chain_step(self):
        """Добавить звено в цепочку"""
        # Таблица цепочек удалена - она есть во вкладке "Обработка"
        pass
    
    def _remove_chain_step(self):
        """Удалить звено из цепочки"""
        # Таблица цепочек удалена - она есть во вкладке "Обработка"
        pass

    def _move_chain_step(self, direction):
        """Переместить звено цепочки вверх (direction=-1) или вниз (direction=1)."""
        # Таблица цепочек удалена - она есть во вкладке "Обработка"
        pass

    def _copy_chain_step(self):
        """Скопировать выбранное звено цепочки в буфер."""
        # Таблица цепочек удалена - она есть во вкладке "Обработка"
        pass

    def _paste_chain_step(self):
        """Вставить звено из буфера в цепочку."""
        # Таблица цепочек удалена - она есть во вкладке "Обработка"
        pass

    def _update_region_coords_from_spinboxes(self):
        """Обновить координаты региона из полей ввода"""
        if self.data_manager and self._current_camera_id and self._current_region_name:
            self.data_manager.update_region(
                self._current_camera_id, self._current_region_name,
                x1=self.region_x1.value(), y1=self.region_y1.value(),
                x2=self.region_x2.value(), y2=self.region_y2.value(),
            )
            self._refresh_regions_ui()
            if self.callback:
                self.callback()
            return
        row = self.regions_table.currentRow()
        if row < 0 or not self.controls_post_processing:
            return
        regions = self.controls_post_processing.get("regions", [])
        if 0 <= row < len(regions):
            r = self._region_to_dict(regions[row])
            r["x1"] = self.region_x1.value()
            r["y1"] = self.region_y1.value()
            r["x2"] = self.region_x2.value()
            r["y2"] = self.region_y2.value()
            r["name"] = self.region_name_edit.text().strip() or r.get("name", "region")
            regions[row] = r
            if self.callback:
                self.callback()
    
    def _on_region_enabled_changed(self, state):
        """Обработчик изменения состояния включения региона"""
        row = self.regions_table.currentRow()
        if row < 0:
            return
        
        regions = self.controls_post_processing.get("regions", [])
        if 0 <= row < len(regions):
            r = self._region_to_dict(regions[row])
            r["enabled"] = (state == Qt.Checked)
            regions[row] = r
            
            if self.callback:
                self.callback()
    
    def _region_to_dict(self, r):
        """Привести элемент региона к виду словаря"""
        if isinstance(r, dict):
            return r
        return {"name": str(r), "x1": 0, "y1": 0, "x2": 0, "y2": 0, "enabled": True, "processor_id": 1}
    
    def _refresh_regions_ui(self):
        """Обновить UI списка регионов и режима просмотра"""
        # Работаем с DataManager если он есть, иначе с controls_post_processing
        if self.data_manager and self._current_camera_id:
            # Обновляем таблицу регионов из DataManager
            regions = self.data_manager.get_regions(self._current_camera_id)
            rows = []
            for region_name in regions:
                region = self.data_manager.get_region(self._current_camera_id, region_name)
                x1, y1 = region.get("x1", 0), region.get("y1", 0)
                x2, y2 = region.get("x2", 0), region.get("y2", 0)
                rows.append({
                    "name": region_name,
                    "enabled": region.get("enabled", True),
                    "is_main": region.get("is_main", False),
                    "processing_enabled": region.get("processing_enabled", True),
                    "coords": f"({x1},{y1})-({x2},{y2})",
                })
            self.regions_table.set_data(rows)
            
            # Обновляем таблицу цепочек если выбран регион (удалена - она во вкладке "Обработка")
            row = self.regions_table.currentRow()
            if row >= 0 and 0 <= row < len(regions):
                region_name = regions[row]
                self._current_region_name = region_name
                # Загружаем данные региона в форму редактирования
                self._load_region_to_form(region_name)
        elif self.controls_post_processing:
            # Старый способ: таблица из controls_post_processing
            regions = self.controls_post_processing.get("regions", [])
            rows = []
            for r in regions:
                d = self._region_to_dict(r)
                rows.append({
                    "name": d.get("name", ""),
                    "enabled": d.get("enabled", True),
                    "is_main": d.get("is_main", False),
                    "processing_enabled": d.get("processing_enabled", True),
                    "coords": f"({d['x1']},{d['y1']})-({d['x2']},{d['y2']})",
                })
            self.regions_table.set_data(rows)
    
    def _load_region_to_form(self, region_name):
        """Загрузить данные региона в форму редактирования"""
        if not self.data_manager or not self._current_camera_id:
            return
        
        region = self.data_manager.get_region(self._current_camera_id, region_name)
        if not region:
            return
        
        # Блокируем сигналы чтобы не вызывать обновления при загрузке
        self.region_name_edit.blockSignals(True)
        self.region_x1.blockSignals(True)
        self.region_y1.blockSignals(True)
        self.region_x2.blockSignals(True)
        self.region_y2.blockSignals(True)
        self.region_enabled_checkbox.blockSignals(True)
        self.region_is_main_checkbox.blockSignals(True)
        self.region_processing_enabled_checkbox.blockSignals(True)
        
        self.region_name_edit.setText(region_name)
        self.region_x1.setValue(region.get("x1", 0))
        self.region_y1.setValue(region.get("y1", 0))
        self.region_x2.setValue(region.get("x2", 0))
        self.region_y2.setValue(region.get("y2", 0))
        self.region_enabled_checkbox.setChecked(region.get("enabled", True))
        self.region_is_main_checkbox.setChecked(region.get("is_main", False))
        self.region_processing_enabled_checkbox.setChecked(region.get("processing_enabled", True))
        
        # Разблокируем сигналы
        self.region_name_edit.blockSignals(False)
        self.region_x1.blockSignals(False)
        self.region_y1.blockSignals(False)
        self.region_x2.blockSignals(False)
        self.region_y2.blockSignals(False)
        self.region_enabled_checkbox.blockSignals(False)
        self.region_is_main_checkbox.blockSignals(False)
        self.region_processing_enabled_checkbox.blockSignals(False)
    
    def get_params(self):
        """Возвращает словарь всех параметров этого виджета для сохранения/загрузки рецептов"""
        if not self.controls_post_processing:
            return {}
        
        params = dict(self.controls_post_processing)
        # Сериализуем списки и словари в строки для Excel
        if 'regions' in params:
            import json
            params['regions'] = json.dumps(params['regions'])
        if 'region_chains' in params:
            import json
            params['region_chains'] = json.dumps(params['region_chains'])
        
        return params
    
    def apply_params(self, params_dict):
        """Применяет параметры из словаря к элементам UI виджета"""
        if not params_dict or not self.controls_post_processing:
            return
        
        # Десериализуем сложные структуры
        import json
        for key, value in params_dict.items():
            if key in ['regions', 'region_chains']:
                try:
                    if isinstance(value, str):
                        self.controls_post_processing[key] = json.loads(value)
                    else:
                        self.controls_post_processing[key] = value
                except:
                    self.controls_post_processing[key] = [] if key == 'regions' else {}
            else:
                self.controls_post_processing[key] = value
        
        # Обновляем списки регионов
        self._refresh_regions_ui()
    
    def _on_camera_combo_changed(self, index):
        """Обработчик изменения выбранной камеры в выпадающем списке"""
        if not self.data_manager or not hasattr(self, 'camera_combo'):
            return
        
        camera_id = self.camera_combo.itemData(index)
        if camera_id:
            self._current_camera_id = camera_id
            self.data_manager.set_current_camera(camera_id)
            self._refresh_regions_ui()
    
    def _refresh_camera_combo(self):
        """Обновить выпадающий список камер из DataManager"""
        if not self.data_manager or not hasattr(self, 'camera_combo'):
            return
        
        current_camera_id = self._current_camera_id or self.data_manager.get_current_camera_id()
        
        self.camera_combo.blockSignals(True)
        self.camera_combo.clear()
        
        cameras = self.data_manager.get_cameras()
        for camera_id in cameras:
            camera = self.data_manager.get_camera(camera_id)
            camera_name = camera.get("name", camera_id)
            self.camera_combo.addItem(camera_name, camera_id)
        
        # Устанавливаем текущую камеру
        if current_camera_id and current_camera_id in cameras:
            index = cameras.index(current_camera_id)
            self.camera_combo.setCurrentIndex(index)
        elif cameras:
            # Если текущая камера не установлена, выбираем первую
            self._current_camera_id = cameras[0]
            self.data_manager.set_current_camera(cameras[0])
            self.camera_combo.setCurrentIndex(0)
        
        self.camera_combo.blockSignals(False)
    
    def _on_camera_changed(self, camera_id):
        """Обработчик изменения камеры из DataManager"""
        if camera_id == self._current_camera_id:
            self._refresh_regions_ui()
        self._refresh_camera_combo()
    
    def _on_region_changed_in_manager(self, camera_id, region_name):
        """Обработчик изменения региона из DataManager"""
        if camera_id == self._current_camera_id:
            self._refresh_regions_ui()
    
    def _on_chain_changed_in_manager(self, camera_id, region_name):
        """Обработчик изменения цепочки из DataManager"""
        if camera_id == self._current_camera_id and region_name == self._current_region_name:
            self._refresh_chains_table(region_name)
    
    def _copy_region(self):
        """Копировать выбранный регион в буфер"""
        if not self.data_manager or not self._current_camera_id:
            return
        
        row = self.regions_table.currentRow()
        if row >= 0:
            rd = self.regions_table.get_row_data(row)
            if rd:
                region_name = rd.get("name")
                if region_name:
                    self._copied_region = {
                        "camera_id": self._current_camera_id,
                        "region_name": region_name
                    }
                    QMessageBox.information(self, "Информация", f"Регион '{region_name}' скопирован")
    
    def _paste_region(self):
        """Вставить регион из буфера в текущую камеру"""
        if not self.data_manager or not self._copied_region:
            QMessageBox.warning(self, "Предупреждение", "Нет скопированного региона")
            return
        
        if not self._current_camera_id:
            QMessageBox.warning(self, "Предупреждение", "Выберите камеру")
            return
        
        source_camera_id = self._copied_region["camera_id"]
        source_region_name = self._copied_region["region_name"]
        
        # Генерируем новое имя для региона
        target_region_name = f"{source_region_name}_copy"
        counter = 1
        while target_region_name in self.data_manager.get_regions(self._current_camera_id):
            target_region_name = f"{source_region_name}_copy_{counter}"
            counter += 1
        
        if self.data_manager.copy_region(source_camera_id, source_region_name, self._current_camera_id, target_region_name):
            self._refresh_regions_ui()
            QMessageBox.information(self, "Информация", f"Регион вставлен как '{target_region_name}'")
        else:
            QMessageBox.warning(self, "Ошибка", "Не удалось вставить регион")
    
    def _on_region_is_main_changed(self, state):
        """Обработчик изменения чекбокса is_main"""
        if not self.data_manager or not self._current_camera_id or not self._current_region_name:
            return
        
        is_main = (state == Qt.Checked)
        self.data_manager.update_region(self._current_camera_id, self._current_region_name, is_main=is_main)
        self._refresh_regions_ui()
    
    def _on_region_processing_enabled_changed(self, state):
        """Обработчик изменения чекбокса processing_enabled"""
        if not self.data_manager or not self._current_camera_id or not self._current_region_name:
            return
        
        processing_enabled = (state == Qt.Checked)
        self.data_manager.update_region(self._current_camera_id, self._current_region_name, processing_enabled=processing_enabled)
    
    def _auto_show_region(self):
        """Автоматически показать регион при выборе в таблице"""
        if not self.data_manager or not self._current_camera_id or not self._current_region_name:
            return
        
        # Получаем состояние чекбокса "Обработка" из таблицы
        row = self.regions_table.currentRow()
        if row >= 0:
            row_data = self.regions_table.get_row_data(row)
            processing_enabled = row_data.get("processing_enabled", False) if row_data else False
            
            # Показываем регион с учетом состояния обработки
            self._show_region(show_processed=processing_enabled)
    
    def _show_region(self, show_processed=None):
        """Показать выбранный регион в главном окне"""
        if not self.data_manager or not self._current_camera_id or not self._current_region_name:
            QMessageBox.warning(self, "Предупреждение", "Выберите регион")
            return
        
        # Используем значение из таблицы (чекбокс "Обработка") если не передано явно
        if show_processed is None:
            row = self.regions_table.currentRow()
            if row >= 0:
                row_data = self.regions_table.get_row_data(row)
                show_processed = row_data.get("processing_enabled", False) if row_data else False
            else:
                show_processed = False
        
        # Устанавливаем режим просмотра региона
        if self.controls_post_processing:
            self.controls_post_processing["view_mode"] = "region"
            self.controls_post_processing["selected_region"] = self._current_region_name
            self.controls_post_processing["show_region_processed"] = show_processed
            self.controls_post_processing["selected_image"] = f"region_{self._current_region_name}"
            
            if self.callback:
                self.callback()
    
    def _back_to_main(self):
        """Вернуться к основному изображению"""
        if self.controls_post_processing:
            self.controls_post_processing["view_mode"] = "main"
            self.controls_post_processing["selected_region"] = None
            self.controls_post_processing["show_region_processed"] = False
            self.controls_post_processing["selected_image"] = "main"
            
            if self.callback:
                self.callback()
    
    def showEvent(self, event):
        """При показе виджета обновляем списки камер и регионов"""
        super().showEvent(event)
        if self.data_manager:
            self._refresh_camera_combo()
            if self._current_camera_id:
                self._refresh_regions_ui()
