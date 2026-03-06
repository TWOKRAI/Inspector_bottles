from PyQt5.QtWidgets import (QMainWindow, QVBoxLayout, QHBoxLayout, QWidget, QLabel,
                             QPushButton, QComboBox, QFileDialog, QMessageBox)
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import Qt

import os
import shutil

from App.Components.header import HeaderWidget
from  App.Windows.test_neuroun import ImageSortingWidget


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
            self.stop_event = self.window_manager.stop_event
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

        # # Выпадающий список для выбора папки
        # self.folder_combo = QComboBox()
        # self.folder_combo.addItems(self.file_manager.get_folders())
        # self.folder_combo.currentIndexChanged.connect(self.folder_changed)
        # main_layout.addWidget(self.folder_combo)

        # # Отображение изображения
        # self.image_label = QLabel()
        # self.image_label.setAlignment(Qt.AlignCenter)
        # self.image_label.setFixedSize(120, 120)
        # self.image_label.setScaledContents(True)
        # main_layout.addWidget(self.image_label)

        # # Кнопки для навигации по изображениям
        # nav_layout = QHBoxLayout()
        # self.prev_button = QPushButton("Previous")
        # self.next_button = QPushButton("Next")
        # self.prev_button.clicked.connect(self.show_previous_image)
        # self.next_button.clicked.connect(self.show_next_image)
        # nav_layout.addWidget(self.prev_button)
        # nav_layout.addWidget(self.next_button)
        # main_layout.addLayout(nav_layout)

        # # Кнопки для перемещения изображений
        # move_layout = QHBoxLayout()
        # self.move_buttons = {}
        # folders = self.file_manager.get_folders()
        # for folder in folders:
        #     button = QPushButton(f"Перенести в {folder}")
        #     button.clicked.connect(lambda _, f=folder: self.move_image(f))
        #     self.move_buttons[folder] = button
        #     move_layout.addWidget(button)
        # main_layout.addLayout(move_layout)

        # # Кнопки для удаления и очистки папки
        # action_layout = QHBoxLayout()
        # self.delete_button = QPushButton("Удалить")
        # self.delete_button.clicked.connect(self.delete_current_image)
        # self.clear_button = QPushButton("Очистить папку")
        # self.clear_button.clicked.connect(self.clear_current_folder)
        # action_layout.addWidget(self.delete_button)
        # action_layout.addWidget(self.clear_button)
        # main_layout.addLayout(action_layout)

        # # Метка для отображения количества изображений
        # self.image_count_label = QLabel()
        # main_layout.addWidget(self.image_count_label)
        main_layout.addStretch()


    # def folder_changed(self, index):
    #     # Обработчик изменения выбранной папки
    #     folder_name = self.folder_combo.itemText(index)
    #     self.current_directory = os.path.join(self.file_manager.base_directory, folder_name)
    #     self.load_images()

    # def load_images(self):
    #     # Загрузить изображения из текущей папки
    #     folder_name = self.folder_combo.currentText()
    #     self.images = self.file_manager.get_images(folder_name)
    #     self.current_image_index = 0
    #     self.show_current_image()

    # def show_current_image(self):
    #     # Показать текущее изображение
    #     if not self.images:
    #         self.image_label.clear()
    #         self.image_count_label.setText("No images")
    #         return

    #     image_path = os.path.join(self.current_directory, self.images[self.current_image_index])
    #     image = QImage(image_path)
    #     pixmap = QPixmap.fromImage(image)
    #     self.image_label.setPixmap(pixmap)
    #     self.image_count_label.setText(f"{self.current_image_index + 1}/{len(self.images)}")

    # def show_previous_image(self):
    #     # Показать предыдущее изображение
    #     if self.images:
    #         self.current_image_index = (self.current_image_index - 1) % len(self.images)
    #         self.show_current_image()

    # def show_next_image(self):
    #     # Показать следующее изображение
    #     if self.images:
    #         self.current_image_index = (self.current_image_index + 1) % len(self.images)
    #         self.show_current_image()

    # def move_image(self, target_folder):
    #     # Переместить текущее изображение в указанную папку
    #     if not self.images:
    #         return

    #     source_folder = self.folder_combo.currentText()
    #     self.file_manager.move_image(source_folder, target_folder, self.images[self.current_image_index])
    #     self.load_images()

    # def delete_current_image(self):
    #     # Удалить текущее изображение
    #     if not self.images:
    #         return

    #     reply = QMessageBox.question(self, 'Удаление', 'Вы уверены, что хотите удалить это изображение?',
    #                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
    #     if reply == QMessageBox.Yes:
    #         folder_name = self.folder_combo.currentText()
    #         self.file_manager.delete_image(folder_name, self.images[self.current_image_index])
    #         self.load_images()

    # def clear_current_folder(self):
    #     # Очистить текущую папку
    #     reply = QMessageBox.question(self, 'Очистка папки', 'Вы уверены, что хотите очистить всю папку?',
    #                                  QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
    #     if reply == QMessageBox.Yes:
    #         folder_name = self.folder_combo.currentText()
    #         self.file_manager.clear_folder(folder_name)
    #         self.load_images()
