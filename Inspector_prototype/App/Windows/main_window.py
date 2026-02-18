import os
import cv2
from PyQt5.QtWidgets import (QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QLabel,
                             QSlider, QCheckBox, QTabWidget, QScrollArea, QPushButton, QMessageBox, QComboBox, QGroupBox,
                             QLineEdit, QSpinBox, QListWidget, QListWidgetItem, QFormLayout)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap, QFont
from PyQt5.QtGui import QCursor
from PyQt5.QtCore import QTimer
import time
import cv2
import numpy as np

from PyQt5.QtWidgets import QHBoxLayout, QLabel, QSlider, QWidget
from PyQt5.QtCore import Qt

from App.Components.header import HeaderWidget
from App.Components.slider import SliderControl
from App.Components.checkbox import CheckboxControl
from App.Widget.Visual_settings_widjet.Visual_settings import VisualSettingsWidget
from App.Widget.Circle_widjet.Circle import CircleWidget
from App.Widget.Cropped_area_widjet.Cropped_area import CroppedAreaWidget
from App.Widget.Parameters_widjet.Parameters import ParametersWidget
from App.Widget.Neuroun_widjet.Neuroun import NeurounWidget
from App.Widget.Robot_widjet.Robot import RobotWidget
from App.Widget.Hikvision_widjet.Hikvision import HikvisionWidget
from App.Widget.Processing_widjet.Processing import ProcessingWidget
from App.Widget.Post_processing_widjet.Post_processing import PostProcessingWidget
from App.Components.params_manager import ParamsManager
from App.Components.data_manager import DataManager
from App.Widget.Sort_widjet import SortWidget, SortData


