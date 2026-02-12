# from PyQt5.QtWidgets import (
#     QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QApplication, QGridLayout, QWidget, QSizePolicy
# )
# from PyQt5.QtGui import QPixmap, QFont
# from PyQt5.QtCore import Qt, QTimer, QRect
# from PyQt5.QtGui import QScreen


# from App.Components.keyboard import VirtualKeyboard


# class PasswordDialog(QWidget):
#     def __init__(self, window_manager = None, parent=None):
#         super().__init__(parent)

#         self.window_manager = window_manager

#         self.setWindowTitle("Администрация")
#         self.setFixedSize(450, 300)
#         self.setWindowFlags(Qt.FramelessWindowHint)

#         self.move(300, 150)


#         main_layout = QVBoxLayout()
#         main_layout.setContentsMargins(20, 20, 20, 20)

#         main_layout.addSpacing(20)
    
#         image_text_layout = QHBoxLayout()

#         image_text_layout.addStretch()

#         layout_v = QVBoxLayout()
#         self.image_label = QLabel(self)
#         pixmap = QPixmap("App\Image\icons8-lock-100.png")
#         pixmap = pixmap.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
#         self.image_label.setPixmap(pixmap)
#         self.image_label.setAlignment(Qt.AlignCenter)

#         layout_v.addStretch()
#         layout_v.addWidget(self.image_label)
#         layout_v.addStretch()

#         image_text_layout.addLayout(layout_v)

#         layout_v = QVBoxLayout()
#         self.system_entry_label = QLabel("Вход в систему", self)
#         font = QFont()
#         font.setPointSize(18)
#         self.system_entry_label.setFont(font)

#         layout_v.addStretch()
#         layout_v.addWidget(self.system_entry_label)
#         layout_v.addSpacing(17)

#         image_text_layout.addSpacing(20)
#         image_text_layout.addLayout(layout_v)
#         image_text_layout.addStretch()
        
#         image_text_layout.setAlignment(Qt.AlignVCenter)
#         main_layout.addLayout(image_text_layout)

#         main_layout.addSpacing(10)

#         password_layout = QHBoxLayout()
#         password_layout.addStretch()

#         layout_v = QVBoxLayout()

#         self.text_label = QLabel("Введите пароль:", self)
#         font = QFont()
#         font.setPointSize(15)
#         self.text_label.setFont(font)
        
#         layout_v.addStretch()
#         layout_v.addWidget(self.text_label)
#         #layout_v.addStretch()

#         password_layout.addLayout(layout_v)
#         password_layout.addSpacing(10)

#         layout_v = QVBoxLayout()
#         self.password_input = QLineEdit(self)
#         self.password_input.setEchoMode(QLineEdit.Password)
#         self.password_input.mousePressEvent = self.show_touch_keyboard

#         layout_v.addStretch()
#         layout_v.addWidget(self.password_input)
#         layout_v.addSpacing(1)

#         password_layout.addLayout(layout_v)
#         password_layout.setAlignment(Qt.AlignVCenter)
#         password_layout.addStretch()

#         main_layout.addLayout(password_layout)
#         main_layout.addSpacing(20)

#         buttons_layout = QHBoxLayout()

#         layout_v = QVBoxLayout()

#         self.confirm_button = QPushButton("Подтвердить", self)
#         self.confirm_button.setFixedSize(100, 60)
#         self.confirm_button.clicked.connect(self.check_password)

#         layout_v.addStretch()
#         layout_v.addWidget(self.confirm_button)
#         layout_v.addStretch()

#         buttons_layout.addLayout(layout_v)

#         layout_v = QVBoxLayout()

#         self.cancel_button = QPushButton("Отмена", self)
#         self.cancel_button.setFixedSize(100, 60)
#         self.cancel_button.clicked.connect(self.close)

#         layout_v.addStretch()
#         layout_v.addWidget(self.cancel_button)
#         layout_v.addStretch()

#         buttons_layout.addSpacing(30)
#         buttons_layout.addLayout(layout_v)

#         buttons_layout.setAlignment(Qt.AlignCenter)

