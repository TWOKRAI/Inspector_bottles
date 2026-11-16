# -*- coding: utf-8 -*-
"""Точка обнаружения плагина `camera_device`: `discover()` ищет файлы `plugin.py`, сам класс — в `plugin_base.py`."""

from .plugin_base import CameraDevicePlugin

__all__ = ["CameraDevicePlugin"]
