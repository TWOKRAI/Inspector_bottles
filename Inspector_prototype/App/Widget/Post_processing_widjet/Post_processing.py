from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QLabel, QComboBox, QGroupBox, QTabWidget, QFormLayout,
                             QLineEdit, QSpinBox, QListWidget)
from App.Components.checkbox import CheckboxControl


class PostProcessingWidget(QWidget):
    def __init__(self, window_manager=None, ui_elements=None, controls_post_processing=None, callback=None):
        super().__init__()
        self.window_manager = window_manager
        self.ui_elements = ui_elements
        self.controls_post_processing = controls_post_processing
        self.callback = callback
        self._selected_region_edit_idx = -1
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)

        # Чекбокс включения + режим просмотра
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

        view_group = QGroupBox("Режим просмотра")
        view_layout = QVBoxLayout()
        self.view_mode_combo = QComboBox()
        self.view_mode_combo.addItems(["main", "region", "list"])
        self.view_mode_combo.setCurrentText("main")
        self.view_mode_combo.currentTextChanged.connect(self._on_view_mode_changed)
        view_layout.addWidget(QLabel("Режим:"))
        view_layout.addWidget(self.view_mode_combo)
        self.region_combo = QComboBox()
        self.region_combo.currentTextChanged.connect(self._on_selected_region_changed)
        view_layout.addWidget(QLabel("Область (для region):"))
        view_layout.addWidget(self.region_combo)
        view_group.setLayout(view_layout)
        layout.addWidget(view_group)

        # Подвкладки: Области | Цепочка
        self.op_crop_tabs = QTabWidget()
        self.op_crop_tabs.addTab(self._create_tab_regions(), "1. Области")
        self.op_crop_tabs.addTab(self._create_tab_chain(), "2. Цепочка")
        layout.addWidget(self.op_crop_tabs)
        self._refresh_regions_ui()
    
    def _create_tab_regions(self):
        """Вкладка 1: создание областей выреза (name, x1, y1, x2, y2)."""
        w = QWidget()
        l = QVBoxLayout()
        w.setLayout(l)
        form = QFormLayout()
        self.region_name_edit = QLineEdit()
        self.region_name_edit.setPlaceholderText("cap")
        form.addRow("Имя:", self.region_name_edit)
        self.region_x1 = QSpinBox()
        self.region_x1.setRange(0, 10000)
        self.region_x1.setValue(100)
        self.region_x1.valueChanged.connect(self._update_region_coords_from_spinboxes)
        form.addRow("x1:", self.region_x1)
        self.region_y1 = QSpinBox()
        self.region_y1.setRange(0, 10000)
        self.region_y1.setValue(50)
        self.region_y1.valueChanged.connect(self._update_region_coords_from_spinboxes)
        form.addRow("y1:", self.region_y1)
        self.region_x2 = QSpinBox()
        self.region_x2.setRange(0, 10000)
        self.region_x2.setValue(300)
        self.region_x2.valueChanged.connect(self._update_region_coords_from_spinboxes)
        form.addRow("x2:", self.region_x2)
        self.region_y2 = QSpinBox()
        self.region_y2.setRange(0, 10000)
        self.region_y2.setValue(200)
        self.region_y2.valueChanged.connect(self._update_region_coords_from_spinboxes)
        form.addRow("y2:", self.region_y2)
        l.addLayout(form)
        btn_add = QPushButton("Добавить область")
        btn_add.clicked.connect(self._add_region)
        l.addWidget(btn_add)
        self.regions_list = QListWidget()
        self.regions_list.itemSelectionChanged.connect(self._on_region_selected)
        l.addWidget(QLabel("Список областей:"))
        l.addWidget(self.regions_list)
        btn_remove = QPushButton("Удалить выбранную")
        btn_remove.clicked.connect(self._remove_region)
        l.addWidget(btn_remove)
        btn_save = QPushButton("Сохранить координаты выбранной")
        btn_save.clicked.connect(self._save_region_coords)
        l.addWidget(btn_save)
        return w

    def _update_region_coords_from_spinboxes(self):
        """Обновить выбранную область из полей ввода в реальном времени."""
        row = self.regions_list.currentRow()
        if row < 0:
            return
        regions = self.controls_post_processing.get("regions", [])
        if 0 <= row < len(regions):
            regions[row]["x1"] = self.region_x1.value()
            regions[row]["y1"] = self.region_y1.value()
            regions[row]["x2"] = self.region_x2.value()
            regions[row]["y2"] = self.region_y2.value()
            if self.callback:
                self.callback()

    def _save_region_coords(self):
        """Сохранить текущие координаты в выбранную область."""
        self._update_region_coords_from_spinboxes()
        self._refresh_regions_ui()

    def _create_tab_chain(self):
        """Вкладка 2: цепочка для выбранной области. Добавить шаг, копировать цепочку."""
        w = QWidget()
        l = QVBoxLayout()
        w.setLayout(l)
        l.addWidget(QLabel("Область:"))
        chain_region_row = QHBoxLayout()
        self.chain_region_combo = QComboBox()
        self.chain_region_combo.currentTextChanged.connect(self._refresh_chain_list)
        chain_region_row.addWidget(self.chain_region_combo)
        btn_show_crop = QPushButton("Показать вырез")
        btn_show_crop.clicked.connect(self._show_chain_region_crop)
        chain_region_row.addWidget(btn_show_crop)
        l.addLayout(chain_region_row)
        l.addWidget(QLabel("Шаги цепочки:"))
        self.chain_steps_list = QListWidget()
        l.addWidget(self.chain_steps_list)
        add_layout = QHBoxLayout()
        self.add_processor_combo = QComboBox()
        from Services.Operation_crop.registry import REGISTRY
        for pid, pcls in REGISTRY.items():
            self.add_processor_combo.addItem(pcls().get_name(), pid)
        add_layout.addWidget(self.add_processor_combo)
        btn_add_step = QPushButton("Добавить шаг")
        btn_add_step.clicked.connect(self._add_chain_step)
        add_layout.addWidget(btn_add_step)
        l.addLayout(add_layout)
        btn_remove_step = QPushButton("Удалить шаг")
        btn_remove_step.clicked.connect(self._remove_chain_step)
        l.addWidget(btn_remove_step)
        copy_layout = QHBoxLayout()
        copy_layout.addWidget(QLabel("Копировать в:"))
        self.copy_to_combo = QComboBox()
        copy_layout.addWidget(self.copy_to_combo)
        btn_copy = QPushButton("Копировать цепочку")
        btn_copy.clicked.connect(self._copy_chain)
        copy_layout.addWidget(btn_copy)
        l.addLayout(copy_layout)
        return w

    def _on_view_mode_changed(self, text):
        if self.controls_post_processing:
            self.controls_post_processing["view_mode"] = text
            if self.callback:
                self.callback()

    def _on_selected_region_changed(self, text):
        if self.controls_post_processing:
            self.controls_post_processing["selected_region"] = text if text else None
            if self.callback:
                self.callback()

    def _show_chain_region_crop(self):
        """Переключить отображение на вырезанную область (режим region)."""
        name = self.chain_region_combo.currentText()
        if name and self.controls_post_processing:
            self.controls_post_processing["view_mode"] = "region"
            self.controls_post_processing["selected_region"] = name
            self.view_mode_combo.setCurrentText("region")
            self.region_combo.setCurrentText(name)
            if self.callback:
                self.callback()

    def _add_region(self):
        if not self.controls_post_processing:
            return
        name = self.region_name_edit.text().strip() or "region"
        r = {
            "name": name,
            "x1": self.region_x1.value(),
            "y1": self.region_y1.value(),
            "x2": self.region_x2.value(),
            "y2": self.region_y2.value(),
        }
        self.controls_post_processing.setdefault("regions", []).append(r)
        self.controls_post_processing.setdefault("region_chains", {})[name] = []
        self._refresh_regions_ui()
        self.regions_list.setCurrentRow(len(self.controls_post_processing["regions"]) - 1)
        self._selected_region_edit_idx = len(self.controls_post_processing["regions"]) - 1
        if self.callback:
            self.callback()

    def _remove_region(self):
        if not self.controls_post_processing:
            return
        row = self.regions_list.currentRow()
        if row < 0:
            return
        regions = self.controls_post_processing.get("regions", [])
        if 0 <= row < len(regions):
            name = regions[row]["name"]
            regions.pop(row)
            self.controls_post_processing.get("region_chains", {}).pop(name, None)
        self._refresh_regions_ui()
        if self.callback:
            self.callback()

    def _on_region_selected(self):
        """При выборе области в списке — загрузить координаты в поля и запомнить индекс."""
        if not self.controls_post_processing:
            return
        row = self.regions_list.currentRow()
        self._selected_region_edit_idx = row
        regions = self.controls_post_processing.get("regions", [])
        if 0 <= row < len(regions):
            r = regions[row]
            self.region_name_edit.blockSignals(True)
            self.region_x1.blockSignals(True)
            self.region_y1.blockSignals(True)
            self.region_x2.blockSignals(True)
            self.region_y2.blockSignals(True)
            self.region_name_edit.setText(r.get("name", ""))
            self.region_x1.setValue(r.get("x1", 0))
            self.region_y1.setValue(r.get("y1", 0))
            self.region_x2.setValue(r.get("x2", 0))
            self.region_y2.setValue(r.get("y2", 0))
            self.region_name_edit.blockSignals(False)
            self.region_x1.blockSignals(False)
            self.region_y1.blockSignals(False)
            self.region_x2.blockSignals(False)
            self.region_y2.blockSignals(False)

    def _refresh_regions_ui(self):
        if not self.controls_post_processing:
            return
        self.regions_list.clear()
        for r in self.controls_post_processing.get("regions", []):
            self.regions_list.addItem(f"{r['name']} ({r['x1']},{r['y1']})-({r['x2']},{r['y2']})")
        names = [r["name"] for r in self.controls_post_processing.get("regions", [])]
        for cb in [self.region_combo, self.chain_region_combo, self.copy_to_combo]:
            cb.blockSignals(True)
            cb.clear()
            cb.addItems(names)
            cb.blockSignals(False)
        self._refresh_chain_list()

    def _refresh_chain_list(self):
        if not self.controls_post_processing:
            return
        name = self.chain_region_combo.currentText()
        if not name:
            return
        chain = self.controls_post_processing.get("region_chains", {}).get(name, [])
        self.chain_steps_list.clear()
        from Services.Operation_crop.registry import REGISTRY
        for step in chain:
            pid = step.get("processor_id", "?")
            pname = REGISTRY[pid]().get_name() if pid in REGISTRY else pid
            self.chain_steps_list.addItem(pname)

    def _add_chain_step(self):
        if not self.controls_post_processing:
            return
        name = self.chain_region_combo.currentText()
        if not name:
            return
        pid = self.add_processor_combo.currentData()
        if not pid:
            return
        step = {"processor_id": pid, "params": {}}
        chains = self.controls_post_processing.setdefault("region_chains", {})
        chains.setdefault(name, []).append(step)
        self._refresh_chain_list()
        if self.callback:
            self.callback()

    def _remove_chain_step(self):
        if not self.controls_post_processing:
            return
        name = self.chain_region_combo.currentText()
        row = self.chain_steps_list.currentRow()
        if not name or row < 0:
            return
        chain = self.controls_post_processing.get("region_chains", {}).get(name, [])
        if 0 <= row < len(chain):
            chain.pop(row)
        self._refresh_chain_list()
        if self.callback:
            self.callback()

    def _copy_chain(self):
        if not self.controls_post_processing:
            return
        src = self.chain_region_combo.currentText()
        dst = self.copy_to_combo.currentText()
        if not src or not dst or src == dst:
            return
        from Services.Operation_crop.chain import copy_chain
        src_chain = self.controls_post_processing.get("region_chains", {}).get(src, [])
        self.controls_post_processing.setdefault("region_chains", {})[dst] = copy_chain(src_chain)
        self._refresh_chain_list()
        if self.callback:
            self.callback()
    
    def get_params(self):
        """Возвращает словарь всех параметров этого виджета для сохранения/загрузки рецептов"""
        # Для Operation Crop нужно сериализовать сложные структуры (regions, region_chains)
        # Преобразуем в JSON-совместимый формат
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
            self.view_mode_combo.setCurrentText(str(params_dict['view_mode']))
        if 'selected_region' in params_dict:
            self.region_combo.setCurrentText(str(params_dict['selected_region']) if params_dict['selected_region'] else "")
        
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
