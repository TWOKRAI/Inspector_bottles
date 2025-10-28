from PyQt5.QtWidgets import QMainWindow, QWidget
from PyQt5.QtGui import QCursor

from .base_window import IWindow


class QtWindowAdapter(IWindow):
    """Адаптер для окон PyQt5, реализующий общий интерфейс"""
    
    def __init__(self, qt_window: QWidget):
        self._qt_window = qt_window
    
    def show(self) -> None:
        self._qt_window.show()
    
    def hide(self) -> None:
        self._qt_window.hide()
    
    def close(self) -> None:
        self._qt_window.close()
    
    def showFullScreen(self) -> None:
        self._qt_window.showFullScreen()
    
    def showNormal(self) -> None:
        self._qt_window.showNormal()
    
    def setCursor(self, cursor) -> None:
        self._qt_window.setCursor(cursor)
    
    def isVisible(self) -> bool:
        return self._qt_window.isVisible()
    
    def winId(self) -> int:
        return self._qt_window.winId()
    
    def update_access_level(self, access_level: int) -> None:
        # Если у окна есть такой метод, вызываем его
        if hasattr(self._qt_window, 'update_access_level'):
            self._qt_window.update_access_level(access_level)


class MainWindowAdapter(QtWindowAdapter):
    """Специализированный адаптер для главного окна"""
    
    def __init__(self, main_window):
        super().__init__(main_window)
        self._main_window = main_window
    
    # Можно добавить специфичные для главного окна методы
    def some_special_method(self):
        if hasattr(self._main_window, 'some_special_method'):
            return self._main_window.some_special_method()