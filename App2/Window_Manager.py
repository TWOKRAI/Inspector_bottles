import sys
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QCursor
import qdarkstyle

from App2.Windows.main_window import MainWindow


class WindowManager:
    def __init__(self, queue_manager, name, control_queue):
        """Инициализация менеджера окон.
        
        Args:
            queue_manager: Менеджер очередей для межпроцессного взаимодействия
            name: Имя процесса
            control_queue: Очередь управления
        """
        self.process_name = str(name)
        self.queue_manager = queue_manager
        
        # Инициализация приложения
        self.app = QApplication(sys.argv)
        self.app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
        
        # Словарь для хранения всех окон
        self.windows = {}
        
        # Состояния приложения
        self.fullscreen = False
        self.access_level = 2
        
        # Создание окон и потоков
        self.create_all_windows()
        self.create_thread()
        
        # Настройка начального состояния
        self.set_settings()


    def create_all_windows(self):
        """Создает все окна приложения и добавляет их в словарь окон."""
        # Создаем главное окно
        self.windows['main'] = MainWindow(window_manager=self)
        self.windows['main'].hide()
        
        # Пример добавления других окон (раскомментировать при необходимости)
        # self.windows['loading'] = LoadingWindow(window_manager=self)
        # self.windows['loading'].hide()


    def create_thread(self):
        """Создает и запускает рабочие потоки."""
        # Пример создания потоков (раскомментировать при необходимости)
        # self.bot_thread = BotThread(window_manager=self)
        # self.bot_thread.message.connect(self.show_message)
        # self.bot_thread.start()
        pass


    def set_settings(self):
        # Настройка начального состояния
        self.toggle_cursor_visibility(True)
        self.set_fullscreen(self.fullscreen)
        self.admin_function(self.access_level)


    def set_fullscreen(self, fullscreen):
        """Устанавливает полноэкранный режим для всех окон.
        
        Args:
            fullscreen: True - полноэкранный режим, False - обычный режим
        """
        self.fullscreen = fullscreen
        
        for window_name, window in self.windows.items():
            if window and self._is_window_valid(window):
                try:
                    if fullscreen:
                        window.showFullScreen()
                    else:
                        window.showNormal()
                except RuntimeError:
                    pass


    def toggle_cursor_visibility(self, visible):
        """Переключает видимость курсора для всех окон.
        
        Args:
            visible: True - курсор виден, False - скрыт
        """
        cursor = QCursor(Qt.ArrowCursor) if visible else QCursor(Qt.BlankCursor)
        
        for window in self.windows.values():
            if window and self._is_window_valid(window):
                window.setCursor(cursor)


    def change_language(self, language):
        """Изменяет язык интерфейса для всех окон.
        
        Args:
            language: Код языка (например, 'ru', 'en')
        """
        # TODO: Реализовать смену языка для всех окон
        pass


    def admin_function(self, access_level):
        """Устанавливает уровень доступа и обновляет интерфейс.
        
        Args:
            access_level: Уровень доступа (1 - админ, 2 - пользователь и т.д.)
        """
        self.access_level = access_level
        # Обновляем уровень доступа в главном окне
        if 'main' in self.windows and self.windows['main']:
            self.windows['main'].update_access_level(access_level)

    def close_program(self):
        """Корректно закрывает все окна и освобождает ресурсы."""
        # Закрываем все окна
        self._close_all_windows()
        
        # Останавливаем менеджер очередей
        self.queue_manager.stop_event.set()
        self.queue_manager.memory_manager.close_all()

    def _close_all_windows(self):
        """Закрывает все окна в словаре окон."""
        for window_name, window in list(self.windows.items()):
            if window and self._is_window_valid(window):
                try:
                    window.close()
                    window.deleteLater()
                except RuntimeError:
                    pass


    def _is_window_valid(self, window):
        """Проверяет, является ли окно валидным (не было удалено).
        
        Args:
            window: Объект окна для проверки
            
        Returns:
            bool: True если окно валидно, False если было удалено
        """
        try:
            # Простая проверка - пытаемся получить свойство окна
            _ = window.isVisible()
            return True
        except RuntimeError:
            # Окно было удалено, убираем из словаря
            self.windows[window_name] = None
            return False


    def run(self):
        """Запускает главный цикл приложения."""
        # Показываем окно загрузки если оно есть
        if self.windows.get('loading'):
            self.windows['loading'].show()
        
        sys.exit(self.app.exec_())

    def close_loading_window(self):
        """Закрывает окно загрузки если оно существует."""
        if self.windows.get('loading'):
            if self._is_window_valid(self.windows['loading']):
                self.windows['loading'].close()
                self.windows['loading'].deleteLater()
            self.windows['loading'] = None


    # Вспомогательные методы для работы с конкретными окнами
    def get_window(self, window_name):
        """Возвращает окно по имени.
        
        Args:
            window_name: Имя окна
            
        Returns:
            Объект окна или None если окно не найдено
        """
        return self.windows.get(window_name)


    def show_window(self, window_name):
        """Показывает указанное окно."""
        if self.windows.get(window_name):
            self.windows[window_name].show()


    def hide_window(self, window_name):
        """Скрывает указанное окно."""
        if self.windows.get(window_name):
            self.windows[window_name].hide()