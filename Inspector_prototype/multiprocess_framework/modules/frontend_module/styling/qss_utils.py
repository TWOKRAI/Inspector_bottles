# -*- coding: utf-8 -*-
"""
Чистые функции для QSS: шаблон, слои токенов, загрузка файла.

Без импорта Qt — удобно для unit-тестов без GUI.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union

PathLike = Union[str, Path]


def merge_token_layers(*layers: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """
    Плоское слияние слоёв слева направо: правый перекрывает левый.

    Типичный порядок для UI:
    1. глобальные токены сессии (палитра, шрифты приложения);
    2. дефолты именованного стиля (`style_id` в реестре);
    3. слой виджета-оболочки (контейнер, вкладка, панель);
    4. слой компонента (конкретный контрол).

    None-аргументы пропускаются.
    """
    out: Dict[str, Any] = {}
    for layer in layers:
        if layer:
            out.update(dict(layer))
    return out


def render_qss(template: str, tokens: Mapping[str, Any]) -> str:
    """
    Подстановка плейсхолдеров {key} в шаблоне QSS.

    Отсутствующий ключ: плейсхолдер остаётся в строке (явно видно в UI при отладке).
    Значения приводятся к str().
    """
    if not template:
        return ""
    result = template
    for key, value in tokens.items():
        result = result.replace(f"{{{key}}}", str(value))
    return result


def load_qss_file(path: PathLike, *, encoding: str = "utf-8") -> str:
    """Прочитать файл QSS. При ошибке — пустая строка."""
    try:
        p = Path(path)
        return p.read_text(encoding=encoding)
    except OSError:
        return ""


def minimal_fallback_qss() -> str:
    """Минимальный безопасный QSS при сбое загрузки шаблона."""
    return """
        QWidget {
            font-family: Arial, sans-serif;
            font-size: 12px;
            color: #333333;
        }
    """


def resolve_template(
    *,
    inline_template: Optional[str] = None,
    template_path: Optional[PathLike] = None,
) -> str:
    """Приоритет: inline, иначе файл, иначе пустая строка."""
    if inline_template:
        return inline_template
    if template_path:
        return load_qss_file(template_path)
    return ""
