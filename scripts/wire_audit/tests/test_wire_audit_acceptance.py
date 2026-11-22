"""Слепые приёмочные тесты CLI `python -m scripts.wire_audit` (Task 3).

Источник истины — только текст задачи docs/reports/sim-audit/tasks/3.md (DESIGN п.1-15,
ACCEPTANCE). Внутренних функций тесты не знают: каждый тест гонит CLI в подпроцессе и
смотрит на код возврата, итоговую строку `ИТОГ: ...` и ключи причин в таблице.

Ожидаемые числа (слова провода, итоговые строки) — литералы из текста задачи или
ручной арифметики по формулам п.5 и п.8, а не вызовы кода под тестом.

Фикстуры строятся из строк форматов п.2 (журнал обмена), п.4 (журнал диска),
п.10 (паспорта сима) и п.11 (журнал сима). Реальные файлы run1 — отдельные тесты.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
CLI_TIMEOUT_S = 60

WORD = "ПЕРЕМИРИЕ"
LETTER = dict(enumerate(WORD))  # ячейка -> буква слова ПЕРЕМИРИЕ (0 П, 1 Е, 2 Р, 3 Е, 4 М, 5 И, 6 Р, 7 И, 8 Е)

# Регистры run1 (scripts/wire_audit/tests/fixtures/registers.json): first_x 320, first_y -440,
# pitch 2*55 = 110, line_angle 90, place_z = pick_z = -132, angle_zero 0, не инвертирован.
DEFAULT_REGS = {
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

# ARGS[7] (place y) ячеек 0..8, в словах провода (литералы из текста задачи).
Y_WORD = {0: 61136, 1: 62236, 2: 63336, 3: 64436, 4: 0, 5: 1100, 6: 2200, 7: 3300, 8: 4400}
Y_MM = {0: -440.0, 1: -330.0, 2: -220.0, 3: -110.0, 4: 0.0, 5: 110.0, 6: 220.0, 7: 330.0, 8: 440.0}

# ARGS[9] (place rz) по сырому углу сети при DEFAULT_REGS:
# rz = -100 + wrap180(0 - a), слово = round(rz * 10) mod 65536 (ручной счёт; 91.9 -> 63617, 281.5 -> 65321 из текста).
RZ = {
    0.0: 64536,
    5.0: 64486,
    10.0: 64436,
    20.0: 64336,
    30.0: 64236,
    40.0: 64136,
    44.0: 64096,
    46.0: 64076,
    50.0: 64036,
    60.0: 63936,
    70.0: 63836,
    80.0: 63736,
    90.0: 63636,
    91.9: 63617,
    100.0: 63536,
    110.0: 63436,
    120.0: 63336,
    240.0: 200,
    250.0: 100,
    260.0: 0,
    281.5: 65321,
    280.0: 65336,
    290.0: 65236,
    300.0: 65136,
    310.0: 65036,
    320.0: 64936,
    330.0: 64836,
}

SUMMARY_RE = re.compile(
    r"^ИТОГ: (PASS|FAIL) \(взятий (\d+), заданий (\d+), FAIL (\d+), "
    r"пропусков (\d+), повторов (\d+), предупреждений (\d+)\)$"
)
HEADER_ROW = "| # | заливка | буква | сеть° | ячейка | x | y | rz | ecap | seq | ответ | А | Б | итог |"

COL_FILL, COL_LETTER, COL_NET, COL_CELL = 1, 2, 3, 4
COL_ECAP, COL_SEQ, COL_ANSWER, COL_A, COL_B, COL_RESULT = 8, 9, 10, 11, 12, 13


# ---------------------------------------------------------------- генераторы строк журналов


def ts(t: float) -> str:
    """Секунды от 2026-11-12 13:30:00 -> `2026-11-12 13:30:10,300`."""
    dt = datetime(2026, 11, 12, 13, 30, 0) + timedelta(milliseconds=round(t * 1000))
    return dt.strftime("%Y-%m-%d %H:%M:%S") + f",{dt.microsecond // 1000:03d}"


class Exchange:
    """Журнал обмена по п.2: `#<строка> <дата> <время> [INFO] S.d.d.e.robot_main: #<n> in|out ...`."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self._fileno = 40
        self._n = 0

    def _emit(self, t: float, text: str, n: int | None = None) -> None:
        self._fileno += 1
        if n is None:
            self._n += 1
            n = self._n
        self.lines.append(f"#{self._fileno} {ts(t)} [INFO] S.d.d.e.robot_main: #{n} {text}")

    def connect(self, t: float) -> None:
        """Открывает инкарнацию: номер n = 1 (`#1  connect ok`)."""
        self._n = 0
        self._emit(t, " connect ok")

    def reply(self, t: float, seq: int, status: int = 1, errno: int = 0, span: str = "+12") -> None:
        label = "ОК" if (status, errno) == (1, 0) else "ошибка"
        self._emit(
            t,
            f"out R RES_SEQ..{span} RES_SEQ = {seq}, RES_STATUS = {status}, RES_ERRNO = {errno} ({label})",
        )

    def block(
        self,
        t: float,
        seq: int,
        opcode: int,
        name: str,
        args: list[int],
        *,
        argc: int | None = None,
        omit: tuple[int, ...] = (),
        reply: bool = True,
        status: int = 1,
        errno: int = 0,
        reply_dt: float = 0.026,
    ) -> None:
        self._emit(t, f"in W* CMD_SEQ = {seq}")
        self._emit(t, f"in W* CMD_OPCODE = {opcode} ({name})")
        self._emit(t, f"in W* CMD_ARGC = {len(args) if argc is None else argc}")
        for i, word in enumerate(args):
            if i not in omit:
                self._emit(t, f"in W* CMD_ARGS[{i}] = {word}")
        self._emit(t, "in W CMD_FLAG = 1")
        if reply:
            self.reply(t + reply_dt, seq, status, errno)

    def job(self, t: float, seq: int, args: list[int], **kw) -> None:
        self.block(t, seq, 32, "CVT_JOB", args, **kw)

    def noise(self, t: float) -> None:
        """Строки, которые разборщик обязан пропускать молча (п.2)."""
        self._emit(t, "in W 0x1200 = 5")
        self._emit(t, "in W 0x1204 = 1")
        self._emit(t, "in W SC_BUF[2] = 7")
        self._emit(t, "in W STOP_REQ = 1")
        self._emit(t, "out R RES_SEQ..+80 RES_SEQ = 0, RES_STATUS = 0, RES_ERRNO = 0 (ОК)")
        self.lines.append(f"#{self._fileno + 1} {ts(t)} [INFO] S.d.d.e.robot_main: #{self._n} … ×16")
        self._fileno += 1
        self._emit(t, " disconnect")

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


