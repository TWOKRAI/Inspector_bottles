from PyQt5.QtWidgets import (QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QLabel,
                             QPushButton, QComboBox, QFileDialog, QMessageBox)
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import Qt

import os
import shutil

from App2.Components.header import HeaderWidget
from App2.Windows.test_neuroun import ImageSortingWidget


class FileManager:
    def __init__(self, base_directory):
        self.base_directory = base_directory
        self.ensure_folders_exist()

    def ensure_folders_exist(self):
        # Убедиться, что все необходимые папки существуют
        folders = self.get_folders()
        for folder in folders:
            folder_path = os.path.join(self.base_directory, folder)
            if not os.path.exists(folder_path):
                os.makedirs(folder_path)

    def get_folders(self):
        # Получить список папок
        return ["Data_all", "Data_good", "Data_bad", "Data_none"]

    def get_images(self, folder_name):
        # Получить список изображений в указанной папке
        directory = os.path.join(self.base_directory, folder_name)
        return sorted([f for f in os.listdir(directory) if f.endswith(('.png', '.jpg', '.jpeg'))])

    def move_image(self, source_folder, target_folder, image_name):
        # Переместить изображение из одной папки в другую
        source_path = os.path.join(self.base_directory, source_folder, image_name)
        target_path = os.path.join(self.base_directory, target_folder)

        # Убедиться, что целевая директория существует
        if not os.path.exists(target_path):
            os.makedirs(target_path)

        # Сгенерировать уникальное имя файла на основе порядкового номера
        new_image_name = self.get_next_filename(target_path, image_name)
        target_path = os.path.join(target_path, new_image_name)

        shutil.move(source_path, target_path)

    def get_next_filename(self, directory, image_name):
        # Извлечь расширение из оригинального имени изображения
        _, extension = os.path.splitext(image_name)

        # Найти наибольший номер в директории
        existing_files = [f for f in os.listdir(directory) if f.endswith(extension)]
        if not existing_files:
            return "1" + extension

        # Извлечь номера из имен файлов и найти наибольший
        numbers = [int(os.path.splitext(f)[0]) for f in existing_files if os.path.splitext(f)[0].isdigit()]
        highest_number = max(numbers) if numbers else 0

        return f"{highest_number + 1}{extension}"

    def delete_image(self, folder_name, image_name):
        # Удалить изображение из указанной папки
        image_path = os.path.join(self.base_directory, folder_name, image_name)
        if os.path.exists(image_path):
            os.remove(image_path)

    def clear_folder(self, folder_name):
        # Очистить указанную папку от всех файлов
        folder_path = os.path.join(self.base_directory, folder_name)
        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)


class NeurounWindow(QMainWindow):
    def __init__(self, window_manager = None):
        super().__init__()

        self.window_manager = window_manager

        if not window_manager is None:
            self.queue_manager = self.window_manager.queue_manager
            #self.stop_event = self.window_manager.stop_event
            self.fullscreen = self.window_manager.fullscreen

        self.header = HeaderWidget(self.window_manager)

        self.file_manager = FileManager('Neuron/Data_image')
        self.current_directory = ""
        self.current_image_index = 0
        self.images = []

        self.init_ui()
        # self.load_images()
        if self.fullscreen: self.showFullScreen()
        

    def init_ui(self):
        # Настройка основного окна
        self.setWindowTitle("Image Manager")
        self.setGeometry(100, 100, 800, 600)

        main_layout = QVBoxLayout()
        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

        main_layout.addWidget(self.header)
    
        sorting = ImageSortingWidget()

        sorting_layout = QHBoxLayout()
        #sorting_layout.addSpacing(25)
        sorting_layout.addWidget(sorting)
       # sorting_layout.addSpacing(25)

        main_layout.addLayout(sorting_layout)

