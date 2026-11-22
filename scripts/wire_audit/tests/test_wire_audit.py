"""Тесты автора ядра аудита провода (Task 3): опасности порядка, инкарнаций, ответов и повторов.

Ядро вызывается напрямую (``core.audit``): фикстуры собираются из строк форматов журналов. Один тест гонит
реальные файлы run1 через CLI в подпроцессе, без фейков разборщика. Ожидаемые слова — литералы ручного счёта.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from scripts.wire_audit import core

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
WORD = "ПЕРЕМИРИЕ"
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
# place y (ARGS[7]) ячеек и place rz (ARGS[9]) по сырому углу сети при REGS — ручной счёт
Y_WORD = {0: 61136, 1: 62236, 2: 63336, 3: 64436, 4: 0, 5: 1100, 6: 2200, 7: 3300, 8: 4400}
Y_MM = {0: -440.0, 1: -330.0, 2: -220.0, 3: -110.0, 4: 0.0, 5: 110.0, 6: 220.0, 7: 330.0, 8: 440.0}
RZ_WORD = {30.0: 64236, 60.0: 63936, 90.0: 63636, 120.0: 63336}


def ts(t: float) -> str:
    dt = datetime(2026, 11, 12, 13, 30, 0) + timedelta(milliseconds=round(t * 1000))
    return dt.strftime("%Y-%m-%d %H:%M:%S") + f",{dt.microsecond // 1000:03d}"


class Ex:
    """Журнал обмена: строки ``#<файл> <время> [INFO] S.d.d.e.robot_main: #<n> in|out ...``."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self._file = 0
        self._n = 0

    def _emit(self, t: float, text: str) -> None:
        self._file += 1
        self._n += 1
        self.lines.append(f"#{self._file} {ts(t)} [INFO] S.d.d.e.robot_main: #{self._n} {text}")

    def connect(self, t: float) -> None:
        self._n = 0
        self._emit(t, " connect ok")

    def reply(self, t: float, seq: int, status: int = 1, errno: int = 0, span: str = "+12") -> None:
        self._emit(t, f"out R RES_SEQ..{span} RES_SEQ = {seq}, RES_STATUS = {status}, RES_ERRNO = {errno} (x)")

    def job(
        self,
        t: float,
        seq: int,
        cell: int,
        net: float,
        *,
        status: int | None = 1,
        errno: int = 0,
        rz: int | None = None,
    ) -> None:
        args = [18178, 1, 4602, 62104, 64216, 3, 3200, Y_WORD[cell], 64216, RZ_WORD[net] if rz is None else rz]
        self._emit(t, f"in W* CMD_SEQ = {seq}")
        self._emit(t, "in W* CMD_OPCODE = 32 (CVT_JOB)")
        self._emit(t, "in W* CMD_ARGC = 10")
        for i, word in enumerate(args):
            self._emit(t, f"in W* CMD_ARGS[{i}] = {word}")
        self._emit(t, "in W CMD_FLAG = 1")
        if status is not None:
            self.reply(t + 0.026, seq, status, errno)

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


