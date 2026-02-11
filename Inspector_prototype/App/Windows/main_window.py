import cv2
from PyQt5.QtWidgets import (QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QLabel,
                             QSlider, QCheckBox, QTabWidget, QScrollArea, QPushButton, QMessageBox)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap, QFont
from PyQt5.QtGui import QCursor
from PyQt5.QtCore import QTimer
import time

from PyQt5.QtWidgets import QHBoxLayout, QLabel, QSlider, QWidget
from PyQt5.QtCore import Qt

from App.Components.header import HeaderWidget
from  App.Components.slider import SliderControl2


class SliderControl(QWidget):
    def __init__(self, name, min_val, max_val, init_val, transfer_k=1, round_k=0, min_access = 0, ui_elements=None, controls=[], callback=[], parent=None):
        super().__init__(parent)
        self.name = name
        self.min_access = min_access
        self.ui_elements = ui_elements
        self.controls = controls

        # self.func_update = callbacks if callbacks else lambda: None

        # Инициализация списка контролов
        self.controls = controls

        # Инициализация списка функций
        self.func_update = callback

        self.min_access = min_access 
        
        # Создание компоновки
        self.hbox = QHBoxLayout(self)

        # Создание виджетов
        self.label = QLabel()
        self.value_label = QLabel()
        self.slider = QSlider(Qt.Horizontal)

        # Настройка слайдера
        self.slider.setMinimum(min_val)
        self.slider.setMaximum(max_val)
        self.slider.setValue(init_val)
        self.slider.setMinimumHeight(45)
        self.slider.setMinimumWidth(690)

        self.slider.setStyleSheet("""
            QSlider::handle:horizontal {
                height: 50px;  /* Увеличение высоты в 2 раза */
                width: 25px;   /* Увеличение ширины в 1.5 раза */
                margin: -15px 0;  /* Корректировка отступов для центрирования */
                border: 2px solid #4682B4;
                border-radius: 7px;
                background: gray;
            }
        """)

        self.transfer_k = transfer_k
        self.round_k = round_k

        self.value = self.transfer_value(init_val)

        self.value_label.setText(str(self.value))

        font_family = "Arial"
        font_size = 11
        self.font = QFont(font_family, font_size)
        self.label.setFont(self.font)
        self.label.setWordWrap(True)
        self.label.setFixedSize(100, 40)
        self.label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.label.setText(name)

        font_family = "Arial"
        font_size = 12
        self.font = QFont(font_family, font_size)
        self.value_label.setFont(self.font)

        # Подключение сигнала изменения значения
        self.slider.valueChanged.connect(self.update_slider_value)
        self.slider.sliderReleased.connect(self.slider_release)

        # Отключение прокрутки колесом мыши
        self.slider.wheelEvent = lambda event: None

        # Добавление виджетов в компоновку
        self.hbox.addSpacing(25)
        self.hbox.addWidget(self.label)
        self.hbox.addStretch()
        self.hbox.addWidget(self.value_label)
        self.hbox.addSpacing(10)
        self.hbox.addWidget(self.slider)
        self.hbox.addSpacing(25)

        if self.ui_elements is not None:
            self.ui_elements[name] = {'element': self.slider, 'value': init_val, 'min_access': self.min_access}

        if self.controls is not None:
            if isinstance(self.controls, list):
                for control in self.controls:
                    control[self.name] = self.value
            else:
                self.controls[self.name] = self.value


    def update_slider_value(self, value):
        self.value = value
        self.value_transfer = self.transfer_value(self.value)

        self.value_label.setText(str(self.value_transfer))

        if self.ui_elements is not None:
            self.ui_elements[self.name]['value'] = self.value_transfer
        
        if self.controls is not None:
            if isinstance(self.controls, list):
                for control in self.controls:
                    control[self.name] = self.value_transfer
            else:
                self.controls[self.name] = self.value_transfer

        if self.func_update is not None:
            if isinstance(self.controls, list):
                for func_update in self.func_update:
                    func_update()
            else:
                self.func_update()

        
    def slider_release(self):
        print(f"Slider {self.name} value changed to {self.value}")


    def transfer_value(self, value):
        value_k = value * self.visual_k

        if self.round_k == 0:
            print(int(round(value_k, self.round_k)))
            return int(round(value_k, self.round_k)) 
        else:
            print(round(value_k, self.round_k))
            return round(value_k, self.round_k)
        

    def transfer_value(self, value):
        value_k = value * self.transfer_k
        rounded = round(value_k, self.round_k)
        return int(rounded) if self.round_k == 0 else rounded


