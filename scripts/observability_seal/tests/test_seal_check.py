# -*- coding: utf-8 -*-
"""Тесты самого проверяющего пломбы (2.V1).

Проверяющий — тоже мой код, и правило шапки Ф2.V прямо это признаёт: он
проверяется слом-инъекцией, как всё остальное. Самое ценное здесь — не «нашёл
дырку», а **«не смог проверить» отличается от «проверил, всё хорошо»**: оракул,
молчащий при неспособности прочитать, был бы четвёртым проглоченным сбоем —
его тишину приняли бы за одобрение.

Файлы здесь пишутся руками, БЕЗ участия фреймворка: проверяющий обязан работать
на байтах, а не на согласии с логгером.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import List

from scripts.observability_seal.seal_check import check_seal, main, _compact


def _write(path: Path, seqs: List[int], *, unsealed: int = 0) -> None:
    lines = [f"#{seq} 2026-07-27 12:00:00,000 [INFO] mod: сообщение {seq}" for seq in seqs]
    lines += ["#- 2026-07-27 12:00:00,000 [INFO] mod: запись мимо точки эмиссии"] * unsealed
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# =============================================================================
# «Не смог проверить» ≠ «всё хорошо»
# =============================================================================


def test_empty_directory_is_not_a_pass(tmp_path: Path) -> None:
    report = check_seal([tmp_path])
    assert not report.verifiable
    assert not report.ok
    assert report.exit_code == 2
    assert "ПРОВЕРИТЬ НЕ УДАЛОСЬ" in report.render()


def test_missing_path_is_named(tmp_path: Path) -> None:
    report = check_seal([tmp_path / "нет-такого"])
    assert report.exit_code == 2
    assert any("не существует" in why for _, why in report.unreadable)


def test_file_without_a_single_seal_is_not_a_pass(tmp_path: Path) -> None:
    """Лог, написанный до 2.V1, обязан дать код 2, а не «непрерывно».

    Это и есть класс дефекта, ради которого правило написано: ноль найденных
    дырок в файле, где искать было нечего, выглядит как успех.
    """
    (tmp_path / "old.log").write_text("2026-07-01 10:00:00,000 [INFO] mod: строка без пломбы\n", encoding="utf-8")
    report = check_seal([tmp_path])
    assert report.files_read, "файл прочитан"
    assert report.sealed_lines == 0
    assert not report.verifiable
    assert report.exit_code == 2


def test_holes_and_no_seals_are_different_verdicts(tmp_path: Path) -> None:
    """Оба «плохо», но коды разные — иначе их не различить в CI."""
    _write(tmp_path / "a.log", [1, 2, 4])
    assert check_seal([tmp_path]).exit_code == 1
    (tmp_path / "a.log").unlink()
    (tmp_path / "a.log").write_text("без пломб\n", encoding="utf-8")
    assert check_seal([tmp_path]).exit_code == 2


# =============================================================================
# Арифметика на номерах
# =============================================================================


def test_holes_are_named_exactly(tmp_path: Path) -> None:
    _write(tmp_path / "system.log", [1, 2, 3, 6, 7, 10])
    report = check_seal([tmp_path])
    assert report.holes == [4, 5, 8, 9]
    assert report.exit_code == 1


def test_continuous_range_is_green(tmp_path: Path) -> None:
    _write(tmp_path / "system.log", list(range(1, 51)))
    report = check_seal([tmp_path])
    assert report.holes == []
    assert report.exit_code == 0
    assert "непрерывно" in report.render()


def test_union_across_files_closes_a_hole(tmp_path: Path) -> None:
    """Две плоскости процесса — два файла; непрерывность считается по объединению.

    Проверка по каждому файлу в отдельности назвала бы потерей нормальное
    разделение записей между логами и ошибками.
    """
    _write(tmp_path / "system.log", [1, 3, 5])
    _write(tmp_path / "errors.log", [2, 4])
    report = check_seal([tmp_path])
    assert report.holes == []
    assert report.exit_code == 0


def test_sequence_need_not_start_at_one(tmp_path: Path) -> None:
    """Окно проверки может начаться в середине (ротация, обрезанный файл).

    Непрерывность считается от min до max: требование «начинается с 1» делало
    бы любой хвост лога ложной тревогой.
    """
    _write(tmp_path / "system.log", [900, 901, 902])
    assert check_seal([tmp_path]).exit_code == 0


def test_duplicate_number_is_reported(tmp_path: Path) -> None:
    """Дубликат — тоже дефект: либо запись легла дважды, либо в каталоге
    смешались два процесса, и тогда вердикт о непрерывности не имеет смысла."""
    _write(tmp_path / "a.log", [1, 2, 3])
    _write(tmp_path / "b.log", [2, 4])
    report = check_seal([tmp_path])
    assert report.duplicates == {2: 2}
    assert report.exit_code == 1


def test_unsealed_lines_break_the_verdict(tmp_path: Path) -> None:
    """Запись без пломбы не потеря, но и не «всё хорошо» — её нет в учёте."""
    _write(tmp_path / "a.log", [1, 2, 3], unsealed=2)
    report = check_seal([tmp_path])
    assert report.unsealed_lines == 2
    assert report.holes == []
    assert report.exit_code == 1


def test_multiline_message_does_not_invent_numbers(tmp_path: Path) -> None:
    """Traceback внутри записи — не новые записи.

    Пломба стоит префиксом первой строки намеренно: суффикс уехал бы на
    последнюю строку блока, а продолжения ``  File "..."`` с ``#<цифры> `` не
    начинаются.
    """
    (tmp_path / "a.log").write_text(
        "#1 [ERROR] mod: упало\n"
        "Traceback (most recent call last):\n"
        '  File "x.py", line 1, in <module>\n'
        "ValueError: 42\n"
        "#2 [INFO] mod: дальше\n",
        encoding="utf-8",
    )
    report = check_seal([tmp_path])
    assert sorted(report.seqs) == [1, 2]
    assert report.exit_code == 0


# =============================================================================
# Форматы файлов
# =============================================================================


def test_floor_jsonl_is_read_by_field(tmp_path: Path) -> None:
    payload = {"timestamp": 1.0, "level": "ERROR", "message": "у", "module": "m", "extra": {}, "seq": 7}
    (tmp_path / "errors_floor.jsonl").write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
    _write(tmp_path / "system.log", [5, 6, 8])
    report = check_seal([tmp_path])
    assert 7 in report.seqs
    assert report.holes == []


def test_broken_jsonl_line_is_counted_not_swallowed(tmp_path: Path) -> None:
    (tmp_path / "errors_floor.jsonl").write_text("{битый json\n", encoding="utf-8")
    report = check_seal([tmp_path])
    assert report.unsealed_lines == 1
    assert report.exit_code == 2  # ни одной пломбы — проверить не удалось


def test_rotated_gzip_backup_is_read(tmp_path: Path) -> None:
    with gzip.open(tmp_path / "system.log.1.gz", "wt", encoding="utf-8") as handle:
        handle.write("#1 [INFO] mod: старое\n#2 [INFO] mod: старое\n")
    _write(tmp_path / "system.log", [3, 4])
    report = check_seal([tmp_path])
    assert report.holes == []
    assert report.exit_code == 0


def test_unreadable_file_is_loud(tmp_path: Path) -> None:
    """Сбой чтения обязан попасть в отчёт, а не исчезнуть в ``except: pass``."""
    bad = tmp_path / "locked.log"
    bad.mkdir()  # каталог с именем .log: открыть как файл нельзя
    _write(tmp_path / "ok.log", [1, 2])
    report = check_seal([tmp_path, bad])
    assert any(str(bad) in path for path, _ in report.unreadable)
    assert "НЕ ПРОЧИТАНО" in report.render()


# =============================================================================
# Вывод
# =============================================================================


def test_compact_folds_runs() -> None:
    assert _compact([1, 2, 3, 7, 9, 10]) == "1-3, 7, 9-10"
    assert _compact([]) == ""


def test_cli_writes_report_and_returns_the_code(tmp_path: Path, capsys) -> None:
    _write(tmp_path / "system.log", [1, 2, 4])
    out = tmp_path / "отчёт" / "seal.txt"
    code = main([str(tmp_path), "--report", str(out)])
    assert code == 1
    assert out.exists()
    assert "дырок" in out.read_text(encoding="utf-8")
    captured = capsys.readouterr()
    # Вердикт идёт в stderr: проверяющий не смешивает его с данными конвейера.
    assert "ВЕРДИКТ" in captured.err
    assert captured.out == ""