#         main_layout.addLayout(buttons_layout)
#         main_layout.addSpacing(20)

#         self.setLayout(main_layout)

#         self.keyboard = None

#         self.status_label = QLabel("", self)
#         self.status_label.setAlignment(Qt.AlignCenter)
#         font = QFont()
#         font.setPointSize(15)
#         self.status_label.setFont(font)
#         self.status_label.hide()  # Скрываем изначально

#         # Модифицируем разметку
#         main_layout.insertWidget(3, self.status_label)  # Добавляем статусную метку


#     def close(self):
#         super().close()

#         if self.keyboard is not None:
#             self.keyboard.close()
#             self.keyboard = None
        
#         self.deleteLater()


#     def show_touch_keyboard(self, event):
#         self.password_input.setFocus()
#         self.keyboard = VirtualKeyboard()
#         self.keyboard.input = self.password_input 
#         self.keyboard.enter = self.check_password
#         self.keyboard.show()
#         # self.keyboard.raise_()
#         # self.keyboard.activateWindow()
#         super(QLineEdit, self.password_input).mousePressEvent(event)


#     def check_password(self):
#         password = self.password_input.text()
#         access_granted = False

#         # Скрываем элементы ввода
#         self.password_input.hide()
#         self.text_label.hide()
#         self.confirm_button.hide()
#         self.cancel_button.hide()

#         if password == "innotech":
#             message = "Полный доступ предоставлен!"
#             self.window_manager.admin_function(2)
#             access_granted = True
#         elif password == "2222":
#             message = "Расширенный доступ!"
#             self.window_manager.admin_function(1)
#             access_granted = True
#         elif password == "1111":
#             message = "Стандартный доступ!"
#             self.window_manager.admin_function(0)
#             access_granted = True
#         else:
#             message = "Неверный пароль!"
#             self.password_input.clear()

#         # Показываем статус
#         self.status_label.setText(message)
#         self.status_label.show()

#         if access_granted:
#             # Запускаем таймер на закрытие
#             QTimer.singleShot(2000, self.close)
#         else:
#             # Восстанавливаем интерфейс для повторного ввода
#             QTimer.singleShot(2000, self.reset_ui)

#     def check_password(self):
#         password = self.password_input.text()
#         access_levels = {
#             "innotech": (2, "Полный доступ предоставлен!", "#4CAF50"),
#             "2222": (1, "Расширенный доступ!", "#2196F3"),
#             "1111": (0, "Стандартный доступ!", "#FF9800")
#         }

#         if password in access_levels:
#             level, message, color = access_levels[password]
#             self.handle_success(message, color)
#             self.window_manager.admin_function(level)
            
#         else:
#             self.handle_wrong_password()


#     def handle_success(self, message, color):
#         self.password_input.hide()
#         self.text_label.hide()
#         self.confirm_button.hide()
#         self.cancel_button.hide()
        
#         self.status_label.setText(message)
#         self.status_label.setStyleSheet(f"color: {color};")
#         self.status_label.show()
#         QTimer.singleShot(3000,  self.close)


#     def handle_wrong_password(self):
#         self.password_input.clear()
#         self.status_label.setText("Неверный пароль!")
#         self.status_label.setStyleSheet("color: #F44336;")
#         self.status_label.show()
#         QTimer.singleShot(2000, self.reset_ui)
        
            
#     def reset_ui(self):
#         """Восстанавливает элементы интерфейса"""
#         self.status_label.hide()
#         self.password_input.show()
#         self.text_label.show()
#         self.confirm_button.show()
#         self.cancel_button.show()


# if __name__ == "__main__":
#     import sys
#     app = QApplication(sys.argv)
#     window = PasswordDialog()
#     window.show()
#     sys.exit(app.exec_())


# from PyQt5.QtWidgets import (
#     QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
#     QPushButton, QWidget, QApplication
# )
# from PyQt5.QtGui import QPixmap, QFont
# from PyQt5.QtCore import Qt, QTimer
# from PyQt5.QtGui import QScreen
# from App.Components.keyboard import VirtualKeyboard

