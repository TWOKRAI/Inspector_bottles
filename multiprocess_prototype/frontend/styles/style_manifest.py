"""style_manifest — манифест компонентных QSS-файлов.

Определяет порядок конкатенации QSS-файлов при сборке темы.
Порядок критичен для каскада: primitives → domains.

Публичный API:
    PRIMITIVE_STYLE_FILES   — универсальные Qt-виджеты (фреймворк)
    DOMAIN_STYLE_FILES      — доменные стили прототипа
    STYLE_MANIFEST          — полный список (primitives + domains)
    assemble_qss_by_manifest(theme_dir, manifest) — конкатенация по манифесту
    assemble_domain_qss(theme_dir)                — только доменные стили
"""
from __future__ import annotations

from pathlib import Path

from multiprocess_framework.modules.logger_module.utils import FallbackLogger

_logger = FallbackLogger(__name__)

# Порядок = порядок секций в main.qss (каскад)
PRIMITIVE_STYLE_FILES: list[str] = [
    "components/primitives/chrome_header.qss",
    "components/primitives/buttons.qss",
    "components/primitives/groupbox.qss",
    "components/primitives/tabs.qss",
    "components/primitives/combobox.qss",
    "components/primitives/text_input.qss",
    "components/primitives/spinbox.qss",
    "components/primitives/checkbox.qss",
    "components/primitives/radio.qss",
    "components/primitives/slider.qss",
    "components/primitives/progress.qss",
    "components/primitives/scrollbars.qss",
    "components/primitives/menu.qss",
    "components/primitives/statusbar.qss",
    "components/primitives/tables.qss",
    "components/primitives/splitter.qss",
    "components/primitives/image_slot.qss",
    "components/primitives/cards.qss",
    "components/primitives/note.qss",
    "components/primitives/typography.qss",
    "components/primitives/chrome_misc.qss",
    "components/primitives/displays.qss",
    "components/primitives/toggle.qss",
    "components/primitives/error_banner.qss",
    "components/primitives/validation.qss",
    "components/primitives/error_border.qss",
    "components/primitives/slot_button.qss",
    "components/primitives/auth_readonly.qss",
]

DOMAIN_STYLE_FILES: list[str] = [
    "components/domains/recipes.qss",
    "components/domains/diff_scroll.qss",
    "components/domains/pipeline.qss",
    "components/domains/inspector.qss",
    "components/domains/settings.qss",
    "components/domains/dialogs.qss",
    "components/domains/pagination.qss",
    # sources.qss — заглушка, добавить когда появятся доменные стили
]

STYLE_MANIFEST: list[str] = PRIMITIVE_STYLE_FILES + DOMAIN_STYLE_FILES


def assemble_qss_by_manifest(
    theme_dir: Path, manifest: list[str] | None = None
) -> str:
    """Собрать QSS из файлов по манифесту.

    Args:
        theme_dir: путь к директории темы (напр. themes/innotech_theme/)
        manifest: список относительных путей; None = STYLE_MANIFEST

    Returns:
        Собранный QSS (может быть пустой строкой).
    """
    if manifest is None:
        manifest = STYLE_MANIFEST

    parts: list[str] = []
    for rel_path in manifest:
        file_path = theme_dir / rel_path
        if file_path.is_file():
            try:
                parts.append(file_path.read_text(encoding="utf-8"))
            except OSError as exc:
                _logger.warning("[style_manifest] не удалось прочитать %s: %s", file_path, exc)
        else:
            _logger.warning("[style_manifest] файл не найден: %s", file_path)

    return "\n\n".join(parts)


def assemble_domain_qss(theme_dir: Path) -> str:
    """Собрать только доменные стили (для Этапа B — registry заменит primitives)."""
    return assemble_qss_by_manifest(theme_dir, DOMAIN_STYLE_FILES)
