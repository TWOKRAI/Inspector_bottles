import cv2
from PyQt5.QtWidgets import (QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QLabel,
                             QSlider, QCheckBox, QTabWidget, QScrollArea, QPushButton, QMessageBox,
                             QSpacerItem, QSizePolicy)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap, QFont
from PyQt5.QtGui import QCursor
from PyQt5.QtCore import QTimer
import time
import pandas as pd

from PyQt5.QtWidgets import QHBoxLayout, QLabel, QSlider, QWidget
from PyQt5.QtCore import Qt

# from App.Components.header import HeaderWidget
from  App2.Components.sliders import SliderControl, SliderControl_change
from  App2.Components.Checkboxs import CheckboxControl
from  App2.Components.sort_widget import SpinWidget

from App2.Widget.Frame_process_widjet.Threads.thread_image_update import UpdateImage


class FrameProcessWindow(QMainWindow):
    def __init__(self, window_manager = None):
        super().__init__()

        self.window_manager = window_manager

        if not window_manager is None:
            self.queue_manager = self.window_manager.queue_manager
            #self.stop_event = self.window_manager.stop_event
            self.fullscreen = self.window_manager.fullscreen
        
        #self.header = HeaderWidget(window_manager=self.window_manager)

        self.ui_elements = {}
        self.controls = {}
        self.controls_camera = {}
        self.controls_camera_out = {}
        self.controls_neuroun = {}
        self.controls_draw = {}
        self.controls_robot = {}
        self.controls_conveyor = {}
        
        self.current_access_level = 0

        self.init_ui()

        if self.fullscreen: self.showFullScreen()


        #self.load_dataframe_from_excel()
 
        self.change= True

        self.create_dataframe()


        self.coloumn = 'real_value'

        self.apply_settings_from_dict(value_column=self.coloumn)
        

        #self.coloumn = 'default_value'
        

        self.update_controls()
        self.update_controls_camera()
        self.update_controls_camera_out()
        self.update_controls_neuroun()
        self.update_controls_draw()
        self.update_controls_robot()
        self.update_controls_conveyor()

        
        self.update_access_level(self.current_access_level)

        self.worker_update_image = UpdateImage(window_manager = self)
        self.worker_update_image.update_frame.connect(self.update_data)
        self.worker_update_image.start()


    def init_ui(self):
        # Создание главного окна
        self.setWindowTitle("Image Processing App")
        #self.setGeometry(100, 100, 1200, 800)
        self.setGeometry(100, 100, 800, 600)

        main_layout = QVBoxLayout()
        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

        #main_layout.addSpacing(3)
        main_content_layout = self.create_main_content_layout()
        main_layout.addLayout(main_content_layout)
        main_layout.addSpacing(15)

        main_layout.addStretch()
        tab_widget = self.create_tabs()
        main_layout.addWidget(tab_widget)


    def create_main_content_layout(self):
        main_content_layout = QHBoxLayout()

        # # Левая панель с чекбоксами
        # checkbox_layout_left = QVBoxLayout()

        # checkbox_control = CheckboxControl("draw", 
        #                                    True, 
        #                                    "top", 
        #                                    ui_elements=self.ui_elements, 
        #                                     controls=[self.controls_draw], 
        #                                     callback = [self.update_controls_draw], 
        #                                    parent=self
        #                                    )
        
        # checkbox_layout_left.addWidget(checkbox_control)

        # checkbox_control = CheckboxControl("circles",
        #                                     True, 
        #                                     "top", 
        #                                     ui_elements=self.ui_elements, 
        #                                     controls=[self.controls_draw], 
        #                                     callback = [self.update_controls_draw], 
        #                                     parent=self
        #                                     )

        # checkbox_layout_left.addWidget(checkbox_control)

        # checkbox_control = CheckboxControl("rectangles", 
        #                                    True, 
        #                                    "top", 
        #                                    ui_elements=self.ui_elements, 
        #                                     controls=[self.controls_draw], 
        #                                     callback = [self.update_controls_draw], 
        #                                    parent=self
        #                                    )
        
        # checkbox_layout_left.addWidget(checkbox_control)

        # checkbox_control = CheckboxControl("record_video", 
        #                                    False, 
        #                                    "top", 
        #                                    ui_elements=self.ui_elements, 
        #                                    controls=[self.controls_camera, self.controls, self.controls_draw], 
        #                                    callback = [self.update_controls_camera, self.update_controls, self.update_controls_draw], 
        #                                    parent=self
        #                                    )
        
        # checkbox_layout_left.addWidget(checkbox_control)

        main_content_layout.addSpacing(10)

        tabs = [
            ('ВКЛАДКА 1', self.create_tab_checkbox_camera),
            ('ВКЛАДКА 2', self.create_tab_checkbox_draw),
        ]
        tabs_checkbox_left = self.create_tabs_checkbox(position='left', tabs=tabs)

        #tabs_checkbox_left = self.create_tabs_checkbox(position='left')
        main_content_layout.addWidget(tabs_checkbox_left)

        main_content_layout.addSpacing(12)

        # Центральная панель с изображением
        image_layout = QVBoxLayout()
        image_layout.addStretch()

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setScaledContents(False)
        self.image_label.setStyleSheet("border: 2px solid white; border-radius: 10px;")
        image_layout.addWidget(self.image_label)

        image_layout.addStretch()
        main_content_layout.addLayout(image_layout)

        main_content_layout.addSpacing(12)

        tabs = [
            ('ВКЛАДКА 1', self.create_tab_checkbox_robotic),
            ('ВКЛАДКА 2', self.create_tab_checkbox_neuroun),
        ]
        tabs_checkbox_right = self.create_tabs_checkbox(position='right', tabs=tabs)

        #tabs_checkbox_right = self.create_tabs_checkbox_2(position='right')
        main_content_layout.addWidget(tabs_checkbox_right)

        main_content_layout.addSpacing(20)

        return main_content_layout


    def create_tabs_checkbox_2(self, position='left'):
        self.tab_widgets_checkbox = QTabWidget()
        self.tab_widgets_checkbox.setFixedHeight(345)

        match position:
            case 'left': 
                self.tab_widgets_checkbox.setTabPosition(QTabWidget.West)
            case 'right': 
                self.tab_widgets_checkbox.setTabPosition(QTabWidget.East)

        self.tab_widgets_checkbox.setStyleSheet("QTabBar::tab { height: 160px; width: 20px; }") 
        
        self.create_tab(self.tab_widgets_checkbox, '1', self.create_tab_vision(), scrollable=False)
        self.create_tab(self.tab_widgets_checkbox, '2', self.create_tab_robotic(), scrollable=False)

        return self.tab_widgets_checkbox


    def create_tabs_checkbox(self, position='left', tabs=None):
        self.tab_widgets_checkbox = QTabWidget()
        self.tab_widgets_checkbox.setFixedHeight(345)

        match position:
            case 'left':
                self.tab_widgets_checkbox.setTabPosition(QTabWidget.West)
            case 'right':
                self.tab_widgets_checkbox.setTabPosition(QTabWidget.East)

        self.tab_widgets_checkbox.setStyleSheet("QTabBar::tab { height: 160px; width: 20px; }")

        for tab_name, tab_function in tabs:
            self.create_tab(self.tab_widgets_checkbox, tab_name, tab_function(), scrollable=False)

        return self.tab_widgets_checkbox


    # def create_tab_vision(self):
    #     tab = QWidget()
    #     layout = QVBoxLayout()
    #     tab.setLayout(layout)

    #     checkbox_control = CheckboxControl("draw", 
    #                                        True, 
    #                                        "top", 
    #                                        min_access=0,
    #                                        ui_elements=self.ui_elements, 
    #                                         controls=[self.controls_draw], 
    #                                         callback = [self.update_controls_draw], 
    #                                        parent=self
    #                                        )
        
    #     layout.addWidget(checkbox_control)

    #     checkbox_control = CheckboxControl("circles",
    #                                         True, 
    #                                         "top", 
    #                                         min_access=0,
    #                                         ui_elements=self.ui_elements, 
    #                                         controls=[self.controls_draw], 
    #                                         callback = [self.update_controls_draw], 
    #                                         parent=self
    #                                         )

    #     layout.addWidget(checkbox_control)

    #     checkbox_control = CheckboxControl("rectangles", 
    #                                        True, 
    #                                        "top",
    #                                        min_access=0,
    #                                        ui_elements=self.ui_elements, 
    #                                         controls=[self.controls_draw], 
    #                                         callback = [self.update_controls_draw], 
    #                                        parent=self
    #                                        )
        
    #     layout.addWidget(checkbox_control)

    #     checkbox_control = CheckboxControl("record_video", 
    #                                        False, 
    #                                        "top", 
    #                                        min_access=2,
    #                                        ui_elements=self.ui_elements, 
    #                                        controls=[self.controls_camera, self.controls, self.controls_draw], 
    #                                        callback = [self.update_controls_camera, self.update_controls, self.update_controls_draw], 
    #                                        parent=self
    #                                        )
        
    #     layout.addWidget(checkbox_control)

    #     return tab
    

    def create_tab_checkbox_camera(self):
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)

        checkbox_control = CheckboxControl("enable_camera", 
                                           True, 
                                           "top", 
                                           min_access=1,
                                           ui_elements=self.ui_elements, 
                                           controls=self.controls_camera, 
                                           callback = self.update_controls_camera, 
                                           parent=self
                                           )
        
        layout.addWidget(checkbox_control)

        checkbox_control = CheckboxControl("camera_robot", 
                                           False, 
                                           "top", 
                                           min_access=1,
                                           ui_elements=self.ui_elements, 
                                            controls=[self.controls_draw], 
                                            callback = [self.update_controls_draw], 
                                           parent=self
                                           )
        
        layout.addWidget(checkbox_control)


        checkbox_control = CheckboxControl("enable_camera_out", 
                                           True, 
                                           "top", 
                                           min_access=1,
                                           ui_elements=self.ui_elements, 
                                            controls=[self.controls_camera_out], 
                                            callback = [self.update_controls_camera_out], 
                                           parent=self
                                           )
        
        layout.addWidget(checkbox_control)


        checkbox_control = CheckboxControl("record_video", 
                                           False, 
                                           "top", 
                                           ui_elements=self.ui_elements, 
                                           controls=[self.controls_camera, self.controls, self.controls_draw], 
                                           callback = [self.update_controls_camera, self.update_controls, self.update_controls_draw], 
                                           parent=self
                                           )
        
        layout.addWidget(checkbox_control)

        return tab
    

    def create_tab_checkbox_draw(self):
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)

        checkbox_control = CheckboxControl("draw", 
                                           True, 
                                           "top", 
                                           min_access=0,
                                           ui_elements=self.ui_elements, 
                                            controls=[self.controls_draw], 
                                            callback = [self.update_controls_draw], 
                                           parent=self
                                           )
        
        layout.addWidget(checkbox_control)

        checkbox_control = CheckboxControl("circles",
                                            True, 
                                            "top", 
                                            min_access=0,
                                            ui_elements=self.ui_elements, 
                                            controls=[self.controls_draw], 
                                            callback = [self.update_controls_draw], 
                                            parent=self
                                            )

        layout.addWidget(checkbox_control)

        checkbox_control = CheckboxControl("rectangles", 
                                           True, 
                                           "top", 
                                           min_access=0,
                                           ui_elements=self.ui_elements, 
                                            controls=[self.controls_draw], 
                                            callback = [self.update_controls_draw], 
                                           parent=self
                                           )
        
        layout.addWidget(checkbox_control)

        return tab


    def create_tab_checkbox_robotic(self):
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)

        checkbox_control = CheckboxControl("servo_on", 
                                           False, 
                                           "top", 
                                           min_access=1,
                                           ui_elements=self.ui_elements, 
                                           controls=self.controls_robot, 
                                           callback = self.update_controls_robot,
                                            parent=self
                                            )
        
        layout.addWidget(checkbox_control)

        self.checkbox_control_2 = CheckboxControl("robot_on", 
                                           False, 
                                           "top", 
                                           min_access=1,
                                           ui_elements=self.ui_elements, 
                                           controls= self.controls_robot, 
                                           callback = self.update_controls_robot, 
                                           parent=self
                                           )
        layout.addWidget(self.checkbox_control_2)

        self.checkbox_control_3 = CheckboxControl("capture",
                                                False,
                                                "top",
                                                min_access=2,
                                                ui_elements=self.ui_elements,
                                                controls=self.controls_robot,
                                                callback=self.update_controls_robot,
                                                parent=self
                                                )
        layout.addWidget(self.checkbox_control_3)


        checkbox_control = CheckboxControl("server", 
                                           True, 
                                           "top", 
                                           min_access=1,
                                           ui_elements=self.ui_elements, 
                                           controls=self.controls_robot, 
                                           callback = self.update_controls_robot, 
                                           parent=self
                                           )
        
        layout.addWidget(checkbox_control)

        return tab


    def create_tab_checkbox_neuroun(self):
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)

        checkbox_control = CheckboxControl("neuroun", 
                                           True, 
                                           "top", 
                                           min_access=1,
                                           ui_elements=self.ui_elements, 
                                           controls=self.controls_neuroun, 
                                           callback = self.update_controls_neuroun, 
                                           parent=self)
        
        layout.addWidget(checkbox_control)

        checkbox_control = CheckboxControl("processing", 
                                           True, 
                                           "top", 
                                           min_access=1,
                                           ui_elements=self.ui_elements, 
                                           controls=self.controls, 
                                           callback = self.update_controls, 
                                           parent=self
                                           )
        
        layout.addWidget(checkbox_control)

        return tab


    def create_tabs(self):
        self.tab_widget = QTabWidget()
        self.tab_widget.setFixedHeight(270)
        self.tab_widget.setStyleSheet("QTabBar::tab { height: 35px; width: 95px; }")  # Увеличение размера вкладок

        self.create_tab(self.tab_widget, "Сорта", self.create_tab_sort())
        self.create_tab(self.tab_widget, "Форма", self.create_tab_circle())
        self.create_tab(self.tab_widget, "Разное", self.create_tab_cropped_area()) 
        self.create_tab(self.tab_widget, "Параметры", self.create_tab_parameters()) 
        self.create_tab(self.tab_widget, "Нейрон", self.create_tab_neuroun())
        self.create_tab(self.tab_widget, "Робот", self.create_tab_robot()) 

        return self.tab_widget


    def create_tab(self, tabs: QTabWidget, name, content_widget, scrollable=True):
        if scrollable:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setStyleSheet("QScrollBar:vertical { width: 40px; }")
            
            scroll.setWidget(content_widget)
            tabs.addTab(scroll, name)
        else:
            tabs.addTab(content_widget, name)


    def label_tab(self, label):
        widget = QWidget()

        layout = QHBoxLayout()

        # Создайте надпись
        label = QLabel(label)

        font = QFont("Arial", 14)
        label.setFont(font)

        # Добавьте растяжку слева
        left_spacer = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout.addSpacerItem(left_spacer)

        # Добавьте надпись в центре
        layout.addWidget(label)

        # Добавьте растяжку справа
        right_spacer = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        layout.addSpacerItem(right_spacer)

        widget.setLayout(layout)

        return widget
    

    def create_tab_sort(self):
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)

        label_tab = self.label_tab('Сортовые параметры')
        layout.addWidget(label_tab)

        
        self.sort_widget = SpinWidget(2)
        layout.addWidget(self.sort_widget)

        self.sort_widget.applied.connect(
            lambda column_name: self.apply_sort(column_name)
        )

        self.sort_widget.saved.connect(
            lambda column_name: self.save_sort(column_name)
        )
        self.sort_widget.default.connect(
            lambda column_name: self.default_sort(column_name)
        )

        self.button_default = QPushButton('Сбросить значения')  # Устанавливаем название кнопки
        self.button_default.setFixedSize(200, 50)  # Устанавливаем размеры кнопки (ширина, высота)
        
        # Добавляем действие по нажатию
        self.button_default.clicked.connect(self.reset_count)

        layout.addWidget(self.button_default)

        return tab


    def create_tab_circle(self):
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)

        label_tab = self.label_tab('Параметры нахождения кругов')
        layout.addWidget(label_tab)

        slider_control = SliderControl_change("dp", 
                                       1, 
                                       20, 
                                       14, 
                                       transfer_k= 0.1, 
                                       round_k=1, 
                                       min_access=2, 
                                       ui_elements=self.ui_elements, 
                                       controls=self.controls, 
                                       callback = self.update_controls, 
                                       parent=self,
                                       label = 'Разрешение'
                                       )
        
        layout.addWidget(slider_control)

        slider_control = SliderControl_change("minDist", 
                                                1, 
                                                100,
                                                51, 
                                                min_access=2,
                                                ui_elements=self.ui_elements, 
                                                controls=self.controls, 
                                                callback = self.update_controls, 
                                                parent=self,
                                                label = 'Мин. расстояние'
                                                )
        layout.addWidget(slider_control)

        slider_control = SliderControl_change("param1", 
                                       5, 
                                       200, 
                                       47, 
                                       min_access=2, 
                                       ui_elements=self.ui_elements, 
                                       controls=self.controls, 
                                       callback = self.update_controls, 
                                       parent=self,
                                       label = 'Чувствительность границ'
                                       )
        
        layout.addWidget(slider_control)

        slider_control = SliderControl_change("param2", 
                                        5,
                                        200, 
                                        31,  
                                        min_access=2,
                                        ui_elements=self.ui_elements, 
                                        controls=self.controls, 
                                        callback = self.update_controls, 
                                        parent=self,
                                        label = 'Чувствительность центра'
                                        )
        
        layout.addWidget(slider_control)

        slider_control = SliderControl_change("minRadius", 
                                       0, 
                                       100, 
                                       22,  
                                       min_access=2, 
                                       ui_elements=self.ui_elements, 
                                       controls=self.controls, 
                                       callback = self.update_controls, 
                                       parent=self,
                                       label = 'Мин. радиус'
                                       )
        
        layout.addWidget(slider_control)

        slider_control = SliderControl_change("maxRadius", 
                                       0, 
                                       100, 
                                       41,  
                                       min_access=2, 
                                       ui_elements=self.ui_elements, 
                                       controls=self.controls, 
                                       callback = self.update_controls, 
                                       parent=self,
                                       label = 'Макс. радиус'
                                       )
        
        layout.addWidget(slider_control)

        return tab

    def create_tab_cropped_area(self):
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)

        
        # checkbox_control = CheckboxControl("camera_robot", 
        #                                    False, 
        #                                    "top", 
        #                                    ui_elements=self.ui_elements, 
        #                                     controls=[self.controls_draw], 
        #                                     callback = [self.update_controls_draw], 
        #                                    parent=self
        #                                    )
        
        # layout.addWidget(checkbox_control)


        # checkbox_control = CheckboxControl("enable_camera_out", 
        #                                    True, 
        #                                    "top", 
        #                                    ui_elements=self.ui_elements, 
        #                                     controls=[self.controls_camera_out], 
        #                                     callback = [self.update_controls_camera_out], 
        #                                    parent=self
        #                                    )
        
        # layout.addWidget(checkbox_control)

        # self.setLayout(layout)

        self.slider_control_b1 = SliderControl_change("history", 
                                       0, 
                                       120, 
                                       120, 
                                       transfer_k=1, 
                                       round_k=1, 
                                       min_access=1, 
                                       ui_elements=self.ui_elements, 
                                       controls=[self.controls_draw], 
                                       callback = [self.update_controls_draw], 
                                       parent=self,
                                       label = 'История'
                                       )
        
        layout.addWidget(self.slider_control_b1)


        # slider_control = SliderControl("history", 
        #                                0, 
        #                                120, 
        #                                120, 
        #                                ui_elements=self.ui_elements, 
        #                                controls=[self.controls_draw], 
        #                                callback = [self.update_controls_draw], 
        #                                parent=self
        #                                )
        
        # layout.addWidget(slider_control)

        self.slider_control_b2 = SliderControl_change("height", 
                                       0, 
                                       600, 
                                       250, 
                                       transfer_k=1, 
                                       round_k=1, 
                                       min_access=2, 
                                       ui_elements=self.ui_elements, 
                                       controls=[self.controls], 
                                       callback = [self.update_controls], 
                                       parent=self,
                                       label = 'высота выреза'
                                       )
        
        layout.addWidget(self.slider_control_b2)

        # slider_control = SliderControl("height", 0, 600, 250, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
        # layout.addWidget(slider_control)

        self.slider_control_b3 = SliderControl_change("y_delta", 
                                       0, 
                                       100, 
                                       31, 
                                       transfer_k=1, 
                                       round_k=1, 
                                       min_access=1, 
                                       ui_elements=self.ui_elements, 
                                       controls=[self.controls, self.controls_draw], 
                                       callback = [self.update_controls, self.update_controls_draw], 
                                       parent=self,
                                       label = 'Y дельта'
                                       )
        
        layout.addWidget(self.slider_control_b3)

        # slider_control = SliderControl("y_delta", 
        #                                0, 
        #                                100, 
        #                                31, 
        #                                ui_elements=self.ui_elements, 
        #                                controls=[self.controls, self.controls_draw], 
        #                                callback = [self.update_controls, self.update_controls_draw], 
        #                                parent=self
        #                                )
        
        # layout.addWidget(slider_control)

        self.slider_control_b4 = SliderControl_change("x_delta", 
                                       0, 
                                       100, 
                                       21, 
                                       transfer_k=1, 
                                       round_k=1, 
                                       min_access=1, 
                                       ui_elements=self.ui_elements, 
                                       controls=[self.controls], 
                                       callback = [self.update_controls], 
                                       parent=self,
                                       label = 'X дельта'
                                       )
        
        layout.addWidget(self.slider_control_b4)

        # slider_control = SliderControl("x_delta", 0, 100, 21, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
        # layout.addWidget(slider_control)

        self.slider_control_b5 = SliderControl_change("x_min", 
                                       0, 
                                       1280, 
                                       150, 
                                       transfer_k=1, 
                                       round_k=1, 
                                       min_access=1, 
                                       ui_elements=self.ui_elements, 
                                       controls=[self.controls, self.controls_draw], 
                                       callback = [self.update_controls, self.update_controls_draw], 
                                       parent=self,
                                       label = 'Минимальный Х'
                                       )
        
        layout.addWidget(self.slider_control_b5)

        # slider_control = SliderControl_change("x_min", 
        #                                0, 
        #                                1280, 
        #                                150, 
        #                                ui_elements=self.ui_elements, 
        #                                controls=[self.controls, self.controls_draw], 
        #                                callback = [self.update_controls, self.update_controls_draw], 
        #                                parent=self, 
        #                                label = 'Минимальный Х'
        #                                )
        
        # layout.addWidget(slider_control)

        self.slider_control_b6 = SliderControl_change("x_max", 
                                       0, 
                                       1280, 
                                       730, 
                                       transfer_k=1, 
                                       round_k=1, 
                                       min_access=1, 
                                       ui_elements=self.ui_elements, 
                                       controls=[self.controls, self.controls_draw], 
                                       callback = [self.update_controls, self.update_controls_draw], 
                                       parent=self,
                                       label = 'Максимальный Х'
                                       )
        
        layout.addWidget(self.slider_control_b6)


        # slider_control = SliderControl("x_max", 
        #                                0, 
        #                                1280, 
        #                                730, 
        #                                ui_elements=self.ui_elements, 
        #                                controls=[self.controls, self.controls_draw], 
        #                                callback = [self.update_controls, self.update_controls_draw], 
        #                                parent=self
        #                                )
        

        # layout.addWidget(slider_control)

        self.slider_control_b7 = SliderControl_change("conveyor_freq", 
                                       10, 
                                       50, 
                                       25, 
                                       transfer_k=1, 
                                       round_k=1, 
                                       min_access=1, 
                                       ui_elements=self.ui_elements, 
                                       controls=[self.controls_conveyor], 
                                       callback = [self.update_controls_conveyor], 
                                       parent=self,
                                       label = 'Скорость конвейра'
                                       )
        
        layout.addWidget(self.slider_control_b7)


        # slider_control = SliderControl("conveyor_freq", 1, 50, 25, ui_elements=self.ui_elements, controls=self.controls_conveyor, callback = self.update_controls_conveyor, parent=self)
        # layout.addWidget(slider_control)

        return tab

    # def create_tab_parameters_2(self):
    #     tab = QWidget()
    #     layout = QVBoxLayout()
    #     tab.setLayout(layout)

    #     slider_control = SliderControl("hl", 
    #                                    0, 
    #                                    179, 
    #                                    0, 
    #                                    ui_elements=self.ui_elements, 
    #                                    controls=self.controls, 
    #                                    callback = self.update_controls, 
    #                                    parent=self
    #                                    )
        
    #     layout.addWidget(slider_control)

    #     slider_control = SliderControl("sl", 0, 255, 50, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
    #     layout.addWidget(slider_control)

    #     slider_control = SliderControl("vl", 0, 255, 28, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
    #     layout.addWidget(slider_control)

    #     slider_control = SliderControl("hm", 0, 179, 179, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
    #     layout.addWidget(slider_control)

    #     slider_control = SliderControl("sm", 0, 255, 255, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
    #     layout.addWidget(slider_control)

    #     slider_control = SliderControl("vm", 0, 255, 255, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
    #     layout.addWidget(slider_control)

    #     slider_control = SliderControl("mode_image", 0, 5, 0, ui_elements=self.ui_elements, controls=self.controls_draw, callback = self.update_controls_draw, parent=self)
    #     layout.addWidget(slider_control)

    #     slider_control = SliderControl("area_threshold", 0, 5200, 140, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
    #     layout.addWidget(slider_control)

    #     slider_control = SliderControl("snap_y", 
    #                                     0, 
    #                                     600, 
    #                                     200, 
    #                                     ui_elements=self.ui_elements, 
    #                                     controls=[self.controls, self.controls_robot, self.controls_draw], 
    #                                     callback = [self.update_controls, self.update_controls_robot, self.update_controls_draw], 
    #                                     parent=self
    #                                     )
        
    #     layout.addWidget(slider_control)

    #     slider_control = SliderControl("shift", 0, 7000, 717, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
    #     layout.addWidget(slider_control)

    #     slider_control = SliderControl("shift_y", 0, 1000, 120, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
    #     layout.addWidget(slider_control)

    #     slider_control = SliderControl("mode", 0, 1, 1, ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
    #     layout.addWidget(slider_control)

    #     slider_control = SliderControl("fps", 
    #                                    1, 
    #                                    25, 
    #                                    5, 
    #                                    ui_elements=self.ui_elements, 
    #                                    controls=[self.controls_camera, self.controls_draw], 
    #                                    callback = [self.update_controls_camera, self.update_controls_draw], 
    #                                    parent=self
    #                                    )
                                       
    #     layout.addWidget(slider_control)

    #     checkbox_control = CheckboxControl("calibration_line", 
    #                                        False, 
    #                                        "top", 
    #                                        ui_elements=self.ui_elements, 
    #                                         controls=[self.controls_draw], 
    #                                         callback = [self.update_controls_draw], 
    #                                        parent=self
    #                                        )
        
    #     layout.addWidget(checkbox_control)

    #     checkbox_control = CheckboxControl("calibration_circle", 
    #                                        False, 
    #                                        "top", 
    #                                        ui_elements=self.ui_elements, 
    #                                         controls=[self.controls_draw], 
    #                                         callback = [self.update_controls_draw], 
    #                                        parent=self
    #                                        )
        
    #     layout.addWidget(checkbox_control)

    #     slider_control = SliderControl("resize_delta", 
    #                                    -50, 
    #                                    50, 
    #                                    0, 
    #                                    ui_elements=self.ui_elements, 
    #                                    controls=[self.controls_draw],  
    #                                    callback = [self.update_controls_draw],
    #                                    parent=self)
        
    #     layout.addWidget(slider_control)

    #     self.slider_control_1 = SliderControl("blend_alpha", 
    #                                    0, 
    #                                    100, 
    #                                    100, 
    #                                    transfer_k= 0.01, 
    #                                    round_k=2,
    #                                    ui_elements=self.ui_elements, 
    #                                    controls=[self.controls_draw],  
    #                                    callback = [self.update_controls_draw],
    #                                    parent=self)
        
    #     layout.addWidget(self.slider_control_1)

    #     slider_control = SliderControl("k_size", 
    #                                    0, 
    #                                    200, 
    #                                    115, 
    #                                    transfer_k= 0.01, 
    #                                    round_k=2,
    #                                    ui_elements=self.ui_elements, 
    #                                    controls=[self.controls],  
    #                                    callback = [self.update_controls],
    #                                    parent=self)
        
    #     layout.addWidget(slider_control)

    #     slider_control = SliderControl("method_resize", 
    #                                    0, 
    #                                    4, 
    #                                    2, 
    #                                 #    transfer_k= 0.01, 
    #                                 #    round_k=2,
    #                                    ui_elements=self.ui_elements, 
    #                                    controls=[self.controls],  
    #                                    callback = [self.update_controls],
    #                                    parent=self)
        
    #     layout.addWidget(slider_control)

    #     slider_control = SliderControl("top", 
    #                                     0, 
    #                                     300, 
    #                                     145, 
    #                                 #    transfer_k= 0.01, 
    #                                 #    round_k=2,
    #                                     ui_elements=self.ui_elements, 
    #                                     controls=[self.controls],  
    #                                     callback = [self.update_controls],
    #                                     parent=self)
        
    #     layout.addWidget(slider_control)

    #     slider_control = SliderControl("bottom", 
    #                                     0, 
    #                                     1000, 
    #                                     535, 
    #                                 #    transfer_k= 0.01, 
    #                                 #    round_k=2,
    #                                     ui_elements=self.ui_elements, 
    #                                     controls=[self.controls],  
    #                                     callback = [self.update_controls],
    #                                     parent=self)
        
    #     layout.addWidget(slider_control)

    #     slider_control = SliderControl("left", 
    #                                     0, 
    #                                     500, 
    #                                     190, 
    #                                 #    transfer_k= 0.01, 
    #                                 #    round_k=2,
    #                                     ui_elements=self.ui_elements, 
    #                                     controls=[self.controls],  
    #                                     callback = [self.update_controls],
    #                                     parent=self)
        
    #     layout.addWidget(slider_control)

    #     slider_control = SliderControl("right", 
    #                                     0, 
    #                                     1500, 
    #                                     1054, 
    #                                 #    transfer_k= 0.01, 
    #                                 #    round_k=2,
    #                                     ui_elements=self.ui_elements, 
    #                                     controls=[self.controls],  
    #                                     callback = [self.update_controls],
    #                                     parent=self)
        
    #     layout.addWidget(slider_control)
        
    #     return tab
    
    def create_tab_parameters(self):
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)

        self.slider_control_c1 = SliderControl_change("hl",
                                            0,
                                            179,
                                            0,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls],
                                            callback=[self.update_controls],
                                            parent=self,
                                            label='HL'
                                            )
        layout.addWidget(self.slider_control_c1)

        self.slider_control_c2 = SliderControl_change("sl",
                                            0,
                                            255,
                                            50,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls],
                                            callback=[self.update_controls],
                                            parent=self,
                                            label='SL'
                                            )
        layout.addWidget(self.slider_control_c2)

        self.slider_control_c3 = SliderControl_change("vl",
                                            0,
                                            255,
                                            28,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls],
                                            callback=[self.update_controls],
                                            parent=self,
                                            label='VL'
                                            )
        layout.addWidget(self.slider_control_c3)

        self.slider_control_c4 = SliderControl_change("hm",
                                            0,
                                            179,
                                            179,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls],
                                            callback=[self.update_controls],
                                            parent=self,
                                            label='HM'
                                            )
        layout.addWidget(self.slider_control_c4)

        self.slider_control_c5 = SliderControl_change("sm",
                                            0,
                                            255,
                                            255,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls],
                                            callback=[self.update_controls],
                                            parent=self,
                                            label='SM'
                                            )
        layout.addWidget(self.slider_control_c5)

        self.slider_control_c6 = SliderControl_change("vm",
                                            0,
                                            255,
                                            255,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls],
                                            callback=[self.update_controls],
                                            parent=self,
                                            label='VM'
                                            )
        layout.addWidget(self.slider_control_c6)

        self.slider_control_c7 = SliderControl_change("mode_image",
                                            0,
                                            5,
                                            0,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls_draw],
                                            callback=[self.update_controls_draw],
                                            parent=self,
                                            label='Mode Image'
                                            )
        layout.addWidget(self.slider_control_c7)

        self.slider_control_c8 = SliderControl_change("area_threshold",
                                            0,
                                            5200,
                                            140,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls],
                                            callback=[self.update_controls],
                                            parent=self,
                                            label='Area Threshold'
                                            )
        layout.addWidget(self.slider_control_c8)

        self.slider_control_c9 = SliderControl_change("snap_y",
                                            0,
                                            600,
                                            200,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls, self.controls_robot, self.controls_draw],
                                            callback=[self.update_controls, self.update_controls_robot, self.update_controls_draw],
                                            parent=self,
                                            label='Snap Y'
                                            )
        layout.addWidget(self.slider_control_c9)

        # self.slider_control_c10 = SliderControl_change("shift",
        #                                     0,
        #                                     7000,
        #                                     717,
        #                                     transfer_k=1,
        #                                     round_k=1,
        #                                     min_access=2,
        #                                     ui_elements=self.ui_elements,
        #                                     controls=[self.controls],
        #                                     callback=[self.update_controls],
        #                                     parent=self,
        #                                     label='Shift'
        #                                     )
        # layout.addWidget(self.slider_control_c10)

        self.slider_control_c11 = SliderControl_change("shift_y",
                                            0,
                                            1000,
                                            120,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls],
                                            callback=[self.update_controls],
                                            parent=self,
                                            label='Shift Y'
                                            )
        layout.addWidget(self.slider_control_c11)

        self.slider_control_c12 = SliderControl_change("mode",
                                            0,
                                            1,
                                            1,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls],
                                            callback=[self.update_controls],
                                            parent=self,
                                            label='Mode'
                                            )
        layout.addWidget(self.slider_control_c12)

        self.slider_control_c13 = SliderControl_change("fps",
                                            1,
                                            25,
                                            5,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls_camera, self.controls_draw],
                                            callback=[self.update_controls_camera, self.update_controls_draw],
                                            parent=self,
                                            label='FPS'
                                            )
        layout.addWidget(self.slider_control_c13)

        checkbox_control = CheckboxControl("calibration_line",
                                        False,
                                        "top",
                                        min_access=1,
                                        ui_elements=self.ui_elements,
                                        controls=[self.controls_draw],
                                        callback=[self.update_controls_draw],
                                        parent=self
                                        )
        layout.addWidget(checkbox_control)

        checkbox_control = CheckboxControl("calibration_circle",
                                        False,
                                        "top",
                                        min_access=1,
                                        ui_elements=self.ui_elements,
                                        controls=[self.controls_draw],
                                        callback=[self.update_controls_draw],
                                        parent=self
                                        )
        layout.addWidget(checkbox_control)

        self.slider_control_c14 = SliderControl_change("resize_delta",
                                            -50,
                                            50,
                                            0,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls_draw],
                                            callback=[self.update_controls_draw],
                                            parent=self,
                                            label='Resize Delta'
                                            )
        layout.addWidget(self.slider_control_c14)

        self.slider_control_c15 = SliderControl_change("blend_alpha",
                                            0,
                                            100,
                                            100,
                                            transfer_k=0.01,
                                            round_k=2,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls_draw],
                                            callback=[self.update_controls_draw],
                                            parent=self,
                                            label='Blend Alpha'
                                            )
        layout.addWidget(self.slider_control_c15)

        self.slider_control_c16 = SliderControl_change("k_size",
                                            0,
                                            200,
                                            115,
                                            transfer_k=0.01,
                                            round_k=2,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls],
                                            callback=[self.update_controls],
                                            parent=self,
                                            label='K Size'
                                            )
        layout.addWidget(self.slider_control_c16)

        self.slider_control_c17 = SliderControl_change("method_resize",
                                            0,
                                            4,
                                            2,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls],
                                            callback=[self.update_controls],
                                            parent=self,
                                            label='Method Resize'
                                            )
        layout.addWidget(self.slider_control_c17)

        self.slider_control_c18 = SliderControl_change("top",
                                            0,
                                            300,
                                            145,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls],
                                            callback=[self.update_controls],
                                            parent=self,
                                            label='Top'
                                            )
        layout.addWidget(self.slider_control_c18)

        self.slider_control_c19 = SliderControl_change("bottom",
                                            0,
                                            1000,
                                            535,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls],
                                            callback=[self.update_controls],
                                            parent=self,
                                            label='Bottom'
                                            )
        layout.addWidget(self.slider_control_c19)

        self.slider_control_c20 = SliderControl_change("left",
                                            0,
                                            500,
                                            190,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls],
                                            callback=[self.update_controls],
                                            parent=self,
                                            label='Left'
                                            )
        layout.addWidget(self.slider_control_c20)

        self.slider_control_c21 = SliderControl_change("right",
                                            0,
                                            1500,
                                            1054,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls],
                                            callback=[self.update_controls],
                                            parent=self,
                                            label='Right'
                                            )
        layout.addWidget(self.slider_control_c21)

        return tab


    # def create_tab_robot_2(self):            
    #     tab = QWidget()
    #     layout = QVBoxLayout()
    #     tab.setLayout(layout)


    #     self.slider_control_2 = SliderControl("blend_alpha", 
    #                                    0, 
    #                                    100, 
    #                                    100, 
    #                                    transfer_k= 0.01, 
    #                                    round_k=2,
    #                                    ui_elements=self.ui_elements, 
    #                                    controls=[self.controls_draw],  
    #                                    callback = [self.update_controls_draw],
    #                                    parent=self)
        
    #     layout.addWidget(self.slider_control_2)

    #     # Связываем слайдеры через лямбда-функции
    #     self.slider_control_c15.slider.sliderReleased.connect(
    #         lambda: self.slider_control_2.slider.setValue(self.slider_control_c15.slider.value()))
            
    #     self.slider_control_2.slider.sliderReleased.connect(
    #         lambda: self.slider_control_c15.slider.setValue(self.slider_control_2.slider.value()))


    #     # checkbox_control = CheckboxControl("robot_on", 
    #     #                                    False, 
    #     #                                    "left", 
    #     #                                    ui_elements=self.ui_elements, 
    #     #                                    controls= self.controls_robot, 
    #     #                                    callback = self.update_controls_robot, 
    #     #                                    parent=self
    #     #                                    )
    #     # layout.addWidget(checkbox_control)

    #     checkbox_control = CheckboxControl("capture", 
    #                                        False, 
    #                                        "left", 
    #                                        ui_elements=self.ui_elements, 
    #                                        controls= self.controls_robot, 
    #                                        callback = self.update_controls_robot, 
    #                                        parent=self
    #                                        )
    #     layout.addWidget(checkbox_control)


    #     slider_control = SliderControl("position", 0, 3, 0, ui_elements=self.ui_elements, controls=self.controls_robot, callback = self.update_controls_robot, parent=self)
    #     layout.addWidget(slider_control)

    #     #1760
    #     slider_control = SliderControl("shift_time", 0, 2000, 1760, ui_elements=self.ui_elements, controls=self.controls_robot, callback = self.update_controls_robot, min_access=2, parent=self)
    #     layout.addWidget(slider_control)

    #     slider_control = SliderControl("shift", 0, 1000, 0, ui_elements=self.ui_elements, controls=self.controls_robot,  callback = self.update_controls_robot, parent=self)
    #     layout.addWidget(slider_control)

    #     slider_control = SliderControl("lenght", 0, 200, 0, ui_elements=self.ui_elements, controls=self.controls_robot, callback = self.update_controls_robot,  parent=self)
    #     layout.addWidget(slider_control)
    #     # 46
    #     slider_control = SliderControl("back", -200, 200, 0, ui_elements=self.ui_elements, controls=self.controls_robot, callback = self.update_controls_robot, parent=self)
    #     layout.addWidget(slider_control)

    #     slider_control = SliderControl("pr", 600, 1400, 1130, transfer_k=0.001, round_k=3, ui_elements=self.ui_elements, controls=self.controls_robot, callback = self.update_controls_robot, parent=self)
    #     layout.addWidget(slider_control)

    #     slider_control = SliderControl("tracking", 0, 800, 50, transfer_k=1, round_k=0, ui_elements=self.ui_elements, controls=self.controls_robot, callback = self.update_controls_robot, parent=self)
    #     layout.addWidget(slider_control)

    #     checkbox_control = CheckboxControl("do1", False, "left", ui_elements=self.ui_elements, controls=self.controls_robot, callback = self.update_controls_robot, parent=self)
    #     layout.addWidget(checkbox_control)

    #     checkbox_control = CheckboxControl("do2", False, "left", ui_elements=self.ui_elements, controls=self.controls_robot, callback = self.update_controls_robot, parent=self)
    #     layout.addWidget(checkbox_control)


    #     slider_control = SliderControl("min_rob_x", 
    #                                     50, 
    #                                     590,
    #                                     78,
    #                                     ui_elements=self.ui_elements, 
    #                                     controls=self.controls_robot, 
    #                                     callback = self.update_controls_robot,
    #                                     parent=self
    #                                     )
        
    #     layout.addWidget(slider_control)

    #     slider_control = SliderControl("max_rob_x", 
    #                                     50, 
    #                                     590,
    #                                     488,
    #                                     ui_elements=self.ui_elements, 
    #                                     controls=self.controls_robot, 
    #                                     callback = self.update_controls_robot,
    #                                     parent=self
    #                                     )
        
    #     layout.addWidget(slider_control)


    #     return tab
    
    def create_tab_robot(self):       
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)

        self.checkbox_control_d1 = CheckboxControl("robot_on",
                                                False,
                                                "left",
                                                min_access=1,
                                                ui_elements=self.ui_elements,
                                                controls=self.controls_robot,
                                                callback=self.update_controls_robot,
                                                parent=self
                                                )
        layout.addWidget(self.checkbox_control_d1)

        self.checkbox_control_d2 = CheckboxControl("capture",
                                                False,
                                                "left",
                                                min_access=2,
                                                ui_elements=self.ui_elements,
                                                controls=self.controls_robot,
                                                callback=self.update_controls_robot,
                                                parent=self
                                                )
        layout.addWidget(self.checkbox_control_d2)

        self.slider_control_d1 = SliderControl_change("position",
                                            0,
                                            3,
                                            0,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls_robot],
                                            callback=[self.update_controls_robot],
                                            parent=self,
                                            label='Position'
                                            )
        layout.addWidget(self.slider_control_d1)

        self.slider_control_d2 = SliderControl_change("shift_time",
                                            0,
                                            2000,
                                            1760,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls_robot],
                                            callback=[self.update_controls_robot],
                                            parent=self,
                                            label='Shift Time'
                                            )
        layout.addWidget(self.slider_control_d2)

        self.slider_control_d3 = SliderControl_change("shift",
                                            0,
                                            1000,
                                            0,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls_robot],
                                            callback=[self.update_controls_robot],
                                            parent=self,
                                            label='Shift'
                                            )
        layout.addWidget(self.slider_control_d3)

        self.slider_control_d4 = SliderControl_change("lenght",
                                            0,
                                            200,
                                            0,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=1,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls_robot],
                                            callback=[self.update_controls_robot],
                                            parent=self,
                                            label='Length'
                                            )
        layout.addWidget(self.slider_control_d4)

        self.slider_control_d5 = SliderControl_change("back",
                                            -200,
                                            200,
                                            0,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls_robot],
                                            callback=[self.update_controls_robot],
                                            parent=self,
                                            label='Back'
                                            )
        layout.addWidget(self.slider_control_d5)

        self.slider_control_d6 = SliderControl_change("pr",
                                            600,
                                            1400,
                                            1130,
                                            transfer_k=0.001,
                                            round_k=3,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls_robot],
                                            callback=[self.update_controls_robot],
                                            parent=self,
                                            label='PR'
                                            )
        layout.addWidget(self.slider_control_d6)

        self.slider_control_d7 = SliderControl_change("tracking",
                                            0,
                                            800,
                                            50,
                                            transfer_k=1,
                                            round_k=0,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls_robot],
                                            callback=[self.update_controls_robot],
                                            parent=self,
                                            label='Tracking'
                                            )
        layout.addWidget(self.slider_control_d7)

        self.checkbox_control_d3 = CheckboxControl("do1",
                                                False,
                                                "left",
                                                min_access=2,
                                                ui_elements=self.ui_elements,
                                                controls=self.controls_robot,
                                                callback=self.update_controls_robot,
                                                parent=self
                                                )
        layout.addWidget(self.checkbox_control_d3)

        self.checkbox_control_d4 = CheckboxControl("do2",
                                                False,
                                                "left",
                                                min_access=2,
                                                ui_elements=self.ui_elements,
                                                controls=self.controls_robot,
                                                callback=self.update_controls_robot,
                                                parent=self
                                                )
        layout.addWidget(self.checkbox_control_d4)

        self.slider_control_d8 = SliderControl_change("min_rob_x",
                                            50,
                                            590,
                                            78,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls_robot],
                                            callback=[self.update_controls_robot],
                                            parent=self,
                                            label='Min Rob X'
                                            )
        layout.addWidget(self.slider_control_d8)

        self.slider_control_d9 = SliderControl_change("max_rob_x",
                                            50,
                                            590,
                                            488,
                                            transfer_k=1,
                                            round_k=1,
                                            min_access=2,
                                            ui_elements=self.ui_elements,
                                            controls=[self.controls_robot],
                                            callback=[self.update_controls_robot],
                                            parent=self,
                                            label='Max Rob X'
                                            )
        layout.addWidget(self.slider_control_d9)

        return tab


    def create_tab_neuroun(self):
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)

        # checkbox_control = CheckboxControl("neuroun", True, "left", ui_elements=self.ui_elements, controls=self.controls_neuroun, callback = self.update_controls_neuroun, parent=self)
        # layout.addWidget(checkbox_control)

        # slider_control = SliderControl("predict", 0, 100, 43, transfer_k=0.01, round_k=2, ui_elements=self.ui_elements, controls=self.controls_neuroun, callback = self.update_controls_neuroun, parent=self)
        # layout.addWidget(slider_control)


        slider_control = SliderControl_change("bad_threshould", 
                                       0, 
                                       100, 
                                       50, 
                                       transfer_k= 0.01, 
                                       round_k=2, 
                                       min_access=1, 
                                       ui_elements=self.ui_elements, 
                                       controls=self.controls_neuroun, 
                                       callback = self.update_controls_neuroun, 
                                       parent=self,
                                       label = 'порог для плохих'
                                       )
        
        layout.addWidget(slider_control)

        slider_control = SliderControl_change("good_threshould", 
                                       0, 
                                       100, 
                                       50, 
                                       transfer_k= 0.01, 
                                       round_k=2, 
                                       min_access=1, 
                                       ui_elements=self.ui_elements, 
                                       controls=self.controls_neuroun, 
                                       callback = self.update_controls_neuroun, 
                                       parent=self,
                                       label = 'порог для хороших'
                                       )
        
        layout.addWidget(slider_control)

        slider_control = SliderControl_change("neutral_threshould", 
                                       0, 
                                       100, 
                                       50, 
                                       transfer_k= 0.01, 
                                       round_k=2, 
                                       min_access=1, 
                                       ui_elements=self.ui_elements, 
                                       controls=self.controls_neuroun, 
                                       callback = self.update_controls_neuroun, 
                                       parent=self,
                                       label = 'порог для нейтральных'
                                       )
        
        layout.addWidget(slider_control)

        checkbox_control = CheckboxControl("find_object", 
                                            True, 
                                            "left", 
                                            min_access=1,
                                            ui_elements=self.ui_elements,
                                            controls=self.controls_neuroun, 
                                            callback = self.update_controls_neuroun, 
                                            parent=self
                                            )
        
        layout.addWidget(checkbox_control)

        checkbox_control = CheckboxControl("find_object_train", 
                                            False, 
                                            "left", 
                                            min_access=2,
                                            ui_elements=self.ui_elements, 
                                            controls=[self.controls, self.controls_neuroun], 
                                            callback = [self.update_controls, self.update_controls_neuroun],
                                            parent=self
                                            )
        
        layout.addWidget(checkbox_control)
        
        checkbox_control = CheckboxControl("save_image_brak", 
                                           True, 
                                           "left", 
                                           min_access=1,
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

        # self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_frame_process)
        # self.queue_manager.control_frame_process.put(self.controls)

        self.save_to_excel(value_column=self.coloumn)


    def update_controls_camera(self):
        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_camera)
        self.queue_manager.control_camera.put(self.controls_camera)   
        #self.queue_manager.control_camera_event.set() 

        self.save_to_excel(value_column=self.coloumn)


    def update_controls_camera_out(self):
        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_camera_out)
        self.queue_manager.control_camera_out.put(self.controls_camera_out)   
        #.queue_manager.control_camera_out_event.set() 

        self.save_to_excel(value_column=self.coloumn)




    def update_controls_neuroun(self):
        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_neuroun)
        self.queue_manager.control_neuroun.put(self.controls_neuroun)
        #self.queue_manager.control_neuroun_event.set()

        self.save_to_excel(value_column=self.coloumn)

    
    def update_controls_draw(self):
        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_draw)
        self.queue_manager.control_draw.put(self.controls_draw)
        #self.queue_manager.control_draw_event.set()

        self.save_to_excel(value_column=self.coloumn)


    def update_controls_robot(self):
        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_robot)
        self.queue_manager.control_robot.put(self.controls_robot)
        #self.queue_manager.control_robot_event.set()

        self.save_to_excel(value_column=self.coloumn)

    def update_controls_conveyor(self):
        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_conveyor)
        self.queue_manager.control_conveyor.put(self.controls_conveyor)
        #self.queue_manager.control_conveyor_event.set()

        self.save_to_excel(value_column=self.coloumn)


    def update_access_level(self, level: int):
        self.current_access_level = level

        for name, data  in self.ui_elements.items():
            #print(name, data)
            if name == 'func_update': continue
            widget = data['element'].parent()  # Получаем родительский виджет
            enable = level >= data.get('min_access', 0)
            data['element'].setEnabled(enable)
            widget.setEnabled(enable)
            
            widget.setStyleSheet("opacity: 0.3;" if not enable else "opacity: 1;")         
            #widget.setVisible(enable)  # Скрываем полностью при необходимости


    # def save_to_excel(self, filename='value_settings.xlsx', value_column='Default Value'):
    #     """Сохраняет текущие значения всех параметров в Excel с выбором названия столбца для значений"""
    #     try:
    #         # Собираем все параметры из всех групп
    #         all_params = {}
    #         groups = [
    #             self.controls,
    #             self.controls_camera,
    #             self.controls_camera_out,
    #             self.controls_neuroun,
    #             self.controls_draw,
    #             self.controls_robot,
    #             self.controls_conveyor
    #         ]

    #         for group in groups:
    #             for param, value in group.items():
    #                 all_params[param] = value

    #         # Создаем DataFrame
    #         df = pd.DataFrame({
    #             'Parameter': list(all_params.keys()),
    #             value_column: list(all_params.values())
    #         })

    #         # Сохраняем в файл
    #         df.to_excel(filename, index=False)
    #         # QMessageBox.information(self, 'Успех', f'Значения сохранены в {filename}')

    #     except Exception as e:
    #         QMessageBox.critical(self, 'Ошибка', f'Ошибка при сохранении: {str(e)}')


    def get_all_params(self):
        """Возвращает словарь всех параметров"""
        all_params = {}
        groups = [
            self.controls,
            self.controls_camera,
            self.controls_camera_out,
            self.controls_neuroun,
            self.controls_draw,
            self.controls_robot,
            self.controls_conveyor
        ]

        for group in groups:
            for param, value in group.items():
                all_params[param] = value

        all_params_sorted = {k: all_params[k] for k in sorted(all_params)}

        return all_params_sorted


    def create_dataframe(self):
        """Создает DataFrame, пытаясь сначала загрузить из файла"""
        # Пытаемся загрузить существующие данные
        if not self.load_dataframe_from_excel():
            # Если загрузка не удалась - создаем новый DataFrame
            all_params = self.get_all_params()
            self.df = pd.DataFrame({
                'Parameter': list(all_params.keys())
            })

            self.save_to_excel(value_column='default_value')
            self.save_to_excel(value_column='real_value')

            for number in range(22):
                self.save_to_excel(value_column=number)


        return self.df


    def load_dataframe_from_excel(self, filename='value_settings.xlsx'):
        """Загружает DataFrame из Excel файла"""
        try:
            # Читаем файл и проверяем структуру
            temp_df = pd.read_excel(filename)
            
            if 'Parameter' not in temp_df.columns:
                QMessageBox.critical(self, 'Ошибка', 'Некорректный формат файла')
                return False
                
            # Если все проверки пройдены - сохраняем в основной DataFrame
            self.df = temp_df
            return True
            
        except FileNotFoundError:
            # Файл не найден - это нормальная ситуация при первом запуске
            return False
        except Exception as e:
            QMessageBox.critical(self, 'Ошибка', f'Ошибка чтения файла: {str(e)}')
            return False


    def save_to_excel(self, filename='value_settings.xlsx', value_column='default_value'):
        """Сохраняет текущие значения всех параметров в Excel в виде строк"""
        try:
            # Преобразуем все значения в строки перед сохранением
            all_params = self.get_all_params()
            str_value = [str(v) for v in all_params.values()]
            # print( value_column, str_value)
            self.df[str(value_column)] = str_value            
            
            # Сохраняем в файл
            self.df.to_excel(filename, index=False)
            print(f'сохранился столбец {value_column}')
        except Exception as e:
            print(f'НЕ сохранился столбец {value_column}')
            QMessageBox.critical(self, 'Ошибка', f'Ошибка при сохранении: {str(e)}')


    def read_from_excel(self, filename='value_settings.xlsx', value_column='default_value'):
        """Считывает значения из указанного столбца Excel-файла и создает словарь"""
        try:
            # Читаем Excel-файл
            df = pd.read_excel(filename)

            # Проверяем, что указанный столбец существует в DataFrame
            if value_column not in df.columns:
                raise ValueError(f"Столбец '{value_column}' не найден в файле {filename}")

            # Создаем словарь из значений столбцов 'Parameter' и указанного столбца
            params_dict = dict(zip(df['Parameter'], df[value_column]))
            
            print(f'СЧИТАЛОСЬ ИЗ ФАЙЛА столбец {value_column}')

            #print('params_dict', params_dict)
            return params_dict

        except Exception as e:
            print(f'НЕ СЧИТАЛОСЬ ИЗ ФАЙЛА столбец {value_column}')
            #QMessageBox.critical(self, 'Ошибка', f'Ошибка при чтении файла: {str(e)}')
            return {}
        

                        
    def apply_settings_from_dict(self, value_column='default_value'):
        """Применяет настройки из словаря к элементам интерфейса с преобразованием типов"""
        settings_dict = self.read_from_excel(value_column=str(value_column))

        if not settings_dict:
            settings_dict = self.read_from_excel(value_column='default_value')
            self.save_to_excel(value_column=str(value_column))


        for param_name, param_value_str in settings_dict.items():
            if param_name in self.ui_elements:
                element_data = self.ui_elements[param_name]
                element = element_data['element']
                transfer_k = element_data.get('transfer_k', 1)

                try:
                    # Для слайдеров: строка → число → int
                    if isinstance(element, QSlider):
                        value = float(param_value_str)
                        value = value / transfer_k  # Применяем коэффициент
                        element.setValue(int(round(value)))
                    
                    # Для чекбоксов: строка → bool
                    elif isinstance(element, QCheckBox):
                        value = param_value_str.lower() in ['true', '1', 'yes']
                        element.setChecked(value)
   
                except Exception as e:
                    print(f"Ошибка установки значения для {param_name}: {e}")


    def apply_sort(self, number):
        self.apply_settings_from_dict(value_column=f'{number}')


    def save_sort(self, number):
        if number != 0:
            self.save_to_excel(value_column=f'{number}')


    def default_sort(self, number):
        self.apply_settings_from_dict(value_column=f'default_value')


    def reset_count(self):
        self.queue_manager.reset_count.set()


    def show(self):
        super().show()

    
    def close(self):
        super().close()


    def close_programm(self):
        self.stop_event.set()
        time.sleep(3)
        self.close()



# if __name__ == "__main__":
#     import sys
#     from PyQt5.QtWidgets import QApplication

#     app = QApplication(sys.argv)
#     widget = FrameProcessWindow()
#     widget.setWindowTitle("Frame Process")
#     widget.resize(800, 600)
#     widget.show()
#     sys.exit(app.exec_())
