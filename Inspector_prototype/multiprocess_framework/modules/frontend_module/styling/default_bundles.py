# -*- coding: utf-8 -*-
"""
Именованные стили фреймворка: пути к `.qss` рядом с виджетами/компонентами и дефолтные токены.

Регистрация: `register_default_bundles(registry)`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

from frontend_module.styling.registry import NamedStyleRegistry

_FM_ROOT = Path(__file__).resolve().parent.parent

# --- Пути к шаблонам (рядом с соответствующими пакетами) ---

_KEYBOARD_STYLES = _FM_ROOT / "widgets" / "keyboard" / "styles"
_TABS_STYLES = _FM_ROOT / "widgets" / "tabs" / "styles"
_HEADER_STYLES = _FM_ROOT / "widgets" / "header" / "styles"
_COMMON_QSS = _FM_ROOT / "components" / "common" / "qss"
_CHECKBOX_QSS = _FM_ROOT / "components" / "checkbox" / "qss"


@dataclass(frozen=True)
class StyleBundleSpec:
    """Описание одного `style_id` для реестра."""

    style_id: str
    qss_path: Path
    default_tokens: Dict[str, Any]


def iter_bundle_specs() -> Iterator[StyleBundleSpec]:
    """Все встроенные стили `app_*` (порядок стабилен для тестов и доков)."""
    yield StyleBundleSpec(
        style_id="app_keyboard_mini",
        qss_path=_KEYBOARD_STYLES / "keyboard_mini.qss",
        default_tokens={
            "kb_bg": "#f0f0f0",
            "kb_border": "#ccc",
            "kb_radius": "5",
            "kb_padding": "10",
            "kb_font_size": "16",
            "kb_min_w": "50",
            "kb_min_h": "50",
            "kb_hover": "#e0e0e0",
            "kb_pressed": "#d0d0d0",
        },
    )
    yield StyleBundleSpec(
        style_id="app_slider_handle",
        qss_path=_COMMON_QSS / "slider_handle.qss",
        default_tokens={
            "sl_handle_h": "50",
            "sl_handle_w": "25",
            "sl_handle_margin_v": "-15",
            "sl_border_w": "2",
            "sl_border_color": "#4682B4",
            "sl_radius": "7",
            "sl_bg": "gray",
        },
    )
    yield StyleBundleSpec(
        style_id="app_tab_main",
        qss_path=_TABS_STYLES / "tab_main.qss",
        default_tokens={
            "tab_h": "35",
            "tab_w": "95",
            "pane_border": "#ccc",
        },
    )
    yield StyleBundleSpec(
        style_id="app_tab_toggle",
        qss_path=_TABS_STYLES / "tab_toggle.qss",
        default_tokens={
            "tg_bg": "#f0f0f0",
            "tg_hover": "#e0e0e0",
            "tg_pressed": "#d0d0d0",
            "tg_radius": "4",
            "tg_font": "12",
        },
    )
    yield StyleBundleSpec(
        style_id="app_tab_scrollbar",
        qss_path=_TABS_STYLES / "tab_scrollbar.qss",
        default_tokens={"sb_w": "40"},
    )
    yield StyleBundleSpec(
        style_id="app_header_button",
        qss_path=_HEADER_STYLES / "header_button.qss",
        default_tokens={
            "hdr_bg": "transparent",
            "hdr_border": "none",
            "hdr_font": "20px",
            "hdr_font_pressed": "25px",
        },
    )
    yield StyleBundleSpec(
        style_id="app_checkbox_indicator",
        qss_path=_CHECKBOX_QSS / "checkbox_indicator.qss",
        default_tokens={
            "cb_ind_w": "44",
            "cb_ind_h": "44",
        },
    )


def register_default_bundles(registry: NamedStyleRegistry) -> None:
    """Зарегистрировать все встроенные QSS-шаблоны фреймворка."""
    for spec in iter_bundle_specs():
        registry.register_path(
            spec.style_id,
            spec.qss_path,
            default_tokens=dict(spec.default_tokens),
        )


def style_ids_legacy_map() -> Dict[str, Tuple[str, Dict[str, Any]]]:
    """
    Совместимость с прототипом: ``style_id → (имя файла .qss, дефолтные токены)``.
    """
    out: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    for spec in iter_bundle_specs():
        out[spec.style_id] = (spec.qss_path.name, dict(spec.default_tokens))
    return out


def list_bundle_specs() -> List[StyleBundleSpec]:
    return list(iter_bundle_specs())
