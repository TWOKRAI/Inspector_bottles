"""Секция «Hikvision камера» во вкладке Services.

Повторяет поля SDK App (Services/hikvision_camera/sdk_app/main_window.py):
поиск устройств, открыть/закрыть, старт/стоп захвата, параметры (FPS/exposure/
gain), плюс кнопка запуска оригинального окна SDK App. Изображение выводится в
дисплей активного рецепта (отдельного превью в секции нет).
"""

from .section import build_hikvision_section

__all__ = ["build_hikvision_section"]
