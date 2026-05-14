"""Тесты для scripts/sync/adr_toc.py.

Проверяют:
- scan_global_adrs: is_obsolete=True и superseded_by при соответствующих строках.
- render_toc: сортировка по num вне зависимости от порядка входа.
- Обнаружение дрифта: добавление нового ADR в тело приводит к разным render_toc.
"""

from __future__ import annotations


from scripts.sync.adr_toc import GlobalAdr, render_toc, scan_global_adrs


# ---------------------------------------------------------------------------
# Тест 1: scan_global_adrs — is_obsolete и superseded_by
# ---------------------------------------------------------------------------


def test_scan_with_obsolete(tmp_path):
    """Текст с '- Статус: устарело' → is_obsolete=True; '- Суперсед: **ADR-200**' → superseded_by=200."""
    decisions = tmp_path / "DECISIONS.md"
    decisions.write_text(
        "# ADR\n\n"
        "## ADR-100: Первое решение\n\n"
        "- Статус: принято\n\n"
        "## ADR-200: Устаревшее решение\n\n"
        "- Статус: устарело\n"
        "- Суперсед: **ADR-100**\n\n",
        encoding="utf-8",
    )

    adrs = scan_global_adrs(decisions)

    assert len(adrs) == 2, f"Ожидалось 2 ADR, получено {len(adrs)}"

    adr_100 = next((a for a in adrs if a.num == 100), None)
    adr_200 = next((a for a in adrs if a.num == 200), None)

    assert adr_100 is not None, "ADR-100 должен быть распознан"
    assert not adr_100.is_obsolete, "ADR-100 не должен быть устаревшим"
    assert adr_100.superseded_by is None, "ADR-100 не должен иметь superseded_by"

    assert adr_200 is not None, "ADR-200 должен быть распознан"
    assert adr_200.is_obsolete, "ADR-200 должен быть помечен как устаревший"
    assert adr_200.superseded_by == 100, f"Ожидался superseded_by=100, получен {adr_200.superseded_by}"


# ---------------------------------------------------------------------------
# Тест 2: render_toc сортирует по num
# ---------------------------------------------------------------------------


def test_sort_by_number(tmp_path):
    """render_toc сортирует по num вне зависимости от порядка во входе."""
    adrs = [
        GlobalAdr(num=10, title="Десятое", is_obsolete=False, superseded_by=None),
        GlobalAdr(num=2, title="Второе", is_obsolete=False, superseded_by=None),
        GlobalAdr(num=5, title="Пятое", is_obsolete=False, superseded_by=None),
    ]

    toc = render_toc(adrs)
    lines = [line for line in toc.split("\n") if line.strip()]

    # Извлекаем номера из строк
    nums_in_order = []
    for line in lines:
        if "ADR-002" in line:
            nums_in_order.append(2)
        elif "ADR-005" in line:
            nums_in_order.append(5)
        elif "ADR-010" in line:
            nums_in_order.append(10)

    assert nums_in_order == [2, 5, 10], f"Ожидался порядок [2, 5, 10], получен {nums_in_order}"


# ---------------------------------------------------------------------------
# Тест 3: добавление нового ADR → render_toc даёт другой результат
# ---------------------------------------------------------------------------


def test_drift_on_new_adr(tmp_path):
    """Добавление нового ADR в тело → render_toc возвращает другой результат (дрифт)."""
    # Состояние «до»: только ADR-100
    before_adrs = [
        GlobalAdr(num=100, title="Старое", is_obsolete=False, superseded_by=None),
    ]
    toc_before = render_toc(before_adrs)

    # Состояние «после»: добавили ADR-119
    decisions = tmp_path / "DECISIONS.md"
    decisions.write_text(
        "# ADR\n\n## ADR-100: Старое\n\n- Статус: принято\n\n## ADR-119: Foo\n\n- Статус: принято\n\n",
        encoding="utf-8",
    )
    after_adrs = scan_global_adrs(decisions)
    toc_after = render_toc(after_adrs)

    assert toc_before != toc_after, "TOC должен измениться после добавления нового ADR"
    assert "ADR-119" in toc_after, "Новый ADR-119 должен присутствовать в обновлённом TOC"
    assert "ADR-119" not in toc_before, "ADR-119 не должен быть в старом TOC"