# SliderControl и CheckboxControl теперь импортируются из Components


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
        self.controls_camera = {
            'source': 'camera',  # 'camera' или 'image' — переключатель источника кадров
            'image_path': 'Data/last_frame.png',  # путь к PNG при source='image'
        }
        self.controls_neuroun = {}
        self.controls_draw = {}
        self.controls_robot = {}
        self.controls_conveyor = {}
        self.controls_hikvision = {}
        self.controls_processing = {
            'crop_top': 0,
            'crop_bottom': 2160,  # Максимальная высота по умолчанию
            'crop_left': 0,
            'crop_right': 3840,  # Максимальная ширина по умолчанию
            'enable_processing': False,
            'show_mask': False,
            'show_processed': False,
            'image_width': 1024,
            'image_height': 780,
            'hl': 0, 'sl': 0, 'vl': 0,
            'hm': 179, 'sm': 255, 'vm': 255,
            'region_processor_type': None,  # None для HSV, или 'rgb', 'bgr', 'grayscale'
        }
        
        # Operation Crop: области + цепочки обработки
        self.controls_post_processing = {
            'enable_post_processing': False,
            'regions': [],  # [{name, x1, y1, x2, y2, processor_id}, ...]
            'region_chains': {},  # {name: [{processor_id, params}, ...]}
            'view_mode': 'main',  # main | region | list
            'selected_region': None,
            'show_region_processed': False,  # Показывать обработанный регион или оригинал
        }
        # Визуальная настройка (масштаб изображения для экономии места)
        # Рисунки (FPS, регионы) управляются чекбоксом Draw в controls_draw
        self.controls_visual = {
            'image_scale': 0.5,
        }
        
        # Список устройств камеры для Hikvision
        self.hikvision_device_list = []
        
        # FPS значения
        self.fps_sdk = 0.0  # FPS из SDK камеры
        self.fps_after_processing = 0.0  # FPS после обработки (вычисляется на основе времени между кадрами)
        self.processing_time_ms = 0.0  # Время обработки в миллисекундах
        self.total_time_ms = 0.0  # Общее время от захвата до отображения в миллисекундах
        
        # Размер изображения с камеры
        self.image_height = 0  # Высота оригинального изображения
        self.image_width = 0   # Ширина оригинального изображения
        
        self.current_access_level = 0
        
        # Инициализируем базовый UI (без вкладок)
        self.init_ui_base()
        
        # Создаем виджеты для вкладок
        self.create_widgets()
        
        # Заполняем вкладки виджетами
        self.update_tabs_with_widgets()
        
        # Завершаем инициализацию UI
        self.init_ui_finish()

        # Применяем fullscreen с учетом ограничения из конфигурации приложения
        if self.fullscreen:
            app_config = self.window_manager.app_config if self.window_manager and hasattr(self.window_manager, 'app_config') else None
            if app_config:
                limit_fullhd = app_config.get_limit_fullhd()
                if limit_fullhd:
                    # Ограничиваем размер до заданного разрешения вместо fullscreen
                    limit_width = app_config.get_fullscreen_limit_width()
                    limit_height = app_config.get_fullscreen_limit_height()
                    self.showNormal()
                    self.setFixedSize(limit_width, limit_height)
                    # Центрируем окно на экране
                    screen = self.screen().availableGeometry()
                    x = (screen.width() - limit_width) // 2
                    y = (screen.height() - limit_height) // 2
                    self.move(x, y)
                else:
                    self.showFullScreen()
            else:
                self.showFullScreen()
        else:
            self.showNormal()

        self.update_controls()
        self.update_controls_camera()
        self.update_controls_neuroun()
        self.update_controls_draw()
        self.update_controls_robot()
        self.update_controls_conveyor()
        self.update_controls_hikvision()
        self.update_controls_processing()
        self.update_controls_post_processing()

        self.update_access_level(self.current_access_level)
        
        # Поток камеры запускается внутри HikvisionWidget
        # Подключаем обработку сообщений для обновления ProcessingWidget и других компонентов
        if hasattr(self, 'hikvision_widget') and self.hikvision_widget.camera_message_thread:
            self.hikvision_widget.camera_message_thread.message_received.connect(self.handle_camera_message)
    
    def _load_current_recipe_on_startup(self):
        """Загрузить текущий рецепт при старте приложения"""
        try:
            current_recipe_number = self.sort_data.get_current_recipe_number()
            if current_recipe_number is not None:
                print(f"Автозагрузка текущего рецепта: {current_recipe_number}")
                self.params_manager.apply_recipe(current_recipe_number)
                print(f"Рецепт {current_recipe_number} успешно загружен")
            else:
                # Если текущий рецепт не установлен, загружаем default_value
                print("Текущий рецепт не установлен, загрузка default_value")
                self.params_manager.apply_recipe("default_value")
        except Exception as e:
            print(f"Ошибка при автозагрузке рецепта: {e}")
            import traceback
            traceback.print_exc()
    
    def _auto_save_backup(self):
        """Автоматическое сохранение в backup рецепт"""
        try:
            if hasattr(self, 'data_manager'):
                self.data_manager.save_to_recipe("backup")
                # Также сохраняем параметры других виджетов
                if hasattr(self, 'params_manager'):
                    self.params_manager.save_to_excel("backup")
        except Exception as e:
            print(f"Ошибка автосохранения в backup: {e}")
    
    def _on_data_changed(self):
        """Обработчик изменения данных в DataManager"""
        # Можно добавить дополнительную логику при изменении данных
        pass
    
    def create_widgets(self):
        """Создание всех виджетов для вкладок"""
        # VisualSettingsWidget
        app_config = self.window_manager.app_config if self.window_manager and hasattr(self.window_manager, 'app_config') else None
        self.visual_settings_widget = VisualSettingsWidget(
            window_manager=self.window_manager,
            ui_elements=self.ui_elements,
            controls=self.controls_visual,
            callback=self.update_controls_visual,
            app_config=app_config
        )
        
        # CircleWidget
        self.circle_widget = CircleWidget(
            window_manager=self.window_manager,
            ui_elements=self.ui_elements,
            controls=self.controls,
            callback=self.update_controls
        )
        
        # CroppedAreaWidget
        self.cropped_area_widget = CroppedAreaWidget(
            window_manager=self.window_manager,
            ui_elements=self.ui_elements,
            controls=self.controls,
            controls_draw=self.controls_draw,
            controls_conveyor=self.controls_conveyor,
            callback=self.update_controls,
            callback_draw=self.update_controls_draw,
            callback_conveyor=self.update_controls_conveyor
        )
        
        # ParametersWidget
        self.parameters_widget = ParametersWidget(
            window_manager=self.window_manager,
            ui_elements=self.ui_elements,
            controls=self.controls,
            controls_draw=self.controls_draw,
            controls_robot=self.controls_robot,
            controls_camera=self.controls_camera,
            callback=self.update_controls,
            callback_draw=self.update_controls_draw,
            callback_robot=self.update_controls_robot,
            callback_camera=self.update_controls_camera
        )
        
        # NeurounWidget
        self.neuroun_widget = NeurounWidget(
            window_manager=self.window_manager,
            ui_elements=self.ui_elements,
            controls=self.controls,
            controls_neuroun=self.controls_neuroun,
            controls_draw=self.controls_draw,
            callback=self.update_controls,
            callback_neuroun=self.update_controls_neuroun,
            callback_draw=self.update_controls_draw
        )
        
        # RobotWidget
        self.robot_widget = RobotWidget(
            window_manager=self.window_manager,
            ui_elements=self.ui_elements,
            controls_robot=self.controls_robot,
            callback=self.update_controls_robot
        )
        
        # Создаем DataManager перед HikvisionWidget, чтобы передать его в конструктор
        self.sort_data = SortData()
        self.data_manager = DataManager(self.sort_data)
        self.data_manager.data_changed.connect(self._on_data_changed)
        
        # HikvisionWidget
        self.hikvision_widget = HikvisionWidget(
            window_manager=self.window_manager,
            ui_elements=self.ui_elements,
            controls_hikvision=self.controls_hikvision,
            controls_camera=self.controls_camera,
            callback=self.update_controls_hikvision,
            callback_camera=self.update_controls_camera,
            stop_event=self.stop_event if hasattr(self, 'stop_event') else None,
            data_manager=self.data_manager
        )
        
        # ProcessingWidget и PostProcessingWidget создаём с data_manager
        self.processing_widget = ProcessingWidget(
            window_manager=self.window_manager,
            ui_elements=self.ui_elements,
            controls_processing=self.controls_processing,
            callback=self.update_controls_processing,
            data_manager=self.data_manager,
            controls_post_processing=self.controls_post_processing,
            callback_post_processing=self.update_controls_post_processing,
        )
        
        self.post_processing_widget = PostProcessingWidget(
            window_manager=self.window_manager,
            ui_elements=self.ui_elements,
            controls_post_processing=self.controls_post_processing,
            callback=self.update_controls_post_processing,
            data_manager=self.data_manager
        )
        
        self.widgets_dict = {
            'visual': self.visual_settings_widget,
            'circle': self.circle_widget,
            'cropped_area': self.cropped_area_widget,
            'parameters': self.parameters_widget,
            'neuroun': self.neuroun_widget,
            'robot': self.robot_widget,
            'hikvision': self.hikvision_widget,
            'processing': self.processing_widget,
            'post_processing': self.post_processing_widget,
        }
        self.params_manager = ParamsManager(self.widgets_dict, self.sort_data)
        
        # Автозагрузка текущего рецепта при старте приложения
        self._load_current_recipe_on_startup()
        
        # Настраиваем автосохранение в backup рецепт каждые 5 секунд
        self.backup_timer = QTimer()
        self.backup_timer.timeout.connect(self._auto_save_backup)
        self.backup_timer.start(5000)  # 5000 мс = 5 секунд
    
    def update_tabs_with_widgets(self):
        """Обновляет вкладки, добавляя виджеты"""
        # Очищаем существующие вкладки если есть
        while self.tab_widget.count() > 0:
            self.tab_widget.removeTab(0)
        
        # Добавляем вкладки с виджетами
        self.create_tab(self.tab_widget, "Сорта", self.create_tab_sort())
        self.create_tab(self.tab_widget, "Визуальная настройка", self.visual_settings_widget)
        # Закомментированные вкладки: Форма, Разное, Параметры, Нейрон, Робот
        # self.create_tab(self.tab_widget, "Форма", self.circle_widget)
        # self.create_tab(self.tab_widget, "Разное", self.cropped_area_widget) 
        # self.create_tab(self.tab_widget, "Параметры", self.parameters_widget) 
        # self.create_tab(self.tab_widget, "Нейрон", self.neuroun_widget)
        # self.create_tab(self.tab_widget, "Робот", self.robot_widget)
        self.create_tab(self.tab_widget, "Hikvision", self.hikvision_widget)
        self.create_tab(self.tab_widget, "Регионы", self.post_processing_widget)  # Переименовано из Operation Crop и перемещено перед Обработкой
        self.create_tab(self.tab_widget, "Обработка", self.processing_widget)
    
    def handle_camera_message(self, message):
        """Обработать сообщение от процесса камеры"""
        msg_type = message.get('type')
        print(f"App received camera message: type={msg_type}, message={message}")
        
        if msg_type == 'enum_devices_response':
            # Обработка enum_devices_response теперь полностью происходит в HikvisionWidget
            devices = message.get('devices', [])
            self.hikvision_device_list = devices
            print(f"App: Processing {len(devices)} devices (handled by HikvisionWidget)")
        
        elif msg_type == 'parameters_response':
            # Обработка происходит в HikvisionWidget, но обновляем метрики здесь
            params = message.get('parameters', {})
            self.fps_sdk = params.get('frame_rate', 0.0)
            # Обновляем FPS в HikvisionWidget
            if hasattr(self, 'hikvision_widget'):
                self.hikvision_widget.fps_sdk = self.fps_sdk
                self.hikvision_widget.update_fps_display()
        
        elif msg_type == 'image_size':
            # Обновляем размер изображения
            self.image_height = message.get('height', 0)
            self.image_width = message.get('width', 0)
            
            # Обновляем максимальные значения слайдеров обрезки через ProcessingWidget
            if hasattr(self, 'processing_widget'):
                self.processing_widget.update_image_size(self.image_width, self.image_height)
            
            # Обновляем FPS в HikvisionWidget
            if hasattr(self, 'hikvision_widget'):
                self.hikvision_widget.image_width = self.image_width
                self.hikvision_widget.image_height = self.image_height
                self.hikvision_widget.update_fps_display()
            
            print(f"App: Image size updated: {self.image_width}x{self.image_height}")
        

        self.update_controls()
        self.update_controls_camera()
        self.update_controls_neuroun()
        self.update_controls_draw()
        self.update_controls_robot()
        self.update_controls_conveyor()
        self.update_controls_hikvision()
        self.update_controls_processing()
        self.update_controls_post_processing()

        self.update_access_level(self.current_access_level)


    def init_ui_base(self):
        """Базовая инициализация UI без вкладок"""
        try:
            # Создание главного окна
            self.setWindowTitle("Image Processing App")
            self.setGeometry(100, 100, 1200, 800)
            # Убираем фиксированный размер чтобы окно могло изменяться
            self.setMinimumSize(800, 600)  # Минимальный размер вместо фиксированного

            main_layout = QVBoxLayout()
            central_widget = QWidget()
            central_widget.setLayout(main_layout)
            self.setCentralWidget(central_widget)
        except Exception as e:
            print(f"Error in init_ui_base: {e}")
            import traceback
            traceback.print_exc()
            raise

        main_layout.addWidget(self.header)

        main_layout.addSpacing(2)
        main_content_layout = self.create_main_content_layout()
        main_layout.addLayout(main_content_layout)
        main_layout.addSpacing(3)
        
        # Создаем tab_widget, но пока без вкладок
        self.tab_widget = QTabWidget()
        self.tab_widget.setMinimumHeight(220)
        # Стиль для вкладок и corner widget
        self.tab_widget.setStyleSheet("""
            QTabBar::tab { 
                height: 35px; 
                width: 95px; 
            }
            QTabWidget::pane {
                border: 1px solid #ccc;
            }
        """)
        
        # Кнопка «Скрыть»/«Показать» — в правом углу строки вкладок
        # Делаем её такой же как кнопки вкладок
        self.btn_toggle_tabs = QPushButton("Скрыть")
        self.btn_toggle_tabs.setFixedHeight(35)  # Такая же высота как у вкладок
        self.btn_toggle_tabs.setFixedWidth(95)  # Такая же ширина как у вкладок
        self.btn_toggle_tabs.clicked.connect(self.toggle_tabs_visibility)
        # Применяем стиль максимально похожий на вкладки
        self.btn_toggle_tabs.setStyleSheet("""
            QPushButton {
                background-color: #f0f0f0;
                border: none;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                padding: 0px;
                font-size: 12px;
                margin: 0px;
            }
            QPushButton:hover {
                background-color: #e0e0e0;
            }
            QPushButton:pressed {
                background-color: #d0d0d0;
            }
        """)
        self.tabs_visible = True
        
        # Создаем контейнер для правильного выравнивания кнопки
        corner_container = QWidget()
        corner_layout = QHBoxLayout(corner_container)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        corner_layout.setSpacing(0)
        corner_layout.addWidget(self.btn_toggle_tabs)
        
        # Устанавливаем контейнер в corner widget строки вкладок
        self.tab_widget.setCornerWidget(corner_container, Qt.TopRightCorner)
        
        main_layout.addWidget(self.tab_widget, 1)
    
    def init_ui_finish(self):
        """Завершение инициализации UI - проверки"""
        # Проверяем что все элементы созданы
        if not hasattr(self, 'tab_widget'):
            print("WARNING: tab_widget not created!")
        if not hasattr(self, 'image_label'):
            print("WARNING: image_label not created!")
        if not hasattr(self, 'hikvision_widget'):
            print("WARNING: hikvision_widget not created!")
        elif not hasattr(self.hikvision_widget, 'combo_cameras'):
            print("WARNING: hikvision_widget.combo_cameras not created!")


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

        # Источник кадров перенесён во вкладку Hikvision (таблица «Источник кадров»)
        
        checkbox_control = CheckboxControl("enable_camera", True, "top", ui_elements=self.ui_elements, controls=self.controls_camera, callback = self.update_controls_camera, parent=self)
        checkbox_layout_right.addWidget(checkbox_control)

        checkbox_control = CheckboxControl("processing", True, "top", ui_elements=self.ui_elements, controls=self.controls, callback = self.update_controls, parent=self)
        checkbox_layout_right.addWidget(checkbox_control)

        checkbox_control = CheckboxControl("server", True, "top", ui_elements=self.ui_elements, controls=self.controls_robot, callback = self.update_controls_robot, parent=self)
        checkbox_layout_right.addWidget(checkbox_control)

        main_content_layout.addLayout(checkbox_layout_right)

        return main_content_layout


    def create_tabs(self):
        """Создание вкладок - теперь вызывается из update_tabs_with_widgets()"""
        pass
    
    def create_tab_sort(self):
        """Создать вкладку управления рецептами (сортами)"""
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)
        
        label_tab = QLabel("Сортовые параметры")
        label_tab.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(14)
        label_tab.setFont(font)
        layout.addWidget(label_tab)
        
        self.sort_widget = SortWidget(self.sort_data, default_number=2, params_provider=self.get_all_params)
        layout.addWidget(self.sort_widget)
        
        self.sort_widget.applied.connect(self.apply_sort)
        self.sort_widget.saved.connect(self.save_sort)
        self.sort_widget.default.connect(self.default_sort)
        
        self.button_default = QPushButton('Сбросить значения')
        self.button_default.setFixedSize(200, 50)
        self.button_default.clicked.connect(self.reset_count)
        layout.addWidget(self.button_default)
        
        return tab
    
    def reset_count(self):
        """Сбросить счетчики"""
        if hasattr(self, 'queue_manager') and hasattr(self.queue_manager, 'reset_count'):
            self.queue_manager.reset_count.set() 


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

        slider_control = SliderControl("x_min", 
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
        
        # Кнопка Enum Devices и выпадающий список камер рядом
        enum_layout = QHBoxLayout()
        btn_enum = QPushButton("Enum Devices")
        btn_enum.setMinimumHeight(40)
        btn_enum.setMinimumWidth(150)
        btn_enum.clicked.connect(self.sdk_enum_devices)
        enum_layout.addWidget(btn_enum)
        
        # Выпадающий список камер рядом с кнопкой
        camera_label = QLabel("Камера:")
        camera_label.setFixedWidth(60)
        enum_layout.addWidget(camera_label)
        
        self.combo_cameras = QComboBox()
        self.combo_cameras.setMinimumHeight(35)
        enum_layout.addWidget(self.combo_cameras, stretch=1)
        layout.addLayout(enum_layout)
        
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
        
        # FPS и временная информация
        fps_group = QGroupBox("FPS & Performance")
        fps_layout = QVBoxLayout()
        fps_group.setLayout(fps_layout)
        
        self.fps_sdk_label = QLabel("SDK FPS: 0.0")
        self.fps_sdk_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #3498db;")
        fps_layout.addWidget(self.fps_sdk_label)
        
        self.image_size_label = QLabel("Image Size: 0x0")
        self.image_size_label.setStyleSheet("font-size: 12px; color: #9b59b6;")
        fps_layout.addWidget(self.image_size_label)
        
        self.fps_after_label = QLabel("Display FPS: 0.0")
        self.fps_after_label.setStyleSheet("font-size: 12px; color: #2ecc71;")
        fps_layout.addWidget(self.fps_after_label)
        
        self.processing_time_label = QLabel("Processing: 0.0 ms")
        self.processing_time_label.setStyleSheet("font-size: 12px; color: #e67e22;")
        fps_layout.addWidget(self.processing_time_label)
        
        self.total_time_label = QLabel("Total (capture→display): 0.0 ms")
        self.total_time_label.setStyleSheet("font-size: 12px; color: #e74c3c;")
        fps_layout.addWidget(self.total_time_label)
        
        layout.addWidget(fps_group)
        
        # Кнопки показа/скрытия UI SDK окна (внизу)
        btn_show_ui = QPushButton("Показать UI SDK")
        btn_show_ui.setMinimumHeight(50)
        btn_show_ui.clicked.connect(lambda: self.toggle_sdk_ui(True))
        layout.addWidget(btn_show_ui)
        
        btn_hide_ui = QPushButton("Скрыть UI SDK")
        btn_hide_ui.setMinimumHeight(50)
        btn_hide_ui.clicked.connect(lambda: self.toggle_sdk_ui(False))
        layout.addWidget(btn_hide_ui)
        
        return tab
    
    def toggle_sdk_ui(self, show):
        """Показать/скрыть UI SDK окно"""
        try:
            self.queue_manager.control_ui.put({'type': 'show' if show else 'hide'})
        except Exception as e:
            print(f"Error toggling SDK UI: {e}")
    
    def update_fps_display(self):
        """Обновить отображение FPS и временных метрик во вкладке Hikvision"""
        if hasattr(self, 'fps_sdk_label'):
            self.fps_sdk_label.setText(f"SDK FPS: {self.fps_sdk:.1f}")
        if hasattr(self, 'image_size_label'):
            if self.image_width > 0 and self.image_height > 0:
                self.image_size_label.setText(f"Image Size: {self.image_width}x{self.image_height}")
            else:
                self.image_size_label.setText("Image Size: Not detected")
        if hasattr(self, 'fps_after_label'):
            self.fps_after_label.setText(f"Display FPS: {self.fps_after_processing:.1f}")
        if hasattr(self, 'processing_time_label'):
            self.processing_time_label.setText(f"Processing: {self.processing_time_ms:.1f} ms")
        if hasattr(self, 'total_time_label'):
            self.total_time_label.setText(f"Total (capture→display): {self.total_time_ms:.1f} ms")
        
        # Обновляем отображение времени обработки во вкладке Processing
        if hasattr(self, 'processing_time_display_label'):
            self.processing_time_display_label.setText(f"Время обработки: {self.processing_time_ms:.1f} ms")
        if hasattr(self, 'total_time_display_label'):
            self.total_time_display_label.setText(f"Общее время (захват→отображение): {self.total_time_ms:.1f} ms")
    
    def sdk_enum_devices(self):
        """Перечислить устройства камеры"""
        try:
            self.queue_manager.ui_to_camera.put({'type': 'enum_devices'})
        except Exception as e:
            print(f"Error enumerating devices: {e}")
    
    def sdk_open_camera(self):
        """Открыть камеру"""
        try:
            # Используем combo_cameras из HikvisionWidget
            if hasattr(self, 'hikvision_widget') and hasattr(self.hikvision_widget, 'combo_cameras'):
                camera_index = self.hikvision_widget.combo_cameras.currentIndex()
            else:
                camera_index = 0
            
            if camera_index < 0 or camera_index >= len(self.hikvision_device_list):
                camera_index = 0
            
            # Получаем реальный индекс устройства
            if len(self.hikvision_device_list) > 0:
                selected_device = self.hikvision_device_list[camera_index]
                real_camera_index = selected_device.get('index', camera_index)
            else:
                real_camera_index = camera_index
                
            self.queue_manager.ui_to_camera.put({'type': 'open', 'camera_index': real_camera_index})
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
            # Автоматически запрашиваем параметры после начала захвата для получения SDK FPS
            import threading
            def delayed_get_params():
                import time
                time.sleep(0.5)  # Небольшая задержка чтобы камера успела начать захват
                self.sdk_get_parameters()
            threading.Thread(target=delayed_get_params, daemon=True).start()
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
        """Обновить отображаемые данные (кадры) с наложением FPS"""
        if frames is None or len(frames) == 0:
            return
        
        frame = frames[0]
        if frame is not None:
            self.update_image(frame)
        
        #total =  round((time.time() - timestrap) * 1000, 0)
        #total_all = data['total_all']
        #self.total_label.setText(f'{total} ms\nall: {total_all}')
        #self.total_label.setText(f'all: {total_all}')

    def update_image(self, frame):
        """Обновление изображения в label с наложением FPS"""
        if frame is None:
            return
        
        try:
            # Убеждаемся что исходный кадр является непрерывным numpy массивом
            if not isinstance(frame, np.ndarray):
                return
            if not frame.flags['C_CONTIGUOUS']:
                frame = np.ascontiguousarray(frame, dtype=np.uint8)
            
            # Убеждаемся что копия непрерывная
            if not frame.flags['C_CONTIGUOUS']:
                frame = np.ascontiguousarray(frame, dtype=np.uint8)
            
            # Обновляем метрики в HikvisionWidget
            if hasattr(self, 'hikvision_widget'):
                self.hikvision_widget.update_fps_metrics(
                    self.fps_after_processing,
                    self.processing_time_ms,
                    self.total_time_ms
                )
            
            # Просто используем оригинальное изображение - overlay применяется в отдельном процессе
            frame_with_fps = frame.copy()
            
            height, width = frame_with_fps.shape[:2]
            if height <= 0 or width <= 0:
                return  # пустой кадр — пропускаем обновление
            
            channel = frame_with_fps.shape[2] if len(frame_with_fps.shape) == 3 else 1
            
            # Масштаб из вкладки «Визуальная настройка»
            scale = self.controls_visual.get('image_scale', 0.5)
            scale = max(0.2, min(1.0, float(scale)))
            new_height = max(1, int(height * scale))
            new_width = max(1, int(width * scale))

            frame_resized = cv2.resize(frame_with_fps, (new_width, new_height))

            bytes_per_line = 3 * new_width
            # Пайплайн отдаёт RGB (на сохранённом PNG цвета верные). В PyQt виджет на части систем
            # трактует буфер как BGR — отдаём BGR в Format_RGB888, тогда отрисовка совпадает с PNG.
            if len(frame_resized.shape) == 3 and frame_resized.shape[2] == 3:
                frame_bgr = cv2.cvtColor(frame_resized, cv2.COLOR_RGB2BGR)
                q_img = QImage(frame_bgr.data, new_width, new_height, bytes_per_line, QImage.Format_RGB888)
            else:
                q_img = QImage(frame_resized.data, new_width, new_height, bytes_per_line, QImage.Format_RGB888)
            
            pixmap = QPixmap.fromImage(q_img)
            if hasattr(self, 'image_label'):
                self.image_label.setPixmap(pixmap)
        except Exception as e:
            print(f"Error updating image: {e}")
            import traceback
            traceback.print_exc()


    def update_controls(self):
        # self.controls['top'] = 145
        # self.controls['bottom'] = 535
        # self.controls['left'] = 225
        # self.controls['right'] = 1030

        self.controls['neuroun'] = self.controls_neuroun.get('neuroun', False)

        if hasattr(self, 'queue_manager') and self.queue_manager:
            self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_frame_process)
            self.queue_manager.control_frame_process.put(self.controls)
        
        # Автоматическое сохранение в текущий рецепт (real_value)
        if hasattr(self, 'params_manager'):
            try:
                self.params_manager.save_to_excel('real_value')
            except Exception as e:
                print(f"Ошибка автосохранения параметров: {e}")
        # Обновить таблицу сортов (с задержкой, чтобы не перерисовывать на каждый тик)
        if hasattr(self, 'sort_widget') and self.sort_widget and hasattr(self.sort_widget, 'schedule_refresh'):
            self.sort_widget.schedule_refresh()

    def update_controls_camera(self):
        self.controls_camera['source'] = self.controls_camera.get('source', 'camera')
        self.controls_camera['image_path'] = self.controls_camera.get('image_path', 'Data/last_frame.png')
        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_camera)
        self.queue_manager.control_camera.put(dict(self.controls_camera))
        self.queue_manager.control_camera_event.set()
        # Отправляем источник кадров (camera/image) — в две очереди, т.к. camera и image_source оба читают
        source_ctrl = {'source': self.controls_camera['source'], 'image_path': self.controls_camera['image_path']}
        for q in (self.queue_manager.control_source, self.queue_manager.control_source_image):
            self.queue_manager.remove_old_frame_if_full(q)
            q.put(source_ctrl)
        if hasattr(self, 'sort_widget') and self.sort_widget and hasattr(self.sort_widget, 'schedule_refresh'):
            self.sort_widget.schedule_refresh() 


    def update_controls_conveyor(self):
        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_conveyor)
        self.queue_manager.control_conveyor.put(self.controls_conveyor)
        self.queue_manager.control_conveyor_event.set()


    def update_controls_neuroun(self):
        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_neuroun)
        self.queue_manager.control_neuroun.put(self.controls_neuroun)
        self.queue_manager.control_neuroun_event.set()
        if hasattr(self, 'sort_widget') and self.sort_widget and hasattr(self.sort_widget, 'schedule_refresh'):
            self.sort_widget.schedule_refresh()

    
    def update_controls_draw(self):
        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_draw)
        self.queue_manager.control_draw.put(self.controls_draw)
        self.queue_manager.control_draw_event.set()
        # Отправляем в overlay: Draw чекбокс управляет включением/выключением рисунков (FPS, регионы)
        if hasattr(self.queue_manager, 'control_overlay'):
            overlay_controls = {
                'draw': self.controls_draw.get('draw', True),
                'enable_overlay': self.controls_draw.get('draw', True),
                'show_fps': True,
                'show_regions': True,
                'show_region_names': True,
            }
            try:
                self.queue_manager.control_overlay.put_nowait(overlay_controls)
            except Exception:
                pass
        if hasattr(self, 'sort_widget') and self.sort_widget and hasattr(self.sort_widget, 'schedule_refresh'):
            self.sort_widget.schedule_refresh()


    def update_controls_robot(self):
        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_robot)
        self.queue_manager.control_robot.put(self.controls_robot)
        self.queue_manager.control_robot_event.set()
        if hasattr(self, 'sort_widget') and self.sort_widget and hasattr(self.sort_widget, 'schedule_refresh'):
            self.sort_widget.schedule_refresh()
    
    def update_controls_hikvision(self):
        """Обновление управления Hikvision SDK"""
        # Параметры уже отправляются через отдельные методы в HikvisionWidget
        pass
    
    def update_controls_visual(self):
        """Обновление визуальных настроек (масштаб и т.д.). Рисунки управляются чекбоксом Draw."""
        pass
    
    def get_all_params(self):
        """Получить все параметры (для совместимости с системой рецептов)"""
        if hasattr(self, 'params_manager'):
            return self.params_manager.get_all_params()
        return {}
    
    def apply_sort(self, number):
        """Применить рецепт (сорт)"""
        if hasattr(self, 'params_manager'):
            self.params_manager.apply_recipe(number)
    
    def save_sort(self, number):
        """Сохранить текущие значения в рецепт"""
        if hasattr(self, 'params_manager'):
            self.params_manager.save_recipe(number)
        if hasattr(self, 'sort_widget'):
            self.sort_widget.refresh_table()
    
    def default_sort(self, number):
        """Установить рецепт как дефолтный"""
        if hasattr(self, 'params_manager'):
            self.params_manager.set_default_recipe(number)
    
    def toggle_tabs_visibility(self):
        """Скрыть/показать контент вкладок (строка вкладок остается видимой)."""
        self.tabs_visible = not self.tabs_visible
        if self.tabs_visible:
            # Показываем содержимое вкладок
            self.tab_widget.setMaximumHeight(16777215)  # Убираем ограничение
            self.tab_widget.setMinimumHeight(220)  # Восстанавливаем минимальную высоту
            self.tab_widget.setFixedHeight(16777215)  # Убираем фиксированную высоту
            
            # Показываем все виджеты вкладок
            for i in range(self.tab_widget.count()):
                widget = self.tab_widget.widget(i)
                if widget:
                    widget.setVisible(True)
            self.btn_toggle_tabs.setText("Скрыть")
        else:
            # Скрываем содержимое вкладок полностью, оставляя только tab bar
            # Получаем точную высоту tab bar
            tab_bar = self.tab_widget.tabBar()
            tab_bar_height = tab_bar.sizeHint().height()
            # Добавляем небольшую поправку для corner widget (кнопка)
            corner_widget_height = self.btn_toggle_tabs.sizeHint().height() if self.btn_toggle_tabs else 0
            total_height = max(tab_bar_height, corner_widget_height) + 2  # +2 для небольших отступов
            
            # Устанавливаем фиксированную высоту равную высоте tab bar
            self.tab_widget.setMaximumHeight(total_height)
            self.tab_widget.setMinimumHeight(total_height)
            self.tab_widget.setFixedHeight(total_height)
            
            # Скрываем содержимое всех вкладок
            for i in range(self.tab_widget.count()):
                widget = self.tab_widget.widget(i)
                if widget:
                    widget.setVisible(False)
            self.btn_toggle_tabs.setText("Показать")
    
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
        
        # Отображение времени обработки
        processing_time_group = QGroupBox("Время обработки")
        processing_time_layout = QVBoxLayout()
        self.processing_time_display_label = QLabel("Время обработки: 0.0 ms")
        self.processing_time_display_label.setStyleSheet("font-size: 12px; color: #e67e22; font-weight: bold;")
        processing_time_layout.addWidget(self.processing_time_display_label)
        self.total_time_display_label = QLabel("Общее время (захват→отображение): 0.0 ms")
        self.total_time_display_label.setStyleSheet("font-size: 12px; color: #9b59b6; font-weight: bold;")
        processing_time_layout.addWidget(self.total_time_display_label)
        processing_time_group.setLayout(processing_time_layout)
        layout.addWidget(processing_time_group)
        
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
        
        # Регуляторы обрезки изображения (максимальные значения будут обновляться при получении размера)
        self.crop_top_slider = SliderControl("crop_top", 0, 2160, 0,
                                      ui_elements=self.ui_elements,
                                      controls=self.controls_processing,
                                      callback=self.update_controls_processing,
                                      parent=self)
        layout.addWidget(self.crop_top_slider)
        
        self.crop_bottom_slider = SliderControl("crop_bottom", 0, 2160, 2160,
                                      ui_elements=self.ui_elements,
                                      controls=self.controls_processing,
                                      callback=self.update_controls_processing,
                                      parent=self)
        layout.addWidget(self.crop_bottom_slider)
        
        self.crop_left_slider = SliderControl("crop_left", 0, 3840, 0,
                                      ui_elements=self.ui_elements,
                                      controls=self.controls_processing,
                                      callback=self.update_controls_processing,
                                      parent=self)
        layout.addWidget(self.crop_left_slider)
        
        self.crop_right_slider = SliderControl("crop_right", 0, 3840, 3840,
                                      ui_elements=self.ui_elements,
                                      controls=self.controls_processing,
                                      callback=self.update_controls_processing,
                                      parent=self)
        layout.addWidget(self.crop_right_slider)
        
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
        
        # Если включена обработка регионов, формируем region_config из controls_post_processing
        if self.controls_processing.get('enable_processing', False):
            # Проверяем есть ли регионы для обработки
            regions = self.controls_post_processing.get('regions', [])
            if regions:
                # Формируем region_config для отправки регионов в процессоры
                region_config = {}
                for i, r in enumerate(regions):
                    if isinstance(r, dict):
                        region_name = r.get('name', f'region_{i+1}')
                        processor_id = r.get('processor_id', (i % 2) + 1)  # По умолчанию распределяем между процессорами
                        enabled = r.get('enabled', True)
                        
                        if enabled:  # Отправляем только включенные регионы
                            region_config[region_name] = {
                                'processor_id': processor_id,
                                'x1': r.get('x1', 0),
                                'y1': r.get('y1', 0),
                                'x2': r.get('x2', 0),
                                'y2': r.get('y2', 0),
                            }
                
                if region_config:
                    self.controls_processing['enable_region_mode'] = True
                    self.controls_processing['region_config'] = region_config
                else:
                    self.controls_processing['enable_region_mode'] = False
            else:
                self.controls_processing['enable_region_mode'] = False
        else:
            self.controls_processing['enable_region_mode'] = False
        
        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_processing)
        self.queue_manager.control_processing.put(self.controls_processing)
        self.queue_manager.control_processing_event.set()
        
        # Overlay управляется через update_controls_draw (Draw чекбокс)

    def create_tab_visual_settings(self):
        """Визуальная настройка: масштаб изображения для экономии места под регуляторы."""
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)
        layout.addWidget(QLabel("Масштаб окна изображения (меньше = больше места для регуляторов):"))
        scale_slider = SliderControl("image_scale", 20, 100, 50, transfer_k=0.01, round_k=2,
                                    ui_elements=self.ui_elements, controls=self.controls_visual,
                                    callback=self._on_visual_scale_changed, parent=self)
        layout.addWidget(scale_slider)
        self.visual_scale_label = QLabel("Масштаб: 0.50")
        layout.addWidget(self.visual_scale_label)
        return tab

    def _on_visual_scale_changed(self):
        scale = self.controls_visual.get('image_scale', 0.5)
        if hasattr(self, 'visual_scale_label'):
            self.visual_scale_label.setText(f"Масштаб: {scale:.2f}")

    def create_tab_post_processing(self):
        """Operation Crop: вкладки «Области» и «Цепочка». Каждая область — своя цепочка."""
        tab = QWidget()
        layout = QVBoxLayout()
        tab.setLayout(layout)

        # Чекбокс включения + режим просмотра
        checkbox_control = CheckboxControl("enable_post_processing", False, "left",
                                         ui_elements=self.ui_elements,
                                         controls=self.controls_post_processing,
                                         callback=self.update_controls_post_processing,
                                         parent=self)
        layout.addWidget(checkbox_control)

        view_group = QGroupBox("Режим просмотра")
        view_layout = QVBoxLayout()
        self.view_mode_combo = QComboBox()
        self.view_mode_combo.addItems(["main", "region", "list"])
        self.view_mode_combo.setCurrentText("main")
        self.view_mode_combo.currentTextChanged.connect(self._on_view_mode_changed)
        
        # Чекбокс переключения до/после обработки для регионов
        checkbox_region_processed = CheckboxControl("show_region_processed", False, "left",
                                                   ui_elements=self.ui_elements,
                                                   controls=self.controls_post_processing,
                                                   callback=self.update_controls_post_processing,
                                                   parent=self)
        view_layout.addWidget(checkbox_region_processed)
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
        return tab

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
            self.update_controls_post_processing()

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
        self.controls_post_processing["view_mode"] = text
        self.update_controls_post_processing()

    def _on_selected_region_changed(self, text):
        self.controls_post_processing["selected_region"] = text if text else None
        self.update_controls_post_processing()

    def _show_chain_region_crop(self):
        """Переключить отображение на вырезанную область (режим region)."""
        name = self.chain_region_combo.currentText()
        if name:
            self.controls_post_processing["view_mode"] = "region"
            self.controls_post_processing["selected_region"] = name
            self.view_mode_combo.setCurrentText("region")
            self.region_combo.setCurrentText(name)
            self.update_controls_post_processing()

    def _add_region(self):
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
        self.update_controls_post_processing()

    def _remove_region(self):
        row = self.regions_list.currentRow()
        if row < 0:
            return
        regions = self.controls_post_processing.get("regions", [])
        if 0 <= row < len(regions):
            name = regions[row]["name"]
            regions.pop(row)
            self.controls_post_processing.get("region_chains", {}).pop(name, None)
        self._refresh_regions_ui()
        self.update_controls_post_processing()

    def _on_region_selected(self):
        """При выборе области в списке — загрузить координаты в поля и запомнить индекс."""
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
        self.update_controls_post_processing()

    def _remove_chain_step(self):
        name = self.chain_region_combo.currentText()
        row = self.chain_steps_list.currentRow()
        if not name or row < 0:
            return
        chain = self.controls_post_processing.get("region_chains", {}).get(name, [])
        if 0 <= row < len(chain):
            chain.pop(row)
        self._refresh_chain_list()
        self.update_controls_post_processing()

    def _copy_chain(self):
        src = self.chain_region_combo.currentText()
        dst = self.copy_to_combo.currentText()
        if not src or not dst or src == dst:
            return
        from Services.Operation_crop.chain import copy_chain
        src_chain = self.controls_post_processing.get("region_chains", {}).get(src, [])
        self.controls_post_processing.setdefault("region_chains", {})[dst] = copy_chain(src_chain)
        self._refresh_chain_list()
        self.update_controls_post_processing()

    def update_controls_post_processing(self):
        """Отправка controls в процесс пост-обработки. Данные берутся из DataManager при наличии."""
        if not hasattr(self, 'queue_manager') or self.queue_manager is None:
            return
        
        # Синхронизация из DataManager: собираем regions и region_chains для текущей камеры
        if hasattr(self, 'data_manager') and self.data_manager:
            camera_id = self.data_manager.get_current_camera_id()
            if camera_id:
                regions_list = []
                region_chains_dict = {}
                for region_name in self.data_manager.get_regions(camera_id):
                    r = self.data_manager.get_region(camera_id, region_name)
                    if not r.get('enabled', True):
                        continue
                    regions_list.append({
                        'name': region_name,
                        'x1': r.get('x1', 0), 'y1': r.get('y1', 0),
                        'x2': r.get('x2', 0), 'y2': r.get('y2', 0),
                        'enabled': True,
                        'processor_id': 1,
                    })
                    region_chains_dict[region_name] = r.get('chains', [])
                self.controls_post_processing['regions'] = regions_list
                self.controls_post_processing['region_chains'] = region_chains_dict
        
        # Обновляем также обработку регионов в controls_processing для процессоров
        if self.controls_post_processing.get('enable_post_processing', False):
            regions = self.controls_post_processing.get('regions', [])
            if regions:
                region_config = {}
                for i, r in enumerate(regions):
                    if isinstance(r, dict):
                        region_name = r.get('name', f'region_{i+1}')
                        processor_id = r.get('processor_id', (i % 2) + 1)
                        enabled = r.get('enabled', True)
                        
                        if enabled:
                            region_config[region_name] = {
                                'processor_id': processor_id,
                                'x1': r.get('x1', 0),
                                'y1': r.get('y1', 0),
                                'x2': r.get('x2', 0),
                                'y2': r.get('y2', 0),
                            }
                
                if region_config:
                    self.controls_processing['enable_region_mode'] = True
                    self.controls_processing['region_config'] = region_config
                    self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_processing)
                    self.queue_manager.control_processing.put(self.controls_processing)
        
        ctrl = dict(self.controls_post_processing)
        self.queue_manager.remove_old_frame_if_full(self.queue_manager.control_post_processing)
        self.queue_manager.control_post_processing.put(ctrl)
        
        # Overlay управляется через update_controls_draw (Draw чекбокс)


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
        try:
            super().show()
            print("MainWindow.show() called")
        except Exception as e:
            print(f"Error in show(): {e}")
            import traceback
            traceback.print_exc()

    
    def close(self):
        print("MainWindow.close() called")
        super().close()
    
    def closeEvent(self, event):
        """Обработчик события закрытия окна"""
        print("MainWindow.closeEvent() called")
        event.accept()


    def close_programm(self):
        # Останавливаем поток сообщений камеры в HikvisionWidget
        if hasattr(self, 'hikvision_widget'):
            self.hikvision_widget.stop_thread()
        
        # Также останавливаем старый поток если он еще существует
        if hasattr(self, 'camera_message_thread'):
            self.camera_message_thread.stop()
        
        self.stop_event.set()
        time.sleep(3)
        self.close()