class CheckboxControl(QWidget):
    def __init__(self, name, init_val, position="right", min_access = 0, ui_elements=None, controls=[], callback=[], parent=None):
        super().__init__(parent)
        self.name = name
        self.ui_elements = ui_elements
        # self.controls = controls

        # if callback is not None:
        #     self.func_update = callback
        # else:
        #     self.func_update = lambda: None

        # Инициализация списка контролов
        self.controls = controls

        # Инициализация списка функций
        self.func_update = callback

        self.min_access = min_access 

        # Создание компоновки
        self.vbox = QVBoxLayout(self)
        self.vbox.setAlignment(Qt.AlignCenter)

        # Создание виджетов
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(init_val)
        self.checkbox.setStyleSheet("QCheckBox::indicator { width: 44px; height: 44px; }")
        self.checkbox.stateChanged.connect(self.update_control)

        self.label = QLabel(name)
        self.label.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(12)
        self.label.setFont(font)

        # Настройка расположения
        self.setup_layout(position)

        if self.ui_elements is not None:
            self.ui_elements[name] = {'element': self.checkbox, 
                                      'value': init_val, 
                                      'min_access': self.min_access}

        if self.controls is not None:
            if isinstance(self.controls, list):
                for control in self.controls:
                    control[self.name] = init_val
            else:
                self.controls[self.name] = init_val


    def setup_layout(self, position):
        if position in ["top", "bottom"]:
            hbox_0 = QHBoxLayout()
            hbox_0.setAlignment(Qt.AlignCenter)
            hbox_1 = QHBoxLayout()
            hbox_1.setAlignment(Qt.AlignCenter)

            if position == "top":
                hbox_0.addStretch()
                hbox_0.addWidget(self.label)
                hbox_0.addStretch()

                hbox_1.addStretch()
                hbox_1.addWidget(self.checkbox)
                hbox_1.addStretch()

                self.vbox.addLayout(hbox_0)
                self.vbox.addLayout(hbox_1)
            else:
                self.vbox.addWidget(self.checkbox)
                self.vbox.addWidget(self.label)
        else:
            hbox = QHBoxLayout()
            hbox.setAlignment(Qt.AlignCenter)
            if position == "left":
                hbox.addWidget(self.label)
                hbox.addWidget(self.checkbox)
            else:
                hbox.addWidget(self.checkbox)
                hbox.addWidget(self.label)
            self.vbox.addLayout(hbox)

    def update_control(self, state):
        if self.ui_elements is not None:
            self.ui_elements[self.name]['value'] = bool(state)
            
        if self.controls is not None:
            if isinstance(self.controls, list):
                for control in self.controls:
                    control[self.name] = bool(state)
            else:
                self.controls[self.name] = bool(state)

        if self.func_update is not None:
            if isinstance(self.controls, list):
                for func_update in self.func_update:
                    func_update()
            else:
                self.func_update()


        print(f"Checkbox {self.name} state changed to {bool(state)}")


