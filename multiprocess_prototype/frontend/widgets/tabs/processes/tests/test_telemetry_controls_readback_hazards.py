# -*- coding: utf-8 -*-
"""Авторские hazard-тесты readback-каталога секции телеметрии (Task 4.2).

Дополняют независимую приёмку (``test_telemetry_controls_readback_catalogue.py``,
писалась до реализации, слепо) — не заменяют её. Здесь то, что видно только со
стороны механизма :meth:`TelemetryControlsSection.apply_readback`:

* readback приходит НЕ на конструктор, а ПОЗЖЕ, во время жизни секции (живой
  случай — ``TelemetryPoller`` отвечает уже после того, как карточка процесса
  открыта) — метод обязан ДОБАВИТЬ строку, а не тронуть уже построенные (иначе
  повторный/поздний readback тихо сбрасывал бы чекбокс/частоту, которые
  оператор уже выставил руками);
* readback приходит малформленным (не dict / без ключа / не-list / список с
  мусором) — секция не имеет права упасть (правило 5 CLAUDE.md: панель не
  падает из-за читалки);
* readback приходит дважды с одним и тем же именем — строка не должна
  задваиваться (грид индексируется вручную ``_next_row``, и это ровно то место,
  где легко словить дублирующийся/съехавший row-индекс);
* readback никогда не приходит («процесс не отвечает») — каталог обязан
  остаться РОВНО импортным фолбэком сколько угодно тиков подряд.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QLabel

from multiprocess_prototype.frontend.widgets.tabs.processes._telemetry_controls import (
    TelemetryControlsSection,
)


def _label_texts(section: TelemetryControlsSection) -> set[str]:
    return {lbl.text() for lbl in section.findChildren(QLabel)}


class TestLateArrivalPreservesExistingRowState:
    def test_apply_readback_after_construction_adds_row_without_resetting_existing_ones(self, qtbot) -> None:
        section = TelemetryControlsSection("app_proc", ["fps"], readback=None)
        qtbot.addWidget(section)

        # Оператор уже потрогал строку fps: выключил публикацию и поднял частоту.
        fps_row = section._rows["fps"]
        fps_row.enable.setChecked(False)
        fps_row.interval.setValue(12.5)

        # Поздний readback (пришёл уже ПОСЛЕ открытия карточки — живой случай).
        section.apply_readback({"gated_metrics": ["fps", "letter_confidence"]})

        assert "letter_confidence" in _label_texts(section)
        # Состояние строки fps НЕ тронуто повторным приходом readback.
        assert fps_row.enable.isChecked() is False
        assert fps_row.interval.value() == pytest.approx(12.5)

    def test_apply_readback_twice_with_same_metric_does_not_duplicate_the_row(self, qtbot) -> None:
        section = TelemetryControlsSection("app_proc", ["fps"], readback=None)
        qtbot.addWidget(section)

        section.apply_readback({"gated_metrics": ["letter_confidence"]})
        section.apply_readback({"gated_metrics": ["letter_confidence"]})  # тот же ответ второй раз

        texts = [lbl.text() for lbl in section.findChildren(QLabel)]
        assert texts.count("letter_confidence") == 1, "повторный readback задвоил строку метрики"
        assert len(section._rows) == 2  # fps + letter_confidence, не 3


class TestMalformedReadbackIsASilentNoOp:
    @pytest.mark.parametrize(
        "readback",
        [
            None,
            "not-a-dict",
            42,
            [],
            {},
            {"gated_metrics": "not-a-list"},
            {"gated_metrics": None},
            {"gated_metrics": {}},
            {"gated_metrics": [None, 5, "", ""]},
        ],
        ids=[
            "none",
            "string",
            "int",
            "bare-list",
            "empty-dict",
            "string-value",
            "none-value",
            "dict-value",
            "only-invalid-entries",
        ],
    )
    def test_apply_readback_malformed_forms_add_no_rows_and_do_not_raise(self, qtbot, readback) -> None:
        section = TelemetryControlsSection("app_proc", ["fps"], readback=None)
        qtbot.addWidget(section)

        section.apply_readback(readback)  # не должно бросить исключение

        assert set(section._rows) == {"fps"}

    def test_apply_readback_filters_invalid_entries_but_keeps_the_valid_one(self, qtbot) -> None:
        section = TelemetryControlsSection("app_proc", ["fps"], readback=None)
        qtbot.addWidget(section)

        section.apply_readback({"gated_metrics": [None, 5, "", "letter_confidence"]})

        assert set(section._rows) == {"fps", "letter_confidence"}


class TestProcessNeverAnswers:
    def test_catalogue_stays_the_import_fallback_across_many_empty_polls(self, qtbot) -> None:
        """Живой аналог: поллер тикает раз за разом, процесс не отвечает
        (``response.get("success")`` вообще не бывает True) — владелец секции
        никогда не зовёт ``apply_readback`` с непустым readback. Каталог не
        имеет права «сам» когда-нибудь дополниться."""
        section = TelemetryControlsSection("app_proc", ["fps", "latency_ms"], readback=None)
        qtbot.addWidget(section)

        for _ in range(50):  # 50 «тиков» без ответа
            section.apply_readback(None)

        assert set(section._rows) == {"fps", "latency_ms"}