# class PasswordDialog(QWidget):
#     def __init__(self, window_manager=None, parent=None):
#         super().__init__(parent)
#         self.window_manager = window_manager
        
#         # Настройка основных параметров окна
#         self.setup_ui()
#         #self.setup_styles()
#         self.update_ui_mode()

#     def setup_ui(self):
#         self.setWindowTitle("Администрация")
#         self.setFixedSize(450, 300)
#         self.setWindowFlags(Qt.FramelessWindowHint)
#         self.center_window()

#         # Главный контейнер
#         self.main_widget = QWidget()
#         self.main_layout = QVBoxLayout(self.main_widget)
#         self.main_layout.setContentsMargins(20, 20, 20, 20)
#         self.main_layout.setSpacing(15)
#         self.setLayout(QVBoxLayout())
#         self.layout().addWidget(self.main_widget)

#         # Создаем оба варианта интерфейса
#         self.setup_login_ui()
#         self.setup_access_ui()

#     # def setup_styles(self):

#     def center_window(self):
#         screen = QApplication.primaryScreen().geometry()
#         x = (screen.width() - self.width()) // 2
#         y = (screen.height() - self.height()) // 2
#         self.move(x, y)

#     def setup_login_ui(self):
#         """Интерфейс для ввода пароля"""
#         # Иконка замка
#         self.lock_icon = QLabel()
#         pixmap = QPixmap("App\Image\icons8-lock-100.png")
#         pixmap = pixmap.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
#         self.lock_icon.setPixmap(pixmap)
#         self.lock_icon.setAlignment(Qt.AlignCenter)

#         # Заголовок
#         self.title_label = QLabel("Вход в систему")
#         self.title_label.setFont(QFont("Arial", 18, QFont.Bold))
#         self.title_label.setAlignment(Qt.AlignCenter)

#         # Поле ввода пароля
#         self.password_input = QLineEdit()
#         self.password_input.setEchoMode(QLineEdit.Password)
#         self.password_input.setPlaceholderText("Введите пароль")
#         self.password_input.mousePressEvent = self.show_touch_keyboard
#         # self.password_input.setStyleSheet("""
#         #     QLineEdit {
#         #         padding: 8px;
#         #         border: 2px solid #cccccc;
#         #         border-radius: 5px;
#         #         font-size: 14px;
#         #     }
#         # """)

#         # Кнопки
#         self.confirm_btn = QPushButton("Подтвердить")
#         self.confirm_btn.setFixedSize(120, 40)
#         self.confirm_btn.clicked.connect(self.check_password)
        
#         self.cancel_btn = QPushButton("Отмена")
#         self.cancel_btn.setFixedSize(120, 40)
#         self.cancel_btn.clicked.connect(self.close)

#         # Собираем layout
#         self.login_layout = QVBoxLayout()
#         self.login_layout.addWidget(self.lock_icon)
#         self.login_layout.addSpacing(10)
#         self.login_layout.addWidget(self.title_label)
#         self.login_layout.addSpacing(20)
#         self.login_layout.addWidget(self.password_input)
        
#         buttons_layout = QHBoxLayout()
#         buttons_layout.addWidget(self.confirm_btn)
#         buttons_layout.addWidget(self.cancel_btn)
        
#         self.login_layout.addLayout(buttons_layout)
#         self.login_layout.addStretch()

#     def setup_access_ui(self):
#         """Интерфейс с информацией о доступе"""
#         self.access_layout = QVBoxLayout()
        
#         # Иконка
#         self.access_icon = QLabel()
#         self.access_icon.setPixmap(QPixmap("App\Image\icons8-lock-100.png"))
#         self.access_icon.setAlignment(Qt.AlignCenter)

#         # Информация о доступе
#         self.access_label = QLabel()
#         self.access_label.setAlignment(Qt.AlignCenter)
#         self.access_label.setFont(QFont("Arial", 16, QFont.Bold))

#         # Кнопка выхода
#         self.logout_btn = QPushButton("Выйти")
#         self.logout_btn.setFixedSize(120, 40)
#         self.logout_btn.clicked.connect(self.logout)

