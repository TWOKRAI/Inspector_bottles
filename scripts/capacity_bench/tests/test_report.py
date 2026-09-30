"""Слепые acceptance-тесты 4.8a: `report.write_report`.

Источник истины — `plans/transport-single-policy/task-4.8.md`, п. 6 публичного API.
Литералы отчёта из спеки: «CPU-числа на этой машине ненадёжны», «сборка не прошла тесты».

Чего спека НЕ фиксирует (значит, и тест не пинит): формат чисел в таблице, заголовки
столбцов, формулировку строки самопроверки. Поэтому числовые проверки в markdown
терпимы к округлению, а строка самопроверки ищется по префиксу значения.
"""

from __future__ import annotations

import copy
import datetime
import importlib
import json

HOST = "TESTHOST"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
UNRELIABLE = "CPU-числа на этой машине ненадёжны"
TESTS_FAILED = "сборка не прошла тесты"


def _write(result, out_dir):
    return importlib.import_module("scripts.capacity_bench.report").write_report(result, out_dir)


def _today():
    """Сегодняшняя дата (риск полуночи между вызовами — см. отчёт)."""
    return datetime.date.today().isoformat()


def _fields(**over):
    base = {
        "hz": 58.1,
        "inner_cores": 1.69,
        "plugin_ms": {"color_mask": 11.5},
        "queue_wait_ms": 1097.9,
        "transport_ms": 26.6,
        "pacer_late": 456,
        "shm": {"bytes_written": 1000, "bytes_read": 900, "bytes_mapped": 8192, "stale_drops": 3, "torn_reads": 0},
    }
    base.update(over)
    return base


def _result(**over):
    result = {
        "passport": {"host": HOST, "commit": COMMIT, "commit_dirty": False, "cpu_model": "TestCPU 9000"},
        "selfcheck": {"measured": 1.013, "ok": True, "method": "cycles"},
        "tests": None,
        "profile": "quick",
        "cases": [
            {
                "height": 1080,
                "fps": 100,
                "secs": 30,
                "sha": COMMIT,
                "tree": "baseline",
                "total_ext_cores": 2.5,
                "processes": {
                    "processor": {"ext_cores": 1.5, **_fields()},
                    "camera_0": {"ext_cores": 1.0, **_fields(queue_wait_ms=None, transport_ms=None)},
                },
            },
            {
                "height": 1080,
                "fps": 100,
                "secs": 30,
                "sha": COMMIT,
                "tree": "candidate",
                "total_ext_cores": 2.4,
                "processes": {"processor": {"ext_cores": 1.4, **_fields()}},
            },
        ],
    }
    result.update(over)
    return result


def _md(path):
    return path.read_bytes().decode("utf-8")


def test_first_report_names_and_types(tmp_path):
    md, js = _write(_result(), tmp_path)
    day = _today()
    assert md.name == f"{HOST}_{day}.md"
    assert js.name == f"{HOST}_{day}.json"
    assert md.parent == tmp_path and js.parent == tmp_path
    assert md.is_file() and js.is_file()


def test_json_is_result_as_is(tmp_path):
    result = _result()
    snapshot = copy.deepcopy(result)
    _, js = _write(result, tmp_path)
    assert json.loads(js.read_bytes().decode("utf-8")) == snapshot


def test_second_report_same_day_gets_suffix(tmp_path):
    md1, js1 = _write(_result(), tmp_path)
    md1_bytes, js1_bytes = md1.read_bytes(), js1.read_bytes()
    md2, js2 = _write(_result(profile="full"), tmp_path)
    day = _today()
    assert md2.name == f"{HOST}_{day}_2.md"
    assert js2.name == f"{HOST}_{day}_2.json"
    assert md1.read_bytes() == md1_bytes  # первый отчёт не тронут
    assert js1.read_bytes() == js1_bytes


def test_third_report_same_day_gets_suffix_3(tmp_path):
    for _ in range(2):
        _write(_result(), tmp_path)
    md3, js3 = _write(_result(), tmp_path)
    day = _today()
    assert md3.name == f"{HOST}_{day}_3.md"
    assert js3.name == f"{HOST}_{day}_3.json"


def test_markdown_has_passport_commit_and_selfcheck_value(tmp_path):
    md, _ = _write(_result(), tmp_path)
    text = _md(md)
    assert HOST in text
    assert COMMIT in text
    assert "1.0" in text  # measured 1.013 — при любом округлении начинается с «1.0»


def test_markdown_has_process_names_and_per_process_values(tmp_path):
    md, _ = _write(_result(), tmp_path)
    text = _md(md)
    assert "processor" in text
    assert "camera_0" in text
    assert "456" in text  # pacer_late — целое, форматирование не искажает
    assert "1097.9" in text or "1098" in text


def test_markdown_labels_baseline_and_candidate_trees(tmp_path):
    """Трактовка: метка `tree` попадает в отчёт словами — иначе A/B не отличить."""
    md, _ = _write(_result(), tmp_path)
    text = _md(md)
    assert "baseline" in text
    assert "candidate" in text


def test_unreliable_literal_present_when_selfcheck_not_ok(tmp_path):
    result = _result(selfcheck={"measured": 1.2, "ok": False, "method": "cycles"})
    md, _ = _write(result, tmp_path)
    assert UNRELIABLE in _md(md)


def test_unreliable_literal_absent_when_selfcheck_ok(tmp_path):
    md, _ = _write(_result(), tmp_path)
    assert UNRELIABLE not in _md(md)


def test_tests_failed_literal_present_when_rc_nonzero(tmp_path):
    result = _result(tests={"rc": 1, "passed": 10, "failed": 2, "duration_s": 3.5})
    md, _ = _write(result, tmp_path)
    assert TESTS_FAILED in _md(md)


def test_tests_failed_literal_absent_when_rc_zero(tmp_path):
    result = _result(tests={"rc": 0, "passed": 12, "failed": 0, "duration_s": 3.5})
    md, _ = _write(result, tmp_path)
    assert TESTS_FAILED not in _md(md)


def test_tests_failed_literal_absent_when_tests_not_run(tmp_path):
    md, _ = _write(_result(tests=None), tmp_path)
    assert TESTS_FAILED not in _md(md)


def test_report_with_no_cases_is_written(tmp_path):
    """Форма результата --dry-run: cases == [] — отчёт всё равно пишется."""
    md, js = _write(_result(cases=[]), tmp_path)
    assert md.is_file() and js.is_file()
    assert COMMIT in _md(md)
