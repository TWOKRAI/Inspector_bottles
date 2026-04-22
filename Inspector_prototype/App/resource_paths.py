# -*- coding: utf-8 -*-
"""
Пути к ресурсам приложения (изображения, иконки и т.д.).
Все ресурсы хранятся в App/Resources/ — единая точка для дизайна и стилей.
"""
import os


def _app_dir():
    """Корень пакета App (каталог, где лежит main_app.py и т.д.)."""
    return os.path.dirname(os.path.abspath(__file__))


def get_resource_path(*parts: str) -> str:
    """
    Абсолютный путь к файлу в App/Resources/.
    Работает независимо от текущей рабочей директории.

    Примеры:
        get_resource_path('innotech.png')
        get_resource_path('icons', 'icons8-lock-100.png')
    """
    return os.path.join(_app_dir(), 'Resources', *parts)
