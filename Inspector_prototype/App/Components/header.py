from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QToolButton
from PyQt5.QtGui import QImage, QPixmap, QIcon
from PyQt5.QtCore import Qt, QSize, pyqtSignal


from App.Windows.admin_window import PasswordDialog


class ButtonHeader:
    width = 80
    height = 80
    icon_size = QSize(60, 60)
    pressed_icon_size = QSize(75, 75)

    def __init__(self) -> None:
        self.name = ''
        self.image = None
        self.func = lambda: None

        self.init_ui()

    def init_ui(self):
        self.button = QPushButton()
        if self.name:
            self.button.setText(self.name)

        self.button.setMinimumSize(self.width, self.height)

        self.button.clicked.connect(self.func)

        if self.image:
            icon = QIcon(self.image)
            self.button.setIcon(icon)
            self.button.setIconSize(self.icon_size)


        # Подключаем сигналы нажатия и отпускания кнопки
        self.button.pressed.connect(self.on_button_pressed)
        self.button.released.connect(self.on_button_released)

        # # Подключаем сигналы нажатия и отпускания кнопки к методам анимации
        # self.button.pressed.connect(self.animate_grow)
        # self.button.released.connect(self.animate_shrink)

        # Устанавливаем стиль для кнопки
        self.button.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                font-size: 20px;
            }
            QPushButton:pressed {
                font-size: 25px;
            }
        """)

    # def animate_grow(self):
    #     # Создаем анимацию для увеличения иконки и текста
    #     self.anim_icon = QPropertyAnimation(self.button, b"iconSize")
    #     self.anim_icon.setDuration(200)  # Длительность анимации в миллисекундах

    #     # Устанавливаем начальный и конечный размеры иконки
    #     start_size = self.button.iconSize()
    #     end_size = QSize(int(start_size.width() * 1.3), int(start_size.height() * 1.3))

    #     self.anim_icon.setStartValue(start_size)
    #     self.anim_icon.setEndValue(end_size)

    #     # Устанавливаем кривую анимации для плавного перехода
    #     self.anim_icon.setEasingCurve(QEasingCurve.OutBounce)

    #     # Создаем анимацию для увеличения текста
    #     self.anim_text = QPropertyAnimation(self.button, b"font")
    #     self.anim_text.setDuration(200)

    #     start_font = self.button.font()
    #     end_font = self.button.font()
    #     end_font.setPointSize(int(start_font.pointSize() * 1.3))

    #     self.anim_text.setStartValue(start_font)
    #     self.anim_text.setEndValue(end_font)

    #     self.anim_text.setEasingCurve(QEasingCurve.OutBounce)

    #     # Запускаем анимации
    #     self.anim_icon.start()
    #     self.anim_text.start()

    # def animate_shrink(self):
    #     # Создаем анимацию для уменьшения иконки и текста
    #     self.anim_icon = QPropertyAnimation(self.button, b"iconSize")
    #     self.anim_icon.setDuration(200)  # Длительность анимации в миллисекундах

    #     # Устанавливаем начальный и конечный размеры иконки
    #     end_size = self.button.iconSize()
    #     start_size = QSize(int(end_size.width() / 1.3), int(end_size.height() / 1.3))

    #     self.anim_icon.setStartValue(end_size)
    #     self.anim_icon.setEndValue(start_size)

    #     # Устанавливаем кривую анимации для плавного перехода
    #     self.anim_icon.setEasingCurve(QEasingCurve.InBounce)

    #     # Создаем анимацию для уменьшения текста
    #     self.anim_text = QPropertyAnimation(self.button, b"font")
    #     self.anim_text.setDuration(200)

    #     end_font = self.button.font()
    #     start_font = self.button.font()
    #     start_font.setPointSize(int(end_font.pointSize() / 1.3))

    #     self.anim_text.setStartValue(end_font)
    #     self.anim_text.setEndValue(start_font)

    #     self.anim_text.setEasingCurve(QEasingCurve.InBounce)

    #     # Запускаем анимации
    #     self.anim_icon.start()
    #     self.anim_text.start()
        
    def on_button_pressed(self):
        # Увеличиваем иконку при нажатии
        self.button.setIconSize(self.pressed_icon_size)

    def on_button_released(self):
        # Возвращаем иконку к исходному размеру
        self.button.setIconSize(self.icon_size)

    def update(self):
        self.init_ui()
        return self.button
    

class HeaderWidget(QWidget):
    main_show = pyqtSignal()
    neuroun_show = pyqtSignal()

    def __init__(self, window_manager):
        super().__init__()
        self.window_manager = window_manager

        if not window_manager is None:
            self.queue_manager = self.window_manager.queue_manager
            self.stop_event = self.window_manager.stop_event
            self.fullscreen = self.window_manager.fullscreen

        self.init_ui()
        

    def init_ui(self):
        self.all_layout = QVBoxLayout()
        
        self.all_layout.addSpacing(9)

        self.top_layout = QHBoxLayout()
        self.top_layout.addSpacing(5)
        layout_buttons = self.setup_buttons()
        self.top_layout.addLayout(layout_buttons)
        self.top_layout.addStretch()

        self.setup_logo()

        self.top_layout.addSpacing(12)

        self.all_layout.addLayout(self.top_layout)
        #self.all_layout.addSpacing(5)

        self.setLayout(self.all_layout)

    def setup_buttons(self):
        layout_buttons = QHBoxLayout()
        layout_buttons.addSpacing(50)

        self.admin_button = ButtonHeader()
        self.admin_button.image = 'App\Image\icons8-test-account-96.png'
        self.admin_button.func = self.admin
        layout_buttons.addWidget(self.admin_button.update())
        layout_buttons.addSpacing(30)

        self.home_button = ButtonHeader()
        self.home_button.name = 'Домой'
        self.home_button.func = self.show_home
        layout_buttons.addWidget(self.home_button.update())
        layout_buttons.addSpacing(30)

        self.neuroun_button = ButtonHeader()
        self.neuroun_button.name = 'Нейрон'
        self.neuroun_button.func = self.show_neuroun
        layout_buttons.addWidget(self.neuroun_button.update())
        layout_buttons.addSpacing(30)

        self.fullscreen_button = ButtonHeader()
        self.fullscreen_button.name = 'ЭКРАН'
        self.fullscreen_button.func = self.toggle_fullscreen
        layout_buttons.addWidget(self.fullscreen_button.update())
        layout_buttons.addSpacing(30)

        self.close_button = ButtonHeader()
        self.close_button.name = 'ЗАКРЫТЬ'
        self.close_button.func = self.close_programm
        layout_buttons.addWidget(self.close_button.update())
        layout_buttons.addSpacing(30)

        return layout_buttons

    def setup_logo(self):
        layout_logo_v = QHBoxLayout()
        layout_logo_v.addStretch()

        top_image_label = QLabel()

        image = QImage('App/Image/innotech.png')
        if not image.isNull():
            scaled_image = image.scaled(image.width() // 2, image.height() // 2, Qt.KeepAspectRatio)
            top_pixmap = QPixmap.fromImage(scaled_image)
            top_image_label.setPixmap(top_pixmap)

        top_image_label.setAlignment(Qt.AlignCenter)
        top_image_label.setScaledContents(False)
        layout_logo_v.addWidget(top_image_label)
        layout_logo_v.addStretch()

        self.top_layout.addLayout(layout_logo_v)

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen

        self.window_manager.set_fullscreen(self.fullscreen)


    def close_programm(self):
        if self.window_manager:
            self.window_manager.close_program()


    def show_home(self):
        # if self.window_manager:
        #     self.window_manager.main_window.show()
        #     self.window_manager.main_window.raise_()
        self.main_show.emit()
        print('Отправил сигнал на откртыие майна')


    
    def show_neuroun(self):
        # if self.window_manager.neuroun_window:
        #     self.window_manager.neuroun_window.show()
        #     self.window_manager.neuroun_window.raise_()
        self.neuroun_show.emit()
        print('Отправил сигнал на откртыие нейрона')


    def admin(self):
        dialog = PasswordDialog(self.window_manager)
        dialog.show()