class Lay:
    """Журнал диска; строки можно дописывать в любом порядке (время задаётся явно)."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def _emit(self, t: float, src: str, text: str) -> None:
        self.lines.append(f"#{len(self.lines) + 1} {ts(t)} [INFO] {src} {text}")

    def init(self, t: float) -> None:
        self._emit(t, "[-] logger_manager:", "LoggerManager initialized")

    def word(self, t: float, word: str) -> None:
        self._emit(t, "[layout] word_layout:", f"WordLayoutPlugin: слово '{word}' (источник: регистр)")

    def change(self, t: float, old: str, new: str) -> None:
        self._emit(
            t,
            "[layout] word_layout:",
            f"WordLayoutPlugin: смена слова '{old}' → '{new}' (источник: регистр) — ячейки с нуля (было заполнено 1/9)",
        )

    def pick(self, t: float, letter: str, net: float, cell: int) -> None:
        corr = 180.0 if net == 180.0 else ((-net + 180.0) % 360.0) - 180.0
        self._emit(
            t,
            "[layout] word_layout:",
            f"WordLayoutPlugin: диск '{letter}' {net:.1f}° → ячейка {cell}: взять(460.2,-343.2) → "
            f"положить x320.0 y{Y_MM[cell]:.1f} z-132.0 r{corr:.1f}° [1/9]",
        )

    def skip(self, t: float, letter: str, net: float, reason: str) -> None:
        self._emit(t, "[layout] word_layout:", f"WordLayoutPlugin: диск '{letter}' {net:.1f}° → пропуск: {reason}")

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


def fresh() -> tuple[Ex, Lay]:
    ex, lay = Ex(), Lay()
    ex.connect(0.0)
    lay.init(0.5)
    lay.word(5.0, WORD)
    return ex, lay


def run(ex: Ex, lay: Lay, **kw) -> core.AuditResult:
    kw.setdefault("words", [WORD])
    kw.setdefault("zone_max_mm", 600.0)
    return core.audit(ex.text(), lay.text(), REGS, **kw)


def row_of(res: core.AuditResult, net: str) -> core.Row:
    hits = [r for r in res.rows if r.net == net]
    assert len(hits) == 1, [r.net for r in res.rows]
    return hits[0]


# ------------------------------------------------------------------ числа и слова


@pytest.mark.parametrize(
    ("value", "word"),
    [(-100.0, 64536), (91.9, 919), (-191.9, 63617), (0.0, 0), (-0.05, 65535), (0.05, 1)],
)
def test_encode_word_half_away_and_modulo(value, word):
    assert core.encode_word(value) == word


def test_decode_cvt_signed_words_and_ecap_example():
    wire = core.decode_cvt({0: 18178, 1: 1, 2: 4602, 3: 62104, 9: 64536})
    assert wire["ecap"] == 83714
    assert wire["pick_x"] == 460.2
    assert wire["pick_y"] == -343.2
    assert wire["place_rz"] == -100.0


def test_wrap180_range_is_minus_180_exclusive_plus_180_inclusive():
    assert core.wrap180(-180.0) == 180.0
    assert core.wrap180(180.0) == 180.0
    assert core.wrap180(270.0) == -90.0
    assert core.wrap180(-190.0) == 170.0


# ------------------------------------------------------------------ порядок: задания и строки диска


def test_jobs_in_reverse_order_still_bind_by_cell_word():
    """Задания в файле идут в обратном порядке по ячейкам: привязка по ARGS[7], а не по очерёдности."""
    ex, lay = fresh()
    lay.pick(10.0, "Е", 30.0, 1)
    lay.pick(11.0, "Р", 60.0, 2)
    ex.job(12.0, 101, 2, 60.0)  # задание второго взятия стоит в файле первым
    ex.job(12.5, 102, 1, 30.0)
    res = run(ex, lay)
    assert res.exit_code == 0
    assert (row_of(res, "30.0").seq, row_of(res, "60.0").seq) == ("102", "101")


def test_three_e_with_jobs_in_reverse_file_order_get_their_own_cells():
    ex, lay = fresh()
    for t, net, cell in ((10.0, 30.0, 1), (20.0, 60.0, 3), (30.0, 90.0, 8)):
        lay.pick(t, "Е", net, cell)
    ex.job(30.5, 203, 8, 90.0)
    ex.job(20.5, 202, 3, 60.0)
    ex.job(10.5, 201, 1, 30.0)
    res = run(ex, lay)
    assert res.exit_code == 0
    assert [row_of(res, n).seq for n in ("30.0", "60.0", "90.0")] == ["201", "202", "203"]


def test_layout_lines_out_of_time_order_in_file_are_sorted_by_time():
    ex, lay = fresh()
    lay.pick(20.0, "Р", 60.0, 2)  # в файле позже по времени стоит раньше
    lay.pick(10.0, "Е", 30.0, 1)
    ex.job(10.5, 301, 1, 30.0)
    ex.job(20.5, 302, 2, 60.0)
    res = run(ex, lay)
    assert res.exit_code == 0
    assert [r.net for r in res.rows] == ["30.0", "60.0"]  # строки таблицы идут по времени


def test_job_earlier_than_its_pick_in_time_is_not_taken_by_that_pick():
    ex, lay = fresh()
    lay.pick(10.0, "Е", 30.0, 1)
    ex.job(9.0, 401, 1, 30.0)
    res = run(ex, lay)
    assert res.exit_code == 1
    assert "потеря" in row_of(res, "30.0").reasons
    assert res.jobs == 1


# ------------------------------------------------------------------ смена слова посреди прохода


def test_word_change_cuts_fills_and_upper_bound_stops_theft_of_next_fill_job():
    ex, lay = fresh()
    lay.pick(10.0, "Р", 30.0, 2)  # задание потеряно
    lay.change(30.0, WORD, "МИР")
    lay.pick(40.0, "Р", 60.0, 2)
    ex.job(40.5, 501, 2, 60.0)
    res = run(ex, lay, words=[WORD, "МИР"])
    assert res.exit_code == 1
    assert (res.picks, res.jobs, res.fails) == (2, 1, 1)
    assert row_of(res, "30.0").reasons == ["потеря"]
    assert (row_of(res, "30.0").fill, row_of(res, "60.0").fill) == ("1", "2")
    assert row_of(res, "60.0").result == "PASS"


def test_word_mismatch_between_words_option_and_journal_fails_every_row_of_that_fill():
    ex, lay = fresh()
    lay.pick(10.0, "Е", 30.0, 1)
    lay.skip(15.0, "Б", 5.0, "нет в слове")
    ex.job(10.5, 601, 1, 30.0)
    res = run(ex, lay, words=["БЕРЕМИРИЕ"])
    assert len(res.rows) == 2
    assert all("слово" in r.reasons for r in res.rows)


def test_words_count_mismatch_is_code_2():
    ex, lay = fresh()
    lay.pick(10.0, "Е", 30.0, 1)
    ex.job(10.5, 701, 1, 30.0)
    with pytest.raises(core.AuditError) as err:
        run(ex, lay, words=[WORD, "МИР"])
    assert err.value.code == 2
    assert WORD not in err.value.message


# ------------------------------------------------------------------ поздний ответ R


def test_late_reply_plus80_with_same_status_is_not_a_failure_even_after_next_blocks():
    ex, lay = fresh()
    lay.pick(10.0, "Е", 30.0, 1)
    lay.pick(20.0, "Р", 60.0, 2)
    ex.job(10.5, 801, 1, 30.0)
    ex.job(20.5, 802, 2, 60.0)
    ex.reply(40.0, 801, 1, 0, span="+80")
    res = run(ex, lay)
    assert res.exit_code == 0


def test_late_reply_with_other_errno_is_contradictory_on_the_right_job_only():
    ex, lay = fresh()
    lay.pick(10.0, "Е", 30.0, 1)
    lay.pick(20.0, "Р", 60.0, 2)
    ex.job(10.5, 801, 1, 30.0)
    ex.job(20.5, 802, 2, 60.0)
    ex.reply(40.0, 801, 1, 9, span="+80")
    res = run(ex, lay)
    assert res.exit_code == 1
    assert row_of(res, "30.0").reasons == ["ответ противоречив"]
    assert row_of(res, "60.0").reasons == []


def test_reply_before_command_flag_is_not_the_answer():
    """R с нужным seq раньше блока (чужой, старый) не считается ответом: ответ — после CMD_FLAG."""
    ex, lay = fresh()
    lay.pick(10.0, "Е", 30.0, 1)
    ex.reply(9.0, 901, 1, 0)
    ex.job(10.5, 901, 1, 30.0, status=None)
    res = run(ex, lay)
    assert row_of(res, "30.0").reasons == ["нет ответа"]


# ------------------------------------------------------------------ две инкарнации


def test_two_incarnations_only_last_is_judged_in_both_logs():
    ex, lay = Ex(), Lay()
    ex.connect(0.0)
    lay.init(0.5)
    lay.word(5.0, WORD)
    lay.pick(10.0, "Е", 30.0, 1)  # старая инкарнация: взятие без задания
    ex.job(12.0, 1, 1, 30.0)
    ex.connect(100.0)
    lay.init(100.5)
    lay.word(105.0, WORD)
    lay.pick(110.0, "Р", 60.0, 2)
    ex.job(110.5, 2, 2, 60.0)
    res = run(ex, lay)
    assert res.exit_code == 0
    assert (res.picks, res.jobs) == (1, 1)


# ------------------------------------------------------------------ повтор после отказа (E_BUSY)


def test_busy_retry_chain_two_refusals_then_accept_is_two_retries_and_pass():
    ex, lay = fresh()
    lay.pick(10.0, "Е", 30.0, 1)
    ex.job(10.5, 11, 1, 30.0, status=3, errno=5)
    ex.job(11.5, 12, 1, 30.0, status=3, errno=5)
    ex.job(12.5, 13, 1, 30.0)
    res = run(ex, lay)
    assert res.exit_code == 0
    assert (res.retries, res.jobs, res.picks) == (2, 1, 1)
    assert row_of(res, "30.0").seq == "13"


def test_busy_retry_reusing_the_same_seq_is_not_a_duplicate():
    ex, lay = fresh()
    lay.pick(10.0, "Е", 30.0, 1)
    ex.job(10.5, 11, 1, 30.0, status=3, errno=5)
    ex.job(11.5, 11, 1, 30.0)
    res = run(ex, lay)
    assert res.exit_code == 0
    assert res.retries == 1


def test_refused_job_followed_by_job_with_different_words_is_status_failure():
    ex, lay = fresh()
    lay.pick(10.0, "Е", 30.0, 1)
    lay.pick(20.0, "Р", 60.0, 2)
    ex.job(10.5, 21, 1, 30.0, status=3, errno=5)
    ex.job(20.5, 22, 2, 60.0)
    res = run(ex, lay)
    assert res.exit_code == 1
    assert row_of(res, "30.0").reasons == ["статус 3"]
    assert res.retries == 0


# ------------------------------------------------------------------ рубеж ±180° и паспорта сима


@pytest.mark.parametrize("rz_word", [800, 62736], ids=["plus80", "minus280"])
def test_rz_word_accepted_on_either_side_of_the_180_degree_edge(rz_word):
    """Сеть 180,0 в журнале: провод мог получить 179,96 (rz -279,96) или 180,04 (rz 79,96) — обе стороны верны."""
    ex, lay = fresh()
    lay.pick(10.0, "Е", 180.0, 1)
    ex.job(10.5, 31, 1, 30.0, rz=rz_word)
    res = run(ex, lay)
    assert res.exit_code == 0, res.rows[-1].result


def test_rz_word_off_the_180_edge_by_360_is_still_a_failure_away_from_the_edge():
    ex, lay = fresh()
    lay.pick(10.0, "Е", 30.0, 1)  # rz = -130,0 -> 64236; сдвиг на 360 град (62636) не прощается
    ex.job(10.5, 32, 1, 30.0, rz=64236 - 3600)
    res = run(ex, lay)
    assert res.exit_code == 1
    assert row_of(res, "30.0").reasons == ["rz"]


def test_passports_of_one_letter_go_to_disks_by_time_not_file_order_pick_x_matched():
    """Копия приёмочного сценария с верным px 458.2: порядок паспортов в файле обратный."""
    ex, lay = fresh()
    lay.pick(10.0, "Е", 30.0, 1)
    lay.pick(20.0, "Е", 60.0, 3)
    ex.job(10.5, 41, 1, 30.0)
    ex.job(20.5, 42, 3, 60.0)
    ex_text = ex.text().replace("CMD_ARGS[2] = 4602", "CMD_ARGS[2] = 4582")
    lay_text = lay.text().replace("взять(460.2", "взять(458.2")
    objects = [
        {"object_id": "o2", "class_name": "Е", "angle_deg": 60.0, "lateral_px": 0.0, "t": ts(15.0)},
        {"object_id": "o1", "class_name": "Е", "angle_deg": 30.0, "lateral_px": 0.0, "t": ts(8.0)},
    ]
    res = core.audit(ex_text, lay_text, REGS, words=[WORD], zone_max_mm=600.0, sim_objects=objects)
    assert res.exit_code == 0
    assert [row_of(res, n).result for n in ("30.0", "60.0")] == ["PASS", "PASS"]


def test_pick_x_two_millimetres_off_is_yellow_zone_not_fail():
    """Приёмочный тест `..._time_order_not_file_order` берёт px 460.2: dx = +2,0 мм — жёлтая зона (1; 2], не PASS."""
    ex, lay = fresh()
    lay.pick(10.0, "Е", 30.0, 1)
    ex.job(10.5, 51, 1, 30.0)
    objects = [{"object_id": "o1", "class_name": "Е", "angle_deg": 30.0, "lateral_px": 0.0, "t": ts(8.0)}]
    res = run(ex, lay, sim_objects=objects)
    assert res.exit_code == 0
    assert row_of(res, "30.0").result == "PASS~"
    assert res.warnings == 0


# ------------------------------------------------------------------ реальные файлы через CLI


def _cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "scripts.wire_audit", *args],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
    )


def test_run1_real_files_through_cli_without_parser_fakes(tmp_path):
    out_file = tmp_path / "report.md"
    proc = _cli(
        "--exchange",
        str(FIXTURES / "run1_robot_exchange.txt"),
        "--layout",
        str(FIXTURES / "run1_layout_messages.txt"),
        "--registers",
        str(FIXTURES / "registers.json"),
        "--words",
        "ПЕРЕМИРИЕ,МИР,ПЕРЕМИРИЕ",
        "--zone-max-mm",
        "600",
        "--out",
        str(out_file),
    )
    summary = "ИТОГ: PASS (взятий 15, заданий 15, FAIL 0, пропусков 34, повторов 0, предупреждений 0)"
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().splitlines()[-1] == summary
    assert out_file.read_text(encoding="utf-8") == proc.stdout
    pick_rows = [ln for ln in proc.stdout.splitlines() if ln.startswith("|") and " 1/0 " in ln]
    assert len(pick_rows) == 15
    assert all(ln.rstrip().endswith("| PASS |") for ln in pick_rows)


def test_core_and_cli_do_not_import_alpha():
    for name in ("core.py", "__main__.py"):
        source = (ROOT / "scripts" / "wire_audit" / name).read_text(encoding="utf-8")
        assert "alpha_sim" not in source
