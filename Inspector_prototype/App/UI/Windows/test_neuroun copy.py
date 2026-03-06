import os
import shutil
import traceback
from PyQt5.QtWidgets import (QWidget, QGridLayout, QHBoxLayout, QVBoxLayout, 
                            QLabel, QCheckBox, QRadioButton, QPushButton, 
                            QComboBox, QMessageBox, QButtonGroup, QSizePolicy,
                            QStyle, QStyleOptionButton, QFrame)
from PyQt5.QtGui import QPixmap, QColor, QPainter, QPen
from PyQt5.QtCore import Qt, QSize, pyqtSignal, QPoint

class ColoredRadioButton(QRadioButton):
    def __init__(self, color, category, parent=None):
        super().__init__(parent)
        self.color = color
        self.category = category
        self.setFixedSize(35, 35)  # Увеличиваем размер для удобства
        self.setStyleSheet("""
            ColoredRadioButton {
                margin: 0;
                padding: 0;
            }
        """)

    def hitButton(self, pos: QPoint) -> bool:
        """Реагирует на клик в любой точке виджета"""
        return self.rect().contains(pos)

    def paintEvent(self, event):
        painter = QPainter(self)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        
        # Рисуем фон
        painter.setBrush(self.color)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(option.rect, 8, 8)
        
        # Рисуем индикатор выбора
        if self.isChecked():
            painter.setBrush(Qt.black)
            painter.drawEllipse(option.rect.center(), 8, 8)  # Увеличиваем точку


class ClickableLabel(QLabel):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._border_color = Qt.transparent
        self.setFrameStyle(QFrame.Box)
        self.setLineWidth(3)

    def set_border_color(self, color):
        self._border_color = color
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setPen(QPen(self._border_color, 7))
        painter.drawRect(self.rect().adjusted(1, 1, -1, -1))
    
    
    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)

def create_handler(chk):
    def handler():
        chk.setChecked(not chk.isChecked())
    return handler


