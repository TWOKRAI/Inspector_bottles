# -*- coding: utf-8 -*-
"""Поиск и ленивая загрузка ``MvCodeReaderCtrl.dll``.

SDK в репозиторий не кладём (32 МБ вендорских бинарников). Каталог ищется в порядке:
аргумент → env ``MVCR_SDK_DIR`` → каталог плагина установленного IDMVS.
Импорт модуля DLL не трогает: грузит только ``load_library``.

``ctypes.WinDLL`` и ``os.add_dll_directory`` зовутся через атрибуты модулей (не
``from ctypes import WinDLL``) — тесты их подменяют.
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path
from typing import Any

from .errors import SdkNotFoundError

DLL_NAME = "MvCodeReaderCtrl.dll"
ENV_VAR = "MVCR_SDK_DIR"
# Та же DLL с 34 зависимостями, что ставит IDMVS (проверено 2026-09-29).
IDMVS_PLUGIN_DIR: Path = Path(r"C:\Program Files (x86)\IDMVSSTD\Applications\Win64\plugins\mvsidcamctrl")

# Куки add_dll_directory держим живыми, пока жив процесс: каталог нужен DLL на всё время работы.
# Одна кука на каталог — повторные load_library не копят записи пути поиска (ревью 6.1, п.4).
_dll_dir_cookies: dict[str, Any] = {}


def _candidates(explicit: str | Path | None) -> list[Path]:
    """Каталоги в порядке приоритета (IDMVS_PLUGIN_DIR читается в момент вызова)."""
    out: list[Path] = []
    if explicit is not None:
        out.append(Path(explicit))
    env = os.environ.get(ENV_VAR)
    if env:
        out.append(Path(env))
    out.append(Path(IDMVS_PLUGIN_DIR))
    return out


def find_sdk_dir(explicit: str | Path | None = None) -> Path | None:
    """Первый каталог, где лежит ``MvCodeReaderCtrl.dll``; ``None`` — нигде. Без побочных эффектов."""
    for path in _candidates(explicit):
        if (path / DLL_NAME).is_file():
            return path
    return None


def load_library(explicit: str | Path | None = None) -> Any:
    """Загрузить ``MvCodeReaderCtrl.dll`` (``__stdcall`` → ``ctypes.WinDLL``).

    Не Windows или DLL не найдена → ``SdkNotFoundError``, в тексте — все проверенные пути.
    """
    if sys.platform != "win32":
        raise SdkNotFoundError(f"MvCodeReader SDK есть только под Windows (платформа {sys.platform})")
    sdk_dir = find_sdk_dir(explicit)
    if sdk_dir is None:
        checked = "\n".join(f"  - {p}" for p in _candidates(explicit))
        raise SdkNotFoundError(f"{DLL_NAME} не найдена. Проверены каталоги (аргумент, ${ENV_VAR}, IDMVS):\n{checked}")
    # Зависимости DLL лежат рядом с ней: без add_dll_directory WinDLL их не найдёт.
    key = str(sdk_dir)
    added = key not in _dll_dir_cookies
    if added:
        _dll_dir_cookies[key] = os.add_dll_directory(key)
    try:
        return ctypes.WinDLL(str(sdk_dir / DLL_NAME))
    except OSError as exc:
        # DLL на месте, но не грузится: нет зависимости или не та разрядность (ревью 6.1, п.1).
        if added:
            _dll_dir_cookies.pop(key).close()
        raise SdkNotFoundError(
            f"{sdk_dir / DLL_NAME}: файл найден, но не загрузился (нет зависимости рядом или не та разрядность): {exc}"
        ) from exc
