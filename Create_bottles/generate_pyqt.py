import os
import random
import numpy as np
from pathlib import Path
from PIL import Image, ImageEnhance
import cv2
import sys
from datetime import datetime

from generate_bottle_module import BottleGroup, ImageComposer

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QSlider, QCheckBox, QPushButton, QGroupBox, QSpinBox,
                             QDoubleSpinBox, QScrollArea, QFrame, QFileDialog)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QPixmap, QImage


class BottleGenerator:
    def __init__(self):
        self.CANVAS_WIDTH = 1920
        self.CANVAS_HEIGHT = 1100
        self.BOTTLE_WIDTH = 288
        self.BOTTLE_HEIGHT = 665
        self.GREEN_BG = (210, 210, 210, 255)
        self.image_dir = Path("Create_bottles/Images")
        
        if not os.path.exists(self.image_dir):
            os.makedirs(self.image_dir)
            print(f"Создана папка {self.image_dir}. Добавьте изображения компонентов бутылки.")
        else:
            print(f"Папка {self.image_dir} существует")
    
        self.conveyor = np.zeros((self.CANVAS_HEIGHT, self.CANVAS_WIDTH, 4), dtype=np.uint8)
        self.conveyor[:] = self.GREEN_BG
        
        # Параметры бутылки по умолчанию
        self.default_params = {
            'fill_level': 0.82,
            'cap_visible': True,
            'ring_visible': True,
            'label_visible': True,
            'label_offset': 0,
            'label_angle': 0,
            'label_vertical_offset': 0,
            'bottle_spacing': 160,
            'n_bottles': 1,
            'cap_offset_x': 0,
            'cap_offset_y': 0,
            'ring_offset_x': 0,
            'ring_offset_y': 0,
            'cap_angle': 0,
            'ring_angle': 0,
            'bottle_offset_x': 0,
            'bottle_offset_y': 0,
            'bottle_scale': 1.0,
            'cap_scale': 1.0,
            'ring_scale': 1.0,
            'label_scale': 1.0,
            'brightness': 1.0,
            'contrast': 1.0,
            'saturation': 1.0,
            'sharpness': 1.0,
        }
        
        # Текущие параметры
        self.params = self.default_params.copy()
        
        self.bottle_config = {
            "bottle": {
                "file": "bottle3.png",
                "position": (0, 90),
                "angle": 0,
                "scale": 1.0,
                "visible": True,
                "offset": 0,
                "filler_enable": True,
                "filler_level": 0.7,
                "filler_color": (100, 200, 200, 180),
            },
            "cap": {
                "file": "cap2.png",
                "position": (51, 122),
                "angle": 0,
                "scale": 1.0,
                "visible": True,
                "offset": 0
            },
            "ring": {
                "file": "ring2.png",
                "position": (51, 155),
                "angle": 0,
                "scale": 1.0,
                "visible": True,
                "offset": 0
            },
            "label": {
                "file": "eticet2.png",
                "position": (0, 490),
                "angle": 0,
                "scale": 1.0,
                "visible": True, 
                "offset": 0
            }
        }

    def reset_to_default(self):
        """Сбрасывает параметры к значениям по умолчанию"""
        self.params = self.default_params.copy()

    def generate_image(self):
        """Генерирует изображение с текущими параметрами (без случайных отклонений)"""
        composer = ImageComposer(self.CANVAS_WIDTH, self.CANVAS_HEIGHT, (0, 0, 0, 0))
        composer.add_layer(self.conveyor, (0, 0))
        
        start_x = 100
        current_x = start_x
        
        for i in range(self.params['n_bottles']):
            config = {k: v.copy() for k, v in self.bottle_config.items()}
            
            # Уровень наполнения
            config['bottle']['filler_level'] = self.params['fill_level']
            
            # Основная бутылка
            bottle_base_x, bottle_base_y = config['bottle']['position']
            config['bottle']['position'] = (bottle_base_x + self.params['bottle_offset_x'], 
                                          bottle_base_y + self.params['bottle_offset_y'])
            config['bottle']['scale'] = self.params['bottle_scale']
            
            # Крышка
            config['cap']['visible'] = self.params['cap_visible']
            
            if self.params['cap_visible']:
                cap_base_x, cap_base_y = config['cap']['position']
                config['cap']['position'] = (cap_base_x + self.params['cap_offset_x'], 
                                            cap_base_y + self.params['cap_offset_y'])
                config['cap']['angle'] = self.params['cap_angle']
                config['cap']['scale'] = self.params['cap_scale']
            
            # Кольцо
            config['ring']['visible'] = self.params['ring_visible']
            
            if self.params['ring_visible']:
                ring_base_x, ring_base_y = config['ring']['position']
                config['ring']['position'] = (ring_base_x + self.params['ring_offset_x'], 
                                             ring_base_y + self.params['ring_offset_y'])
                config['ring']['angle'] = self.params['ring_angle']
                config['ring']['scale'] = self.params['ring_scale']
            
            # Этикетка
            config['label']['visible'] = self.params['label_visible']
            
            if self.params['label_visible']:
                config['label']['offset'] = self.params['label_offset']
                config['label']['angle'] = self.params['label_angle']
                config['label']['scale'] = self.params['label_scale']
                
                base_pos = config['label']['position']
                config['label']['position'] = (base_pos[0], base_pos[1] + self.params['label_vertical_offset'])
            
            # Создаем бутылку
            bottle = BottleGroup(self.image_dir, config, position=(80+current_x, 0))
            
            # Добавляем слои
            for img, pos in bottle.get_layers():
                composer.add_layer(img, pos)
            
            current_x += self.BOTTLE_WIDTH + self.params['bottle_spacing']

        # Применяем коррекции изображения
        image = composer.compose()
        
        # Конвертируем в PIL для применения коррекций
        pil_image = Image.fromarray(image)
        
        # Применяем коррекции
        if self.params['brightness'] != 1.0:
            enhancer = ImageEnhance.Brightness(pil_image)
            pil_image = enhancer.enhance(self.params['brightness'])
        
        if self.params['contrast'] != 1.0:
            enhancer = ImageEnhance.Contrast(pil_image)
            pil_image = enhancer.enhance(self.params['contrast'])
        
        if self.params['saturation'] != 1.0:
            enhancer = ImageEnhance.Color(pil_image)
            pil_image = enhancer.enhance(self.params['saturation'])
        
        if self.params['sharpness'] != 1.0:
            enhancer = ImageEnhance.Sharpness(pil_image)
            pil_image = enhancer.enhance(self.params['sharpness'])
        
        return np.array(pil_image)