#         self.cancel_btn = QPushButton("Отмена")
#         self.cancel_btn.setFixedSize(120, 40)
#         self.cancel_btn.clicked.connect(self.close)

#         buttons_layout = QHBoxLayout()
#         buttons_layout.addWidget(self.logout_btn)
#         buttons_layout.addWidget(self.cancel_btn)

#         # self.logout_btn.setStyleSheet("""
#         #     QPushButton {
#         #         background-color: #ff4444;
#         #         color: white;
#         #         border-radius: 5px;
#         #     }
#         #     QPushButton:hover {
#         #         background-color: #cc0000;
#         #     }
#         # """)

#         # Собираем layout
#         self.access_layout.addWidget(self.access_icon)
#         self.access_layout.addSpacing(20)
#         self.access_layout.addWidget(self.access_label)
#         self.access_layout.addSpacing(30)
#         self.access_layout.addLayout(buttons_layout)
        
#         self.access_layout.addStretch()

#         # Контейнеры
#         self.login_widget = QWidget()
#         self.login_widget.setLayout(self.login_layout)
        
#         self.access_widget = QWidget()
#         self.access_widget.setLayout(self.access_layout)
        
#         self.main_layout.addWidget(self.login_widget)
#         self.main_layout.addWidget(self.access_widget)

#     def update_ui_mode(self):
#         """Обновление интерфейса в зависимости от уровня доступа"""
#         if self.window_manager and self.window_manager.access_level != -1:
#             self.show_access_mode()
#         else:
#             self.show_login_mode()

#     def show_login_mode(self):
#         """Показать режим входа"""
#         self.login_widget.show()
#         self.access_widget.hide()
#         self.password_input.clear()

#     def show_access_mode(self):
#         """Показать информацию о доступе"""
#         levels = {
#             0: ("Стандартный доступ", "#4CAF50"),
#             1: ("Расширенный доступ", "#2196F3"),
#             2: ("Полный доступ", "#FF9800")
#         }
        
#         level = self.window_manager.access_level
#         text, color = levels.get(level, ("Неизвестный уровень", "#9E9E9E"))
        
#         self.access_label.setText(text)
#         self.access_label.setStyleSheet(f"color: {color};")
#         self.login_widget.hide()
#         self.access_widget.show()

#     def check_password(self):
#         password = self.password_input.text()
#         access_levels = {
#             "innotech": 2,
#             "2222": 1,
#             "1111": 0
#         }

#         if password in access_levels:
#             level = access_levels[password]
#             self.window_manager.admin_function(level)
#             self.show_access_mode()
#             QTimer.singleShot(3000, self.close)
#         else:
#             self.show_error_message()

#     def show_error_message(self):
#         """Показать сообщение об ошибке"""
#         self.password_input.clear()
#         self.password_input.setPlaceholderText("Неверный пароль!")
#         self.password_input.setStyleSheet("border-color: #ff4444;")
#         QTimer.singleShot(2000, self.reset_input_field)

#     def reset_input_field(self):
#         """Сброс поля ввода"""
#         self.password_input.setStyleSheet("")
#         self.password_input.setPlaceholderText("Введите пароль")

#     def logout(self):
#         """Выход из системы"""
#         if self.window_manager:
#             self.window_manager.admin_function(-1)
#         self.update_ui_mode()

#     def show_touch_keyboard(self, event):
#         """Показать виртуальную клавиатуру"""
#         self.keyboard = VirtualKeyboard()
#         self.keyboard.input = self.password_input
#         self.keyboard.enter = self.check_password
#         self.keyboard.show()
#         super(QLineEdit, self.password_input).mousePressEvent(event)

#     def closeEvent(self, event):
#         """Обработка закрытия окна"""
#         if hasattr(self, 'keyboard') and self.keyboard:
#             self.keyboard.close()
#         super().closeEvent(event)

# if __name__ == "__main__":
#     import sys
#     app = QApplication(sys.argv)
    
#     # Для тестирования создаем mock window_manager
#     class MockWindowManager:
#         def __init__(self):
#             self.access_level = None
#         def admin_function(self, level):
#             self.access_level = level
    
