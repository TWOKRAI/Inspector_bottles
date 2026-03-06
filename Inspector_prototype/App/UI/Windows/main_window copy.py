import cv2
from PyQt5.QtWidgets import (QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QLabel,
                             QSlider, QCheckBox, QTabWidget, QScrollArea, QPushButton, QMessageBox)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap, QFont
from PyQt5.QtGui import QCursor
import time

from App.Components.header import HeaderWidget


class MainWindow(QMainWindow):
    def __init__(self, window_manager = None):
        super().__init__()

        self.window_manager = window_manager

        if not window_manager is None:
            self.queue_manager = self.window_manager.queue_manager
            self.stop_event = self.window_manager.stop_event
            self.fullscreen = self.window_manager.fullscreen
        
        self.header = HeaderWidget(self.window_manager)

        self.controls = {}

        self.init_ui()

        if self.fullscreen: self.showFullScreen()


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
        self.create_tabs()
        main_layout.addWidget(self.tab_widget)

        self.initialize_controls()
    
        print('инициализация окна прошла успешно')


    def create_main_content_layout(self):
        main_content_layout = QHBoxLayout()

        checkbox_layout_left = QVBoxLayout()
        main_content_layout.addLayout(checkbox_layout_left)

        self.create_checkbox(checkbox_layout_left, "Draw", 1, position='top')
        self.create_checkbox(checkbox_layout_left, "Circles", 1, position='top')
        self.create_checkbox(checkbox_layout_left, "Rectangles", 1, position='top')
        self.create_checkbox(checkbox_layout_left, "Record_video", 0, position='top')

        image_layout = QVBoxLayout()
        image_layout.addStretch()  # Верхний spacer

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setScaledContents(False)
        self.image_label.setStyleSheet("border: 2px solid white; border-radius: 10px;")  # Скругление углов
        image_layout.addWidget(self.image_label)

        image_layout.addStretch()  # Нижний spacer
        main_content_layout.addLayout(image_layout)

        checkbox_layout_right = QVBoxLayout()
        
        self.create_checkbox(checkbox_layout_right, "Servo_on", 1, position='top')
        self.create_checkbox(checkbox_layout_right, "Enable_camera", 1, position='top')
        self.create_checkbox(checkbox_layout_right, "Processing", 1, position='top')
        self.create_checkbox(checkbox_layout_right, "Neuron", 1, position='top')

        self.total_label = QLabel()
        self.total_label.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(16)
        self.total_label.setFont(font)
        #checkbox_layout_right.addWidget(self.total_label)

        #main_content_layout.addWidget(self.total_label)

        main_content_layout.addLayout(checkbox_layout_right)

        return main_content_layout


    def create_tabs(self):
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("QTabBar::tab { height: 35px; width: 95px; }")  # Увеличение размера вкладок

        self.create_tab("General")
        self.add_controls_to_tab(0, [
            ("dp", 0, 20, 12),
            ("minDist", 0, 100, 20),
            ("param1", 0, 200, 50),
            ("param2", 0, 200, 42),
            ("minRadius", 0, 100, 22),
            ("maxRadius", 0, 100, 45)
        ])

        self.create_tab("Cropped Area")
        self.add_controls_to_tab(1, [
            ("history", 0, 100, 100),
            ("height", 0, 600, 250),
            ("y_delta", 0, 100, 37),
            ("x_delta", 0, 100, 21),
            ("x_min", 0, 1280, 120),
            ("x_max", 0, 1280, 700),
            ("conveyor_freq", 26, 50, 30)
        ])

        self.create_tab("Parameters")
        self.add_controls_to_tab(2, [
            ("HL", 0, 255, 0),
            ("SL", 0, 255, 0),
            ("VL", 0, 255, 200),
            ("HM", 0, 255, 255),
            ("SM", 0, 255, 255),
            ("VM", 0, 255, 255),
            ("AREA", 0, 5200, 2600),
            ("SAVE_IMAGE", 0),
            ("snap_y", 0, 600, 200),
            ("shift", 0, 7000, 717),
            ("shift_y", 0, 1000, 120),
            ("mode", 1),

            ("fps", 1, 25, 5)
        ])

        self.create_tab("Robot")
        self.add_controls_to_tab(3, [
            # ("Servo_on", 0),
            ("Position", 0, 3, 0),
            ("Shift_time", 0, 2000, 1100), #250
            ("Shift", 0, 1000, 0),
            ("Lenght", 0, 200, 0),
            ("Back", 0, 400, 0),
            ("DO1", 0),
            ("DO2", 0),
        ])


    def create_tab(self, name):
        tab = QScrollArea()
        tab.setStyleSheet("""
            QScrollBar:vertical {
                width: 30px;
            }
        """)  

        tab.setWidgetResizable(True)
        content = QWidget()
        tab.setWidget(content)
        layout = QVBoxLayout(content)
        self.tab_widget.addTab(tab, name)
        return layout


    def add_controls_to_tab(self, tab_index, controls):
        layout = self.tab_widget.widget(tab_index).widget().layout()
        if layout is None:
            layout = QVBoxLayout()
            self.tab_widget.widget(tab_index).widget().setLayout(layout)
        for control in controls:
            if len(control) == 2:
                self.create_checkbox(layout, *control)
            else:
                self.create_slider(layout, *control)


    def create_slider(self, layout, name, min_val, max_val, init_val):
        hbox = QHBoxLayout()
        label = QLabel(name)
        
        value_label = QLabel(str(init_val))
        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(min_val)
        slider.setMaximum(max_val)
        slider.setValue(init_val)
        slider.setMinimumHeight(45)  # Увеличение размера слайдера
        slider.setMinimumWidth(300)  # Увеличение ширины слайдера
        slider.valueChanged.connect(lambda value, n=name, l=value_label: self.update_slider_value(n, value, l))
        slider.wheelEvent = lambda event: None  # Отключение прокрутки колесом мыши
        hbox.addWidget(label)
        hbox.addWidget(value_label)
        hbox.addWidget(slider)
        layout.addLayout(hbox)
        self.controls[name] = slider


    def create_checkbox(self, layout, name, init_val, position="right"):
        vbox = QVBoxLayout()
        vbox.setAlignment(Qt.AlignCenter)

        hbox_0 = QHBoxLayout()
        hbox_0.setAlignment(Qt.AlignCenter)
        hbox_1 = QHBoxLayout()
        hbox_1.setAlignment(Qt.AlignCenter)

        checkbox = QCheckBox()
        checkbox.setChecked(init_val)
        checkbox.stateChanged.connect(lambda state, n=name: self.update_control(n, state))
        checkbox.setStyleSheet("QCheckBox::indicator { width: 44px; height: 44px; }")

        label = QLabel(name)
        label.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(12)
        label.setFont(font)

        if position in ["top", "bottom"]:
            if position == "top":
                hbox_0.addStretch()
                hbox_0.addWidget(label)
                hbox_0.addStretch()

                hbox_1.addStretch()
                hbox_1.addWidget(checkbox)
                hbox_1.addStretch()

                vbox.addLayout(hbox_0)
                vbox.addLayout(hbox_1)
            else:
                vbox.addWidget(checkbox)
                vbox.addWidget(label)
        else:
            hbox = QHBoxLayout()
            hbox.setAlignment(Qt.AlignCenter)
            if position == "left":
                hbox.addWidget(label)
                hbox.addWidget(checkbox)
            else:
                hbox.addWidget(checkbox)
                hbox.addWidget(label)
            vbox.addLayout(hbox)

        layout.addLayout(vbox)
        self.controls[name] = checkbox

    def update_slider_value(self, name, value, label):
        label.setText(str(value))
        self.update_control(name, value)

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def update_control(self, name, value):
        control = {
            'top': 145,
            'bottom': 535,
            'left': 225,
            'right': 1030,
            'hl': self.get_control_value("HL"),
            'sl': self.get_control_value("SL"),
            'vl': self.get_control_value("VL"),
            'hm': self.get_control_value("HM"),
            'sm': self.get_control_value("SM"),
            'vm': self.get_control_value("VM"),
            'area_threshold': self.get_control_value("AREA"),
            'save_image': self.get_control_value("SAVE_IMAGE"),
            'snap_y': self.get_control_value("snap_y"),
            'shift': self.get_control_value("shift"),
            'shift_y': self.get_control_value("shift_y"),
            'mode': self.get_control_value("mode"),
            'processing': self.get_control_value("Processing"),
            'neuroun': self.get_control_value("Neuron"),
            'y_delta': self.get_control_value("y_delta"),
            'x_delta': self.get_control_value("x_delta"),
            'x_min': self.get_control_value("x_min"),
            'x_max': self.get_control_value("x_max"),
            'dp': self.get_control_value("dp") / 10.0,
            'minDist': self.get_control_value("minDist"),
            'param1': self.get_control_value("param1"),
            'param2': self.get_control_value("param2"),
            'minRadius': self.get_control_value("minRadius"),
            'maxRadius': self.get_control_value("maxRadius"),
            'height': self.get_control_value("height"),
            'fps': self.get_control_value("fps"),
            'record_video': self.get_control_value("Record_video"),
            'conveyor_freq':  self.get_control_value("conveyor_freq"),
            'draw': self.get_control_value("Draw"),
            'circles': self.get_control_value("Circles"),
            'rectangles': self.get_control_value("Rectangles"),
            'record_video': self.get_control_value("Record_video"),
            'enable_process_camera': self.get_control_value("Enable_camera"),
        }

        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_display)
        self.queue_manager.control_display.put(control)

        control_camera = {
            'enable_process_camera': self.get_control_value("Enable_camera"),
            'record_video': self.get_control_value("Record_video"),
            'fps': self.get_control_value("fps"),
        }
        
        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_camera)
        self.queue_manager.control_camera.put(control_camera)    

        control_conveyor = {
            'conveyor_freq': self.get_control_value("conveyor_freq"),
        }

        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_conveyor)
        self.queue_manager.control_conveyor.put(control_conveyor)

        control_robot = {
            'snap_y': self.get_control_value("snap_y"),
            'Servo_on': self.get_control_value("Servo_on"),
            'Position': self.get_control_value("Position"),
            'Shift_time': self.get_control_value("Shift_time"),
            'Shift': self.get_control_value("Shift"),
            'Lenght': self.get_control_value("Lenght"),
            'Back': self.get_control_value("Back"),
            'DO1': self.get_control_value("DO1"),
            'DO2': self.get_control_value("DO2"),
        }

        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_robot)
        self.queue_manager.control_robot.put(control_robot)

        history = self.get_control_value("history")
        if history != 100:
            if len(self.window_manager.worker_update_image.save_frame) > history - 1 and len(self.window_manager.worker_update_image.save_frame) > 0:
                self.update_image(self.window_manager.worker_update_image.save_frame[history - 1])


    def get_control_value(self, name):
        if name in self.controls:
            control = self.controls[name]
            if isinstance(control, QSlider):
                return control.value()
            elif isinstance(control, QCheckBox):
                return control.isChecked()
        return 0

    def initialize_controls(self):
        for name, control in self.controls.items():
            if isinstance(control, QSlider):
                value = control.value()
            elif isinstance(control, QCheckBox):
                value = control.isChecked()
            self.update_control(name, value)


    # Добавим функцию для обновления стиля рамки
    def update_image_border(self, pixmap):
        width = pixmap.width()
        height = pixmap.height()
        self.image_label.setStyleSheet(f"border: 1px solid white; width: {width}px; height: {height}px;")


    def update_data(self, data):
        frame = data['frame']
        timestrap = data['timestrap']

        if self.get_control_value("history") == 100:
            self.update_image(frame)
        
        #total =  round((time.time() - timestrap) * 1000, 0)
        total_all = data['total_all']
        #self.total_label.setText(f'{total} ms\nall: {total_all}')
        self.total_label.setText(f'all: {total_all}')


    def update_image(self, frame):
        height, width, channel = frame.shape
        new_height = int(height * 0.69)
        new_width = int(width * 0.69)

        frame_resized = cv2.resize(frame, (new_width, new_height))

        bytes_per_line = 3 * new_width
        q_img = QImage(frame_resized.data, new_width, new_height, bytes_per_line, QImage.Format_RGB888).rgbSwapped()
        pixmap = QPixmap.fromImage(q_img)
        self.image_label.setPixmap(pixmap)


    def show(self):
        super().show()

    
    def close(self):
        super().close()


    def close_programm(self):
        self.stop_event.set()
        time.sleep(3)
        self.close()