class Layout:
    """Журнал диска по п.4: `#<строка> <дата> <время> [INFO] [layout] word_layout: WordLayoutPlugin: ...`."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self._fileno = 0

    def _emit(self, t: float, src: str, text: str) -> None:
        self._fileno += 1
        self.lines.append(f"#{self._fileno} {ts(t)} [INFO] {src} {text}")

    def init(self, t: float) -> None:
        self._emit(t, "[-] logger_manager:", "LoggerManager initialized")

    def word(self, t: float, word: str) -> None:
        self._emit(t, "[layout] word_layout:", f"WordLayoutPlugin: слово '{word}' (источник: регистр)")

    def change(self, t: float, old: str, new: str, filled: int = 1, of: int = 9) -> None:
        self._emit(
            t,
            "[layout] word_layout:",
            f"WordLayoutPlugin: смена слова '{old}' → '{new}' (источник: регистр) — "
            f"ячейки с нуля (было заполнено {filled}/{of})",
        )

    def pick(
        self,
        t: float,
        letter: str,
        net: float,
        cell: int,
        *,
        px: float = 460.2,
        py: float = -343.2,
        place: tuple[float, float, float] | None = None,
        r: float | None = None,
        idx: int = 1,
        of: int = 9,
    ) -> None:
        corr = ((-net + 180.0) % 360.0) - 180.0
        pl_x, pl_y, pl_z = place if place is not None else (320.0, Y_MM[cell], -132.0)
        r_txt = corr if r is None else r
        self._emit(
            t,
            "[layout] word_layout:",
            f"WordLayoutPlugin: диск '{letter}' {net:.1f}° → ячейка {cell}: взять({px:.1f},{py:.1f}) → "
            f"положить x{pl_x:.1f} y{pl_y:.1f} z{pl_z:.1f} r{r_txt:.1f}° [{idx}/{of}]",
        )

    def skip(self, t: float, letter: str, net: float, reason: str) -> None:
        self._emit(
            t,
            "[layout] word_layout:",
            f"WordLayoutPlugin: диск '{letter}' {net:.1f}° → пропуск: {reason}",
        )

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


def jargs(cell: int, net: float, ov: dict[int, int] | None = None) -> list[int]:
    """Слова CVT_JOB при DEFAULT_REGS: pick (460.2, -343.2, z -132), flags 3, place по ячейке."""
    args = [18178, 1, 4602, 62104, 64216, 3, 3200, Y_WORD[cell], 64216, RZ[net]]
    for i, v in (ov or {}).items():
        args[i] = v
    return args


# ---------------------------------------------------------------- прогон CLI


@dataclass
class Result:
    code: int
    out: str
    err: str

    @property
    def both(self) -> str:
        return self.out + "\n" + self.err

    @property
    def line(self) -> str:
        found = [ln.strip() for ln in self.out.splitlines() if ln.strip().startswith("ИТОГ:")]
        assert found, f"нет строки ИТОГ; код {self.code}\nstdout:\n{self.out[-1500:]}\nstderr:\n{self.err[-1500:]}"
        return found[-1]

    def summary(self) -> dict:
        m = SUMMARY_RE.match(self.line)
        assert m, f"строка ИТОГ не по формату п.13: {self.line!r}"
        keys = ("verdict", "picks", "jobs", "fail", "skips", "retries", "warnings")
        return {k: (v if k == "verdict" else int(v)) for k, v in zip(keys, m.groups())}

    def rows(self) -> list[list[str]]:
        found = []
        for ln in self.out.splitlines():
            s = ln.strip()
            if not s.startswith("|"):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) == 14 and cells[0].isdigit():
                found.append(cells)
        return found

    def row_by_net(self, net: str) -> list[str]:
        hits = [r for r in self.rows() if r[COL_NET] == net]
        assert len(hits) == 1, f"строк с сетью {net}: {len(hits)}\n{self.out[-2500:]}"
        return hits[0]


def has_reason(result_cell: str, key: str) -> bool:
    """Последняя ячейка таблицы `FAIL: <причина>[; <причина>]` содержит причину с ключом key."""
    if not result_cell.startswith("FAIL"):
        return False
    body = result_cell.split(":", 1)[1] if ":" in result_cell else ""
    return any(re.match(re.escape(key) + r"(?!\w)", r.strip()) for r in body.split(";"))


def run_cli(args: list[str]) -> Result:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "scripts.wire_audit", *args],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=CLI_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"CLI завис дольше {CLI_TIMEOUT_S} с")
    if "No module named" in proc.stderr and "wire_audit" in proc.stderr:
        pytest.fail(f"CLI-модуль scripts.wire_audit не найден (ModuleNotFoundError): {proc.stderr.strip()[-300:]}")
    return Result(proc.returncode, proc.stdout, proc.stderr)


class Case:
    """Один прогон: журналы обмена и диска в tmp_path и файл регистров."""

    def __init__(self, tmp_path: Path, regs: dict | None = None) -> None:
        self.tmp = tmp_path
        self.ex = Exchange()
        self.lay = Layout()
        self.regs = dict(DEFAULT_REGS if regs is None else regs)

    def files(self) -> tuple[Path, Path, Path]:
        ex = self.tmp / "exchange.log"
        lay = self.tmp / "messages.log"
        regs = self.tmp / "registers.json"
        ex.write_text(self.ex.text(), encoding="utf-8")
        lay.write_text(self.lay.text(), encoding="utf-8")
        regs.write_text(json.dumps(self.regs), encoding="utf-8")
        return ex, lay, regs

    def base_args(self) -> list[str]:
        ex, lay, regs = self.files()
        return ["--exchange", str(ex), "--layout", str(lay), "--registers", str(regs)]

    def run(self, *extra: str) -> Result:
        return run_cli(self.base_args() + list(extra))


def fresh(tmp_path: Path, *, word: str | None = WORD, regs: dict | None = None) -> Case:
    """Инкарнация обмена (connect ok) и диска (LoggerManager initialized), слово задано в t=5."""
    c = Case(tmp_path, regs)
    c.ex.connect(0.0)
    c.lay.init(0.5)
    if word is not None:
        c.lay.word(5.0, word)
    return c


def add_pick_job(
    c: Case,
    t: float,
    letter: str,
    net: float,
    cell: int,
    *,
    seq: int,
    ov: dict[int, int] | None = None,
    px: float = 460.2,
    job: bool = True,
    **job_kw,
) -> None:
    """Строка взятия в t и задание через 0.3 с (допуск п.6: время задания >= времени взятия)."""
    c.lay.pick(t, letter, net, cell, px=px)
    if job:
        c.ex.job(t + 0.3, seq, jargs(cell, net, ov), **job_kw)


def write_jsonl(path: Path, items: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(i, ensure_ascii=False) for i in items) + "\n", encoding="utf-8")
    return path


# ================================================================= (а) PASS-путь и формат вывода


def test_a_one_pick_one_job_correct_words_pass(tmp_path):
    c = fresh(tmp_path)
    add_pick_job(c, 10.0, "Е", 91.9, 3, seq=60466)
    res = c.run("--words", WORD)
    assert res.code == 0
    assert res.line == "ИТОГ: PASS (взятий 1, заданий 1, FAIL 0, пропусков 0, повторов 0, предупреждений 0)"


def test_a_example_row_has_columns_from_p13(tmp_path):
    """Пример строки п.13: Е 91.9, ячейка 3, ecap 18178/1 -> 83714, seq 60466, ответ 1/0, А PASS, Б '-'."""
    c = fresh(tmp_path)
    add_pick_job(c, 10.0, "Е", 91.9, 3, seq=60466)
    res = c.run("--words", WORD)
    assert res.code == 0
    row = res.row_by_net("91.9")
    assert row[COL_FILL] == "1"
    assert row[COL_LETTER] == "Е"
    assert row[COL_CELL] == "3"
    assert row[5:8] == ["320.0", "-110.0", "-191.9"]
    assert row[COL_ECAP] == "83714"
    assert row[COL_SEQ] == "60466"
    assert row[COL_ANSWER] == "1/0"
    assert row[COL_A] == "PASS"
    assert row[COL_B] == "-"
    assert row[COL_RESULT] == "PASS"


def test_table_header_is_exact(tmp_path):
    c = fresh(tmp_path)
    add_pick_job(c, 10.0, "Е", 91.9, 3, seq=60466)
    res = c.run("--words", WORD)
    assert HEADER_ROW in [ln.strip() for ln in res.out.splitlines()]


@pytest.mark.parametrize(
    ("args01", "ecap"),
    [([18178, 1], "83714"), ([65297, 0], "65297"), ([2041, 1], "67577")],
)
def test_a_ecap_column_is_hi_times_65536_plus_lo(tmp_path, args01, ecap):
    c = fresh(tmp_path)
    c.lay.pick(10.0, "Е", 91.9, 3)
    c.ex.job(10.3, 60466, jargs(3, 91.9, {0: args01[0], 1: args01[1]}))
    res = c.run("--words", WORD)
    assert res.code == 0
    assert res.row_by_net("91.9")[COL_ECAP] == ecap


def test_header_marks_word_as_not_independent_without_words(tmp_path):
    c = fresh(tmp_path)
    add_pick_job(c, 10.0, "Е", 91.9, 3, seq=60466)
    res = c.run()
    assert res.code == 0
    assert "слово не независимо" in res.out


def test_header_has_no_dependence_note_with_words(tmp_path):
    c = fresh(tmp_path)
    add_pick_job(c, 10.0, "Е", 91.9, 3, seq=60466)
    res = c.run("--words", WORD)
    assert res.code == 0
    assert "слово не независимо" not in res.out


def test_header_prints_word_p_pick_and_zone_limit(tmp_path):
    regs = dict(DEFAULT_REGS, p_pick_rz_deg=-87.5)
    c = fresh(tmp_path, regs=regs)
    c.lay.pick(10.0, "Е", 30.0, 3)
    # rz = -87.5 + wrap180(0 - 30) = -117.5 -> -1175 -> 64361
    c.ex.job(10.3, 60466, jargs(3, 30.0, {9: 64361}))
    res = c.run("--words", WORD, "--zone-max-mm", "543.5")
    assert res.code == 0
    assert WORD in res.out
    assert "-87.5" in res.out
    assert "543.5" in res.out


def test_p_pick_rz_defaults_to_minus_100_when_absent(tmp_path):
    regs = {k: v for k, v in DEFAULT_REGS.items() if k != "p_pick_rz_deg"}
    c = fresh(tmp_path, regs=regs)
    add_pick_job(c, 10.0, "Е", 91.9, 3, seq=60466)  # слово 63617 = -191.9 = -100 + (-91.9)
    res = c.run("--words", WORD)
    assert res.code == 0
    assert res.summary()["fail"] == 0


def test_expectations_come_from_registers_not_from_defaults(tmp_path):
    """line_angle 0, pitch_mm 100, инверсия угла, свои z и p_pick_rz; ячейка 3, a=40:
    x = 100+3*100 = 400.0 -> 4000; y = -200 -> 63536; place z -100 -> 64536; pick z -120 -> 64336;
    rz = -90 + wrap180(10 - (-1)*40) = -40.0 -> -400 -> 65136."""
    regs = dict(
        DEFAULT_REGS,
        first_x=100.0,
        first_y=-200.0,
        pitch_mm=100.0,
        line_angle_deg=0.0,
        place_z_mm=-100.0,
        pick_z_mm=-120.0,
        angle_zero_deg=10.0,
        angle_invert=True,
        p_pick_rz_deg=-90.0,
    )
    c = fresh(tmp_path, regs=regs)
    c.lay.pick(10.0, "Е", 40.0, 3, place=(400.0, -200.0, -100.0), r=50.0)
    c.ex.job(10.3, 60466, [18178, 1, 4602, 62104, 64336, 3, 4000, 63536, 64536, 65136])
    res = c.run("--words", WORD)
    assert res.code == 0
    assert res.line == "ИТОГ: PASS (взятий 1, заданий 1, FAIL 0, пропусков 0, повторов 0, предупреждений 0)"


def test_pitch_falls_back_to_twice_disk_radius_when_pitch_mm_zero(tmp_path):
    """pitch_mm 0, disk_radius 60 -> шаг 120; ячейка 2 при line_angle 90: y = -440 + 240 = -200 -> 63536."""
    regs = dict(DEFAULT_REGS, disk_radius_mm=60.0, pitch_mm=0.0)
    c = fresh(tmp_path, regs=regs)
    c.lay.pick(10.0, "Р", 30.0, 2, place=(320.0, -200.0, -132.0))
    c.ex.job(10.3, 60466, jargs(2, 30.0, {7: 63536}))
    res = c.run("--words", WORD)
    assert res.code == 0
    assert res.summary()["fail"] == 0


def test_expectations_do_not_come_from_place_fields_of_the_layout_line(tmp_path):
    """П.8: ожидания из регистров, слова и сырого угла, не из полей `положить`/`взять`."""
    c = fresh(tmp_path)
    c.lay.pick(10.0, "Е", 91.9, 3, place=(999.0, 999.0, 0.0), r=5.0)
    c.ex.job(10.3, 60466, jargs(3, 91.9))
    res = c.run("--words", WORD)
    assert res.code == 0
    assert res.summary()["fail"] == 0


def test_out_option_writes_report_file(tmp_path):
    c = fresh(tmp_path)
    add_pick_job(c, 10.0, "Е", 91.9, 3, seq=60466)
    out_path = tmp_path / "report.md"
    res = c.run("--words", WORD, "--out", str(out_path))
    assert res.code == 0
    text = out_path.read_text(encoding="utf-8")
    assert "ИТОГ: PASS (взятий 1, заданий 1, FAIL 0, пропусков 0, повторов 0, предупреждений 0)" in text
    assert HEADER_ROW in text


# ================================================================= (б) квант ARGS[7]


@pytest.mark.parametrize("delta", [1, -1])
def test_b_args7_off_by_one_quantum_fails(tmp_path, delta):
    c = fresh(tmp_path)
    add_pick_job(c, 10.0, "Е", 91.9, 3, seq=60466, ov={7: 64436 + delta})
    res = c.run("--words", WORD)
    assert res.code == 1
    s = res.summary()
    assert s["verdict"] == "FAIL"
    assert s["fail"] >= 1
    assert "потеря" in res.out or "ячейка" in res.out


# ================================================================= (в) знак и слова rz


@pytest.mark.parametrize(
    ("net", "cell", "good", "flipped"),
    [(91.9, 3, 63617, 1919), (281.5, 4, 65321, 215)],
)
def test_v_rz_word_matches_literal_and_sign_flip_fails(tmp_path, net, cell, good, flipped):
    good_dir = tmp_path / "good"
    good_dir.mkdir()
    ok = fresh(good_dir)
    ok.lay.pick(10.0, LETTER[cell], net, cell)
    ok.ex.job(10.3, 60466, jargs(cell, net, {9: good}))
    res_ok = ok.run("--words", WORD)
    assert res_ok.code == 0
    assert res_ok.summary()["fail"] == 0

    sub = tmp_path / "bad"
    sub.mkdir()
    bad = fresh(sub)
    bad.lay.pick(10.0, LETTER[cell], net, cell)
    bad.ex.job(10.3, 60466, jargs(cell, net, {9: flipped}))
    res_bad = bad.run("--words", WORD)
    assert res_bad.code == 1
    assert has_reason(res_bad.row_by_net(f"{net:.1f}")[COL_RESULT], "rz")


@pytest.mark.parametrize(
    ("index", "word", "key", "ok"),
    [
        (9, 63618, "rz", True),  # +1 квант = 0.1 град, допуск 0.10 + 1e-6
        (9, 63619, "rz", False),  # +2 кванта = 0.2 град
        (6, 3201, "x", True),
        (6, 3202, "x", False),
        (8, 64217, "z", True),  # place z
        (8, 64218, "z", False),
        (4, 64217, "z", True),  # pick z
        (4, 64218, "z", False),
    ],
)
def test_column_a_tolerance_is_one_quantum_wide(tmp_path, index, word, key, ok):
    c = fresh(tmp_path)
    c.lay.pick(10.0, "Е", 91.9, 3)
    c.ex.job(10.3, 60466, jargs(3, 91.9, {index: word}))
    res = c.run("--words", WORD)
    cell = res.row_by_net("91.9")[COL_RESULT]
    if ok:
        assert res.code == 0
        assert cell.startswith("PASS")
    else:
        assert res.code == 1
        assert has_reason(cell, key)


def test_flags_word_other_than_3_fails(tmp_path):
    c = fresh(tmp_path)
    c.lay.pick(10.0, "Е", 91.9, 3)
    c.ex.job(10.3, 60466, jargs(3, 91.9, {5: 1}))
    res = c.run("--words", WORD)
    assert res.code == 1
    assert res.summary()["fail"] >= 1
    assert res.row_by_net("91.9")[COL_RESULT].startswith("FAIL")


@pytest.mark.parametrize(
    ("index", "word", "key", "ok"),
    [
        (2, 4549, "окно", True),
        (2, 4548, "окно", False),
        (2, 4615, "окно", True),
        (2, 4616, "окно", False),
        (3, 62096, "окно", True),
        (3, 62095, "окно", False),
        (3, 62116, "окно", True),
        (3, 62117, "окно", False),
    ],
)
def test_alpha_window_on_pick_words_boundaries(tmp_path, index, word, key, ok):
    """Окно α: ARGS[2] in 4549..4615, ARGS[3] in 62096..62116 (границы с обеих сторон).
    Строка диска несёт те же значения, поэтому `передача` не срабатывает."""
    px = (word if index == 2 else 4602) / 10.0
    py = ((word if index == 3 else 62104) - 65536) / 10.0
    c = fresh(tmp_path)
    c.lay.pick(10.0, "Е", 91.9, 3, px=px, py=py)
    c.ex.job(10.3, 60466, jargs(3, 91.9, {index: word}))
    res = c.run("--words", WORD)
    cell = res.row_by_net("91.9")[COL_RESULT]
    if ok:
        assert res.code == 0, res.out
        assert cell.startswith("PASS")
    else:
        assert res.code == 1
        assert has_reason(cell, key)


@pytest.mark.parametrize(
    ("word", "ok"),
    [(4602, True), (4604, False), (4612, False)],  # слово против взять(460.2,...): допуск 0.10
)
def test_pick_words_must_match_layout_line_transfer(tmp_path, word, ok):
    c = fresh(tmp_path)
    c.lay.pick(10.0, "Е", 91.9, 3, px=460.2)
    c.ex.job(10.3, 60466, jargs(3, 91.9, {2: word}))
    res = c.run("--words", WORD)
    cell = res.row_by_net("91.9")[COL_RESULT]
    if ok:
        assert res.code == 0
        assert cell.startswith("PASS")
    else:
        assert res.code == 1
        assert has_reason(cell, "передача")


# ================================================================= (г) лишнее, потеря, дубль seq


def test_g_two_jobs_with_same_args7_for_one_pick_extra_job_fails(tmp_path):
    c = fresh(tmp_path)
    c.lay.pick(10.0, "Е", 91.9, 3)
    c.ex.job(10.3, 60466, jargs(3, 91.9))
    c.ex.job(11.3, 60467, jargs(3, 91.9))
    res = c.run("--words", WORD)
    assert res.code == 1
    s = res.summary()
    assert (s["picks"], s["jobs"], s["fail"]) == (1, 2, 1)
    assert has_reason(res.row_by_net("91.9")[COL_RESULT], "лишнее")


def test_g_pick_without_job_fails_as_lost(tmp_path):
    c = fresh(tmp_path)
    add_pick_job(c, 10.0, "Е", 91.9, 3, seq=60466)
    c.lay.pick(20.0, "Р", 30.0, 2)  # задания нет
    res = c.run("--words", WORD)
    assert res.code == 1
    s = res.summary()
    assert (s["picks"], s["jobs"], s["fail"]) == (2, 1, 1)
    assert has_reason(res.row_by_net("30.0")[COL_RESULT], "потеря")
    assert res.row_by_net("91.9")[COL_RESULT] == "PASS"


def test_g_two_jobs_with_same_cmd_seq_fail_as_duplicate(tmp_path):
    c = fresh(tmp_path)
    add_pick_job(c, 10.0, "Е", 91.9, 3, seq=60466)
    add_pick_job(c, 20.0, "Е", 30.0, 1, seq=60466)
    res = c.run("--words", WORD)
    assert res.code == 1
    assert res.summary()["fail"] >= 1
    assert "дубль seq" in res.out


# ================================================================= (д) ответ задания


def test_d_job_without_reply_fails_and_neighbour_reply_is_not_borrowed(tmp_path):
    c = fresh(tmp_path)
    c.lay.pick(10.0, "Е", 91.9, 3)
    c.ex.job(10.3, 8001, jargs(3, 91.9), reply=False)
    c.lay.pick(20.0, "Е", 30.0, 1)
    c.ex.job(20.3, 8002, jargs(1, 30.0))  # ответ на другой seq идёт сразу за первым заданием
    res = c.run("--words", WORD)
    assert res.code == 1
    assert res.summary()["fail"] == 1
    assert has_reason(res.row_by_net("91.9")[COL_RESULT], "нет ответа")
    assert res.row_by_net("30.0")[COL_RESULT] == "PASS"


def test_d_second_reply_plus80_with_same_status_is_not_a_failure(tmp_path):
    c = fresh(tmp_path)
    add_pick_job(c, 10.0, "Е", 91.9, 3, seq=8001)
    add_pick_job(c, 20.0, "Е", 30.0, 1, seq=8002)
    c.ex.reply(35.0, 8001, 1, 0, span="+80")  # поздний RES_SEQ..+80 с теми же статусом и errno
    res = c.run("--words", WORD)
    assert res.code == 0
    assert res.line == "ИТОГ: PASS (взятий 2, заданий 2, FAIL 0, пропусков 0, повторов 0, предупреждений 0)"


@pytest.mark.parametrize(("status", "errno"), [(2, 0), (1, 7)], ids=["other-status", "other-errno"])
def test_d_second_reply_with_other_status_or_errno_is_contradictory(tmp_path, status, errno):
    c = fresh(tmp_path)
    add_pick_job(c, 10.0, "Е", 91.9, 3, seq=8001)
    add_pick_job(c, 20.0, "Е", 30.0, 1, seq=8002)
    c.ex.reply(35.0, 8001, status, errno, span="+80")
    res = c.run("--words", WORD)
    assert res.code == 1
    assert res.summary()["verdict"] == "FAIL"
    assert "ответ противоречив" in res.out


# ================================================================= (е) пропуски и пустые задания


def test_e_only_skip_rows_and_no_jobs_pass(tmp_path):
    c = Case(tmp_path)
    c.ex.connect(0.0)
    c.ex.block(1.0, 1900, 80, "PARAM_SET", [0, 80])
    c.lay.init(0.5)
    c.lay.skip(2.0, "Ш", 160.5, "слово не задано")
    c.lay.skip(3.0, "Ю", 356.6, "слово не задано")
    c.lay.skip(4.0, "Ч", 335.7, "слово не задано")
    res = c.run()
    assert res.code == 0
    assert res.line == "ИТОГ: PASS (взятий 0, заданий 0, FAIL 0, пропусков 3, повторов 0, предупреждений 0)"


def test_e_pick_without_any_job_is_code_1_not_3(tmp_path):
    c = fresh(tmp_path)
    c.ex.block(1.0, 1900, 80, "PARAM_SET", [0, 80])
    c.lay.pick(10.0, "Е", 91.9, 3)
    res = c.run("--words", WORD)
    assert res.code == 1
    s = res.summary()
    assert (s["verdict"], s["picks"], s["jobs"], s["fail"]) == ("FAIL", 1, 0, 1)
    assert "потеря" in res.out


# ================================================================= (ж) целостность провода


def test_zh_argc_9_fails(tmp_path):
    c = fresh(tmp_path)
    c.lay.pick(10.0, "Е", 91.9, 3)
    c.ex.job(10.3, 60466, jargs(3, 91.9), argc=9)
    res = c.run("--words", WORD)
    assert res.code == 1
    assert has_reason(res.row_by_net("91.9")[COL_RESULT], "argc")


def test_zh_missing_args5_fails(tmp_path):
    c = fresh(tmp_path)
    c.lay.pick(10.0, "Е", 91.9, 3)
    c.ex.job(10.3, 60466, jargs(3, 91.9), omit=(5,))
    res = c.run("--words", WORD)
    assert res.code == 1
    assert "нет ARGS[5]" in res.out


# ================================================================= (з) две инкарнации


def _incarnation(c: Case, t0: float, *, with_job: bool) -> None:
    c.ex.connect(t0)
    c.lay.init(t0 + 0.5)
    c.lay.word(t0 + 5.0, WORD)
    c.lay.pick(t0 + 10.0, "Е", 91.9, 3)
    if with_job:
        c.ex.job(t0 + 10.3, 60466, jargs(3, 91.9))


def test_z_only_last_incarnation_is_judged_old_one_broken(tmp_path):
    c = Case(tmp_path)
    _incarnation(c, 0.0, with_job=False)  # старая: взятие без задания
    c.ex.job(12.0, 111, jargs(4, 0.0))  # и лишнее задание в старой инкарнации обмена
    _incarnation(c, 100.0, with_job=True)
    res = c.run("--words", WORD)
    assert res.code == 0
    assert res.line == "ИТОГ: PASS (взятий 1, заданий 1, FAIL 0, пропусков 0, повторов 0, предупреждений 0)"


def test_z_only_last_incarnation_is_judged_new_one_broken(tmp_path):
    c = Case(tmp_path)
    _incarnation(c, 0.0, with_job=True)
    _incarnation(c, 100.0, with_job=False)
    res = c.run("--words", WORD)
    assert res.code == 1
    s = res.summary()
    assert (s["verdict"], s["picks"], s["jobs"], s["fail"]) == ("FAIL", 1, 0, 1)


# ================================================================= (и) блоки других команд


def test_i_servo_sc_run_stop_req_blocks_are_not_jobs(tmp_path):
    c = fresh(tmp_path)
    c.ex.block(1.0, 9001, 65, "SERVO", [1])
    c.ex.block(2.0, 9002, 48, "SC_RUN", jargs(3, 91.9))  # десять слов, похожих на задание
    add_pick_job(c, 10.0, "Е", 91.9, 3, seq=60466)
    c.ex.block(12.0, 9003, 99, "STOP_REQ", [])
    c.ex.block(13.0, 9004, 48, "SC_RUN", jargs(3, 91.9))
    c.ex.block(14.0, 9005, 65, "SERVO", [0])
    res = c.run("--words", WORD)
    assert res.code == 0
    assert res.line == "ИТОГ: PASS (взятий 1, заданий 1, FAIL 0, пропусков 0, повторов 0, предупреждений 0)"


def test_noise_lines_are_skipped_silently(tmp_path):
    c = fresh(tmp_path)
    c.ex.noise(1.0)
    add_pick_job(c, 10.0, "Е", 91.9, 3, seq=60466)
    c.ex.noise(11.0)
    res = c.run("--words", WORD)
    assert res.code == 0
    assert res.line == "ИТОГ: PASS (взятий 1, заданий 1, FAIL 0, пропусков 0, повторов 0, предупреждений 0)"


# ================================================================= (к) верхняя граница привязки


def test_k_deleted_job_does_not_steal_next_fill_job(tmp_path):
    """Заливка 1: взятие Р (ячейка 2) без задания. Смена слова. Заливка 2: Р (ячейка 2) с заданием.
    Без верхней границы п.6 задание второй заливки досталось бы первому взятию."""
    c = fresh(tmp_path)
    c.lay.pick(10.0, "Р", 10.0, 2)  # задание удалено
    c.lay.change(30.0, WORD, "МИР", 1, 9)
    c.lay.pick(40.0, "Р", 20.0, 2)
    c.ex.job(40.3, 7002, jargs(2, 20.0))
    res = c.run("--words", f"{WORD},МИР")
    assert res.code == 1
    s = res.summary()
    assert (s["picks"], s["jobs"], s["fail"]) == (2, 1, 1)
    first = res.row_by_net("10.0")
    second = res.row_by_net("20.0")
    assert has_reason(first[COL_RESULT], "потеря")
    assert second[COL_RESULT] == "PASS"
    assert second[COL_SEQ] == "7002"
    assert (first[COL_FILL], second[COL_FILL]) == ("1", "2")


# ================================================================= привязка: время, лишнее, заливки


def test_bind_job_earlier_than_pick_is_not_a_candidate(tmp_path):
    """П.6: допуск -50 мс убран, задание на 40 мс раньше взятия не привязывается."""
    c = fresh(tmp_path)
    c.lay.pick(10.0, "Е", 91.9, 3)
    c.ex.job(9.960, 60466, jargs(3, 91.9))
    res = c.run("--words", WORD)
    assert res.code == 1
    assert has_reason(res.row_by_net("91.9")[COL_RESULT], "потеря")
    assert "лишнее" in res.out


def test_bind_job_at_same_timestamp_as_pick_binds(tmp_path):
    c = fresh(tmp_path)
    c.lay.pick(10.0, "Е", 91.9, 3)
    c.ex.job(10.0, 60466, jargs(3, 91.9))
    res = c.run("--words", WORD)
    assert res.code == 0
    assert res.summary()["fail"] == 0


def test_extra_job_after_skip_row_is_marked_after_skip(tmp_path):
    c = fresh(tmp_path)
    add_pick_job(c, 10.0, "Е", 91.9, 3, seq=60466)
    c.lay.skip(20.0, "Б", 5.0, f"нет в слове '{WORD}'")
    c.ex.job(25.0, 60467, jargs(4, 0.0))  # слово ячейки 4, ни одно взятие его не ждёт
    res = c.run("--words", WORD)
    assert res.code == 1
    skip_row = res.row_by_net("5.0")
    assert has_reason(skip_row[COL_RESULT], "лишнее")
    assert "после пропуска" in "|".join(skip_row)


def test_extra_job_before_first_disk_row_is_marked_before_first_pick(tmp_path):
    c = fresh(tmp_path)
    c.ex.job(1.0, 60400, jargs(4, 0.0))
    add_pick_job(c, 10.0, "Е", 91.9, 3, seq=60466)
    res = c.run("--words", WORD)
    assert res.code == 1
    assert "лишнее" in res.out
    assert "до первого взятия" in res.out


def test_fill_numbers_zero_before_first_word_then_cut_by_word_change(tmp_path):
    c = Case(tmp_path)
    c.ex.connect(0.0)
    c.lay.init(0.5)
    c.lay.skip(2.0, "Ш", 160.5, "слово не задано")
    c.lay.word(5.0, WORD)
    add_pick_job(c, 10.0, "Е", 91.9, 3, seq=7001)
    c.lay.change(30.0, WORD, "МИР", 1, 9)
    add_pick_job(c, 40.0, "Р", 20.0, 2, seq=7002)
    res = c.run("--words", f"{WORD},МИР")
    assert res.code == 0
    assert res.line == "ИТОГ: PASS (взятий 2, заданий 2, FAIL 0, пропусков 1, повторов 0, предупреждений 0)"
    assert res.row_by_net("160.5")[COL_FILL] == "0"
    assert res.row_by_net("160.5")[COL_RESULT] == "PASS"
    assert res.row_by_net("91.9")[COL_FILL] == "1"
    assert res.row_by_net("20.0")[COL_FILL] == "2"


# ================================================================= (л) повтор после отказа


def test_l_retry_after_refusal_passes_and_counts_one_retry(tmp_path):
    c = fresh(tmp_path)
    c.lay.pick(10.0, "Е", 91.9, 3)
    c.ex.job(10.3, 7001, jargs(3, 91.9), status=3, errno=5)
    c.ex.job(11.3, 7002, jargs(3, 91.9))
    res = c.run("--words", WORD)
    assert res.code == 0
    s = res.summary()
    assert (s["verdict"], s["picks"], s["fail"], s["retries"]) == ("PASS", 1, 0, 1)
    assert res.row_by_net("91.9")[COL_RESULT] == "PASS"


def test_l_refusal_without_retry_fails_with_status(tmp_path):
    c = fresh(tmp_path)
    c.lay.pick(10.0, "Е", 91.9, 3)
    c.ex.job(10.3, 7001, jargs(3, 91.9), status=3, errno=5)
    res = c.run("--words", WORD)
    assert res.code == 1
    s = res.summary()
    assert (s["verdict"], s["retries"]) == ("FAIL", 0)
    assert has_reason(res.row_by_net("91.9")[COL_RESULT], "статус 3")


def test_l_refusal_followed_by_job_with_other_args_is_not_a_retry(tmp_path):
    c = fresh(tmp_path)
    c.lay.pick(10.0, "Е", 91.9, 3)
    c.ex.job(10.3, 7001, jargs(3, 91.9), status=3, errno=5)
    c.lay.pick(20.0, "Е", 30.0, 1)
    c.ex.job(20.3, 7002, jargs(1, 30.0))
    res = c.run("--words", WORD)
    assert res.code == 1
    s = res.summary()
    assert s["retries"] == 0
    assert has_reason(res.row_by_net("91.9")[COL_RESULT], "статус 3")
    assert res.row_by_net("30.0")[COL_RESULT] == "PASS"


# ================================================================= (м) повтор буквы Е x3


def _e_three_times(c: Case) -> None:
    """Е 30 -> ячейка 1, Е 60 -> ячейка 3, Е 90 -> ячейка 8, четвёртое Е 120 -> пропуск."""
    add_pick_job(c, 10.0, "Е", 30.0, 1, seq=6001)
    add_pick_job(c, 20.0, "Е", 60.0, 3, seq=6002)
    add_pick_job(c, 30.0, "Е", 90.0, 8, seq=6003)
    c.lay.skip(40.0, "Е", 120.0, "ячейки 'Е' заняты (1, 3, 8)")


def test_m_three_e_cells_1_3_8_once_each_and_fourth_e_is_skipped(tmp_path):
    c = fresh(tmp_path)
    _e_three_times(c)
    res = c.run("--words", WORD, "--zone-max-mm", "600")
    assert res.code == 0
    assert res.line == "ИТОГ: PASS (взятий 3, заданий 3, FAIL 0, пропусков 1, повторов 0, предупреждений 0)"
    assert [r[COL_CELL] for r in res.rows() if r[COL_LETTER] == "Е" and r[COL_RESULT] == "PASS"][:3] == [
        "1",
        "3",
        "8",
    ]


def test_m_same_cell_twice_in_one_fill_fails_as_cell(tmp_path):
    c = fresh(tmp_path)
    add_pick_job(c, 10.0, "Е", 30.0, 3, seq=6001)
    add_pick_job(c, 20.0, "Е", 60.0, 3, seq=6002)
    res = c.run("--words", WORD)
    assert res.code == 1
    assert has_reason(res.row_by_net("60.0")[COL_RESULT], "ячейка")


def test_m_cell_of_another_letter_fails_as_cell(tmp_path):
    c = fresh(tmp_path)
    add_pick_job(c, 10.0, "Е", 30.0, 2, seq=6001)  # ячейка 2 принадлежит Р, не Е
    res = c.run("--words", WORD)
    assert res.code == 1
    assert has_reason(res.row_by_net("30.0")[COL_RESULT], "ячейка")


# ================================================================= (н) коды 2 и 3, тексты отказов


def _valid_args(tmp_path: Path) -> list[str]:
    c = fresh(tmp_path)
    add_pick_job(c, 10.0, "Е", 91.9, 3, seq=60466)
    return c.base_args()


@pytest.mark.parametrize("missing", ["--exchange", "--layout", "--registers"])
def test_n_missing_required_argument_is_code_2(tmp_path, missing):
    args = _valid_args(tmp_path)
    i = args.index(missing)
    del args[i : i + 2]
    res = run_cli(args)
    assert res.code == 2


def test_n_unknown_argument_is_code_2(tmp_path):
    res = run_cli(_valid_args(tmp_path) + ["--no-such-flag-xq", "1"])
    assert res.code == 2


def test_n_non_numeric_zone_max_is_code_2_and_text_hides_value(tmp_path):
    res = run_cli(_valid_args(tmp_path) + ["--zone-max-mm", "qzvalue9"])
    assert res.code == 2
    assert "qzvalue9" not in res.both


@pytest.mark.parametrize("words", [f"{WORD},МИР", "МИРЖЖ,МИРЖЖ"], ids=["two-for-one", "other-two-for-one"])
def test_n_words_count_above_word_lines_is_code_2_and_text_hides_value(tmp_path, words):
    res = run_cli(_valid_args(tmp_path) + ["--words", words])
    assert res.code == 2
    assert words not in res.both


def test_n_words_count_below_word_lines_is_code_2(tmp_path):
    c = fresh(tmp_path)
    add_pick_job(c, 10.0, "Е", 91.9, 3, seq=7001)
    c.lay.change(30.0, WORD, "МИР", 1, 9)
    add_pick_job(c, 40.0, "Р", 20.0, 2, seq=7002)
    res = c.run("--words", WORD)  # строк слова/смены слова две, слов одно
    assert res.code == 2


def test_n_word_with_space_and_no_pitch_is_code_2_and_text_hides_value(tmp_path):
    regs = dict(DEFAULT_REGS, use_pitch=False)
    c = fresh(tmp_path, word="ЗЗЯ ЗЗЮ", regs=regs)
    c.lay.skip(10.0, "Б", 5.0, "нет в слове 'ЗЗЯ ЗЗЮ'")
    res = c.run("--words", "ЗЗЯ ЗЗЮ")
    assert res.code == 2
    assert "ЗЗЯ" not in res.both
    assert "ЗЗЮ" not in res.both


@pytest.mark.parametrize("which", ["exchange", "layout"])
def test_n_unreadable_input_is_code_3_and_text_hides_path(tmp_path, which):
    args = _valid_args(tmp_path)
    marker = f"leakmark_{which}_7f3a.log"
    i = args.index(f"--{which}")
    args[i + 1] = str(tmp_path / marker)  # такого файла нет
    res = run_cli(args)
    assert res.code == 3
    assert marker not in res.both
    assert str(tmp_path) not in res.both


@pytest.mark.parametrize("which", ["exchange", "layout"])
def test_n_empty_input_is_code_3_and_text_hides_path(tmp_path, which):
    args = _valid_args(tmp_path)
    marker = f"emptymark_{which}_91c2.log"
    empty = tmp_path / marker
    empty.write_text("", encoding="utf-8")
    i = args.index(f"--{which}")
    args[i + 1] = str(empty)
    res = run_cli(args)
    assert res.code == 3
    assert marker not in res.both


# ================================================================= (о) столбец Б, паспорта сима


def _sim_obj(i: int, letter: str, angle: float, t: float, lateral: float = 0.0) -> dict:
    return {"object_id": f"o{i}", "class_name": letter, "angle_deg": angle, "lateral_px": lateral, "t": ts(t)}


def _nine_disks(tmp_path: Path, nets: list[float], truths: list[float]) -> tuple[Case, Path]:
    """Девять дисков в ячейках 0..8 (ПЕРЕМИРИЕ); px 458.2 (слово 4582) = x_ожид при lateral 0."""
    c = fresh(tmp_path)
    objs = []
    for i, (net, truth) in enumerate(zip(nets, truths, strict=True)):
        t = 10.0 + 8.0 * i
        c.lay.pick(t, LETTER[i], net, i, px=458.2)
        c.ex.job(t + 0.3, 5000 + i, jargs(i, net, {2: 4582}))
        objs.append(_sim_obj(i, LETTER[i], truth, t - 1.0))
    return c, write_jsonl(tmp_path / "objects.jsonl", objs)


NETS_OK = [30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 100.0, 110.0, 120.0]
NETS_FLIPPED = [330.0, 320.0, 310.0, 300.0, 290.0, 280.0, 260.0, 250.0, 240.0]  # 360 - NETS_OK


def test_o_sign_flip_on_nine_disks_fails_zero_shift_or_sign(tmp_path):
    c, objs = _nine_disks(tmp_path, NETS_FLIPPED, NETS_OK)
    res = c.run("--words", WORD, "--zone-max-mm", "600", "--sim-objects", str(objs))
    assert res.code == 1
    assert res.summary()["verdict"] == "FAIL"
    assert "сдвиг нуля или знак" in res.out
    assert not any(has_reason(r[COL_RESULT], "rz") for r in res.rows())  # по диску Б rz не ставит FAIL


def test_o_consistent_nine_disks_pass_clean(tmp_path):
    c, objs = _nine_disks(tmp_path, NETS_OK, NETS_OK)
    res = c.run("--words", WORD, "--zone-max-mm", "600", "--sim-objects", str(objs))
    assert res.code == 0
    assert res.line == "ИТОГ: PASS (взятий 9, заданий 9, FAIL 0, пропусков 0, повторов 0, предупреждений 0)"
    assert all(r[COL_RESULT] == "PASS" for r in res.rows())


def test_o_eight_judged_disks_are_not_enough_to_judge_the_run(tmp_path):
    """Девятый диск с подачей 0 град не судится: судимых 8 < 9, сдвиг нуля не выносится."""
    nets = NETS_FLIPPED[:8] + [60.0]
    truths = NETS_OK[:8] + [0.0]
    c, objs = _nine_disks(tmp_path, nets, truths)
    res = c.run("--words", WORD, "--zone-max-mm", "600", "--sim-objects", str(objs))
    assert res.code == 0
    assert "сдвиг нуля или знак" not in res.out
    assert res.summary()["verdict"] == "PASS"


def test_o_single_outlier_over_30_degrees_is_pass_tilde_not_fail(tmp_path):
    truths = list(NETS_OK)
    truths[3] = 100.0  # диск с сетью 60 при истине 100: e = -60 - (-100) = 40 град
    c, objs = _nine_disks(tmp_path, NETS_OK, truths)
    res = c.run("--words", WORD, "--zone-max-mm", "600", "--sim-objects", str(objs))
    assert res.code == 0
    assert res.line == "ИТОГ: PASS (взятий 9, заданий 9, FAIL 0, пропусков 0, повторов 0, предупреждений 0)"
    assert res.row_by_net("60.0")[COL_RESULT] == "PASS~"
    assert [r[COL_RESULT] for r in res.rows()].count("PASS~") == 1


def _single_disk_with_passport(
    tmp_path: Path,
    net: float,
    truth: float,
    *,
    px: float = 458.2,
    lateral: float = 0.0,
    passport_t: float = 9.0,
) -> Result:
    c = fresh(tmp_path)
    c.lay.pick(10.0, "Е", net, 3, px=px)
    c.ex.job(10.3, 60466, jargs(3, net, {2: round(px * 10)}))
    objs = write_jsonl(tmp_path / "objects.jsonl", [_sim_obj(1, "Е", truth, passport_t, lateral)])
    return c.run("--words", WORD, "--sim-objects", str(objs))


@pytest.mark.parametrize(
    ("net", "truth", "expected"),
    [(44.0, 30.0, "PASS"), (46.0, 30.0, "PASS~"), (90.0, 30.0, "PASS~")],
    ids=["e=-14", "e=-16", "e=-60"],
)
def test_o_error_over_15_degrees_is_pass_tilde_never_fail(tmp_path, net, truth, expected):
    res = _single_disk_with_passport(tmp_path, net, truth)
    assert res.code == 0
    assert res.row_by_net(f"{net:.1f}")[COL_RESULT] == expected


@pytest.mark.parametrize("truth", [0.0, 180.0])
def test_o_feeds_at_0_and_180_degrees_are_not_judged(tmp_path, truth):
    res = _single_disk_with_passport(tmp_path, 60.0, truth)  # при судимости |e| было бы > 15 -> PASS~
    assert res.code == 0
    assert res.row_by_net("60.0")[COL_RESULT] == "PASS"


def test_o_disk_without_passport_is_not_a_failure(tmp_path):
    c, _ = _nine_disks(tmp_path, NETS_OK, NETS_OK)
    objs = write_jsonl(tmp_path / "other.jsonl", [_sim_obj(1, "Щ", 30.0, 5.0)])  # паспорт чужой буквы
    res = c.run("--words", WORD, "--zone-max-mm", "600", "--sim-objects", str(objs))
    assert res.code == 0
    assert res.summary()["fail"] == 0
    assert "нет паспорта" in res.out


def test_o_passport_after_job_time_is_not_used(tmp_path):
    res = _single_disk_with_passport(tmp_path, 90.0, 30.0, passport_t=15.0)  # t позже задания 10.3
    assert res.code == 0
    assert res.row_by_net("90.0")[COL_RESULT] == "PASS"  # без паспорта нет и `~`


def test_o_passports_of_one_letter_go_to_disks_in_time_order_not_file_order(tmp_path):
    c = fresh(tmp_path)
    add_pick_job(c, 10.0, "Е", 30.0, 1, seq=6001)
    add_pick_job(c, 20.0, "Е", 60.0, 3, seq=6002)
    objs = write_jsonl(
        tmp_path / "objects.jsonl",
        [_sim_obj(2, "Е", 60.0, 15.0), _sim_obj(1, "Е", 30.0, 8.0)],  # в файле порядок обратный
    )
    res = c.run("--words", WORD, "--sim-objects", str(objs))
    assert res.code == 0
    assert res.row_by_net("30.0")[COL_RESULT] == "PASS"
    assert res.row_by_net("60.0")[COL_RESULT] == "PASS"


@pytest.mark.parametrize(
    ("px", "expected_prefix"),
    [(457.7, "PASS"), (459.5, "PASS~"), (461.0, "FAIL")],
    ids=["dx=0.5-pass", "dx=1.3-yellow", "dx=2.8-fail"],
)
def test_o_pick_x_against_sim_passport_zones(tmp_path, px, expected_prefix):
    """x_ожид = 458.2 - lateral/8.163265 = 458.2 при lateral 0."""
    res = _single_disk_with_passport(tmp_path, 30.0, 30.0, px=px)
    cell = res.row_by_net("30.0")[COL_RESULT]
    if expected_prefix == "FAIL":
        assert res.code == 1
        assert has_reason(cell, "x")
    else:
        assert res.code == 0
        assert cell == expected_prefix


# ================================================================= (п) журнал сима


def _journal(path: Path, lines: list[str]) -> Path:
    items = [{"t": ts(10.5 + i), "side": "out", "text": text} for i, text in enumerate(lines)]
    return write_jsonl(path, items)


def _two_job_case(tmp_path: Path) -> Case:
    c = fresh(tmp_path)
    add_pick_job(c, 10.0, "Е", 91.9, 3, seq=60466)
    add_pick_job(c, 20.0, "Е", 30.0, 1, seq=60467)
    return c


def test_p_sim_saw_every_accepted_job_pass(tmp_path):
    c = _two_job_case(tmp_path)
    jr = _journal(
        tmp_path / "journal.jsonl",
        ["[v2] CMD seq=60466 op=CVT_JOB", "[v2] CMD seq=777 op=SERVO", "[v2] CMD seq=60467 op=CVT_JOB"],
    )
    with jr.open("a", encoding="utf-8") as f:  # дубль строки кольца склеивается
        f.write(jr.read_text(encoding="utf-8").splitlines()[0] + "\n")
    res = c.run("--words", WORD, "--sim-journal", str(jr))
    assert res.code == 0
    assert res.summary()["fail"] == 0


def test_p_job_missing_at_sim_fails(tmp_path):
    c = _two_job_case(tmp_path)
    jr = _journal(tmp_path / "journal.jsonl", ["[v2] CMD seq=60466 op=CVT_JOB", "[v2] CMD seq=777 op=SERVO"])
    res = c.run("--words", WORD, "--sim-journal", str(jr))
    assert res.code == 1
    assert res.summary()["verdict"] == "FAIL"
    assert "сим не видел" in res.out


def test_p_extra_cvt_job_at_sim_fails(tmp_path):
    c = _two_job_case(tmp_path)
    jr = _journal(
        tmp_path / "journal.jsonl",
        ["[v2] CMD seq=60466 op=CVT_JOB", "[v2] CMD seq=60467 op=CVT_JOB", "[v2] CMD seq=99999 op=CVT_JOB"],
    )
    res = c.run("--words", WORD, "--sim-journal", str(jr))
    assert res.code == 1
    assert res.summary()["verdict"] == "FAIL"
    assert "лишнее у сима" in res.out


def test_p_refused_job_is_not_compared_with_sim(tmp_path):
    c = fresh(tmp_path)
    c.lay.pick(10.0, "Е", 91.9, 3)
    c.ex.job(10.3, 7001, jargs(3, 91.9), status=3, errno=5)  # отказ: симу его не слали
    c.ex.job(11.3, 7002, jargs(3, 91.9))
    jr = _journal(tmp_path / "journal.jsonl", ["[v2] CMD seq=7002 op=CVT_JOB"])
    res = c.run("--words", WORD, "--sim-journal", str(jr))
    assert res.code == 0
    assert res.summary()["fail"] == 0


# ================================================================= (р) зона досягаемости


def _single_cell_case(tmp_path: Path, cell: int) -> Case:
    c = fresh(tmp_path)
    c.lay.pick(10.0, LETTER[cell], 30.0, cell)
    c.ex.job(10.3, 60466, jargs(cell, 30.0))
    return c


@pytest.mark.parametrize("cell", [0, 8])
def test_r_far_cell_at_zone_500_is_pass_tilde_with_one_warning(tmp_path, cell):
    res = _single_cell_case(tmp_path, cell).run("--words", WORD, "--zone-max-mm", "500")
    assert res.code == 0
    assert res.row_by_net("30.0")[COL_RESULT] == "PASS~"
    s = res.summary()
    assert (s["verdict"], s["fail"], s["warnings"]) == ("PASS", 0, 1)


@pytest.mark.parametrize("cell", [0, 8])
def test_r_far_cell_at_zone_600_has_no_warning(tmp_path, cell):
    res = _single_cell_case(tmp_path, cell).run("--words", WORD, "--zone-max-mm", "600")
    assert res.code == 0
    assert res.row_by_net("30.0")[COL_RESULT] == "PASS"
    assert res.line == "ИТОГ: PASS (взятий 1, заданий 1, FAIL 0, пропусков 0, повторов 0, предупреждений 0)"


def test_r_zone_default_is_500(tmp_path):
    res = _single_cell_case(tmp_path, 8).run("--words", WORD)
    assert res.code == 0
    assert res.row_by_net("30.0")[COL_RESULT] == "PASS~"


def test_r_near_cell_has_no_warning_at_zone_500(tmp_path):
    res = _single_cell_case(tmp_path, 4).run("--words", WORD, "--zone-max-mm", "500")
    assert res.code == 0
    assert res.row_by_net("30.0")[COL_RESULT] == "PASS"
    assert res.summary()["warnings"] == 0


@pytest.mark.parametrize(("zone", "warn"), [("544", 1), ("545", 0)])
def test_r_zone_threshold_is_hypot_544_06(tmp_path, zone, warn):
    res = _single_cell_case(tmp_path, 8).run("--words", WORD, "--zone-max-mm", zone)
    assert res.code == 0
    assert res.summary()["warnings"] == warn


# ================================================================= реальные файлы run1 через CLI


def _run1_args(*extra: str) -> list[str]:
    return [
        "--exchange",
        str(FIXTURES / "run1_robot_exchange.txt"),
        "--layout",
        str(FIXTURES / "run1_layout_messages.txt"),
        "--registers",
        str(FIXTURES / "registers.json"),
        *extra,
    ]


RUN1_LINE = "ИТОГ: PASS (взятий 15, заданий 15, FAIL 0, пропусков 34, повторов 0, предупреждений 0)"


def test_run1_real_files_zone_600_exact_summary():
    res = run_cli(_run1_args("--zone-max-mm", "600"))
    assert res.code == 0
    assert res.line == RUN1_LINE
    assert [ln for ln in res.out.splitlines() if ln.strip()][-1].strip() == RUN1_LINE


def test_run1_real_files_with_words_give_same_summary():
    res = run_cli(_run1_args("--words", "ПЕРЕМИРИЕ,МИР,ПЕРЕМИРИЕ", "--zone-max-mm", "600"))
    assert res.code == 0
    assert res.line == RUN1_LINE
    assert "слово не независимо" not in res.out


def test_run1_real_files_zone_500_warns_about_far_cells_but_passes():
    res = run_cli(_run1_args("--zone-max-mm", "500"))
    assert res.code == 0
    s = res.summary()
    assert (s["verdict"], s["picks"], s["jobs"], s["fail"]) == ("PASS", 15, 15, 0)
    assert s["warnings"] > 0
