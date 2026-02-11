import time
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import  Qt


class LoadingWindow(QWidget):
    def __init__(self, window_manager = None):
        super().__init__()

        self.window_manager = window_manager

        if not window_manager is None:
            self.queue_manager =self.window_manager.queue_manager
            self.stop_event = self.window_manager.stop_event

            self.fullscreen = self.window_manager.fullscreen
        
        self.initUI()

        if self.fullscreen: self.showFullScreen()


    def initUI(self):
        # Создаем вертикальный layout
        vbox = QVBoxLayout()

        # Создаем QLabel для отображения изображения
        self.image_label = QLabel(self)
        pixmap = QPixmap('App/Image/innotech.png')  # Замените на путь к вашему изображению
        self.image_label.setPixmap(pixmap)
        self.image_label.setAlignment(Qt.AlignCenter)  # Центрируем изображение

        # Создаем QProgressBar для отображения строки загрузки
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100) 
        self.progress_bar.setAlignment(Qt.AlignCenter)  # Центрируем строку загрузки
        self.progress_bar.setFormat("%p%")  # Отображение процентов
        
        # Метка для отображения процентов
        self.percent_label = QLabel("0%", self)
        self.percent_label.setAlignment(Qt.AlignCenter)
        self.percent_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50;")

        # Добавляем виджеты в вертикальный layout
        vbox.addStretch()
        vbox.addWidget(self.image_label)
        vbox.addSpacing(35)
        vbox.addWidget(self.percent_label)
        vbox.addSpacing(10)
        vbox.addWidget(self.progress_bar)
        vbox.addStretch()

        # Создаем горизонтальный layout для центрирования вертикального layout
        hbox = QHBoxLayout()
        hbox.addStretch(1)
        hbox.addLayout(vbox)
        hbox.addStretch(1)

        # Устанавливаем layout для окна
        self.setLayout(hbox)

        # Устанавливаем параметры окна
        self.setWindowTitle('Loading Window')
        # Размер будет установлен из main_app.py чтобы соответствовать главному окну
        self.setMinimumSize(800, 500)


    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()


    def update_progress(self, percent):
        # Обновляем значение строки загрузки (percent от 0 до 100)
        self.progress_bar.setValue(percent)
        self.percent_label.setText(f"{percent}%")
