# -*- coding: utf-8 -*-
"""Приёмочные тесты (независимый тестер, ДО реализации) — Task 4.2 плана
`observation-port`: «Строки пульта GUI — из readback, не из импорта».

Резидуал назван вслух в `_telemetry_controls.py:11-15`: каталог метрик, из
которого строится секция телеметрии карточки процесса, сегодня наполняется
ИМПОРТОМ производителя — `_panels.py` зовёт `list(gated_metrics())` в самом
GUI-процессе. Метрика, объявленная ТОЛЬКО в бэкенд-процессе (плагин
приложения, который GUI не импортирует), в этот локальный список никогда не
попадает — и строки пульта не получает НИКОГДА, сколько бы тиков ни прошло.

Task 4.2 обязывает строить каталог из readback-дороги, названной там же:
`introspect_telemetry(process).gated_metrics` — ответ команды
`_cmd_introspect_telemetry` (`builtin_commands.py:1215`), несущий ЛОКАЛЬНЫЙ
(полный) реестр объявленных метрик бэкенд-процесса. Импортный список остаётся
фолбэком ДО первого такого ответа — иначе холодный GUI сразу после старта
показывал бы пустой пульт.

**Сиденье контракта, зафиксированное ЭТИМ тестом.** Интерфейса (interface.py)
для этого модуля нет, и реализации Task 4.2 ещё нет — поэтому тестер фиксирует
форму шва сам, а не угадывает чужое имя:

    TelemetryControlsSection(process_name, metrics, *, ..., readback=None)

`metrics` — прежний позиционный параметр (импортный каталог, фолбэк).
`readback` — новый keyword, форма как у секции ответа `_cmd_introspect_telemetry`:
``{"gated_metrics": [...]}``. Когда `readback` содержит непустой `gated_metrics`,
строки пульта строятся из НЕГО; когда `readback` отсутствует (`None`) —
используется `metrics`, как сегодня.

Если реализация выберет другую форму шва (например, отдельный classmethod,
или правку исключительно в `_panels.py` без нового параметра секции) — падение
пойдёт по `TypeError`/`AttributeError` на несуществующем параметре, а не по
`AssertionError` с «неверным значением». Это ожидаемо и разобрано в отчёте
тестера («где критерий оказался неоднозначным»): наблюдаемый эффект (какие
строки видны, с каким текстом) — это и есть проверяемый критерий; конкретное
имя параметра — лишь то, как тестер решил его вызвать, чтобы вообще что-то
проверить.

**Недостижимо на этом стенде** (см. отчёт тестера полностью): реальная IPC до
второго процесса, реальный вызов `introspect_telemetry` через RequestRunner/
command-bridge, реальный бэкенд-плагин, объявляющий метрику. Здесь `readback`
— обычный dict, подставленный тестом напрямую; готовность механизма СОБРАТЬ
такой dict с живого бэкенда не проверяется вовсе.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel

from multiprocess_prototype.frontend.widgets.tabs.processes._telemetry_controls import (
    TelemetryControlsSection,
)


def _label_texts(section: TelemetryControlsSection) -> set[str]:
    """Тексты всех QLabel секции — наблюдаемый эффект (какие строки видны),
    а не имя внутреннего метода/атрибута, которым они были построены."""
    return {lbl.text() for lbl in section.findChildren(QLabel)}


class TestBackendOnlyMetricRowFromReadback:
    """Критерий Task 4.2 дословно: «до правки строки нет — резидуал
    воспроизведён; после — есть; строки метрик фреймворка целы»."""

    def test_metric_known_only_via_readback_gets_a_row_but_not_without_it(self, qtbot) -> None:
        import_only_catalogue = ["fps"]  # то, что импортируется В GUI-процессе
        readback = {"gated_metrics": ["fps", "letter_confidence"]}  # ответ БЭКЕНД-процесса

        # ДО: холодный GUI / процесс ещё не ответил — только импортный каталог.
        # Резидуал воспроизведён: метрики backend-only плагина в пульте нет.
        cold = TelemetryControlsSection("app_proc", import_only_catalogue, readback=None)
        qtbot.addWidget(cold)
        assert "letter_confidence" not in _label_texts(cold)
        assert "fps" in _label_texts(cold)  # якорь существования в ТОМ ЖЕ тесте

        # ПОСЛЕ: readback пришёл — backend-only метрика получает строку.
        warm = TelemetryControlsSection("app_proc", import_only_catalogue, readback=readback)
        qtbot.addWidget(warm)
        assert "letter_confidence" in _label_texts(warm)
        # Строки метрик фреймворка целы (критерий явно требует это ОТДЕЛЬНО).
        assert "fps" in _label_texts(warm)

    def test_readback_content_drives_the_row_not_a_coincidental_union(self, qtbot) -> None:
        """Строка приходит ИЗ readback, а не потому, что имя случайно совпало
        с чем-то в объединении «импорт + readback».

        `readback` здесь вообще не содержит `fps` — то есть пересечения с
        импортным списком нет. Если бы имплементация игнорировала параметр
        `readback` целиком (принимала, но не использовала), backend-only имя
        не появилось бы никогда — этот сценарий уже отличим от предыдущего
        теста тем, что здесь нет совпадающих имён вовсе, которые могли бы
        замаскировать такую ошибку через объединение множеств.
        """
        readback = {"gated_metrics": ["letter_confidence"]}  # backend-only, fps здесь нет вовсе
        section = TelemetryControlsSection("app_proc", ["fps"], readback=readback)
        qtbot.addWidget(section)
        assert "letter_confidence" in _label_texts(section)


class TestImportCatalogueIsAFallback:
    """Импортный каталог — фолбэк ДО первого ответа процесса: холодный GUI
    не остаётся пустым, пока readback не пришёл."""

    def test_cold_gui_still_shows_framework_metric_rows(self, qtbot) -> None:
        section = TelemetryControlsSection("app_proc", ["fps", "latency_ms"], readback=None)
        qtbot.addWidget(section)
        texts = _label_texts(section)
        assert "fps" in texts
        assert "latency_ms" in texts