#     window = PasswordDialog(window_manager=MockWindowManager())
#     window.show()
#     sys.exit(app.exec_())

# from PyQt5.QtWidgets import (
#     QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
#     QPushButton, QWidget, QApplication
# )
# from PyQt5.QtGui import QPixmap, QFont
# from PyQt5.QtCore import Qt, QTimer
# from App.Components.keyboard import VirtualKeyboard

# class PasswordDialog(QWidget):
#     def __init__(self, window_manager=None, parent=None):
#         super().__init__(parent)
#         self.window_manager = window_manager
#         self.setup_ui()

#         if self.window_manager and self.window_manager.access_level != -1:
#             self.show_access_mode()
#         else:
#             self.show_login_mode()

#     def setup_ui(self):
#         self.setWindowTitle("Администрация")
#         self.setFixedSize(450, 300)
#         self.setWindowFlags(Qt.FramelessWindowHint)
#         self.move(300, 150)

#         main_layout = QVBoxLayout()
#         main_layout.setContentsMargins(20, 20, 20, 20)

#         # Общие элементы
#         self.image_label = QLabel()
#         pixmap = QPixmap("App\Image\icons8-lock-100.png")
#         pixmap = pixmap.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
#         self.image_label.setPixmap(pixmap)
#         self.image_label.setAlignment(Qt.AlignCenter)

#         # Элементы для входа
#         self.title_label = QLabel("Вход в систему")
#         self.title_label.setFont(QFont("Arial", 18))

#         self.password_input = QLineEdit()
#         self.password_input.setEchoMode(QLineEdit.Password)
#         self.password_input.mousePressEvent = self.show_touch_keyboard

#         self.confirm_button = QPushButton("Подтвердить")
#         self.confirm_button.setFixedSize(100, 60)
#         self.confirm_button.clicked.connect(self.check_password)

#         self.cancel_button = QPushButton("Отмена")
#         self.cancel_button.setFixedSize(100, 60)
#         self.cancel_button.clicked.connect(self.close)

#         # Элементы для режима доступа
#         self.access_label = QLabel()
#         self.access_label.setFont(QFont("Arial", 18))

#         self.exit_button = QPushButton("Выйти")
#         self.exit_button.setFixedSize(100, 60)
#         self.exit_button.clicked.connect(self.logout)

#         self.close_button = QPushButton("Отмена")
#         self.close_button.setFixedSize(100, 60)
#         self.close_button.clicked.connect(self.close)

#         # Контейнеры
#         self.login_widget = QWidget()
#         self.access_widget = QWidget()

#         self.setup_login_layout()
#         self.setup_access_layout()

#         main_layout.addWidget(self.login_widget)
#         main_layout.addWidget(self.access_widget)
#         self.setLayout(main_layout)

#     def setup_login_layout(self):
#         layout = QVBoxLayout()

#         # Изображение и текст
#         image_text_layout = QHBoxLayout()
#         image_text_layout.addStretch()

#         layout_v = QVBoxLayout()
#         layout_v.addStretch()
#         layout_v.addWidget(self.image_label)
#         layout_v.addStretch()

#         image_text_layout.addLayout(layout_v)

#         layout_v = QVBoxLayout()
#         layout_v.addStretch()
#         layout_v.addWidget(self.title_label)
#         layout_v.addSpacing(17)

#         image_text_layout.addSpacing(20)
#         image_text_layout.addLayout(layout_v)
#         image_text_layout.addStretch()

#         image_text_layout.setAlignment(Qt.AlignVCenter)
#         layout.addLayout(image_text_layout)
#         layout.addSpacing(10)

#         # Пароль
#         password_layout = QHBoxLayout()
#         password_layout.addStretch()

#         layout_v = QVBoxLayout()
#         self.text_label = QLabel("Введите пароль:", self)
#         font = QFont()
#         font.setPointSize(15)
#         self.text_label.setFont(font)

#         layout_v.addStretch()
#         layout_v.addWidget(self.text_label)

#         password_layout.addLayout(layout_v)
#         password_layout.addSpacing(10)