class ImageSortingWidget(QWidget):
    onClose = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image_size = QSize(128, 128)
        self.items_per_page = 12
        self.current_page = 0
        self.total_images = 0
        self.current_folder = ""
        self.image_paths = []
        
        # Настройка папок
        self.base_folder = os.path.normpath("Neuron/Data_image")
        self.all_folder = os.path.join(self.base_folder, "Data_all")
        self.good_folder = os.path.join(self.base_folder, "Data_good")
        self.neutral_folder = os.path.join(self.base_folder, "Data_none")
        self.bad_folder = os.path.join(self.base_folder, "Data_bad")
        
        self.init_ui()
        self.setup_connections()
        self.create_folders()
        self.load_available_folders()


    def init_ui(self):
        # Верхняя панель
        self.folder_combo = QComboBox()
        self.folder_combo.setMinimumSize(120, 50)
        self.clear_btn = QPushButton("Очистить папку")
        self.clear_btn.setMinimumSize(100, 50)

        self.count_label = QLabel("Картинок: 0")

        # Сетка для изображений
        self.grid = QGridLayout()
        self.grid.setSpacing(15)

        self.grid_layout = QVBoxLayout()
        self.grid_layout.addLayout(self.grid)
        self.grid_layout.addStretch()
        self.grid_layout.setContentsMargins(0, 0, 0, 0)

        # Панель навигации
        self.prev_btn = QPushButton("◀")
        self.prev_btn.setMinimumSize(50, 50)
        self.next_btn = QPushButton("▶")
        self.next_btn.setMinimumSize(50, 50)

        button_prev_next_layout = QHBoxLayout()
        button_prev_next_layout.addWidget(self.prev_btn)
        button_prev_next_layout.addStretch()
        button_prev_next_layout.addWidget(self.next_btn)

        self.page_label = QLabel("0/0")

        self.apply_btn = QPushButton("Применить")
        self.apply_btn.setMinimumSize(70, 50)
        self.select_all_btn = QPushButton("Выбрать все")
        self.select_all_btn.setMinimumSize(100, 50)
        self.delete_btn = QPushButton("Удалить")
        self.delete_btn.setMinimumSize(70, 50)
        self.reset_btn = QPushButton("Сбросить")
        self.reset_btn.setMinimumSize(70, 50)

        bottom_left_layout = QVBoxLayout()
        bottom_left_layout.addWidget(self.folder_combo, 1)
        bottom_left_layout.addSpacing(20)
        bottom_left_layout.addWidget(self.page_label)
        bottom_left_layout.addSpacing(20)
        bottom_left_layout.addWidget(self.clear_btn)
        bottom_left_layout.addStretch()

        bottom_right_layout = QVBoxLayout()
        bottom_right_layout.addLayout(button_prev_next_layout)
        bottom_right_layout.addSpacing(20)
        bottom_right_layout.addWidget(self.apply_btn)
        bottom_right_layout.addSpacing(20)
        bottom_right_layout.addWidget(self.reset_btn)
        bottom_right_layout.addSpacing(20)
        bottom_right_layout.addWidget(self.select_all_btn)
        bottom_right_layout.addSpacing(20)
        bottom_right_layout.addWidget(self.delete_btn)
        bottom_right_layout.addStretch()

        # Create containers for the layouts
        bottom_left_container = QWidget()
        bottom_left_container.setLayout(bottom_left_layout)
        bottom_left_container.setFixedWidth(150)  # Set the desired fixed width

        bottom_right_container = QWidget()
        bottom_right_container.setLayout(bottom_right_layout)
        bottom_right_container.setFixedWidth(150)  # Set the desired fixed width

        image_layout = QHBoxLayout()
        image_layout.addWidget(bottom_left_container)
        image_layout.addSpacing(10)
        image_layout.addLayout(self.grid_layout, 1)  # Add stretch factor to center
        image_layout.addSpacing(15)
        image_layout.addWidget(bottom_right_container)

        # Основной лэйаут
        main_layout = QVBoxLayout()
        # main_layout.addLayout(top_layout)
        main_layout.addLayout(image_layout)

        self.setLayout(main_layout)
        self.update_buttons_state()

    def setup_connections(self):
        self.folder_combo.currentTextChanged.connect(self.load_folder)
        self.prev_btn.clicked.connect(self.prev_page)
        self.next_btn.clicked.connect(self.next_page)
        self.clear_btn.clicked.connect(self.confirm_clear_folder)
        self.apply_btn.clicked.connect(self.process_images)
        self.select_all_btn.clicked.connect(self.select_all_on_page)
        self.delete_btn.clicked.connect(self.delete_selected)
        self.reset_btn.clicked.connect(self.reset_current_page_selection)

    def create_folders(self):
        for folder in [self.all_folder, self.good_folder, 
                      self.neutral_folder, self.bad_folder]:
            os.makedirs(folder, exist_ok=True)

    def load_available_folders(self):
        self.folder_combo.clear()
        folders = [
            os.path.basename(self.all_folder),
            os.path.basename(self.good_folder),
            os.path.basename(self.neutral_folder),
            os.path.basename(self.bad_folder)
        ]
        self.folder_combo.addItems(folders)
        self.folder_combo.setCurrentIndex(0)

    def load_folder(self, folder_name):
        """Загрузка папки с дополнительными проверками"""
        if not folder_name:
            QMessageBox.critical(self, "Ошибка", "Не указано имя папки для загрузки")
            return

        full_path = self.get_full_path(folder_name)
        if not full_path:
            QMessageBox.critical(self, "Ошибка", f"Неизвестная папка: {folder_name}")
            return
            
        print(f"Загрузка папки: {full_path}")
        
        try:
            if not os.path.exists(full_path):
                os.makedirs(full_path, exist_ok=True)

            self.current_folder = full_path
            self.image_paths = [
                os.path.join(full_path, f) 
                for f in os.listdir(full_path) 
                if os.path.isfile(os.path.join(full_path, f))
            ]
            self.total_images = len(self.image_paths)
            self.current_page = 0
            self.update_count()
            self.show_page()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка загрузки папки: {str(e)}")

        self.image_paths = [os.path.join(full_path, f) for f in os.listdir(full_path) if os.path.isfile(os.path.join(full_path, f))]
        self.current_page = 0
        self.update_count() 
        self.show_page()


    def get_full_path(self, folder_name):
        return {
            os.path.basename(self.all_folder): self.all_folder,
            os.path.basename(self.good_folder): self.good_folder,
            os.path.basename(self.neutral_folder): self.neutral_folder,
            os.path.basename(self.bad_folder): self.bad_folder
        }.get(folder_name, "")

    def show_page(self):
        # Удаляем старые элементы
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Очистка сетки
        self.clear_grid()

        # Проверка наличия изображений
        if not self.image_paths:
            print("Нет изображений для отображения")
            return

        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        current_images = self.image_paths[start:end]

        for i, path in enumerate(current_images):
            if not os.path.exists(path):
                print(f"Файл не существует: {path}")
                continue

            row = i // 4
            col = i % 4

            container = QWidget()
            container.setFixedSize(self.image_size.width() + 10, self.image_size.height() + 60)

            img_label = ClickableLabel(container)
            img_label.setAlignment(Qt.AlignCenter)
            img_label.setGeometry(10, 10, self.image_size.width(), self.image_size.height())
            
            pixmap = QPixmap(path).scaled(
                self.image_size,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            img_label.setPixmap(pixmap)
            img_label.setProperty("filepath", path)

            # Чекбокс выбора
            select_check = QCheckBox(container)
            select_check.setStyleSheet("""
                QCheckBox {
                    background-color: transparent;
                    border: none;
                }
                QCheckBox::indicator {
                    width: 20px;
                    height: 20px;
                    background-color: transparent;
                    border: 1px solid #666;
                }
                QCheckBox::indicator:checked {
                    background-color: #0078D7;
                }
            """)
            select_check.setFixedSize(50, 50)
            # Позиционирование в правом верхнем углу изображения
            select_check.move(img_label.x() + img_label.width() - 25, img_label.y() - 13)

            select_check.setChecked(True)
            
            # Связь клика по изображению с чекбоксом
            img_label.clicked.connect(create_handler(select_check))

            initial_color = self.get_color_for_category('good')  # По умолчанию
            img_label.set_border_color(initial_color)
            

            # Радио-кнопки
            radio_widget = QWidget(container)
            radio_widget.setGeometry(10, self.image_size.height() + 15, self.image_size.width(), 50)

            good_radio = ColoredRadioButton(QColor('#90EE90'), 'good', radio_widget)
            neutral_radio = ColoredRadioButton(QColor('#FFFACD'), 'neutral', radio_widget)
            bad_radio = ColoredRadioButton(QColor('#FFB6C1'), 'bad', radio_widget)

            radios = [good_radio, neutral_radio, bad_radio]
            
            for radio in radios:
                radio.toggled.connect(
                    lambda checked, r=radio, lbl=img_label: 
                        self.update_border_color(r, lbl) if checked else None
                )
            
            rating_group = QButtonGroup(radio_widget)
            rating_group.addButton(good_radio)
            rating_group.addButton(neutral_radio)
            rating_group.addButton(bad_radio)
            good_radio.setChecked(True)

            radio_layout = QHBoxLayout(radio_widget)
            radio_layout.setContentsMargins(0, 0, 0, 0)  # Убираем отступы
            radio_layout.setSpacing(0)  # Убираем промежутки между кнопками
            
            radio_layout.addWidget(good_radio)
            radio_layout.addStretch()
            radio_layout.addWidget(neutral_radio)
            radio_layout.addStretch()
            radio_layout.addWidget(bad_radio)

            self.grid.addWidget(container, row, col, Qt.AlignCenter)

        self.update_page_label()
        self.update_buttons_state()

    def select_all_on_page(self):
        """Выделить все элементы на текущей странице"""
        for i in range(self.grid.count()):
            container = self.grid.itemAt(i).widget()
            checkbox = container.findChild(QCheckBox)
            if checkbox:
                checkbox.setChecked(True)

    def process_images(self):
        # Подтверждение действия пользователя
        if not self.confirm_action("Применить изменения и переместить выбранные изображения?"):
            return

        # Сбор данных для обработки
        processing_list = []
        try:
            for i in range(self.grid.count()):
                item = self.grid.itemAt(i)
                if not item:
                    continue

                container = item.widget()
                if not container:
                    continue

                # Получаем компоненты
                img_label = container.findChild(QLabel)
                checkbox = container.findChild(QCheckBox)
                radios = container.findChildren(ColoredRadioButton)

                if not all([img_label, checkbox, radios]):
                    continue

                # Проверяем выбран ли чекбокс
                if not checkbox.isChecked():
                    continue

                # Получаем путь к исходному файлу
                src_path = img_label.property("filepath")
                if not src_path or not os.path.exists(src_path):
                    print(f"Файл не найден: {src_path}")
                    continue

                # Определяем целевую папку
                target_folder = None
                for radio in radios:
                    if radio.isChecked():
                        target_folder = {
                            'good': self.good_folder,
                            'neutral': self.neutral_folder,
                            'bad': self.bad_folder
                        }.get(radio.category)
                        break

                if target_folder:
                    processing_list.append((src_path, target_folder))

        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка при сборе данных: {str(e)}")
            return

        # Если нечего обрабатывать
        if not processing_list:
            QMessageBox.information(self, "Информация", "Нет выбранных изображений для обработки")
            return

        # Оптимизация: предрасчет стартовых номеров для папок
        folder_counters = {}
        for _, folder in processing_list:
            if folder not in folder_counters:
                folder_counters[folder] = self.get_next_sequence_number(folder)

        # Перемещение файлов
        success_count = 0
        error_messages = []
        
        for src, folder in processing_list:
            try:
                # Генерируем новое имя
                sequence_num = folder_counters[folder]
                new_filename = f"image_{sequence_num:05d}.jpg"
                dest_path = os.path.join(folder, new_filename)

                # Перемещаем файл
                shutil.move(src, dest_path)
                folder_counters[folder] += 1
                success_count += 1

            except Exception as e:
                error_msg = f"Ошибка перемещения {os.path.basename(src)}: {str(e)}"
                error_messages.append(error_msg)
                print(error_msg)

        # Обновление интерфейса
        self.refresh_interface()

        # Показываем результаты
        result_msg = [
            f"Успешно перемещено: {success_count}",
            f"Ошибок: {len(error_messages)}"
        ]
        
        if error_messages:
            result_msg.append("\nОшибки:\n• " + "\n• ".join(error_messages))
        
        # QMessageBox.information(
        #     self,
        #     "Результат",
        #     "\n".join(result_msg),
        #     QMessageBox.Ok
        # )

    def get_next_sequence_number(self, folder):
        """Возвращает следующий порядковый номер для указанной папки"""
        max_num = 0
        try:
            if os.path.exists(folder):
                # Быстрое сканирование через os.scandir()
                with os.scandir(folder) as it:
                    for entry in it:
                        if entry.is_file() and entry.name.startswith("image_"):
                            try:
                                # Парсинг номера из имени файла
                                num_str = entry.name[6:-4]  # image_00001.jpg -> 00001
                                current_num = int(num_str)
                                if current_num > max_num:
                                    max_num = current_num
                            except:
                                continue
        except Exception as e:
            print(f"Ошибка сканирования папки {folder}: {str(e)}")
        
        return max_num + 1  # Следующий номер

    def refresh_interface(self):
        """Полное обновление интерфейса с принудительной перезагрузкой"""
        
        current_folder = os.path.basename(self.current_folder)
        self.load_folder(current_folder)
        self.current_page = 0
        self.show_page()
        self.update_buttons_state()

    # def move_file(self, src, dest_folder):
    #     try:
    #         src = os.path.abspath(os.path.normpath(src))
    #         dest_folder = os.path.abspath(os.path.normpath(dest_folder))

    #         # Проверка существования исходного файла
    #         if not os.path.exists(src):
    #             print(f"Исходный файл не существует: {src}")
    #             return False

    #         # Создаем папку назначения
    #         os.makedirs(dest_folder, exist_ok=True)

    #         # Формируем конечный путь
    #         dest = os.path.join(dest_folder, os.path.basename(src))

    #         # Проверяем, не пытаемся ли переместить файл в самого себя
    #         if src == dest:
    #             print("Исходный и целевой пути совпадают")
    #             return True

    #         # Удаляем существующий целевой файл только если он отличается от исходного
    #         if os.path.exists(dest) and src != dest:
    #             try:
    #                 os.remove(dest)
    #                 print(f"Удален существующий файл: {dest}")
    #             except Exception as e:
    #                 print(f"Ошибка удаления целевого файла: {str(e)}")
    #                 return False

    #         # Проверяем существование исходного файла перед перемещением
    #         if not os.path.exists(src):
    #             print(f"Исходный файл исчез после проверки: {src}")
    #             return False

    #         # Перемещаем файл
    #         shutil.move(src, dest)
    #         print(f"Успешно перемещено: {src} -> {dest}")
    #         return True

    #     except Exception as e:
    #         print(f"Критическая ошибка перемещения: {traceback.format_exc()}")
    #         return False


    def get_next_number(folder):
        max_num = 0
        for entry in os.scandir(folder):
            if entry.is_file() and entry.name.startswith("image_") and entry.name.endswith(".jpg"):
                try:
                    num = int(entry.name[6:-4])
                    if num > max_num:
                        max_num = num
                except ValueError:
                    continue
        return max_num + 1

    def move_file(self, src, dest_folder):
        try:
            # Получаем следующий номер для целевой папки
            next_num = self.get_next_number(dest_folder)
            
            # Создаем папку если не существует
            os.makedirs(dest_folder, exist_ok=True)
            
            # Генерируем новое имя
            new_name = f"image_{next_num}.jpg"
            dest_path = os.path.join(dest_folder, new_name)
            
            # Перемещаем файл
            shutil.move(src, dest_path)
            return True
            
        except Exception as e:
            print(f"Ошибка перемещения: {str(e)}")
            return False

    def update_buttons_state(self):
        total = len(self.image_paths)
        self.prev_btn.setEnabled(self.current_page > 0)
        self.next_btn.setEnabled((self.current_page + 1) * self.items_per_page < total)


    def update_count(self):
        """Обновление счетчиков изображений и страниц"""
        self.total_images = len(self.image_paths)
        self.count_label.setText(f"Картинок: {self.total_images}")
        
        # Рассчитываем общее количество страниц
        total_pages = ((self.total_images - 1) // self.items_per_page) + 1 if self.total_images > 0 else 0
        current_page = self.current_page + 1 if self.total_images > 0 else 0
        
        # Обновляем метку страниц
        self.page_label.setText(f"Страница {current_page}/{total_pages}")
        self.update_buttons_state()

    def clear_grid(self):
        """Очистка сетки с изображениями"""
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def prev_page(self):
        """Переход на предыдущую страницу"""
        if self.current_page > 0:
            self.current_page -= 1
            self.show_page()

    def next_page(self):
        if (self.current_page + 1) * self.items_per_page < len(self.image_paths):
            self.current_page += 1
            self.show_page()


    def confirm_action(self, message):
        """Подтверждение действия"""
        reply = QMessageBox.question(
            self,
            'Подтверждение',
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        return reply == QMessageBox.Yes

    def confirm_clear_folder(self):
        """Подтверждение очистки папки"""
        if self.confirm_action("Вы уверены, что хотите очистить папку?"):
            self.clear_current_folder()

    def clear_current_folder(self):
        """Очистка текущей папки"""
        if self.current_folder:
            for file in os.listdir(self.current_folder):
                os.remove(os.path.join(self.current_folder, file))
            self.load_folder(os.path.basename(self.current_folder))

    def delete_selected(self):
        """Удаление выбранных изображений"""
        if not self.confirm_action("Удалить выбранные изображения?"):
            return

        deleted = 0
        for i in range(self.grid.count()):
            container = self.grid.itemAt(i).widget()
            if not container:
                continue

            img_label = container.findChild(QLabel)
            select_check = container.findChild(QCheckBox)

            if not all([img_label, select_check]):
                continue

            path = img_label.property("filepath")
            if select_check.isChecked() and path and os.path.exists(path):
                try:
                    os.remove(path)
                    deleted += 1
                except Exception as e:
                    print(f"Ошибка удаления файла: {str(e)}")

        if deleted > 0:
            self.refresh_interface()
            QMessageBox.information(self, "Готово", f"Удалено {deleted} файлов")


    def update_page_label(self):
        """Обновление метки с количеством изображений на странице"""
        start_index = self.current_page * self.items_per_page
        end_index = start_index + self.items_per_page
        current_count = len(self.image_paths[start_index:end_index])
        total_count = len(self.image_paths)
        self.page_label.setText(f"{current_count}/{total_count}")
        self.update_buttons_state()


    def reset_current_page_selection(self):
        """Сбрасывает выбор для всех элементов на текущей странице"""
        for i in range(self.grid.count()):
            item = self.grid.itemAt(i)
            if not item:
                continue
                
            container = item.widget()
            if not container:
                continue

            # Сбрасываем чекбокс
            checkbox = container.findChild(QCheckBox)
            if checkbox:
                checkbox.setChecked(False)

            # Сбрасываем радио-кнопки
            radios = container.findChildren(ColoredRadioButton)
            if radios:
                # Ищем кнопку "good" или используем первую
                good_radio = next((r for r in radios if r.category == "good"), None)
                if good_radio:
                    good_radio.setChecked(True)
                elif radios:
                    radios[0].setChecked(True)

    
    def get_color_for_category(self, category):
        return {
            'good': QColor('#90EE90'),
            'neutral': QColor('#FFFACD'),
            'bad': QColor('#FFB6C1')
        }.get(category, Qt.transparent)


    def update_border_color(self, radio, label):
        label.set_border_color(radio.color)
        label.update()


if __name__ == "__main__":
    import sys
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)
    widget = ImageSortingWidget()
    widget.setWindowTitle("Image Sorter")
    widget.resize(800, 600)
    widget.show()
    sys.exit(app.exec_())