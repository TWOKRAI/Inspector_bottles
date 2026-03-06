import sys
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout
from PyQt5.QtGui import QPixmap, QImage, QFont
from PyQt5.QtCore import Qt
from PIL import Image
from functools import partial



class MessageWindow(QWidget):
    def __init__(self, queue_manager, message):
        super().__init__()
        self.queue_manager = queue_manager

        #self.setWindowFlag(Qt.FramelessWindowHint)

        self.initUI(message)

    def initUI(self, message):
        text = message[0]
        image = message[1]
        buttons = message[2]

        # Основной вертикальный layout
        vbox = QVBoxLayout()

        # Создаем QLabel для изображения
        if not image is None:
            self.image_label = QLabel(self)
            self.update_image(image)
            self.image_label.setAlignment(Qt.AlignCenter)
            self.image_label.mousePressEvent = self.on_image_clicked   # Закрываем окно по клику на изображение
            vbox.addWidget(self.image_label)

        if text == None:
            text = ''

        # Создаем QLabel для текста
        self.text_label = QLabel()
        self.text_label.setAlignment(Qt.AlignCenter)
        self.text_label.setText(f"{text}")
        
        if len(text) > 2:
            font_size = 40
        else:
            font_size = 90

        font = QFont("Tahoma", font_size, QFont.Bold)
        font.setPointSize(font.pointSize() * 1)  # Увеличиваем размер шрифта в 5 раз
        self.text_label.setFont(font)
        self.text_label.mousePressEvent = self.on_image_clicked 

        vbox.addWidget(self.text_label)

        hbox = QHBoxLayout()

        for name in buttons:
            button = QPushButton(f'{name}', self)
            button.setFixedSize(100, 50) 
            button.clicked.connect(partial(self.button_method, name))
            hbox.addWidget(button)

        vbox.addLayout(hbox)

        self.setLayout(vbox)

        self.setMinimumSize(500, 400) 
        self.setWindowTitle('СООБЩЕНИЕ ОТ РОБОТА')


    def button_method(self, button_name):
        print(f"Нажата кнопка: {button_name}")
        self.queue_manager.bot_message_send.put(button_name)


    def update_image(self, image_bytes):
        # Преобразуем байты в объект изображения PIL
        pil_image = Image.open(image_bytes)

        # Преобразуем изображение в формат, который понимает QImage
        pil_image = pil_image.convert("RGB")
        frame = pil_image.tobytes("raw", "RGB")

        # Получаем размеры изображения
        width, height = pil_image.size

        # Вычисляем новые размеры
        new_height = int(height * 0.4)
        new_width = int(width * 0.4)

        # Создаем QImage из байтов
        q_img = QImage(frame, width, height, 3 * width, QImage.Format_RGB888)
        q_img = q_img.scaled(new_width, new_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        # Создаем QPixmap из QImage
        pixmap = QPixmap.fromImage(q_img)

        # Устанавливаем изображение в QLabel
        self.image_label.setPixmap(pixmap)


    def on_image_clicked(self, event):
        self.close()  # Закрываем окно по клику на изображение