#         layout_v = QVBoxLayout()
#         layout_v.addStretch()
#         layout_v.addWidget(self.password_input)
#         layout_v.addSpacing(1)

#         password_layout.addLayout(layout_v)
#         password_layout.setAlignment(Qt.AlignVCenter)
#         password_layout.addStretch()

#         layout.addLayout(password_layout)
#         layout.addSpacing(20)

#         # Кнопки
#         buttons_layout = QHBoxLayout()

#         layout_v = QVBoxLayout()
#         layout_v.addStretch()
#         layout_v.addWidget(self.confirm_button)
#         layout_v.addStretch()

#         buttons_layout.addLayout(layout_v)

#         layout_v = QVBoxLayout()
#         layout_v.addStretch()
#         layout_v.addWidget(self.cancel_button)
#         layout_v.addStretch()

#         buttons_layout.addSpacing(30)
#         buttons_layout.addLayout(layout_v)

#         buttons_layout.setAlignment(Qt.AlignCenter)

#         layout.addLayout(buttons_layout)
#         layout.addSpacing(20)

#         self.login_widget.setLayout(layout)

#     def setup_access_layout(self):
#         layout = QVBoxLayout()

#         # Изображение и текст
#         image_text_layout = QHBoxLayout()
#         image_text_layout.addStretch()

#         layout_v = QVBoxLayout()
#         layout_v.addStretch()
#         layout_v.addWidget(self.image_label)
#         layout_v.addStretch()

#         image_text_layout.addLayout(layout_v)

#         layout_v = QVBoxLayout()
#         layout_v.addStretch()
#         layout_v.addWidget(self.access_label)
#         layout_v.addSpacing(17)

#         image_text_layout.addSpacing(20)
#         image_text_layout.addLayout(layout_v)
#         image_text_layout.addStretch()

#         image_text_layout.setAlignment(Qt.AlignVCenter)
#         layout.addLayout(image_text_layout)
#         layout.addSpacing(10)

#         # Кнопки
#         buttons_layout = QHBoxLayout()

#         layout_v = QVBoxLayout()
#         layout_v.addStretch()
#         layout_v.addWidget(self.exit_button)
#         layout_v.addStretch()

#         buttons_layout.addLayout(layout_v)

#         layout_v = QVBoxLayout()
#         layout_v.addStretch()
#         layout_v.addWidget(self.close_button)
#         layout_v.addStretch()

#         buttons_layout.addSpacing(30)
#         buttons_layout.addLayout(layout_v)

#         buttons_layout.setAlignment(Qt.AlignCenter)

#         layout.addLayout(buttons_layout)
#         layout.addSpacing(20)

#         self.access_widget.setLayout(layout)

#     def show_login_mode(self):
#         self.login_widget.show()
#         self.access_widget.hide()
#         self.password_input.clear()

#     def show_access_mode(self):
#         levels = {
#             0: "Стандартный доступ",
#             1: "Расширенный доступ",
#             2: "Полный доступ"
#         }
#         level = self.window_manager.access_level
#         self.access_label.setText(levels.get(level, "Неизвестный уровень"))
#         self.login_widget.hide()
#         self.access_widget.show()

#     def check_password(self):
#         password = self.password_input.text()
#         access_levels = {
#             "innotech": 2,
#             "2222": 1,
#             "1111": 0
#         }

#         if password in access_levels:
#             level = access_levels[password]
#             self.window_manager.admin_function(level)
#             self.show_access_mode()
#             QTimer.singleShot(3000, self.close)
#         else:
#             self.password_input.clear()
#             QTimer.singleShot(2000, self.close)

#     def logout(self):
#         if self.window_manager:
#             self.window_manager.admin_function(-1)
#         self.show_login_mode()

#     def show_touch_keyboard(self, event):
#         self.keyboard = VirtualKeyboard()
#         self.keyboard.input = self.password_input
#         self.keyboard.enter = self.check_password
#         self.keyboard.show()
#         super(QLineEdit, self.password_input).mousePressEvent(event)

