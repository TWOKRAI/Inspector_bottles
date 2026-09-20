# -*- coding: utf-8 -*-
"""Ф3, Task 3.8: голос фоновой уборки истории наблюдений (независимый приёмочный набор).

Сегодня :func:`sweep_observability_history` работает и молчит — отчёт уборки
(``{"by_age", "by_rows", "remaining"}``) выбрасывается, единственный голос
процесса — WARNING при отказе БД. Эти тесты фиксируют контракт ДО того, как
голос появится:

  * уборка, снявшая N > 0 строк, — ровно один INFO с видимыми числами
    (``by_age``/``by_rows``), а не буквальным текстом;
  * уборка, снявшая 0 строк, НЕ говорит на INFO (иначе восемь процессов ×
    раз в 5 минут = болтовня на пустом месте);
  * но «снято 0» всё равно сказано — на DEBUG, с нулём в строке: молчание и
    ноль различимы;
  * пропущенный такт (срок не наступил ИЛИ стора нет) не говорит вовсе — ни
    INFO, ни DEBUG — это и есть граница «не убирали» vs «убрали ноль»;
  * отказ БД по-прежнему даёт ровно один WARNING и не даёт голоса об успехе;
  * голос не подменяет возвращаемое значение — отчёт (или ``None``) доезжает
    до вызывающего в прежнем виде.

Двойник ``svc`` несёт ``_log_info``/``_log_debug``/``_log_warning`` — тот же
приём, что уже применён в ``test_observability_history_policy.py``: голос
процесса устроен как лесенка кандидатов-методов (см. ``_SAY_FALLBACKS`` /
``process_say`` в ``observability_wiring.py``), поэтому наблюдаемый эффект —
что легло в какой список двойника, а не имя внутренней функции, которая туда
писала.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from multiprocess_framework.modules.process_module.managers.observability_wiring import (
    sweep_observability_history,
)


class _Svc:
    """Процесс с секцией наблюдаемости и тремя независимыми журналами голоса."""

    def __init__(self) -> None:
        self.name = "camera_0"
        self.info_messages: list = []
        self.debug_messages: list = []
        self.warnings: list = []
        self._observability_store: Optional[_Store] = None
        self._observability_history_policy: Optional[Dict[str, Any]] = None

    def get_config(self, key: str, default: Any = None) -> Any:
        return default

    def _log_warning(self, message: str, module: Optional[str] = None) -> None:
        self.warnings.append(str(message))

    def _log_info(self, message: str, module: Optional[str] = None) -> None:
        self.info_messages.append(str(message))

    def _log_debug(self, message: str, module: Optional[str] = None) -> None:
        self.debug_messages.append(str(message))


class _Store:
    """Дубль ``ObservabilityStore`` — ``purge()`` отдаёт заготовленный отчёт или падает."""

    def __init__(self, report: Optional[Dict[str, int]] = None, fail: bool = False) -> None:
        self.calls: list = []
        self._fail = fail
        self._report = dict(report) if report is not None else {"by_age": 0, "by_rows": 0, "remaining": 0}

    def purge(self, *, max_rows: Any = None, max_age_sec: Any = None, now: Any = None) -> Dict[str, int]:
        self.calls.append((max_rows, max_age_sec))
        if self._fail:
            raise RuntimeError("БД закрыта")
        return dict(self._report)


def _wired_svc(report: Dict[str, int]) -> _Svc:
    svc = _Svc()
    svc._observability_store = _Store(report=report)
    svc._observability_history_policy = {"max_rows": 7, "max_age_sec": 42.0, "purge_interval_sec": 100.0}
    return svc


class TestNonZeroSweepVoicesInfoWithNumbers:
    """Критерий 1: N > 0 → ровно один INFO, числа by_age/by_rows видны по существу."""

    def test_info_message_carries_by_age_and_by_rows_numbers(self) -> None:
        svc = _wired_svc({"by_age": 17, "by_rows": 42, "remaining": 986})

        sweep_observability_history(svc, now=1000.0)

        assert len(svc.info_messages) == 1, "уборка, снявшая строки, обязана сказать ровно один раз на INFO"
        message = svc.info_messages[0]
        assert "17" in message, "число by_age обязано быть видно оператору"
        assert "42" in message, "число by_rows обязано быть видно оператору"

    def test_non_zero_sweep_does_not_also_voice_debug(self) -> None:
        svc = _wired_svc({"by_age": 17, "by_rows": 42, "remaining": 986})

        sweep_observability_history(svc, now=1000.0)

        assert svc.debug_messages == [], "успешная уборка не имеет права говорить дважды на двух уровнях"
        assert svc.warnings == []


class TestZeroSweepStaysQuietOnInfo:
    """Критерий 2: N == 0 → НЕ говорит на INFO (иначе болтовня каждые 5 минут на восьми процессах)."""

    def test_zero_removed_produces_no_info_voice(self) -> None:
        svc = _wired_svc({"by_age": 0, "by_rows": 0, "remaining": 17})

        sweep_observability_history(svc, now=1000.0)

        assert svc.info_messages == []


class TestZeroSweepIsStillVoicedOnDebug:
    """Критерий 3: «снято 0» — не молчание, а факт на DEBUG, с нулём в строке."""

    def test_zero_removed_produces_exactly_one_debug_message_with_zero(self) -> None:
        svc = _wired_svc({"by_age": 0, "by_rows": 0, "remaining": 17})

        sweep_observability_history(svc, now=1000.0)

        assert len(svc.debug_messages) == 1, "«отработали и резать было нечего» обязано быть сказано ровно раз"
        assert "0" in svc.debug_messages[0], "ноль обязан быть виден оператору, включившему DEBUG"
        assert svc.warnings == []


class TestSkippedTickStaysCompletelySilent:
    """Критерий 4: пропущенный такт — не «убрали 0», а «не убирали» — ни INFO, ни DEBUG."""

    def test_interval_not_elapsed_adds_no_new_voice(self) -> None:
        """(а) срок purge_interval_sec не наступил."""
        svc = _wired_svc({"by_age": 5, "by_rows": 5, "remaining": 10})

        sweep_observability_history(svc, now=1000.0)  # реальный такт — что-то да сказал
        info_before = list(svc.info_messages)
        debug_before = list(svc.debug_messages)
        warnings_before = list(svc.warnings)

        result = sweep_observability_history(svc, now=1010.0)  # интервал 100с не истёк

        assert result is None
        assert svc.info_messages == info_before, "пропущенный такт не добавляет новый голос INFO"
        assert svc.debug_messages == debug_before, "пропущенный такт не добавляет новый голос DEBUG"
        assert svc.warnings == warnings_before

    def test_missing_store_adds_no_voice_at_all(self) -> None:
        """(б) стора у процесса нет — свип не начинался вовсе, это не «убрали 0»."""
        svc = _Svc()
        svc._observability_history_policy = {"max_rows": 7, "max_age_sec": 42.0, "purge_interval_sec": 100.0}

        result = sweep_observability_history(svc, now=1000.0)

        assert result is None
        assert svc.info_messages == []
        assert svc.debug_messages == [], "«стора нет» не имеет права выглядеть как «убрали 0» на DEBUG"
        assert svc.warnings == []


class TestDbFailureStillWarnsWithoutRegression:
    """Критерий 5: отказ БД — по-прежнему ровно один WARNING, без голоса об успехе."""

    def test_failure_gives_exactly_one_warning_with_error_text(self) -> None:
        svc = _wired_svc({"by_age": 0, "by_rows": 0, "remaining": 0})
        svc._observability_store = _Store(fail=True)

        result = sweep_observability_history(svc, now=1000.0)

        assert result is None
        assert len(svc.warnings) == 1
        assert "БД закрыта" in svc.warnings[0]

    def test_failure_does_not_also_claim_info_or_debug_success(self) -> None:
        svc = _wired_svc({"by_age": 0, "by_rows": 0, "remaining": 0})
        svc._observability_store = _Store(fail=True)

        sweep_observability_history(svc, now=1000.0)

        assert svc.info_messages == []
        assert svc.debug_messages == [], "отказ БД не имеет права выглядеть как успешная уборка на DEBUG"


class TestVoiceDoesNotChangeTheReturnValue:
    """Критерий 6: голос — побочный эффект, отчёт (или None) доезжает без изменений."""

    def test_report_dict_is_returned_unchanged_on_success(self) -> None:
        svc = _wired_svc({"by_age": 2, "by_rows": 3, "remaining": 400})

        result = sweep_observability_history(svc, now=1000.0)

        assert result == {"by_age": 2, "by_rows": 3, "remaining": 400}

    def test_none_is_still_returned_when_tick_is_skipped(self) -> None:
        svc = _Svc()  # без стора — такт пропущен

        result = sweep_observability_history(svc, now=1000.0)

        assert result is None


# ---------------------------------------------------------------------------
# Дополнение к критериям 1-3: то же свойство (INFO ровно когда N > 0, иначе
# ровно DEBUG) на россыпи комбинаций by_age/by_rows. Hypothesis в venv не
# установлен (`ModuleNotFoundError`, проверено 2026-09-07) — заменитель
# property-теста через parametrize, не новая зависимость.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("by_age", "by_rows", "expect_info"),
    [
        (0, 0, False),
        (1, 0, True),
        (0, 1, True),
        (5, 5, True),
        (100, 250, True),
    ],
)
def test_voice_level_follows_whether_anything_was_removed(by_age: int, by_rows: int, expect_info: bool) -> None:
    svc = _wired_svc({"by_age": by_age, "by_rows": by_rows, "remaining": 0})

    sweep_observability_history(svc, now=1000.0)

    assert bool(svc.info_messages) is expect_info, f"by_age={by_age} by_rows={by_rows}"
    assert bool(svc.debug_messages) is (not expect_info), f"by_age={by_age} by_rows={by_rows}"
    assert svc.warnings == []
