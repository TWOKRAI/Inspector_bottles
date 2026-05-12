"""Регрессионные тесты: manifest-сборка функционально идентична main.qss.

Проверяет что разбиение main.qss на компонентные файлы не потеряло
никакого CSS-контента. Порядок правил не проверяется строго — при
тематическом разбиении файлов блоки перегруппированы логически, но
содержат идентичный набор CSS-правил.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from multiprocess_prototype.frontend.styles.style_manifest import (
    DOMAIN_STYLE_FILES,
    PRIMITIVE_STYLE_FILES,
    STYLE_MANIFEST,
    assemble_qss_by_manifest,
)

# Путь к директории темы относительно этого файла
_THEME_DIR = (
    Path(__file__).resolve().parent.parent
    / "styles"
    / "themes"
    / "innotech_theme"
)

# Заглушки, которые намеренно не включены в manifest
_STUB_FILES = {"sources.qss"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize_qss(text: str) -> str:
    """Нормализовать QSS для сравнения без косметических различий.

    Шаги:
    1. Удалить любые блоки комментариев /* ... */
    2. Убрать trailing whitespace на каждой строке
    3. Схлопнуть 2+ подряд пустых строки в одну
    4. strip() начала и конца
    """
    # Удаляем все комментарии (включая заголовочные блоки и inline)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

    # Убираем trailing whitespace на каждой строке
    lines = [line.rstrip() for line in text.splitlines()]

    # Схлопываем 2+ подряд пустых строки в одну
    result_lines: list[str] = []
    prev_empty = False
    for line in lines:
        is_empty = line == ""
        if is_empty and prev_empty:
            continue
        result_lines.append(line)
        prev_empty = is_empty

    return "\n".join(result_lines).strip()


def _extract_css_rules(qss: str) -> set[str]:
    """Извлечь все CSS-правила как нормализованные строки.

    Каждое правило = нормализованный блок "selector { properties }".
    Комментарии удалены. Whitespace нормализован.
    """
    # Убираем комментарии
    no_comments = re.sub(r"/\*.*?\*/", "", qss, flags=re.DOTALL)

    rules: set[str] = set()
    # Ищем пары (селектор){ тело }
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", no_comments):
        selector = re.sub(r"\s+", " ", match.group(1).strip()).strip()
        body = re.sub(r"\s+", " ", match.group(2).strip()).strip()
        if selector:
            # Нормализуем тело: убираем пробелы вокруг : и ;
            rules.add(f"{selector} {{ {body} }}")
    return rules


def _extract_selectors(qss: str) -> set[str]:
    """Извлечь QSS-селекторы из текста.

    Селектор — строка перед `{`, не являющаяся комментарием.
    Возвращает множество нормализованных строк.
    """
    # Убираем комментарии
    no_comments = re.sub(r"/\*.*?\*/", "", qss, flags=re.DOTALL)

    selectors: set[str] = set()
    # Ищем всё что стоит перед открывающей фигурной скобкой
    for match in re.finditer(r"([^{}]+)\{", no_comments):
        raw = match.group(1).strip()
        if raw:
            # Нормализуем whitespace внутри селектора для устойчивого сравнения
            normalized = re.sub(r"\s+", " ", raw).strip()
            if normalized:
                selectors.add(normalized)
    return selectors


def _full_assembled_qss() -> str:
    """Собрать полный QSS: base.qss + компоненты по манифесту."""
    base_path = _THEME_DIR / "base.qss"
    base_content = base_path.read_text(encoding="utf-8")
    assembled_components = assemble_qss_by_manifest(_THEME_DIR)
    return base_content + "\n\n" + assembled_components


# ---------------------------------------------------------------------------
# Тест 1 — КРИТИЧЕСКИЙ: идентичность CSS-правил (без учёта порядка)
# ---------------------------------------------------------------------------

class TestManifestAssemblyMatchesMain:
    """Сборка по манифесту содержит идентичный набор CSS-правил с main.qss."""

    def test_manifest_assembly_matches_main(self) -> None:
        """Набор CSS-правил assembled QSS совпадает с main.qss.

        Порядок правил не проверяется — при тематическом разбиении на файлы
        логические блоки могут идти в ином порядке, но содержимое идентично.
        """
        main_path = _THEME_DIR / "main.qss"
        original = main_path.read_text(encoding="utf-8")
        full_assembled = _full_assembled_qss()

        original_rules = _extract_css_rules(original)
        assembled_rules = _extract_css_rules(full_assembled)

        missing = original_rules - assembled_rules
        extra = assembled_rules - original_rules

        assert not missing and not extra, (
            f"CSS-правила в assembled QSS не совпадают с main.qss.\n"
            f"Отсутствуют в assembled ({len(missing)}):\n"
            + "\n".join(f"  {r}" for r in sorted(missing)[:10])
            + (f"\n  ... и ещё {len(missing) - 10}" if len(missing) > 10 else "")
            + f"\nЛишние в assembled ({len(extra)}):\n"
            + "\n".join(f"  {r}" for r in sorted(extra)[:10])
            + (f"\n  ... и ещё {len(extra) - 10}" if len(extra) > 10 else "")
        )


# ---------------------------------------------------------------------------
# Тест 2 — Все селекторы из main.qss присутствуют в assembled
# ---------------------------------------------------------------------------

class TestAllSelectorsPresent:
    """Ни один CSS-селектор не был потерян при разбиении."""

    def test_all_selectors_present(self) -> None:
        """Селекторы main.qss ⊆ assembled QSS."""
        main_path = _THEME_DIR / "main.qss"
        original = main_path.read_text(encoding="utf-8")
        full_assembled = _full_assembled_qss()

        original_selectors = _extract_selectors(original)
        assembled_selectors = _extract_selectors(full_assembled)

        missing = original_selectors - assembled_selectors
        assert not missing, (
            f"Следующие селекторы из main.qss отсутствуют в assembled QSS "
            f"({len(missing)} шт.):\n" + "\n".join(sorted(missing))
        )


# ---------------------------------------------------------------------------
# Тест 3 — Нет дублирующихся селекторов между файлами
# ---------------------------------------------------------------------------

class TestNoDuplicateSelectorsAcrossFiles:
    """Один селектор определён только в одном компонентном файле."""

    def test_no_duplicate_selectors_across_files(self) -> None:
        """Ни один селектор не встречается одновременно в двух компонентных файлах.

        base.qss исключён — он намеренно может повторять часть main.qss.
        """
        # Собираем только компонентные файлы (primitives + domains)
        component_files = [
            (_THEME_DIR / rel_path, rel_path)
            for rel_path in STYLE_MANIFEST
        ]

        # Словарь: селектор → список файлов где он встречается
        selector_to_files: dict[str, list[str]] = {}

        for file_path, rel_path in component_files:
            if not file_path.is_file():
                continue
            content = file_path.read_text(encoding="utf-8")
            selectors = _extract_selectors(content)
            for sel in selectors:
                selector_to_files.setdefault(sel, []).append(rel_path)

        duplicates = {
            sel: files
            for sel, files in selector_to_files.items()
            if len(files) > 1
        }

        assert not duplicates, (
            f"Найдены дублирующиеся селекторы в компонентных файлах "
            f"({len(duplicates)} шт.):\n"
            + "\n".join(
                f"  {sel!r}: {files}"
                for sel, files in sorted(duplicates.items())
            )
        )


# ---------------------------------------------------------------------------
# Тест 4 — Все .qss файлы в components/ присутствуют в STYLE_MANIFEST
# ---------------------------------------------------------------------------

class TestAllComponentFilesInManifest:
    """Все компонентные .qss файлы зарегистрированы в STYLE_MANIFEST."""

    def test_all_component_files_in_manifest(self) -> None:
        """Каждый .qss файл в primitives/ и domains/ есть в STYLE_MANIFEST."""
        components_dir = _THEME_DIR / "components"

        # Нормализуем пути в манифесте для сравнения
        manifest_set = {
            Path(rel).name  # имя файла для простоты
            for rel in STYLE_MANIFEST
        }

        missing_from_manifest: list[str] = []
        for qss_file in sorted(components_dir.rglob("*.qss")):
            if qss_file.name in _STUB_FILES:
                # Заглушки намеренно не включены в manifest
                continue
            if qss_file.name not in manifest_set:
                rel = qss_file.relative_to(_THEME_DIR)
                missing_from_manifest.append(str(rel))

        assert not missing_from_manifest, (
            "Следующие .qss файлы не найдены в STYLE_MANIFEST:\n"
            + "\n".join(missing_from_manifest)
        )


# ---------------------------------------------------------------------------
# Тест 5 — Порядок групп: primitives идут раньше domains
# ---------------------------------------------------------------------------

class TestManifestOrderMatchesMain:
    """Primitives-файлы в манифесте предшествуют domain-файлам.

    Внутри каждой группы порядок не проверяется строго — при тематическом
    разбиении блоки могут упорядочиваться по логической принадлежности,
    а не по позиции в main.qss.
    """

    def test_primitives_before_domains_in_manifest(self) -> None:
        """Все PRIMITIVE_STYLE_FILES в манифесте идут раньше DOMAIN_STYLE_FILES."""
        primitive_indices = {f: i for i, f in enumerate(STYLE_MANIFEST) if f in PRIMITIVE_STYLE_FILES}
        domain_indices = {f: i for i, f in enumerate(STYLE_MANIFEST) if f in DOMAIN_STYLE_FILES}

        if not primitive_indices or not domain_indices:
            # Если одна из групп пуста — порядок не нарушен
            return

        max_primitive_idx = max(primitive_indices.values())
        min_domain_idx = min(domain_indices.values())

        assert max_primitive_idx < min_domain_idx, (
            f"Все primitives должны идти раньше всех domains в STYLE_MANIFEST.\n"
            f"Последний primitive: {max(primitive_indices, key=primitive_indices.get)} "
            f"(позиция {max_primitive_idx})\n"
            f"Первый domain: {min(domain_indices, key=domain_indices.get)} "
            f"(позиция {min_domain_idx})"
        )

    def test_manifest_order_preserves_primitive_sequence_in_main(self) -> None:
        """Порядок primitive-файлов в манифесте соответствует их порядку в main.qss."""
        main_path = _THEME_DIR / "main.qss"
        main_content = main_path.read_text(encoding="utf-8")
        main_no_comments = re.sub(r"/\*.*?\*/", "", main_content, flags=re.DOTALL)

        positions: list[tuple[str, int]] = []

        for rel_path in PRIMITIVE_STYLE_FILES:
            file_path = _THEME_DIR / rel_path
            if not file_path.is_file():
                continue
            content = file_path.read_text(encoding="utf-8")

            # Найти первый селектор в файле компонента
            no_comments = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
            match = re.search(r"([^{}]+)\{", no_comments)
            if match is None:
                continue

            first_selector = re.sub(r"\s+", " ", match.group(1).strip()).strip()
            if not first_selector:
                continue

            # Найти позицию этого селектора в main.qss
            pos_match = re.search(
                re.escape(first_selector) + r"\s*\{",
                main_no_comments,
            )
            if pos_match is None:
                # Если первый точный селектор не найден — пропускаем
                continue

            positions.append((rel_path, pos_match.start()))

        # Проверяем что позиции строго возрастают
        for i in range(1, len(positions)):
            prev_file, prev_pos = positions[i - 1]
            curr_file, curr_pos = positions[i]
            assert curr_pos > prev_pos, (
                f"Нарушен порядок primitive-файлов в манифесте:\n"
                f"  '{curr_file}' (позиция в main.qss: {curr_pos})\n"
                f"  должен идти ПОСЛЕ '{prev_file}' (позиция: {prev_pos})\n"
                f"Исправьте порядок в PRIMITIVE_STYLE_FILES."
            )


# ---------------------------------------------------------------------------
# Тест 6 — Все @переменные из main.qss сохранены
# ---------------------------------------------------------------------------

class TestAllVariablesPreserved:
    """Все CSS-переменные (@var) из main.qss присутствуют в assembled QSS."""

    def test_all_variables_preserved(self) -> None:
        """Множества @переменных из main.qss и assembled QSS совпадают."""
        main_path = _THEME_DIR / "main.qss"
        original = main_path.read_text(encoding="utf-8")
        full_assembled = _full_assembled_qss()

        original_vars = set(re.findall(r"@(\w+)", original))
        assembled_vars = set(re.findall(r"@(\w+)", full_assembled))

        missing = original_vars - assembled_vars
        assert not missing, (
            f"Следующие @переменные из main.qss отсутствуют в assembled QSS "
            f"({len(missing)} шт.): {sorted(missing)}"
        )

        extra = assembled_vars - original_vars
        assert not extra, (
            f"Следующие @переменные есть в assembled QSS, но отсутствуют в main.qss "
            f"({len(extra)} шт.): {sorted(extra)}"
        )