class BottleGeneratorApp(QMainWindow):
    def __init__(self, generator):
        super().__init__()
        self.generator = generator
        self.current_image = None
        self.image_type = None 
        
        # Создаем папки для сохранения
        self.good_dir = Path("dataset/good")
        self.bad_dir = Path("dataset/bad")
        self.good_dir.mkdir(parents=True, exist_ok=True)
        self.bad_dir.mkdir(parents=True, exist_ok=True)

        self.cap_crop = [(260, 33), (470, 190)]
        
        self.initUI()
        self.generate_image()
        
    def initUI(self):
        self.setWindowTitle('Bottle Generator - Manual Control')
        self.setGeometry(100, 100, 1400, 900)
        
        # Главный виджет и компоновка
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        # Панель управления
        control_panel = QWidget()
        control_panel.setFixedWidth(400)
        control_layout = QVBoxLayout(control_panel)
        
        # Создаем прокручиваемую область для параметров
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        
        # Группа параметров бутылки
        bottle_group = QGroupBox("Параметры бутылки")
        bottle_layout = QVBoxLayout(bottle_group)
        
        # Позиция бутылки X
        bottle_offset_x_layout = QHBoxLayout()
        bottle_offset_x_layout.addWidget(QLabel("Позиция бутылки X:"))
        self.bottle_offset_x_spin = QSpinBox()
        self.bottle_offset_x_spin.setRange(-100, 100)
        self.bottle_offset_x_spin.setValue(self.generator.params['bottle_offset_x'])
        self.bottle_offset_x_spin.valueChanged.connect(self.update_parameter)
        bottle_offset_x_layout.addWidget(self.bottle_offset_x_spin)
        bottle_layout.addLayout(bottle_offset_x_layout)
        
        # Позиция бутылки Y
        bottle_offset_y_layout = QHBoxLayout()
        bottle_offset_y_layout.addWidget(QLabel("Позиция бутылки Y:"))
        self.bottle_offset_y_spin = QSpinBox()
        self.bottle_offset_y_spin.setRange(-100, 100)
        self.bottle_offset_y_spin.setValue(self.generator.params['bottle_offset_y'])
        self.bottle_offset_y_spin.valueChanged.connect(self.update_parameter)
        bottle_offset_y_layout.addWidget(self.bottle_offset_y_spin)
        bottle_layout.addLayout(bottle_offset_y_layout)
        
        # Масштаб бутылки
        bottle_scale_layout = QHBoxLayout()
        bottle_scale_layout.addWidget(QLabel("Масштаб бутылки:"))
        self.bottle_scale_spin = QDoubleSpinBox()
        self.bottle_scale_spin.setRange(0.5, 2.0)
        self.bottle_scale_spin.setSingleStep(0.1)
        self.bottle_scale_spin.setValue(self.generator.params['bottle_scale'])
        self.bottle_scale_spin.valueChanged.connect(self.update_parameter)
        bottle_scale_layout.addWidget(self.bottle_scale_spin)
        bottle_layout.addLayout(bottle_scale_layout)
        
        scroll_layout.addWidget(bottle_group)
        
        # Группа параметров крышки
        cap_group = QGroupBox("Параметры крышки")
        cap_layout = QVBoxLayout(cap_group)
        
        # Видимость крышки
        self.cap_visible_cb = QCheckBox("Крышка видима")
        self.cap_visible_cb.setChecked(self.generator.params['cap_visible'])
        self.cap_visible_cb.stateChanged.connect(self.update_parameter)
        cap_layout.addWidget(self.cap_visible_cb)

        # Масштаб крышки
        cap_scale_layout = QHBoxLayout()
        cap_scale_layout.addWidget(QLabel("Масштаб крышки:"))
        self.cap_scale_spin = QDoubleSpinBox()
        self.cap_scale_spin.setRange(0.5, 2.0)
        self.cap_scale_spin.setSingleStep(0.1)
        self.cap_scale_spin.setValue(self.generator.params['cap_scale'])
        self.cap_scale_spin.valueChanged.connect(self.update_parameter)
        cap_scale_layout.addWidget(self.cap_scale_spin)
        cap_layout.addLayout(cap_scale_layout)
        
        # Смещение крышки X
        cap_offset_x_layout = QHBoxLayout()
        cap_offset_x_layout.addWidget(QLabel("Смещение крышки X:"))
        self.cap_offset_x_spin = QSpinBox()
        self.cap_offset_x_spin.setRange(-100, 100)
        self.cap_offset_x_spin.setValue(self.generator.params['cap_offset_x'])
        self.cap_offset_x_spin.valueChanged.connect(self.update_parameter)
        cap_offset_x_layout.addWidget(self.cap_offset_x_spin)
        cap_layout.addLayout(cap_offset_x_layout)
        
        # Смещение крышки Y
        cap_offset_y_layout = QHBoxLayout()
        cap_offset_y_layout.addWidget(QLabel("Смещение крышки Y:"))
        self.cap_offset_y_spin = QSpinBox()
        self.cap_offset_y_spin.setRange(-100, 100)
        self.cap_offset_y_spin.setValue(self.generator.params['cap_offset_y'])
        self.cap_offset_y_spin.valueChanged.connect(self.update_parameter)
        cap_offset_y_layout.addWidget(self.cap_offset_y_spin)
        cap_layout.addLayout(cap_offset_y_layout)
        
        # Угол крышки
        cap_angle_layout = QHBoxLayout()
        cap_angle_layout.addWidget(QLabel("Угол крышки:"))
        self.cap_angle_spin = QDoubleSpinBox()
        self.cap_angle_spin.setRange(-45, 45)
        self.cap_angle_spin.setValue(self.generator.params['cap_angle'])
        self.cap_angle_spin.valueChanged.connect(self.update_parameter)
        cap_angle_layout.addWidget(self.cap_angle_spin)
        cap_layout.addLayout(cap_angle_layout)
        
        scroll_layout.addWidget(cap_group)
        
        # Группа параметров кольца
        ring_group = QGroupBox("Параметры кольца")
        ring_layout = QVBoxLayout(ring_group)
        
        # Видимость кольца
        self.ring_visible_cb = QCheckBox("Кольцо видимо")
        self.ring_visible_cb.setChecked(self.generator.params['ring_visible'])
        self.ring_visible_cb.stateChanged.connect(self.update_parameter)
        ring_layout.addWidget(self.ring_visible_cb)

        # Масштаб кольца
        ring_scale_layout = QHBoxLayout()
        ring_scale_layout.addWidget(QLabel("Масштаб кольца:"))
        self.ring_scale_spin = QDoubleSpinBox()
        self.ring_scale_spin.setRange(0.5, 2.0)
        self.ring_scale_spin.setSingleStep(0.1)
        self.ring_scale_spin.setValue(self.generator.params['ring_scale'])
        self.ring_scale_spin.valueChanged.connect(self.update_parameter)
        ring_scale_layout.addWidget(self.ring_scale_spin)
        ring_layout.addLayout(ring_scale_layout)
        
        # Смещение кольца X
        ring_offset_x_layout = QHBoxLayout()
        ring_offset_x_layout.addWidget(QLabel("Смещение кольца X:"))
        self.ring_offset_x_spin = QSpinBox()
        self.ring_offset_x_spin.setRange(-100, 100)
        self.ring_offset_x_spin.setValue(self.generator.params['ring_offset_x'])
        self.ring_offset_x_spin.valueChanged.connect(self.update_parameter)
        ring_offset_x_layout.addWidget(self.ring_offset_x_spin)
        ring_layout.addLayout(ring_offset_x_layout)
        
        # Смещение кольца Y
        ring_offset_y_layout = QHBoxLayout()
        ring_offset_y_layout.addWidget(QLabel("Смещение кольца Y:"))
        self.ring_offset_y_spin = QSpinBox()
        self.ring_offset_y_spin.setRange(-100, 100)
        self.ring_offset_y_spin.setValue(self.generator.params['ring_offset_y'])
        self.ring_offset_y_spin.valueChanged.connect(self.update_parameter)
        ring_offset_y_layout.addWidget(self.ring_offset_y_spin)
        ring_layout.addLayout(ring_offset_y_layout)
        
        # Угол кольца
        ring_angle_layout = QHBoxLayout()
        ring_angle_layout.addWidget(QLabel("Угол кольца:"))
        self.ring_angle_spin = QDoubleSpinBox()
        self.ring_angle_spin.setRange(-45, 45)
        self.ring_angle_spin.setValue(self.generator.params['ring_angle'])
        self.ring_angle_spin.valueChanged.connect(self.update_parameter)
        ring_angle_layout.addWidget(self.ring_angle_spin)
        ring_layout.addLayout(ring_angle_layout)
        
        scroll_layout.addWidget(ring_group)

        # Группа параметров этикетки
        label_group = QGroupBox("Параметры этикетки")
        label_layout = QVBoxLayout(label_group)
        
        # Видимость этикетки
        self.label_visible_cb = QCheckBox("Этикетка видима")
        self.label_visible_cb.setChecked(self.generator.params['label_visible'])
        self.label_visible_cb.stateChanged.connect(self.update_parameter)
        label_layout.addWidget(self.label_visible_cb)

        # Масштаб этикетки
        label_scale_layout = QHBoxLayout()
        label_scale_layout.addWidget(QLabel("Масштаб этикетки:"))
        self.label_scale_spin = QDoubleSpinBox()
        self.label_scale_spin.setRange(0.5, 2.0)
        self.label_scale_spin.setSingleStep(0.1)
        self.label_scale_spin.setValue(self.generator.params['label_scale'])
        self.label_scale_spin.valueChanged.connect(self.update_parameter)
        label_scale_layout.addWidget(self.label_scale_spin)
        label_layout.addLayout(label_scale_layout)
        
        # Смещение этикетки X
        label_offset_layout = QHBoxLayout()
        label_offset_layout.addWidget(QLabel("Смещение этикетки X:"))
        self.label_offset_spin = QSpinBox()
        self.label_offset_spin.setRange(-100, 100)
        self.label_offset_spin.setValue(self.generator.params['label_offset'])
        self.label_offset_spin.valueChanged.connect(self.update_parameter)
        label_offset_layout.addWidget(self.label_offset_spin)
        label_layout.addLayout(label_offset_layout)
        
        # Смещение этикетки Y
        label_vertical_offset_layout = QHBoxLayout()
        label_vertical_offset_layout.addWidget(QLabel("Смещение этикетки Y:"))
        self.label_vertical_offset_spin = QSpinBox()
        self.label_vertical_offset_spin.setRange(-100, 100)
        self.label_vertical_offset_spin.setValue(self.generator.params['label_vertical_offset'])
        self.label_vertical_offset_spin.valueChanged.connect(self.update_parameter)
        label_vertical_offset_layout.addWidget(self.label_vertical_offset_spin)
        label_layout.addLayout(label_vertical_offset_layout)
        
        # Угол этикетки
        label_angle_layout = QHBoxLayout()
        label_angle_layout.addWidget(QLabel("Угол этикетки:"))
        self.label_angle_spin = QDoubleSpinBox()
        self.label_angle_spin.setRange(-45, 45)
        self.label_angle_spin.setValue(self.generator.params['label_angle'])
        self.label_angle_spin.valueChanged.connect(self.update_parameter)
        label_angle_layout.addWidget(self.label_angle_spin)
        label_layout.addLayout(label_angle_layout)
        
        scroll_layout.addWidget(label_group)

        # Группа коррекции изображения
        image_correction_group = QGroupBox("Коррекция изображения")
        image_correction_layout = QVBoxLayout(image_correction_group)
        
        # Яркость
        brightness_layout = QHBoxLayout()
        brightness_layout.addWidget(QLabel("Яркость:"))
        self.brightness_spin = QDoubleSpinBox()
        self.brightness_spin.setRange(0.0, 3.0)
        self.brightness_spin.setSingleStep(0.1)
        self.brightness_spin.setValue(self.generator.params['brightness'])
        self.brightness_spin.valueChanged.connect(self.update_parameter)
        brightness_layout.addWidget(self.brightness_spin)
        image_correction_layout.addLayout(brightness_layout)
        
        # Контрастность
        contrast_layout = QHBoxLayout()
        contrast_layout.addWidget(QLabel("Контрастность:"))
        self.contrast_spin = QDoubleSpinBox()
        self.contrast_spin.setRange(0.0, 3.0)
        self.contrast_spin.setSingleStep(0.1)
        self.contrast_spin.setValue(self.generator.params['contrast'])
        self.contrast_spin.valueChanged.connect(self.update_parameter)
        contrast_layout.addWidget(self.contrast_spin)
        image_correction_layout.addLayout(contrast_layout)
        
        # Насыщенность
        saturation_layout = QHBoxLayout()
        saturation_layout.addWidget(QLabel("Насыщенность:"))
        self.saturation_spin = QDoubleSpinBox()
        self.saturation_spin.setRange(0.0, 3.0)
        self.saturation_spin.setSingleStep(0.1)
        self.saturation_spin.setValue(self.generator.params['saturation'])
        self.saturation_spin.valueChanged.connect(self.update_parameter)
        saturation_layout.addWidget(self.saturation_spin)
        image_correction_layout.addLayout(saturation_layout)
        
        # Резкость
        sharpness_layout = QHBoxLayout()
        sharpness_layout.addWidget(QLabel("Резкость:"))
        self.sharpness_spin = QDoubleSpinBox()
        self.sharpness_spin.setRange(0.0, 3.0)
        self.sharpness_spin.setSingleStep(0.1)
        self.sharpness_spin.setValue(self.generator.params['sharpness'])
        self.sharpness_spin.valueChanged.connect(self.update_parameter)
        sharpness_layout.addWidget(self.sharpness_spin)
        image_correction_layout.addLayout(sharpness_layout)
        
        scroll_layout.addWidget(image_correction_group)
        
        # Кнопки управления
        buttons_layout = QVBoxLayout()
        
        # Кнопка сброса
        self.reset_btn = QPushButton("Сбросить параметры")
        self.reset_btn.clicked.connect(self.reset_parameters)
        self.reset_btn.setStyleSheet("background-color: #FF9800; color: white;")
        buttons_layout.addWidget(self.reset_btn)
        
        # Кнопки сохранения
        save_buttons_layout = QHBoxLayout()
        self.save_good_btn = QPushButton("Сохранить как ХОРОШУЮ")
        self.save_good_btn.clicked.connect(self.save_good)
        self.save_good_btn.setStyleSheet("background-color: #4CAF50; color: white;")
        save_buttons_layout.addWidget(self.save_good_btn)
        
        self.save_bad_btn = QPushButton("Сохранить как БРАК")
        self.save_bad_btn.clicked.connect(self.save_bad)
        self.save_bad_btn.setStyleSheet("background-color: #F44336; color: white;")
        save_buttons_layout.addWidget(self.save_bad_btn)
        
        buttons_layout.addLayout(save_buttons_layout)
        scroll_layout.addLayout(buttons_layout)
        
        # Устанавливаем содержимое прокручиваемой области
        scroll_area.setWidget(scroll_content)
        control_layout.addWidget(scroll_area)
        
        # Область предпросмотра
        preview_frame = QFrame()
        preview_frame.setFrameShape(QFrame.StyledPanel)
        preview_layout = QVBoxLayout(preview_frame)
        
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(600, 400)
        self.preview_label.setMaximumSize(600, 400)
        self.preview_label.setText("Предпросмотр изображения")
        preview_layout.addWidget(self.preview_label)
        
        # Добавляем панели в главную компоновку
        main_layout.addWidget(control_panel)
        main_layout.addWidget(preview_frame, 1)
        
    def reset_parameters(self):
        """Сбрасывает все параметры к значениям по умолчанию"""
        self.generator.reset_to_default()
        
        # Обновляем UI элементы
        self.bottle_offset_x_spin.setValue(self.generator.params['bottle_offset_x'])
        self.bottle_offset_y_spin.setValue(self.generator.params['bottle_offset_y'])
        self.bottle_scale_spin.setValue(self.generator.params['bottle_scale'])
        
        self.cap_visible_cb.setChecked(self.generator.params['cap_visible'])
        self.cap_offset_x_spin.setValue(self.generator.params['cap_offset_x'])
        self.cap_offset_y_spin.setValue(self.generator.params['cap_offset_y'])
        self.cap_angle_spin.setValue(self.generator.params['cap_angle'])
        self.cap_scale_spin.setValue(self.generator.params['cap_scale'])
        
        self.ring_visible_cb.setChecked(self.generator.params['ring_visible'])
        self.ring_offset_x_spin.setValue(self.generator.params['ring_offset_x'])
        self.ring_offset_y_spin.setValue(self.generator.params['ring_offset_y'])
        self.ring_angle_spin.setValue(self.generator.params['ring_angle'])
        self.ring_scale_spin.setValue(self.generator.params['ring_scale'])
        
        self.label_visible_cb.setChecked(self.generator.params['label_visible'])
        self.label_offset_spin.setValue(self.generator.params['label_offset'])
        self.label_vertical_offset_spin.setValue(self.generator.params['label_vertical_offset'])
        self.label_angle_spin.setValue(self.generator.params['label_angle'])
        self.label_scale_spin.setValue(self.generator.params['label_scale'])
        
        self.brightness_spin.setValue(self.generator.params['brightness'])
        self.contrast_spin.setValue(self.generator.params['contrast'])
        self.saturation_spin.setValue(self.generator.params['saturation'])
        self.sharpness_spin.setValue(self.generator.params['sharpness'])
        
        self.generate_image()
        
    def update_parameter(self):
        """Обновляет параметры генератора при изменении UI"""
        self.generator.params['bottle_offset_x'] = self.bottle_offset_x_spin.value()
        self.generator.params['bottle_offset_y'] = self.bottle_offset_y_spin.value()
        self.generator.params['bottle_scale'] = self.bottle_scale_spin.value()
        
        self.generator.params['cap_visible'] = self.cap_visible_cb.isChecked()
        self.generator.params['cap_offset_x'] = self.cap_offset_x_spin.value()
        self.generator.params['cap_offset_y'] = self.cap_offset_y_spin.value()
        self.generator.params['cap_angle'] = self.cap_angle_spin.value()
        self.generator.params['cap_scale'] = self.cap_scale_spin.value()
        
        self.generator.params['ring_visible'] = self.ring_visible_cb.isChecked()
        self.generator.params['ring_offset_x'] = self.ring_offset_x_spin.value()
        self.generator.params['ring_offset_y'] = self.ring_offset_y_spin.value()
        self.generator.params['ring_angle'] = self.ring_angle_spin.value()
        self.generator.params['ring_scale'] = self.ring_scale_spin.value()
        
        self.generator.params['label_visible'] = self.label_visible_cb.isChecked()
        self.generator.params['label_offset'] = self.label_offset_spin.value()
        self.generator.params['label_vertical_offset'] = self.label_vertical_offset_spin.value()
        self.generator.params['label_angle'] = self.label_angle_spin.value()
        self.generator.params['label_scale'] = self.label_scale_spin.value()
        
        self.generator.params['brightness'] = self.brightness_spin.value()
        self.generator.params['contrast'] = self.contrast_spin.value()
        self.generator.params['saturation'] = self.saturation_spin.value()
        self.generator.params['sharpness'] = self.sharpness_spin.value()
        
        self.generate_image()
        
    def generate_image(self):
        """Генерирует и отображает изображение с текущими параметрами"""
        image = self.generator.generate_image()
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2RGBA)
        image = image[self.cap_crop[0][1]:self.cap_crop[1][1], self.cap_crop[0][0]:self.cap_crop[1][0]]
        image = cv2.resize(image, (0,0), fx=0.5, fy=0.5)
        
        self.current_image = image
        self.display_image(image)
        
    def display_image(self, image):
        """Отображает изображение в QLabel"""
        height, width, channel = image.shape
        bytes_per_line = 4 * width
        q_img = QImage(image.data, width, height, bytes_per_line, QImage.Format_RGBA8888)
        pixmap = QPixmap.fromImage(q_img)
        
        # Масштабируем изображение для предпросмотра
        scaled_pixmap = pixmap.scaled(
            self.preview_label.width(), 
            self.preview_label.height(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        self.preview_label.setPixmap(scaled_pixmap)
        
    def save_good(self):
        """Сохраняет текущее изображение как хорошее"""
        if self.current_image is not None:
            self.save_image(self.good_dir, "good")
        
    def save_bad(self):
        """Сохраняет текущее изображение как брак"""
        if self.current_image is not None:
            self.save_image(self.bad_dir, "bad")
            
    def save_image(self, directory, category):
        """Сохраняет изображение в указанную директорию"""
        pil_image = Image.fromarray(self.current_image)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{timestamp}.png"
        
        save_path = directory / filename
        pil_image.save(save_path)
        print(f"Изображение сохранено как {category}: {save_path}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    generator = BottleGenerator()
    window = BottleGeneratorApp(generator)
    window.show()
    sys.exit(app.exec_())