class MainWindow(QMainWindow):
    def __init__(self, window_manager = None):
        super().__init__()

        self.window_manager = window_manager

        if not window_manager is None:
            self.queue_manager = self.window_manager.queue_manager
            self.stop_event = self.window_manager.stop_event
            self.fullscreen = self.window_manager.fullscreen
        
        self.header = HeaderWidget(window_manager=self.window_manager)

        self.ui_elements = {}
        self.controls = {}
        self.controls_camera = {}
        self.controls_neuroun = {}
        self.controls_draw = {}
        self.controls_robot = {}
        self.controls_conveyor = {}
        self.controls_hikvision = {}
        self.controls_processing = {}
        
        self.current_access_level = 0

        self.init_ui()

        if self.fullscreen: self.showFullScreen()

        self.update_controls()
        self.update_controls_camera()
        self.update_controls_neuroun()
        self.update_controls_draw()
        self.update_controls_robot()
        self.update_controls_conveyor()
        self.update_controls_hikvision()
        self.update_controls_processing()

        self.update_access_level(self.current_access_level)


    def init_ui(self):
        # Создание главного окна
        self.setWindowTitle("Image Processing App")
        self.setGeometry(100, 100, 1200, 800)
        self.setFixedSize(1024, 780) 

        main_layout = QVBoxLayout()
        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

        main_layout.addWidget(self.header)

        main_layout.addSpacing(3)
        main_content_layout = self.create_main_content_layout()
        main_layout.addLayout(main_content_layout)
        main_layout.addSpacing(15)

        main_layout.addStretch()
        self.create_tabs()
        
        # Контейнер для вкладок с кнопкой скрытия
        tabs_container = QWidget()
        tabs_layout = QVBoxLayout()
        tabs_container.setLayout(tabs_layout)
        
        # Кнопка скрытия/показа вкладок
        self.btn_toggle_tabs = QPushButton("Скрыть вкладки")
        self.btn_toggle_tabs.setMaximumHeight(30)
        self.btn_toggle_tabs.clicked.connect(self.toggle_tabs_visibility)
        tabs_layout.addWidget(self.btn_toggle_tabs)
        
        tabs_layout.addWidget(self.tab_widget)
        self.tabs_visible = True
        
        main_layout.addWidget(tabs_container)


    def create_main_content_layout(self):
        main_content_layout = QHBoxLayout()

        # Левая панель с чекбоксами
        checkbox_layout_left = QVBoxLayout()

        checkbox_control = CheckboxControl("draw", 
                                           True, 
                                           "top", 
                                           ui_elements=self.ui_elements, 
                                            controls=[self.controls_draw], 
                                            callback = [self.update_controls_draw], 
                                           parent=self
                                           )
        
        checkbox_layout_left.addWidget(checkbox_control)

        checkbox_control = CheckboxControl("circles",
                                            True, 
                                            "top", 
                                            ui_elements=self.ui_elements, 
                                            controls=[self.controls_draw], 
                                            callback = [self.update_controls_draw], 
                                            parent=self
                                            )

        checkbox_layout_left.addWidget(checkbox_control)

        checkbox_control = CheckboxControl("rectangles", 
                                           True, 
                                           "top", 
                                           ui_elements=self.ui_elements, 
                                            controls=[self.controls_draw], 
                                            callback = [self.update_controls_draw], 
                                           parent=self
                                           )
        
        checkbox_layout_left.addWidget(checkbox_control)

        checkbox_control = CheckboxControl("record_video", 
                                           False, 
                                           "top", 
                                           ui_elements=self.ui_elements, 
                                           controls=[self.controls_camera, self.controls, self.controls_draw], 
                                           callback = [self.update_controls_camera, self.update_controls, self.update_controls_draw], 
                                           parent=self
                                           )
        
        checkbox_layout_left.addWidget(checkbox_control)

        main_content_layout.addLayout(checkbox_layout_left)

        # Центральная панель с изображением
        image_layout = QVBoxLayout()
        image_layout.addStretch()

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setScaledContents(False)
        self.image_label.setStyleSheet("border: 2px solid white; border-radius: 10px;")
        self.image_label.setMinimumSize(200, 200)  # Минимальный размер
        image_layout.addWidget(self.image_label)

        image_layout.addStretch()
        main_content_layout.addLayout(image_layout)

        # Правая панель с чекбоксами
        checkbox_layout_right = QVBoxLayout()

        checkbox_control = CheckboxControl("servo_on", False, "top", ui_elements=self.ui_elements, controls=self.controls_robot, callback = self.update_controls_robot, parent=self)
        checkbox_layout_right.addWidget(checkbox_control)

        checkbox_control = CheckboxControl("enable_camera", True, "top", ui_elements=self.ui_elements, controls=self.controls_camera, callback = self.update_controls_camera, parent=self)
        checkbox_layout_right.addWidget(checkbox_control)

        checkbox_control = CheckboxControl("processing", True, "top", ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
        checkbox_layout_right.addWidget(checkbox_control)

        checkbox_control = CheckboxControl("server", True, "top", ui_elements=self.ui_elements, controls=self.controls_robot, callback = self.update_controls_robot, parent=self)
        checkbox_layout_right.addWidget(checkbox_control)

        main_content_layout.addLayout(checkbox_layout_right)

        return main_content_layout


    def create_tabs(self):
        self.tab_widget = QTabWidget()
        self.tab_widget.setFixedHeight(270)
        self.tab_widget.setStyleSheet("QTabBar::tab { height: 35px; width: 95px; }")  # Увеличение размера вкладок

        self.create_tab(self.tab_widget, "Форма", self.create_tab_circle())
        self.create_tab(self.tab_widget, "Разное", self.create_tab_cropped_area()) 
        self.create_tab(self.tab_widget, "Параметры", self.create_tab_parameters()) 
        self.create_tab(self.tab_widget, "Нейрон", self.create_tab_neuroun())
        self.create_tab(self.tab_widget, "Робот", self.create_tab_robot())
        self.create_tab(self.tab_widget, "Hikvision", self.create_tab_hikvision())
        self.create_tab(self.tab_widget, "Обработка", self.create_tab_processing()) 


    def create_tab(self, tabs: QTabWidget, name, content_widget, scrollable=True):
        if scrollable:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setStyleSheet("QScrollBar:vertical { width: 40px; }")
            
            scroll.setWidget(content_widget)  # Устанавливаем виджет в ScrollArea
            tabs.addTab(scroll, name)
        else:
            tabs.addTab(content_widget, name)


    # def create_tab(self, tabs: QTabWidget, name, content_widget, scrollable=True):
    #     # Создаем контейнер для QScrollArea
    #     container_widget = QWidget()
    #     container_layout = QVBoxLayout(container_widget)

    #     if scrollable:
    #         scroll = QScrollArea()
    #         scroll.setWidgetResizable(True)
    #         scroll.setStyleSheet("QScrollBar:vertical { width: 30px; }")

    #         # Устанавливаем виджет в ScrollArea
    #         scroll.setWidget(content_widget)

    #         # Добавляем ScrollArea в контейнер
    #         container_layout.addWidget(scroll)

    #         # Задаем отступ справа через стили
    #         container_widget.setStyleSheet("padding-right: 32px;")
    #     else:
    #         # Добавляем content_widget в контейнер
    #         container_layout.addWidget(content_widget)

    #     # Добавляем контейнер как вкладку
    #     tabs.addTab(container_widget, name)


    def create_tab_circle(self):
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)

        slider_control = SliderControl("dp", 0, 20, 14,  transfer_k= 0.1, round_k=1, min_access=1, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
        layout.addWidget(slider_control)

        slider_control = SliderControl("minDist", 0, 100, 51, min_access=1, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
        layout.addWidget(slider_control)

        slider_control = SliderControl("param1", 0, 200, 47, min_access=1, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
        layout.addWidget(slider_control)

        slider_control = SliderControl("param2", 0, 200, 31,  min_access=1, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
        layout.addWidget(slider_control)

        slider_control = SliderControl("minRadius", 0, 100, 22,  min_access=1, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
        layout.addWidget(slider_control)

        slider_control = SliderControl("maxRadius", 0, 100, 41,  min_access=1, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
        layout.addWidget(slider_control)

        return tab

    def create_tab_cropped_area(self):
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)

        
        checkbox_control = CheckboxControl("camera_robot", 
                                           False, 
                                           "top", 
                                           ui_elements=self.ui_elements, 
                                            controls=[self.controls_draw], 
                                            callback = [self.update_controls_draw], 
                                           parent=self
                                           )
        
        layout.addWidget(checkbox_control)

        slider_control = SliderControl("history", 
                                       0, 
                                       120, 
                                       120, 
                                       ui_elements=self.ui_elements, 
                                       controls=[self.controls_draw], 
                                       callback = [self.update_controls_draw], 
                                       parent=self
                                       )
        
        layout.addWidget(slider_control)

        slider_control = SliderControl("height", 0, 600, 250, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
        layout.addWidget(slider_control)

        slider_control = SliderControl("y_delta", 
                                       0, 
                                       100, 
                                       31, 
                                       ui_elements=self.ui_elements, 
                                       controls=[self.controls, self.controls_draw], 
                                       callback = [self.update_controls, self.update_controls_draw], 
                                       parent=self
                                       )
        
        layout.addWidget(slider_control)

        slider_control = SliderControl("x_delta", 0, 100, 21, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
        layout.addWidget(slider_control)

        slider_control = SliderControl2("x_min", 
                                       0, 
                                       1280, 
                                       150, 
                                       ui_elements=self.ui_elements, 
                                       controls=[self.controls, self.controls_draw], 
                                       callback = [self.update_controls, self.update_controls_draw], 
                                       parent=self, 
                                       label = 'Минимальный Х'
                                       )
        
        layout.addWidget(slider_control)

        slider_control = SliderControl("x_max", 
                                       0, 
                                       1280, 
                                       730, 
                                       ui_elements=self.ui_elements, 
                                       controls=[self.controls, self.controls_draw], 
                                       callback = [self.update_controls, self.update_controls_draw], 
                                       parent=self
                                       )
        

        layout.addWidget(slider_control)

        slider_control = SliderControl("conveyor_freq", 1, 50, 25, ui_elements=self.ui_elements, controls=self.controls_conveyor, callback = self.update_controls_conveyor, parent=self)
        layout.addWidget(slider_control)

        return tab

    def create_tab_parameters(self):
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)

        slider_control = SliderControl("hl", 0, 179, 0, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
        layout.addWidget(slider_control)

        slider_control = SliderControl("sl", 0, 255, 50, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
        layout.addWidget(slider_control)

        slider_control = SliderControl("vl", 0, 255, 28, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
        layout.addWidget(slider_control)

        slider_control = SliderControl("hm", 0, 179, 179, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
        layout.addWidget(slider_control)

        slider_control = SliderControl("sm", 0, 255, 255, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
        layout.addWidget(slider_control)

        slider_control = SliderControl("vm", 0, 255, 255, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
        layout.addWidget(slider_control)

        slider_control = SliderControl("mode_image", 0, 5, 0, ui_elements=self.ui_elements, controls=self.controls_draw, callback = self.update_controls_draw, parent=self)
        layout.addWidget(slider_control)

        slider_control = SliderControl("area_threshold", 0, 5200, 140, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
        layout.addWidget(slider_control)

        slider_control = SliderControl("snap_y", 
                                        0, 
                                        600, 
                                        200, 
                                        ui_elements=self.ui_elements, 
                                        controls=[self.controls, self.controls_robot, self.controls_draw], 
                                        callback = [self.update_controls, self.update_controls_robot, self.update_controls_draw], 
                                        parent=self
                                        )
        
        layout.addWidget(slider_control)

        slider_control = SliderControl("shift", 0, 7000, 717, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
        layout.addWidget(slider_control)

        slider_control = SliderControl("shift_y", 0, 1000, 120, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
        layout.addWidget(slider_control)

        slider_control = SliderControl("mode", 0, 1, 1, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
        layout.addWidget(slider_control)

        slider_control = SliderControl("fps", 
                                       1, 
                                       25, 
                                       5, 
                                       ui_elements=self.ui_elements, 
                                       controls=[self.controls_camera, self.controls_draw], 
                                       callback = [self.update_controls_camera, self.update_controls_draw], 
                                       parent=self
                                       )
                                       
        layout.addWidget(slider_control)

        checkbox_control = CheckboxControl("calibration_line", 
                                           False, 
                                           "top", 
                                           ui_elements=self.ui_elements, 
                                            controls=[self.controls_draw], 
                                            callback = [self.update_controls_draw], 
                                           parent=self
                                           )
        
        layout.addWidget(checkbox_control)

        checkbox_control = CheckboxControl("calibration_circle", 
                                           False, 
                                           "top", 
                                           ui_elements=self.ui_elements, 
                                            controls=[self.controls_draw], 
                                            callback = [self.update_controls_draw], 
                                           parent=self
                                           )
        
        layout.addWidget(checkbox_control)

        slider_control = SliderControl("resize_delta", 
                                       -50, 
                                       50, 
                                       0, 
                                       ui_elements=self.ui_elements, 
                                       controls=[self.controls_draw],  
                                       callback = [self.update_controls_draw],
                                       parent=self)
        
        layout.addWidget(slider_control)

        slider_control = SliderControl("blend_alpha", 
                                       0, 
                                       100, 
                                       100, 
                                       transfer_k= 0.01, 
                                       round_k=2,
                                       ui_elements=self.ui_elements, 
                                       controls=[self.controls_draw],  
                                       callback = [self.update_controls_draw],
                                       parent=self)
        
        layout.addWidget(slider_control)

        slider_control = SliderControl("k_size", 
                                       0, 
                                       200, 
                                       115, 
                                       transfer_k= 0.01, 
                                       round_k=2,
                                       ui_elements=self.ui_elements, 
                                       controls=[self.controls],  
                                       callback = [self.update_controls],
                                       parent=self)
        
        layout.addWidget(slider_control)

        slider_control = SliderControl("method_resize", 
                                       0, 
                                       4, 
                                       2, 
                                    #    transfer_k= 0.01, 
                                    #    round_k=2,
                                       ui_elements=self.ui_elements, 
                                       controls=[self.controls],  
                                       callback = [self.update_controls],
                                       parent=self)
        
        layout.addWidget(slider_control)

        slider_control = SliderControl("top", 
                                        0, 
                                        300, 
                                        145, 
                                    #    transfer_k= 0.01, 
                                    #    round_k=2,
                                        ui_elements=self.ui_elements, 
                                        controls=[self.controls],  
                                        callback = [self.update_controls],
                                        parent=self)
        
        layout.addWidget(slider_control)

        slider_control = SliderControl("bottom", 
                                        0, 
                                        1000, 
                                        535, 
                                    #    transfer_k= 0.01, 
                                    #    round_k=2,
                                        ui_elements=self.ui_elements, 
                                        controls=[self.controls],  
                                        callback = [self.update_controls],
                                        parent=self)
        
        layout.addWidget(slider_control)

        slider_control = SliderControl("left", 
                                        0, 
                                        500, 
                                        190, 
                                    #    transfer_k= 0.01, 
                                    #    round_k=2,
                                        ui_elements=self.ui_elements, 
                                        controls=[self.controls],  
                                        callback = [self.update_controls],
                                        parent=self)
        
        layout.addWidget(slider_control)

        slider_control = SliderControl("right", 
                                        0, 
                                        1500, 
                                        1054, 
                                    #    transfer_k= 0.01, 
                                    #    round_k=2,
                                        ui_elements=self.ui_elements, 
                                        controls=[self.controls],  
                                        callback = [self.update_controls],
                                        parent=self)
        
        layout.addWidget(slider_control)
        
        return tab

    def create_tab_robot(self):
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)

        checkbox_control = CheckboxControl("robot_on", 
                                           False, 
                                           "left", 
                                           ui_elements=self.ui_elements, 
                                           controls= self.controls_robot, 
                                           callback = self.update_controls_robot, 
                                           parent=self
                                           )
        layout.addWidget(checkbox_control)

        checkbox_control = CheckboxControl("capture", 
                                           False, 
                                           "left", 
                                           ui_elements=self.ui_elements, 
                                           controls= self.controls_robot, 
                                           callback = self.update_controls_robot, 
                                           parent=self
                                           )
        layout.addWidget(checkbox_control)


        slider_control = SliderControl("position", 0, 3, 0, ui_elements=self.ui_elements, controls=self.controls_robot, callback = self.update_controls_robot, parent=self)
        layout.addWidget(slider_control)

        #1760
        slider_control = SliderControl("shift_time", 0, 2000, 1760, ui_elements=self.ui_elements, controls=self.controls_robot, callback = self.update_controls_robot, min_access=2, parent=self)
        layout.addWidget(slider_control)

        slider_control = SliderControl("shift", 0, 1000, 0, ui_elements=self.ui_elements, controls=self.controls_robot,  callback = self.update_controls_robot, parent=self)
        layout.addWidget(slider_control)

        slider_control = SliderControl("lenght", 0, 200, 0, ui_elements=self.ui_elements, controls=self.controls_robot, callback = self.update_controls_robot,  parent=self)
        layout.addWidget(slider_control)
        # 46
        slider_control = SliderControl("back", -200, 200, 0, ui_elements=self.ui_elements, controls=self.controls_robot, callback = self.update_controls_robot, parent=self)
        layout.addWidget(slider_control)

        slider_control = SliderControl("pr", 600, 1400, 1130, transfer_k=0.001, round_k=3, ui_elements=self.ui_elements, controls=self.controls_robot, callback = self.update_controls_robot, parent=self)
        layout.addWidget(slider_control)

        slider_control = SliderControl("tracking", 0, 800, 50, transfer_k=1, round_k=0, ui_elements=self.ui_elements, controls=self.controls_robot, callback = self.update_controls_robot, parent=self)
        layout.addWidget(slider_control)

        checkbox_control = CheckboxControl("do1", False, "left", ui_elements=self.ui_elements, controls=self.controls_robot, callback = self.update_controls_robot, parent=self)
        layout.addWidget(checkbox_control)

        checkbox_control = CheckboxControl("do2", False, "left", ui_elements=self.ui_elements, controls=self.controls_robot, callback = self.update_controls_robot, parent=self)
        layout.addWidget(checkbox_control)


        slider_control = SliderControl("min_rob_x", 
                                        50, 
                                        590,
                                        78,
                                        ui_elements=self.ui_elements, 
                                        controls=self.controls_robot, 
                                        callback = self.update_controls_robot,
                                        parent=self
                                        )
        
        layout.addWidget(slider_control)

        slider_control = SliderControl("max_rob_x", 
                                        50, 
                                        590,
                                        488,
                                        ui_elements=self.ui_elements, 
                                        controls=self.controls_robot, 
                                        callback = self.update_controls_robot,
                                        parent=self
                                        )
        
        layout.addWidget(slider_control)


        return tab
    
    def create_tab_hikvision(self):
        """Создать вкладку управления Hikvision SDK"""
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)
        
        # Кнопка показа/скрытия UI SDK окна
        btn_show_ui = QPushButton("Показать UI SDK")
        btn_show_ui.setMinimumHeight(50)
        btn_show_ui.clicked.connect(lambda: self.toggle_sdk_ui(True))
        layout.addWidget(btn_show_ui)
        
        btn_hide_ui = QPushButton("Скрыть UI SDK")
        btn_hide_ui.setMinimumHeight(50)
        btn_hide_ui.clicked.connect(lambda: self.toggle_sdk_ui(False))
        layout.addWidget(btn_hide_ui)
        
        # Кнопки управления камерой
        btn_enum = QPushButton("Enum Devices")
        btn_enum.setMinimumHeight(40)
        btn_enum.clicked.connect(self.sdk_enum_devices)
        layout.addWidget(btn_enum)
        
        btn_open = QPushButton("Open Camera")
        btn_open.setMinimumHeight(40)
        btn_open.clicked.connect(self.sdk_open_camera)
        layout.addWidget(btn_open)
        
        btn_close = QPushButton("Close Camera")
        btn_close.setMinimumHeight(40)
        btn_close.clicked.connect(self.sdk_close_camera)
        layout.addWidget(btn_close)
        
        btn_start = QPushButton("Start Grabbing")
        btn_start.setMinimumHeight(40)
        btn_start.clicked.connect(self.sdk_start_grabbing)
        layout.addWidget(btn_start)
        
        btn_stop = QPushButton("Stop Grabbing")
        btn_stop.setMinimumHeight(40)
        btn_stop.clicked.connect(self.sdk_stop_grabbing)
        layout.addWidget(btn_stop)
        
        # Регуляторы параметров камеры
        slider_control = SliderControl("Frame Rate", 0, 100, 0, transfer_k=0.1, round_k=1, 
                                       ui_elements=self.ui_elements, controls=self.controls_hikvision, 
                                       callback=self.update_controls_hikvision, parent=self)
        layout.addWidget(slider_control)
        
        slider_control = SliderControl("Exposure", 0, 100000, 0, transfer_k=1, round_k=0,
                                       ui_elements=self.ui_elements, controls=self.controls_hikvision,
                                       callback=self.update_controls_hikvision, parent=self)
        layout.addWidget(slider_control)
        
        slider_control = SliderControl("Gain", 0, 100, 0, transfer_k=0.1, round_k=1,
                                       ui_elements=self.ui_elements, controls=self.controls_hikvision,
                                       callback=self.update_controls_hikvision, parent=self)
        layout.addWidget(slider_control)
        
        # Кнопки получения/установки параметров
        btn_get_params = QPushButton("Get Parameters")
        btn_get_params.setMinimumHeight(40)
        btn_get_params.clicked.connect(self.sdk_get_parameters)
        layout.addWidget(btn_get_params)
        
        btn_set_params = QPushButton("Set Parameters")
        btn_set_params.setMinimumHeight(40)
        btn_set_params.clicked.connect(self.sdk_set_parameters)
        layout.addWidget(btn_set_params)
        
        layout.addStretch()
        
        return tab
    
    def toggle_sdk_ui(self, show):
        """Показать/скрыть UI SDK окно"""
        try:
            self.queue_manager.control_ui.put({'type': 'show' if show else 'hide'})
        except Exception as e:
            print(f"Error toggling SDK UI: {e}")
    
    def sdk_enum_devices(self):
        """Перечислить устройства камеры"""
        try:
            self.queue_manager.ui_to_camera.put({'type': 'enum_devices'})
        except Exception as e:
            print(f"Error enumerating devices: {e}")
    
    def sdk_open_camera(self):
        """Открыть камеру"""
        try:
            # Получаем индекс из UI элементов если есть
            camera_index = 0
            if 'camera_index' in self.ui_elements:
                camera_index = self.ui_elements['camera_index'].get('value', 0)
            self.queue_manager.ui_to_camera.put({'type': 'open', 'camera_index': camera_index})
        except Exception as e:
            print(f"Error opening camera: {e}")
    
    def sdk_close_camera(self):
        """Закрыть камеру"""
        try:
            self.queue_manager.ui_to_camera.put({'type': 'close'})
        except Exception as e:
            print(f"Error closing camera: {e}")
    
    def sdk_start_grabbing(self):
        """Начать захват кадров"""
        try:
            self.queue_manager.ui_to_camera.put({'type': 'start_grabbing'})
        except Exception as e:
            print(f"Error starting grabbing: {e}")
    
    def sdk_stop_grabbing(self):
        """Остановить захват кадров"""
        try:
            self.queue_manager.ui_to_camera.put({'type': 'stop_grabbing'})
        except Exception as e:
            print(f"Error stopping grabbing: {e}")
    
    def sdk_get_parameters(self):
        """Получить параметры камеры"""
        try:
            self.queue_manager.ui_to_camera.put({'type': 'get_parameters'})
        except Exception as e:
            print(f"Error getting parameters: {e}")
    
    def sdk_set_parameters(self):
        """Установить параметры камеры"""
        try:
            # Получаем значения из controls_hikvision
            frame_rate = self.controls_hikvision.get('Frame Rate', 0)
            exposure = self.controls_hikvision.get('Exposure', 0)
            gain = self.controls_hikvision.get('Gain', 0)
            
            self.queue_manager.ui_to_camera.put({
                'type': 'set_parameters',
                'frame_rate': frame_rate,
                'exposure_time': exposure,
                'gain': gain
            })
        except Exception as e:
            print(f"Error setting parameters: {e}")

    def create_tab_neuroun(self):
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)

        checkbox_control = CheckboxControl("neuroun", True, "left", ui_elements=self.ui_elements, controls=self.controls_neuroun, callback = self.update_controls_neuroun, parent=self)
        layout.addWidget(checkbox_control)

        slider_control = SliderControl("predict", 0, 100, 43, transfer_k=0.01, round_k=2, ui_elements=self.ui_elements, controls=self.controls_neuroun, callback = self.update_controls_neuroun, parent=self)
        layout.addWidget(slider_control)

        checkbox_control = CheckboxControl("find_object", 
                                            True, 
                                            "left", 
                                            ui_elements=self.ui_elements,
                                            controls=self.controls_neuroun, 
                                            callback = self.update_controls_neuroun, 
                                            parent=self
                                            )
        
        layout.addWidget(checkbox_control)

        checkbox_control = CheckboxControl("find_object_train", 
                                            False, 
                                            "left", 
                                            ui_elements=self.ui_elements, 
                                            controls=[self.controls, self.controls_neuroun], 
                                            callback = [self.update_controls, self.update_controls_neuroun],
                                            parent=self
                                            )
        
        layout.addWidget(checkbox_control)
        
        checkbox_control = CheckboxControl("save_image_brak", 
                                           True, 
                                           "left", 
                                           ui_elements=self.ui_elements, 
                                           controls=[self.controls_draw],
                                           callback = [self.update_controls_draw],
                                           parent=self
                                           )
        
        layout.addWidget(checkbox_control)

        return tab
    

    # Добавим функцию для обновления стиля рамки
    def update_image_border(self, pixmap):
        width = pixmap.width()
        height = pixmap.height()
        self.image_label.setStyleSheet(f"border: 1px solid white; width: {width}px; height: {height}px;")


    def update_data(self, frames):


        # frame = data['frame']
        # timestrap = data['timestrap']

        # if self.get_control_value("history") == 100:
        frame = frames[0]
        self.update_image(frame)
        
        #total =  round((time.time() - timestrap) * 1000, 0)
        #total_all = data['total_all']
        #self.total_label.setText(f'{total} ms\nall: {total_all}')
        #self.total_label.setText(f'all: {total_all}')


    def update_image(self, frame):
        height, width, channel = frame.shape
        new_height = int(height * 0.69)
        new_width = int(width * 0.69)

        frame_resized = cv2.resize(frame, (new_width, new_height))

        bytes_per_line = 3 * new_width
        q_img = QImage(frame_resized.data, new_width, new_height, bytes_per_line, QImage.Format_RGB888).rgbSwapped()
        pixmap = QPixmap.fromImage(q_img)
        self.image_label.setPixmap(pixmap)


    def update_controls(self):
        # self.controls['top'] = 145
        # self.controls['bottom'] = 535
        # self.controls['left'] = 225
        # self.controls['right'] = 1030

        self.controls['neuroun'] = self.controls_neuroun['neuroun']

        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_frame_process)
        self.queue_manager.control_frame_process.put(self.controls)


    def update_controls_camera(self):
        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_camera)
        self.queue_manager.control_camera.put(self.controls_camera)   
        self.queue_manager.control_camera_event.set() 


    def update_controls_conveyor(self):
        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_conveyor)
        self.queue_manager.control_conveyor.put(self.controls_conveyor)
        self.queue_manager.control_conveyor_event.set()


    def update_controls_neuroun(self):
        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_neuroun)
        self.queue_manager.control_neuroun.put(self.controls_neuroun)
        self.queue_manager.control_neuroun_event.set()

    
    def update_controls_draw(self):
        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_draw)
        self.queue_manager.control_draw.put(self.controls_draw)
        self.queue_manager.control_draw_event.set()


    def update_controls_robot(self):
        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_robot)
        self.queue_manager.control_robot.put(self.controls_robot)
        self.queue_manager.control_robot_event.set()
    
    def update_controls_hikvision(self):
        """Обновление управления Hikvision SDK"""
        # Параметры уже отправляются через отдельные методы
        pass
    
    def toggle_tabs_visibility(self):
        """Скрыть/показать вкладки"""
        self.tabs_visible = not self.tabs_visible
        if self.tabs_visible:
            self.tab_widget.show()
            self.btn_toggle_tabs.setText("Скрыть вкладки")
        else:
            self.tab_widget.hide()
            self.btn_toggle_tabs.setText("Показать вкладки")
    
    def create_tab_processing(self):
        """Создать вкладку управления обработкой изображений"""
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)
        
        # Чекбокс включения обработки
        checkbox_control = CheckboxControl("enable_processing", False, "left",
                                         ui_elements=self.ui_elements, 
                                         controls=self.controls_processing,
                                         callback=self.update_controls_processing,
                                         parent=self)
        layout.addWidget(checkbox_control)
        
        # Чекбокс показа маски
        checkbox_control = CheckboxControl("show_mask", False, "left",
                                         ui_elements=self.ui_elements,
                                         controls=self.controls_processing,
                                         callback=self.update_controls_processing,
                                         parent=self)
        layout.addWidget(checkbox_control)
        
        # Чекбокс переключения между оригиналом и обработанным
        checkbox_control = CheckboxControl("show_processed", False, "left",
                                         ui_elements=self.ui_elements,
                                         controls=self.controls_processing,
                                         callback=self.update_controls_processing,
                                         parent=self)
        layout.addWidget(checkbox_control)
        
        # Регуляторы размера окна изображения
        slider_control = SliderControl("image_width", 200, 2000, 1024,
                                      ui_elements=self.ui_elements,
                                      controls=self.controls_processing,
                                      callback=self.update_controls_processing,
                                      parent=self)
        layout.addWidget(slider_control)
        
        slider_control = SliderControl("image_height", 200, 2000, 780,
                                      ui_elements=self.ui_elements,
                                      controls=self.controls_processing,
                                      callback=self.update_controls_processing,
                                      parent=self)
        layout.addWidget(slider_control)
        
        # Регуляторы обрезки изображения
        slider_control = SliderControl("crop_top", 0, 720, 0,
                                      ui_elements=self.ui_elements,
                                      controls=self.controls_processing,
                                      callback=self.update_controls_processing,
                                      parent=self)
        layout.addWidget(slider_control)
        
        slider_control = SliderControl("crop_bottom", 0, 720, 720,
                                      ui_elements=self.ui_elements,
                                      controls=self.controls_processing,
                                      callback=self.update_controls_processing,
                                      parent=self)
        layout.addWidget(slider_control)
        
        slider_control = SliderControl("crop_left", 0, 1280, 0,
                                      ui_elements=self.ui_elements,
                                      controls=self.controls_processing,
                                      callback=self.update_controls_processing,
                                      parent=self)
        layout.addWidget(slider_control)
        
        slider_control = SliderControl("crop_right", 0, 1280, 1280,
                                      ui_elements=self.ui_elements,
                                      controls=self.controls_processing,
                                      callback=self.update_controls_processing,
                                      parent=self)
        layout.addWidget(slider_control)
        
        # Регуляторы HSV нижней границы
        slider_control = SliderControl("hl", 0, 179, 0,
                                      ui_elements=self.ui_elements,
                                      controls=self.controls_processing,
                                      callback=self.update_controls_processing,
                                      parent=self)
        layout.addWidget(slider_control)
        
        slider_control = SliderControl("sl", 0, 255, 0,
                                      ui_elements=self.ui_elements,
                                      controls=self.controls_processing,
                                      callback=self.update_controls_processing,
                                      parent=self)
        layout.addWidget(slider_control)
        
        slider_control = SliderControl("vl", 0, 255, 0,
                                      ui_elements=self.ui_elements,
                                      controls=self.controls_processing,
                                      callback=self.update_controls_processing,
                                      parent=self)
        layout.addWidget(slider_control)
        
        # Регуляторы HSV верхней границы
        slider_control = SliderControl("hm", 0, 179, 179,
                                      ui_elements=self.ui_elements,
                                      controls=self.controls_processing,
                                      callback=self.update_controls_processing,
                                      parent=self)
        layout.addWidget(slider_control)
        
        slider_control = SliderControl("sm", 0, 255, 255,
                                      ui_elements=self.ui_elements,
                                      controls=self.controls_processing,
                                      callback=self.update_controls_processing,
                                      parent=self)
        layout.addWidget(slider_control)
        
        slider_control = SliderControl("vm", 0, 255, 255,
                                      ui_elements=self.ui_elements,
                                      controls=self.controls_processing,
                                      callback=self.update_controls_processing,
                                      parent=self)
        layout.addWidget(slider_control)
        
        layout.addStretch()
        
        return tab
    
    def update_controls_processing(self):
        """Обновление управления процессом обработки"""
        # Обновляем размер окна изображения если изменился
        if 'image_width' in self.controls_processing or 'image_height' in self.controls_processing:
            width = self.controls_processing.get('image_width', 1024)
            height = self.controls_processing.get('image_height', 780)
            if hasattr(self, 'image_label'):
                # Изменяем максимальный размер label (реальный размер будет зависеть от layout)
                self.image_label.setMaximumSize(width, height)
                # Также можно изменить размер всего окна
                # self.setFixedSize(width, height)
        
        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_processing)
        self.queue_manager.control_processing.put(self.controls_processing)
        self.queue_manager.control_processing_event.set()


    def update_access_level(self, level: int):
        self.current_access_level = level

        for name, data  in self.ui_elements.items():
            if name == 'func_update': continue
            widget = data['element'].parent()  # Получаем родительский виджет
            enable = level >= data.get('min_access', 0)
            data['element'].setEnabled(enable)
            widget.setEnabled(enable)
            
            widget.setStyleSheet("opacity: 0.4;" if not enable else "opacity: 1;")         
            #widget.setVisible(enable)  # Скрываем полностью при необходимости


    def show(self):
        super().show()

    
    def close(self):
        super().close()


    def close_programm(self):
        self.stop_event.set()
        time.sleep(3)
        self.close()