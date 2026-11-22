"""Тесты автора на опасности `--layout-system`: порядок, двойной отказ, равное время, невалидный UTF-8,
кросс-дата, инкарнации system.log, отказ у диска с заданием, FAIL вместе с отказом.

Ядро (`core.audit` / `core.parse_system`) гоняется напрямую, строки журналов собираются здесь же; CLI — только
там, где важны чтение файла и вывод. Ожидаемые значения записаны литералами.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from scripts.wire_audit import core

ROOT = Path(__file__).resolve().parents[3]
WORD = "ПЕРЕМИРИЕ"  # ячейки 0..8: П Е Р Е М И Р И Е
REGS = {
    "first_x": 320.0,
    "first_y": -440.0,
    "pitch_mm": 0.0,
    "disk_radius_mm": 55.0,
    "line_angle_deg": 90.0,
    "place_z_mm": -132.0,
    "pick_z_mm": -132.0,
    "angle_zero_deg": 0.0,
    "angle_invert": False,
    "use_pitch": True,
    "word_gap_slots": 0,
    "p_pick_rz_deg": -100.0,
}
BASE = datetime(2026, 11, 22, 21, 24, 0)
REASON = "робот остановлен: включите серво"
# Е 91.9° -> ячейка 3: слова CVT_JOB (ARGS[7] = 64436 — y ячейки 3)
JOB_E3 = [18178, 1, 4602, 62104, 64216, 3, 3200, 64436, 64216, 63617]


def ts(when: float | datetime) -> str:
    dt = when if isinstance(when, datetime) else BASE + timedelta(seconds=when)
    return dt.strftime("%Y-%m-%d %H:%M:%S") + f",{dt.microsecond // 1000:03d}"


class Logs:
    """Журнал диска и обмена одного прогона."""

    def __init__(self) -> None:
        self.layout: list[str] = []
        self.exchange: list[str] = ["#41 " + ts(0) + " [INFO] S.d.d.e.robot_main: #1  connect ok"]

    def _lay(self, when: float | datetime, text: str) -> None:
        self.layout.append(f"#{len(self.layout) + 1} {ts(when)} [INFO] [layout] word_layout: WordLayoutPlugin: {text}")

    def word(self, when: float | datetime) -> None:
        self._lay(when, f"слово '{WORD}' (источник: регистр)")

    def pick(self, when: float | datetime, letter: str, net: float, cell: int) -> None:
        self._lay(when, f"диск '{letter}' {net:.1f}° → ячейка {cell}: взять(460.2,-343.2) → положить x320.0")

    def job(self, when: float | datetime, seq: int, args: list[int]) -> None:
        n = len(self.exchange) + 1
        for text in (
            f"in W* CMD_SEQ = {seq}",
            "in W* CMD_OPCODE = 32 (CVT_JOB)",
            f"in W* CMD_ARGC = {len(args)}",
            *(f"in W* CMD_ARGS[{i}] = {w}" for i, w in enumerate(args)),
            "in W CMD_FLAG = 1",
            f"out R RES_SEQ..+12 RES_SEQ = {seq}, RES_STATUS = 1, RES_ERRNO = 0 (ОК)",
        ):
            self.exchange.append(f"#{n + 40} {ts(when)} [INFO] S.d.d.e.robot_main: #{n} {text}")
            n += 1

    def exchange_text(self) -> str:
        return "\n".join(self.exchange) + "\n"

    def layout_text(self) -> str:
        return "\n".join(self.layout) + "\n"

    def audit(self, system: str | None, *, fills: int = 1) -> core.AuditResult:
        return core.audit(self.exchange_text(), self.layout_text(), REGS, words=[WORD] * fills, layout_system=system)


def refusal(when: float | datetime, letter: str, cell: int, reason: str = REASON) -> str:
    return (
        f"#191 {ts(when)} [WARNING] [layout] layout: [health] ResourceUnavailable @ robot_io.forward.refused: "
        f"hub отказ (буква '{letter}', ячейка {cell}): {reason}"
    )


def systext(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def two_fill_same_cell() -> Logs:
    """Р -> ячейка 2 в заливке 1 (t=20) и снова Р -> ячейка 2 в заливке 2 (t=30): ячейка законно свободна заново."""
    logs = Logs()
    logs.word(1)
    logs.pick(20, "Р", 30.0, 2)
    logs.word(25)
    logs.pick(30, "Р", 40.0, 2)
    return logs


def one_lost_disk() -> Logs:
    logs = Logs()
    logs.word(1)
    logs.pick(20, "Р", 30.0, 2)
    return logs


def results(res: core.AuditResult) -> list[str]:
    return [r.result for r in res.rows]


# ------------------------------------------------------------------------- порядок


def test_refusals_in_reverse_file_order_still_bind_by_time():
    res = two_fill_same_cell().audit(systext(refusal(30.5, "Р", 2, "вторая"), refusal(20.5, "Р", 2, "первая")), fills=2)
    assert results(res) == ["PASS~: отказ hub: первая", "PASS~: отказ hub: вторая"]
    assert (res.hub_refusals, res.warnings, res.fails, res.notes) == (2, 2, 0, [])


def test_double_refusal_in_reverse_file_order_closes_the_disk_with_the_earlier_one():
    """Охраняет сортировку по времени: при обратном порядке строк диск закрывает ранний отказ, поздний — примечание."""
    res = one_lost_disk().audit(systext(refusal(20.2, "Р", 2, "второй"), refusal(20.1, "Р", 2, "первый")))
    assert results(res) == ["PASS~: отказ hub: первый"]
    assert res.notes == ["отказ без диска (не FAIL): буква 'Р', ячейка 2, 2026-11-22 21:24:20,200: второй"]


def test_refusal_of_the_second_disk_does_not_close_the_first():
    res = two_fill_same_cell().audit(systext(refusal(30.5, "Р", 2)), fills=2)
    assert results(res) == ["FAIL: потеря", "PASS~: отказ hub: " + REASON]
    assert (res.hub_refusals, res.warnings, res.fails) == (1, 1, 1)


# ------------------------------------------------------------------------- двойной отказ


def test_double_refusal_for_one_disk_closes_one_and_notes_the_other():
    res = one_lost_disk().audit(systext(refusal(20.1, "Р", 2, "первый"), refusal(20.2, "Р", 2, "второй")))
    assert results(res) == ["PASS~: отказ hub: первый"]
    assert (res.hub_refusals, res.warnings, res.fails) == (1, 1, 0)
    assert res.notes == ["отказ без диска (не FAIL): буква 'Р', ячейка 2, 2026-11-22 21:24:20,200: второй"]


def test_same_refusal_line_twice_is_two_refusals_one_disk():
    line = refusal(20.1, "Р", 2)
    res = one_lost_disk().audit(systext(line, line))
    assert (res.hub_refusals, len(res.notes), res.fails) == (1, 1, 0)


# ------------------------------------------------------------------------- равное время


def test_refusal_with_the_disk_timestamp_closes_the_disk():
    res = one_lost_disk().audit(systext(refusal(20.0, "Р", 2)))
    assert results(res) == ["PASS~: отказ hub: " + REASON]


def test_refusal_with_the_next_same_cell_disk_timestamp_belongs_to_the_next_disk():
    """Граница «раньше следующего диска в ту же ячейку» строгая: отказ ровно во время второго диска — второму."""
    res = two_fill_same_cell().audit(systext(refusal(30.0, "Р", 2)), fills=2)
    assert results(res) == ["FAIL: потеря", "PASS~: отказ hub: " + REASON]


def test_refusal_a_millisecond_before_the_disk_does_not_close_it():
    res = one_lost_disk().audit(systext(refusal(19.999, "Р", 2)))
    assert results(res) == ["FAIL: потеря"]
    assert (res.hub_refusals, len(res.notes)) == (0, 1)


# ------------------------------------------------------------------------- кросс-дата


def test_refusal_after_midnight_closes_the_disk_before_midnight():
    logs = Logs()
    logs.word(1)
    logs.pick(datetime(2026, 11, 22, 23, 59, 59, 900000), "Р", 30.0, 2)
    res = logs.audit(systext(refusal(datetime(2026, 11, 23, 0, 0, 0, 50000), "Р", 2)))
    assert results(res) == ["PASS~: отказ hub: " + REASON]


def test_refusal_of_the_previous_day_with_a_later_clock_time_does_not_close_the_disk():
    """Время суток 23:59:59 позже 00:00:00, но дата раньше: сравнивается дата со временем целиком."""
    logs = Logs()
    logs.word(datetime(2026, 11, 22, 23, 0, 0))
    logs.pick(datetime(2026, 11, 23, 0, 0, 0, 100000), "Р", 30.0, 2)
    res = logs.audit(systext(refusal(datetime(2026, 11, 22, 23, 59, 59, 900000), "Р", 2)))
    assert results(res) == ["FAIL: потеря"]
    assert (res.hub_refusals, len(res.notes)) == (0, 1)


# ------------------------------------------------------------------------- system.log дописывается между запусками

# Реальные строки layout/system.log двух прогонов (data/chain_check/home_c104, 20261122T165327Z и 20261122T170206Zb):
# в файле только WARNING, строк `LoggerManager initialized` там нет, второй прогон дописан после первого.
HEARTBEAT_RUN1 = (
    "#40 2026-11-22 19:53:31,152 [WARNING] [layout] heartbeat: Частота метрик ограничена телеметрийным тиком 5.0с: fps "
    "(interval_sec=1.0с), latency_ms (interval_sec=1.0с) — метрика публикуется не чаще тика "
    "(подними tick_sec или ослабь interval_sec)"
)
RUN1_REFUSALS = tuple(
    f"#{no} 2026-11-22 {clock} [WARNING] [layout] layout: [health] ResourceUnavailable @ robot_io.forward.refused: "
    "hub отказ (буква 'Р', ячейка 2): идёт основная остановка робота"
    for no, clock in ((50, "19:54:02,775"), (56, "19:54:33,334"), (67, "19:55:34,860"), (73, "19:56:05,584"))
)
HEARTBEAT_RUN2 = HEARTBEAT_RUN1.replace("19:53:31,152", "20:02:10,420")
RUN2_REFUSALS = tuple(
    f"#{no} 2026-11-22 {clock} [WARNING] [layout] layout: [health] ResourceUnavailable @ robot_io.forward.refused: "
    "hub отказ (буква 'Р', ячейка 2): робот остановлен: включите серво"
    for no, clock in ((50, "20:02:42,715"), (58, "20:03:13,915"), (66, "20:03:45,069"))
)


def run2_logs() -> Logs:
    """Журнал диска второго прогона: три `Р` в ячейку 2 (по одной на заливку), задания не уходили."""
    logs = Logs()
    d = datetime
    logs.word(d(2026, 11, 22, 20, 2, 30))
    logs.pick(d(2026, 11, 22, 20, 2, 42, 702000), "Р", 306.3, 2)
    logs.word(d(2026, 11, 22, 20, 3, 0))
    logs.pick(d(2026, 11, 22, 20, 3, 13, 895000), "Р", 306.7, 2)
    logs.word(d(2026, 11, 22, 20, 3, 30))
    logs.pick(d(2026, 11, 22, 20, 3, 45, 58000), "Р", 305.9, 2)
    return logs


def test_two_runs_glued_in_one_system_log_judge_only_the_second_run():
    glued = systext(HEARTBEAT_RUN1, *RUN1_REFUSALS, HEARTBEAT_RUN2, *RUN2_REFUSALS)
    res = run2_logs().audit(glued, fills=3)
    reason = "робот остановлен: включите серво"
    assert results(res) == [f"PASS~: отказ hub: {reason}"] * 3
    assert (res.hub_refusals, res.warnings, res.fails, res.notes) == (3, 3, 0, [])


def test_second_run_alone_gives_the_same_verdict_as_two_glued_runs():
    alone = run2_logs().audit(systext(HEARTBEAT_RUN2, *RUN2_REFUSALS), fills=3)
    glued = run2_logs().audit(systext(HEARTBEAT_RUN1, *RUN1_REFUSALS, HEARTBEAT_RUN2, *RUN2_REFUSALS), fills=3)
    assert (alone.summary, alone.notes, results(alone)) == (glued.summary, glued.notes, results(glued))


def test_refusal_exactly_at_the_first_layout_event_is_kept_one_millisecond_earlier_is_dropped():
    """Граница судимой инкарнации — время первого события журнала диска (здесь слово в t=1): раньше — молча чужое."""
    res = one_lost_disk().audit(systext(refusal(0.999, "Щ", 5, "чужая"), refusal(1.0, "Щ", 5, "своя")))
    assert res.notes == ["отказ без диска (не FAIL): буква 'Щ', ячейка 5, 2026-11-22 21:24:01,000: своя"]


def test_empty_layout_has_no_boundary_and_keeps_every_refusal_as_a_note():
    res = core.audit("", "", REGS, words=[], layout_system=systext(refusal(5, "Щ", 5)))
    assert (res.picks, res.hub_refusals, len(res.notes)) == (0, 0, 1)


# ------------------------------------------------------------------------- прочие ветви привязки


def test_refusal_of_a_disk_that_has_a_job_is_a_note_not_a_warning():
    logs = Logs()
    logs.word(1)
    logs.pick(10, "Е", 91.9, 3)
    logs.job(10.3, 60466, JOB_E3)
    res = logs.audit(systext(refusal(10.5, "Е", 3)))
    assert results(res) == ["PASS"]
    assert (res.hub_refusals, res.warnings, res.fails, len(res.notes)) == (0, 0, 0, 1)


def test_refusal_letter_is_compared_case_insensitively():
    res = one_lost_disk().audit(systext(refusal(20.1, "р", 2)))
    assert results(res) == ["PASS~: отказ hub: " + REASON]


def test_refused_disk_with_a_repeated_cell_in_the_fill_keeps_its_fail_and_shows_the_refusal():
    """Повтор ячейки в заливке — отказ журнала диска, а не провода: остаётся FAIL, отказ виден в скобках."""
    logs = Logs()
    logs.word(1)
    logs.pick(20, "Р", 30.0, 2)
    logs.pick(30, "Р", 40.0, 2)
    res = logs.audit(systext(refusal(30.5, "Р", 2)))
    assert results(res) == ["FAIL: потеря", "FAIL: ячейка (отказ hub: " + REASON + ")"]
    assert (res.hub_refusals, res.warnings, res.fails) == (1, 1, 2)


def test_empty_reason_is_named_not_left_blank():
    line = refusal(20.1, "Р", 2, "").rstrip()
    res = one_lost_disk().audit(systext(line))
    assert results(res) == ["PASS~: отказ hub: причина не указана"]


HEAD = f"#191 {ts(20.1)} [WARNING] [layout] layout: [health] ResourceUnavailable @ robot_io.forward.refused: "


@pytest.mark.parametrize(
    "tail",
    [
        "hub отказ (буква 'Р', ячейка 2",  # нет закрывающей скобки, обрыв после номера
        "hub отказ (буква 'Р', ячейка 2: робот остановлен: включите серво",  # нет скобки, причина есть
        "hub отказ (буква 'Р', ячейка 2)",  # нет двоеточия и причины
        "hub отказ (буква 'Р', ячейка 2) робот остановлен",  # нет двоеточия, текст после скобки есть
        "hub отказ (буква 'Р', ячейка ",  # обрыв до номера ячейки
        "hub отказ (буква 'Р', ячейка ): робот остановлен",  # скобка и причина есть, номера ячейки нет
        "hub отказ (буква 'Р'",  # обрыв до ячейки
        "hub отказ (robot_return_job): робот остановлен: включите серво",  # другой формат: нет буквы и ячейки
    ],
    ids=[
        "no-paren",
        "no-paren-with-reason",
        "no-colon",
        "no-colon-with-text",
        "no-cell-number",
        "no-cell-digits",
        "no-cell",
        "no-letter",
    ],
)
def test_malformed_refusal_line_with_valid_timestamp_is_not_a_refusal(tail):
    """Метка времени, буква и ячейка корректны, но строка не по формату: диск остаётся `потеря`, примечания нет."""
    res = one_lost_disk().audit(systext(HEAD + tail))
    assert results(res) == ["FAIL: потеря"]
    assert (res.hub_refusals, res.warnings, res.fails, res.notes) == (0, 0, 1, [])
    assert res.summary == (
        "ИТОГ: FAIL (взятий 1, заданий 0, FAIL 1, пропусков 0, повторов 0, предупреждений 0, отказов hub 0)"
    )


def test_refusal_line_cut_in_the_middle_of_the_reason_still_counts_with_the_cut_reason():
    """Обрыв посреди причины неотличим от целой строки: формат (буква, ячейка, `): `) цел, hub диск отказал — отказ."""
    res = one_lost_disk().audit(systext(HEAD + "hub отказ (буква 'Р', ячейка 2): робот остан"))
    assert results(res) == ["PASS~: отказ hub: робот остан"]
    assert (res.hub_refusals, res.fails) == (1, 0)


def test_malformed_refusal_line_does_not_hide_a_good_one_next_to_it():
    res = one_lost_disk().audit(systext(HEAD + "hub отказ (буква 'Р', ячейка 2", refusal(20.2, "Р", 2, "целая")))
    assert results(res) == ["PASS~: отказ hub: целая"]
    assert (res.hub_refusals, res.notes) == (1, [])


def test_pipe_in_reason_does_not_break_the_table_row():
    res = one_lost_disk().audit(systext(refusal(20.1, "Р", 2, "a | b")))
    row = res.rows[0].cells()
    assert len(row) == len(core.TABLE_HEADER)
    assert row[-1] == "PASS~: отказ hub: a / b"


def test_summary_without_system_has_no_hub_field_and_with_system_has_it():
    logs = one_lost_disk()
    assert logs.audit(None).summary.endswith("предупреждений 0)")
    assert logs.audit(systext(refusal(20.1, "Р", 2))).summary == (
        "ИТОГ: PASS (взятий 1, заданий 0, FAIL 0, пропусков 0, повторов 0, предупреждений 1, отказов hub 1)"
    )


def test_every_pick_refused_is_not_the_zero_jobs_fail():
    """Серво выключено весь прогон: заданий 0, но все взятия закрыты отказом hub — код 0, не «ноль заданий»."""
    res = two_fill_same_cell().audit(systext(refusal(20.5, "Р", 2), refusal(30.5, "Р", 2)), fills=2)
    assert (res.picks, res.jobs, res.hub_refusals, res.fails, res.exit_code) == (2, 0, 2, 0, 0)


def test_zero_jobs_with_an_unrefused_pick_is_still_fail():
    res = two_fill_same_cell().audit(systext(refusal(20.5, "Р", 2)), fills=2)
    assert (res.picks, res.jobs, res.hub_refusals, res.fails, res.exit_code) == (2, 0, 1, 1, 1)
    assert results(res) == ["PASS~: отказ hub: " + REASON, "FAIL: потеря"]


# ------------------------------------------------------------------------- CLI: чтение файла и вывод


def run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, "-m", "scripts.wire_audit", *args],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


def cli_args(tmp: Path, logs: Logs, *extra: str) -> list[str]:
    (tmp / "exchange.log").write_text(logs.exchange_text(), encoding="utf-8")
    (tmp / "messages.log").write_text(logs.layout_text(), encoding="utf-8")
    (tmp / "registers.json").write_text(json.dumps(REGS), encoding="utf-8")
    return [
        "--exchange", str(tmp / "exchange.log"),
        "--layout", str(tmp / "messages.log"),
        "--registers", str(tmp / "registers.json"),
        "--words", WORD,
        *extra,
    ]  # fmt: skip


def test_invalid_utf8_bom_and_crlf_in_system_log_are_read_without_error(tmp_path):
    good = refusal(20.1, "Р", 2, "причина")
    raw = (
        b"\xef\xbb\xbf"  # BOM
        + b"\xff\xfe garbage \xc3\x28 line\r\n"  # невалидный UTF-8 в постороннем тексте
        + good.encode("utf-8").replace("причина".encode("utf-8"), b"\xd0\xbf\xff\xd1")  # битый байт в причине
        + b"\r\n"
    )
    sysf = tmp_path / "system.log"
    sysf.write_bytes(raw)
    res = run_cli(cli_args(tmp_path, one_lost_disk(), "--layout-system", str(sysf)))
    assert res.returncode == 0, res.stderr
    assert "Traceback" not in res.stdout + res.stderr
    assert "PASS~: отказ hub: п�" in res.stdout
    assert res.stdout.rstrip().splitlines()[-1].endswith("предупреждений 1, отказов hub 1)")


def test_layout_system_pointing_to_a_directory_is_code_2_without_the_path(tmp_path):
    res = run_cli(cli_args(tmp_path, one_lost_disk(), "--layout-system", str(tmp_path)))
    assert res.returncode == 2
    assert "--layout-system" in res.stderr
    assert str(tmp_path) not in res.stdout + res.stderr
    assert "Traceback" not in res.stderr


def test_out_report_and_wire_commands_show_the_refusal(tmp_path):
    sysf = tmp_path / "system.log"
    sysf.write_text(systext(refusal(20.1, "Р", 2)), encoding="utf-8")
    out_dir = tmp_path / "rep"
    out_dir.mkdir()
    res = run_cli(cli_args(tmp_path, one_lost_disk(), "--layout-system", str(sysf), "--out", str(out_dir / "audit.md")))
    assert res.returncode == 0, res.stderr
    assert "PASS~: отказ hub: " + REASON in (out_dir / "audit.md").read_text(encoding="utf-8")
    assert "отказ hub: " + REASON in (out_dir / "wire_commands.md").read_text(encoding="utf-8")