#     def closeEvent(self, event):
#         if hasattr(self, 'keyboard') and self.keyboard:
#             self.keyboard.close()
#         super().closeEvent(event)

# if __name__ == "__main__":
#     import sys
#     app = QApplication(sys.argv)
#     window = PasswordDialog()
#     window.show()
#     sys.exit(app.exec_())


from PyQt5.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QDialog, QApplication, QWidget
)
from PyQt5.QtGui import QPixmap, QFont
from PyQt5.QtCore import Qt, QTimer
from App.Components.keyboard import VirtualKeyboard

class PasswordDialog(QWidget):
    def __init__(self, window_manager=None, parent=None):
        super().__init__(parent)
        self.window_manager = window_manager
        self.setup_ui()

        if self.window_manager and self.window_manager.access_level != -1:
            self.show_access_mode()
        else:
            self.show_login_mode()

    def setup_ui(self):
        self.setWindowTitle("Администрация")
        self.setFixedSize(450, 300)
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.move(300, 150)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)

        # Общие элементы
        self.image_label = QLabel()
        pixmap = QPixmap("App\Image\icons8-lock-100.png")
        pixmap = pixmap.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(pixmap)
        self.image_label.setAlignment(Qt.AlignCenter)

        # Элементы для входа
        self.title_label = QLabel("Вход в систему")
        self.title_label.setFont(QFont("Arial", 18))

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.mousePressEvent = self.show_touch_keyboard

        self.confirm_button = QPushButton("Подтвердить")
        self.confirm_button.setFixedSize(100, 60)
        self.confirm_button.clicked.connect(self.check_password)

        self.cancel_button = QPushButton("Отмена")
        self.cancel_button.setFixedSize(100, 60)
        self.cancel_button.clicked.connect(self.close)

        # Элементы для режима доступа
        self.access_label = QLabel()
        self.access_label.setFont(QFont("Arial", 18))

        self.exit_button = QPushButton("Выйти")
        self.exit_button.setFixedSize(100, 60)
        self.exit_button.clicked.connect(self.logout)

        self.close_button = QPushButton("Отмена")
        self.close_button.setFixedSize(100, 60)
        self.close_button.clicked.connect(self.close)

        # Контейнеры
        self.login_widget = QDialog()
        self.access_widget = QDialog()

        self.setup_login_layout()
        self.setup_access_layout()

        main_layout.addWidget(self.login_widget)
        main_layout.addWidget(self.access_widget)
        self.setLayout(main_layout)

    def setup_login_layout(self):
        layout = QVBoxLayout()

        # Изображение и текст
        image_text_layout = QHBoxLayout()
        image_text_layout.addStretch()

        self.image_label2 = QLabel()
        pixmap = QPixmap("App\Image\icons8-lock-100.png")
        pixmap = pixmap.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label2.setPixmap(pixmap)
        self.image_label2.setAlignment(Qt.AlignCenter)

        # Добавляем image_label напрямую в image_text_layout
        image_text_layout.addWidget(self.image_label2)

        layout_v = QVBoxLayout()
        layout_v.addStretch()
        layout_v.addWidget(self.title_label)
        layout_v.addSpacing(17)

        image_text_layout.addSpacing(20)
        image_text_layout.addLayout(layout_v)
        image_text_layout.addStretch()

        image_text_layout.setAlignment(Qt.AlignVCenter)
        layout.addLayout(image_text_layout)
        layout.addSpacing(10)

        # Пароль
        password_layout = QHBoxLayout()
        password_layout.addStretch()

        layout_v = QVBoxLayout()
        self.text_label = QLabel("Введите пароль:", self)
        font = QFont()
        font.setPointSize(15)
        self.text_label.setFont(font)

        layout_v.addStretch()
        layout_v.addWidget(self.text_label)

        password_layout.addLayout(layout_v)
        password_layout.addSpacing(10)

        layout_v = QVBoxLayout()
        layout_v.addStretch()
        layout_v.addWidget(self.password_input)
        layout_v.addSpacing(1)

        password_layout.addLayout(layout_v)
        password_layout.setAlignment(Qt.AlignVCenter)
        password_layout.addStretch()

        layout.addLayout(password_layout)
        layout.addSpacing(20)

        # Кнопки
        buttons_layout = QHBoxLayout()

        layout_v = QVBoxLayout()
        layout_v.addStretch()
        layout_v.addWidget(self.confirm_button)
        layout_v.addStretch()

        buttons_layout.addLayout(layout_v)

        layout_v = QVBoxLayout()
        layout_v.addStretch()
        layout_v.addWidget(self.cancel_button)
        layout_v.addStretch()

        buttons_layout.addSpacing(30)
        buttons_layout.addLayout(layout_v)

        buttons_layout.setAlignment(Qt.AlignCenter)

        layout.addLayout(buttons_layout)
        layout.addSpacing(20)

        self.login_widget.setLayout(layout)

        # Убедимся, что image_label добавлен в компоновку
        if self.login_widget.layout().indexOf(self.image_label) == -1:
            print("image_label не добавлен в компоновку login_widget")
        else:
            print("image_label успешно добавлен в компоновку login_widget")

    def setup_access_layout(self):
        layout = QVBoxLayout()

        # Изображение и текст
        image_text_layout = QHBoxLayout()
        image_text_layout.addStretch()

        layout_v = QVBoxLayout()
        layout_v.addStretch()
        layout_v.addWidget(self.image_label)
        layout_v.addStretch()

        image_text_layout.addLayout(layout_v)

        layout_v = QVBoxLayout()
        layout_v.addStretch()
        layout_v.addWidget(self.access_label)
        layout_v.addSpacing(17)

        image_text_layout.addSpacing(20)
        image_text_layout.addLayout(layout_v)
        image_text_layout.addStretch()

        image_text_layout.setAlignment(Qt.AlignVCenter)
        layout.addLayout(image_text_layout)
        layout.addSpacing(10)

        # Кнопки
        buttons_layout = QHBoxLayout()

        layout_v = QVBoxLayout()
        layout_v.addStretch()
        layout_v.addWidget(self.exit_button)
        layout_v.addStretch()

        buttons_layout.addLayout(layout_v)

        layout_v = QVBoxLayout()
        layout_v.addStretch()
        layout_v.addWidget(self.close_button)
        layout_v.addStretch()

        buttons_layout.addSpacing(30)
        buttons_layout.addLayout(layout_v)

        buttons_layout.setAlignment(Qt.AlignCenter)

        layout.addLayout(buttons_layout)
        layout.addSpacing(20)

        self.access_widget.setLayout(layout)

    def show_login_mode(self):
        self.login_widget.show()
        self.access_widget.hide()
        self.password_input.clear()

    def show_access_mode(self):
        levels = {
            0: "Стандартный доступ",
            1: "Расширенный доступ",
            2: "Полный доступ"
        }
        level = self.window_manager.access_level
        self.access_label.setText(levels.get(level, "Неизвестный уровень"))
        self.login_widget.hide()
        self.access_widget.show()

    def check_password(self):
        password = self.password_input.text()
        access_levels = {
            "innotech": 2,
            "2222": 1,
            "1111": 0
        }

        if password in access_levels:
            level = access_levels[password]
            self.window_manager.admin_function(level)
            self.show_access_mode()
            QTimer.singleShot(3000, self.close)
        else:
            self.password_input.clear()
            QTimer.singleShot(2000, self.close)

    def logout(self):
        if self.window_manager:
            self.window_manager.admin_function(-1)
        self.show_login_mode()

    def show_touch_keyboard(self, event):
        self.keyboard = VirtualKeyboard()
        self.keyboard.input = self.password_input
        self.keyboard.enter = self.check_password
        self.keyboard.show()
        self.keyboard.raise_()
        self.keyboard.activateWindow()
        super(QLineEdit, self.password_input).mousePressEvent(event)

    def closeEvent(self, event):
        if hasattr(self, 'keyboard') and self.keyboard:
            self.keyboard.close()
        super().closeEvent(event)

if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    window = PasswordDialog()
    window.exec_()  # Используем exec_() для модального окна
    sys.exit(app.exec_())
