from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QComboBox, QGroupBox, QFormLayout,
                             QLineEdit, QSpinBox, QListWidget, QListWidgetItem,
                             QTableWidget, QTableWidgetItem, QCheckBox, QHeaderView,
                             QMessageBox, QSplitter)
from PyQt5.QtCore import Qt
from App.Components.checkbox import CheckboxControl


class PostProcessingWidget(QWidget):
    def __init__(self, window_manager=None, ui_elements=None, controls_post_processing=None, callback=None):
        super().__init__()
        self.window_manager = window_manager
        self.ui_elements = ui_elements
        self.controls_post_processing = controls_post_processing
        self.callback = callback
        self._selected_region_edit_idx = -1
        self._selected_chain_step_idx = -1
        self._current_processor_params_widget = None
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Чекбокс включения
        checkbox_control = CheckboxControl(
            "enable_post_processing", 
            False, 
            "left",
            ui_elements=self.ui_elements,
            controls=self.controls_post_processing,
            callback=self.callback,
            parent=self
        )
        layout.addWidget(checkbox_control)

        # Режим просмотра - упрощенный список изображений
        view_group = QGroupBox("Режим просмотра")
        view_layout = QVBoxLayout()
        self.view_images_list = QListWidget()
        self.view_images_list.addItems([
            "Оригинальное изображение",
            "Итоговое изображение (с объединенными регионами)"
        ])
        self.view_images_list.currentRowChanged.connect(self._on_view_image_changed)
        view_layout.addWidget(QLabel("Изображения в обработке:"))
        view_layout.addWidget(self.view_images_list)
        view_group.setLayout(view_layout)
        layout.addWidget(view_group)

        # Основной разделитель: слева регионы, справа цепочки
        main_splitter = QSplitter(Qt.Horizontal)
        
        # Левая часть: список камер и регионов
        left_widget = QWidget()
        left_layout = QVBoxLayout()
        left_widget.setLayout(left_layout)
        
        # Список камер (пока одна, но готово для расширения)
        camera_group = QGroupBox("Камеры")
        camera_layout = QVBoxLayout()
        self.camera_list = QListWidget()
        self.camera_list.addItem("Камера 1")
        self.camera_list.setMaximumHeight(80)
        camera_layout.addWidget(self.camera_list)
        camera_group.setLayout(camera_layout)
        left_layout.addWidget(camera_group)
        
        # Кнопки управления регионами
        buttons_layout = QHBoxLayout()
        btn_create = QPushButton("Создать")
        btn_create.clicked.connect(self._create_region)
        btn_save = QPushButton("Сохранить")
        btn_save.clicked.connect(self._save_current_region)
        btn_delete = QPushButton("Удалить")
        btn_delete.clicked.connect(self._delete_region)
        buttons_layout.addWidget(btn_create)
        buttons_layout.addWidget(btn_save)
        buttons_layout.addWidget(btn_delete)
        left_layout.addLayout(buttons_layout)
        
        # Список регионов/изображений
        regions_group = QGroupBox("Регионы / Изображения")
        regions_layout = QVBoxLayout()
        self.regions_list = QListWidget()
        self.regions_list.itemSelectionChanged.connect(self._on_region_selected)
        regions_layout.addWidget(self.regions_list)
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
        
        # Чекбокс включения/выключения региона
        self.region_enabled_checkbox = QCheckBox("Включен")
        self.region_enabled_checkbox.stateChanged.connect(self._on_region_enabled_changed)
        edit_layout.addRow("", self.region_enabled_checkbox)
        
        edit_group.setLayout(edit_layout)
        left_layout.addWidget(edit_group)
        
        main_splitter.addWidget(left_widget)
        
        # Правая часть: цепочки обработки
        right_widget = QWidget()
        right_layout = QVBoxLayout()
        right_widget.setLayout(right_layout)
        
        chains_group = QGroupBox("Цепочки обработки")
        chains_layout = QVBoxLayout()
        
        # Таблица цепочек
        self.chains_table = QTableWidget()
        self.chains_table.setColumnCount(3)
        self.chains_table.setHorizontalHeaderLabels(["Название", "Включено", "Информация"])
        self.chains_table.horizontalHeader().setStretchLastSection(True)
        self.chains_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.chains_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.chains_table.itemSelectionChanged.connect(self._on_chain_step_selected)
        self.chains_table.cellChanged.connect(self._on_chain_table_changed)
        chains_layout.addWidget(self.chains_table)
        
        # Кнопки управления цепочками
        chain_buttons_layout = QHBoxLayout()
        btn_add_step = QPushButton("Добавить звено")
        btn_add_step.clicked.connect(self._add_chain_step)
        btn_remove_step = QPushButton("Удалить звено")
        btn_remove_step.clicked.connect(self._remove_chain_step)
        chain_buttons_layout.addWidget(btn_add_step)
        chain_buttons_layout.addWidget(btn_remove_step)
        chains_layout.addLayout(chain_buttons_layout)
        
        chains_group.setLayout(chains_layout)
        right_layout.addWidget(chains_group)
        
        # Параметры выбранной обработки (динамически меняется)
        self.params_group = QGroupBox("Параметры обработки")
        self.params_layout = QVBoxLayout()
        self.params_group.setLayout(self.params_layout)
        right_layout.addWidget(self.params_group)
        
        main_splitter.addWidget(right_widget)
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 1)
        
        layout.addWidget(main_splitter)
        self._refresh_regions_ui()
    
    def _on_view_image_changed(self, row):
        """Обработчик изменения выбранного изображения в режиме просмотра"""
        if row == 0:
            # Оригинальное изображение
            self.controls_post_processing["view_mode"] = "original"
            self.controls_post_processing["selected_image"] = "original"
        elif row == 1:
            # Итоговое изображение
            self.controls_post_processing["view_mode"] = "merged"
            self.controls_post_processing["selected_image"] = "merged"
        else:
            # Регион (row - 2 будет индексом региона)
            region_idx = row - 2
            regions = self.controls_post_processing.get("regions", [])
            if 0 <= region_idx < len(regions):
                region = self._region_to_dict(regions[region_idx])
                self.controls_post_processing["view_mode"] = "region"
                self.controls_post_processing["selected_region"] = region["name"]
                self.controls_post_processing["selected_image"] = f"region_{region['name']}"
        
        if self.callback:
            self.callback()
    
    def _create_region(self):
        """Создать новый регион (копировать текущий если выбран)"""
        if not self.controls_post_processing:
            return
        
        # Если выбран регион, копируем его
        row = self.regions_list.currentRow()
        if row >= 0:
            regions = self.controls_post_processing.get("regions", [])
            if 0 <= row < len(regions):
                source_region = self._region_to_dict(regions[row]).copy()
                source_region["name"] = f"{source_region['name']}_copy"
            else:
                source_region = None
        else:
            source_region = None
        
        # Создаем новый регион
        if source_region:
            new_region = source_region
        else:
            new_region = {
                "name": f"region_{len(self.controls_post_processing.get('regions', [])) + 1}",
                "x1": 100,
                "y1": 50,
                "x2": 300,
                "y2": 200,
                "enabled": True,
                "processor_id": 1
            }
        
        self.controls_post_processing.setdefault("regions", []).append(new_region)
        self.controls_post_processing.setdefault("region_chains", {})[new_region["name"]] = []
        self._refresh_regions_ui()
        self.regions_list.setCurrentRow(len(self.controls_post_processing["regions"]) - 1)
        self._selected_region_edit_idx = len(self.controls_post_processing["regions"]) - 1
        
        if self.callback:
            self.callback()
    
    def _save_current_region(self):
        """Сохранить текущий регион"""
        self._update_region_coords_from_spinboxes()
        self._refresh_regions_ui()
        if self.callback:
            self.callback()
    
    def _delete_region(self):
        """Удалить выбранный регион с подтверждением"""
        if not self.controls_post_processing:
            return
        
        row = self.regions_list.currentRow()
        if row < 0:
            return
        
        regions = self.controls_post_processing.get("regions", [])
        if 0 <= row < len(regions):
            region = self._region_to_dict(regions[row])
            name = region["name"]
            
            reply = QMessageBox.question(
                self, 
                "Подтверждение удаления",
                f"Вы уверены, что хотите удалить регион '{name}'?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                regions.pop(row)
                self.controls_post_processing.get("region_chains", {}).pop(name, None)
                self._refresh_regions_ui()
                if self.callback:
                    self.callback()
    
    def _on_region_selected(self):
        """При выборе региона - загрузить данные и обновить цепочки"""
        if not self.controls_post_processing:
            return
        
        row = self.regions_list.currentRow()
        self._selected_region_edit_idx = row
        
        if row < 0:
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
        """Обновить таблицу цепочек для выбранного региона"""
        if not region_name:
            self.chains_table.setRowCount(0)
            return
        
        chain = self.controls_post_processing.get("region_chains", {}).get(region_name, [])
        self.chains_table.blockSignals(True)
        self.chains_table.setRowCount(len(chain))
        
        from Services.Operation_crop.registry import REGISTRY
        
        for i, step in enumerate(chain):
            pid = step.get("processor_id", "?")
            processor_class = REGISTRY.get(pid)
            
            # Название
            if processor_class:
                name_item = QTableWidgetItem(processor_class().get_name())
            else:
                name_item = QTableWidgetItem(str(pid))
            name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
            self.chains_table.setItem(i, 0, name_item)
            
            # Чекбокс включения
            enabled = step.get("enabled", True)
            checkbox = QCheckBox()
            checkbox.setChecked(enabled)
            checkbox.stateChanged.connect(lambda state, idx=i: self._on_chain_enabled_changed(idx, state))
            self.chains_table.setCellWidget(i, 1, checkbox)
            
            # Информация
            info_item = QTableWidgetItem(step.get("info", ""))
            info_item.setFlags(info_item.flags() & ~Qt.ItemIsEditable)
            self.chains_table.setItem(i, 2, info_item)
        
        self.chains_table.blockSignals(False)
    
    def _on_chain_step_selected(self):
        """При выборе звена цепочки - показать его параметры"""
        row = self.chains_table.currentRow()
        if row < 0:
            self._clear_processor_params()
            return
        
        region_row = self.regions_list.currentRow()
        if region_row < 0:
            return
        
        regions = self.controls_post_processing.get("regions", [])
        if 0 <= region_row < len(regions):
            region = self._region_to_dict(regions[region_row])
            region_name = region.get("name", "")
            chain = self.controls_post_processing.get("region_chains", {}).get(region_name, [])
            
            if 0 <= row < len(chain):
                step = chain[row]
                pid = step.get("processor_id")
                self._show_processor_params(pid, step.get("params", {}))
    
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
        row = self.chains_table.currentRow()
        region_row = self.regions_list.currentRow()
        
        if row < 0 or region_row < 0:
            return
        
        regions = self.controls_post_processing.get("regions", [])
        if 0 <= region_row < len(regions):
            region = self._region_to_dict(regions[region_row])
            region_name = region.get("name", "")
            chain = self.controls_post_processing.get("region_chains", {}).get(region_name, [])
            
            if 0 <= row < len(chain):
                if "params" not in chain[row]:
                    chain[row]["params"] = {}
                chain[row]["params"][param_key] = value
                
                if self.callback:
                    self.callback()
    
    def _on_chain_enabled_changed(self, row, state):
        """Обработчик изменения состояния чекбокса включения звена"""
        region_row = self.regions_list.currentRow()
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
        if not self.controls_post_processing:
            return
        
        region_row = self.regions_list.currentRow()
        if region_row < 0:
            QMessageBox.warning(self, "Предупреждение", "Выберите регион для добавления звена цепочки")
            return
        
        regions = self.controls_post_processing.get("regions", [])
        if 0 <= region_row < len(regions):
            region = self._region_to_dict(regions[region_row])
            region_name = region.get("name", "")
            
            # Диалог выбора процессора
            from Services.Operation_crop.registry import REGISTRY
            processors = list(REGISTRY.items())
            
            if not processors:
                QMessageBox.warning(self, "Предупреждение", "Нет доступных процессоров")
                return
            
            # Создаем диалог выбора процессора
            from PyQt5.QtWidgets import QDialog, QDialogButtonBox
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
            
            if dialog.exec_() == QDialog.Accepted:
                pid = processor_combo.currentData()
                if pid:
                    step = {"processor_id": pid, "params": {}, "enabled": True}
                    
                    chains = self.controls_post_processing.setdefault("region_chains", {})
                    chains.setdefault(region_name, []).append(step)
                    self._refresh_chains_table(region_name)
                    
                    if self.callback:
                        self.callback()
    
    def _remove_chain_step(self):
        """Удалить звено из цепочки"""
        if not self.controls_post_processing:
            return
        
        row = self.chains_table.currentRow()
        region_row = self.regions_list.currentRow()
        
        if row < 0 or region_row < 0:
            return
        
        regions = self.controls_post_processing.get("regions", [])
        if 0 <= region_row < len(regions):
            region = self._region_to_dict(regions[region_row])
            region_name = region.get("name", "")
            chain = self.controls_post_processing.get("region_chains", {}).get(region_name, [])
            
            if 0 <= row < len(chain):
                chain.pop(row)
                self._refresh_chains_table(region_name)
                self._clear_processor_params()
                
                if self.callback:
                    self.callback()
    
    def _update_region_coords_from_spinboxes(self):
        """Обновить координаты региона из полей ввода"""
        row = self.regions_list.currentRow()
        if row < 0:
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
        row = self.regions_list.currentRow()
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
        if not self.controls_post_processing:
            return
        
        # Обновляем список регионов
        self.regions_list.clear()
        regions = self.controls_post_processing.get("regions", [])
        for r in regions:
            d = self._region_to_dict(r)
            enabled_mark = "✓" if d.get("enabled", True) else "✗"
            self.regions_list.addItem(f"{enabled_mark} {d['name']} ({d['x1']},{d['y1']})-({d['x2']},{d['y2']})")
        
        # Обновляем список изображений в режиме просмотра
        self.view_images_list.blockSignals(True)
        self.view_images_list.clear()
        self.view_images_list.addItem("Оригинальное изображение")
        self.view_images_list.addItem("Итоговое изображение (с объединенными регионами)")
        
        # Добавляем регионы в список изображений
        for r in regions:
            d = self._region_to_dict(r)
            self.view_images_list.addItem(f"Регион: {d['name']} (оригинал)")
            self.view_images_list.addItem(f"Регион: {d['name']} (обработанный)")
        
        self.view_images_list.blockSignals(False)
        
        # Обновляем таблицу цепочек если выбран регион
        row = self.regions_list.currentRow()
        if row >= 0 and 0 <= row < len(regions):
            region = self._region_to_dict(regions[row])
            self._refresh_chains_table(region.get("name", ""))
    
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
        
        # Обновляем UI
        if 'view_mode' in params_dict:
            # Обновляем выбранное изображение в режиме просмотра
            selected_image = params_dict.get('selected_image', 'original')
            if selected_image == 'original':
                self.view_images_list.setCurrentRow(0)
            elif selected_image == 'merged':
                self.view_images_list.setCurrentRow(1)
        
        # Обновляем списки регионов
        self._refresh_regions_ui()
        
        # Применяем чекбокс
        if 'enable_post_processing' in self.ui_elements:
            element_data = self.ui_elements['enable_post_processing']
            element = element_data['element']
            from PyQt5.QtWidgets import QCheckBox
            if isinstance(element, QCheckBox):
                value = str(params_dict.get('enable_post_processing', False)).lower() in ['true', '1', 'yes']
                element.setChecked(value)
