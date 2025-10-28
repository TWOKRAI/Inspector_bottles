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
from  App.Components.sliders import SliderControl, SliderControl_change
from  App.Components.Checkboxs import CheckboxControl


class MainWindow(QMainWindow):
    def __init__(self, window_manager = None):
        super().__init__()

        self.window_manager = window_manager

        if not window_manager is None:
            self.queue_manager = self.window_manager.queue_manager
            #self.stop_event = self.window_manager.stop_event
            self.fullscreen = self.window_manager.fullscreen
        
        self.header = HeaderWidget(window_manager=self.window_manager)

        self.ui_elements = {}
        self.controls = {}
        self.controls_camera = {}
        self.controls_neuroun = {}
        self.controls_draw = {}
        self.controls_robot = {}
        self.controls_conveyor = {}
        
        self.current_access_level = 0

        self.init_ui()

        if self.fullscreen: self.showFullScreen()

        self.update_controls()
        self.update_controls_camera()
        self.update_controls_neuroun()
        self.update_controls_draw()
        self.update_controls_robot()
        self.update_controls_conveyor()

        self.update_access_level(self.current_access_level)


    def init_ui(self):
        # Создание главного окна
        self.setWindowTitle("Image Processing App")
        self.setGeometry(100, 100, 1200, 800)

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
        tab_widget = self.create_tabs()
        main_layout.addWidget(tab_widget)


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

        return self.tab_widget


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

        slider_control = SliderControl_change("x_min", 
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