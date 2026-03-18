# -*- coding: utf-8 -*-
"""
Central PyQt5 imports for frontend_module.

Requires PyQt5. Fail-fast if not installed.
"""
from PyQt5.QtCore import QObject, Qt, QSize, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import (
    QCursor,
    QDoubleValidator,
    QFont,
    QIcon,
    QImage,
    QIntValidator,
    QPixmap,
)
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

__all__ = [
    "QApplication",
    "QCheckBox",
    "QDoubleValidator",
    "QFrame",
    "QGridLayout",
    "QHeaderView",
    "QHBoxLayout",
    "QIcon",
    "QImage",
    "QIntValidator",
    "QLabel",
    "QLineEdit",
    "QMessageBox",
    "QObject",
    "QPixmap",
    "QPushButton",
    "QScrollArea",
    "QSize",
    "QSizePolicy",
    "QSlider",
    "QTabWidget",
    "QTableWidget",
    "QTableWidgetItem",
    "QThread",
    "QTimer",
    "QVBoxLayout",
    "QWidget",
    "Qt",
    "QCursor",
    "QFont",
    "pyqtSignal",
]
