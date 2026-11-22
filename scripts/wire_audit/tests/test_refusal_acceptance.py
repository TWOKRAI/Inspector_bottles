"""Слепые приёмочные тесты `--layout-system` (отказ hub из-за выключенного серво), критерии A1-A10.

Источник истины — только текст критериев приёмки (решение владельца 2026-11-22) и README аудита;
кода аудита тесты не знают: каждый тест гонит CLI в подпроцессе (`python -m scripts.wire_audit`)
и смотрит на код возврата, строку `ИТОГ:` и строки таблицы. Входные файлы собираются в tmp_path.

Ожидаемые значения (итоговые строки, причины) записаны литералами, не считаются кодом аудита.
Слова провода берутся из таблиц регистров run1 (first 320/-440, шаг 110, линия 90 град):
ячейка 1 (Е) y -330, ячейка 2 (Р) y -220, ячейка 3 (Е) y -110; слова ARGS[7] — 62236, 63336, 64436;
rz = -100 + wrap180(0 - сеть), слово = round(rz*10) mod 65536 (ручной счёт).
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

Y_WORD = {1: 62236, 2: 63336, 3: 64436}
Y_MM = {1: -330.0, 2: -220.0, 3: -110.0}
RZ = {30.0: 64236, 40.0: 64136, 60.0: 63936, 91.9: 63617}  # сеть -> слово ARGS[9]

SUMMARY_RE = re.compile(
    r"^ИТОГ: (PASS|FAIL) \(взятий (\d+), заданий (\d+), FAIL (\d+), "
    r"пропусков (\d+), повторов (\d+), предупреждений (\d+)(?:, отказов hub (\d+))?\)$"
)
REASON = "отказ hub: робот остановлен: включите серво"

COL_NET = 3


# ---------------------------------------------------------------- генераторы строк журналов


def ts(t: float) -> str:
    """Секунды от 2026-11-22 21:24:00 -> `2026-11-22 21:24:20,028`."""
    dt = datetime(2026, 11, 22, 21, 24, 0) + timedelta(milliseconds=round(t * 1000))
    return dt.strftime("%Y-%m-%d %H:%M:%S") + f",{dt.microsecond // 1000:03d}"


class Exchange:
    """Журнал обмена: `#<строка> <дата> <время> [INFO] S.d.d.e.robot_main: #<n> in|out ...`."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self._fileno = 40
        self._n = 0

    def _emit(self, t: float, text: str) -> None:
        self._fileno += 1
        self._n += 1
        self.lines.append(f"#{self._fileno} {ts(t)} [INFO] S.d.d.e.robot_main: #{self._n} {text}")

    def connect(self, t: float) -> None:
        self._n = 0
        self._emit(t, " connect ok")

    def job(self, t: float, seq: int, args: list[int]) -> None:
        self._emit(t, f"in W* CMD_SEQ = {seq}")
        self._emit(t, "in W* CMD_OPCODE = 32 (CVT_JOB)")
        self._emit(t, f"in W* CMD_ARGC = {len(args)}")
        for i, word in enumerate(args):
            self._emit(t, f"in W* CMD_ARGS[{i}] = {word}")
        self._emit(t, "in W CMD_FLAG = 1")
        self._emit(t + 0.026, f"out R RES_SEQ..+12 RES_SEQ = {seq}, RES_STATUS = 1, RES_ERRNO = 0 (ОК)")

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


class Layout:
    """Журнал диска (messages.log). `prod=True` — вид строки из критериев: без `word_layout:`."""

    def __init__(self, prod: bool = False) -> None:
        self.lines: list[str] = []
        self._fileno = 0
        self._wl = "[layout] " if prod else "[layout] word_layout: "

    def _emit(self, t: float, src: str, text: str) -> None:
        self._fileno += 1
        self.lines.append(f"#{self._fileno} {ts(t)} [INFO] {src}{text}")

    def init(self, t: float) -> None:
        self._emit(t, "[-] logger_manager: ", "LoggerManager initialized")

    def word(self, t: float, word: str) -> None:
        self._emit(t, self._wl, f"WordLayoutPlugin: слово '{word}' (источник: регистр)")

    def pick(self, t: float, letter: str, net: float, cell: int) -> None:
        corr = ((-net + 180.0) % 360.0) - 180.0
        self._emit(
            t,
            self._wl,
            f"WordLayoutPlugin: диск '{letter}' {net:.1f}° → ячейка {cell}: взять(460.2,-343.2) → "
            f"положить x320.0 y{Y_MM[cell]:.1f} z-132.0 r{corr:.1f}° [{cell}/9]",
        )

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


def jargs(cell: int, net: float) -> list[int]:
    """Слова CVT_JOB: pick (460.2, -343.2, z -132), flags 3, place по ячейке."""
    return [18178, 1, 4602, 62104, 64216, 3, 3200, Y_WORD[cell], 64216, RZ[net]]


def refusal_line(
    t: float, letter: str, cell: int, no: int = 191, reason: str = "робот остановлен: включите серво"
) -> str:
    """Строка отказа в system.log ровно такого вида, как дал владелец."""
    return (
        f"#{no} {ts(t)} [WARNING] [layout] layout: [health] ResourceUnavailable @ robot_io.forward.refused: "
        f"hub отказ (буква '{letter}', ячейка {cell}): {reason}"
    )


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

    @property
    def last_nonempty(self) -> str:
        return [ln for ln in self.out.splitlines() if ln.strip()][-1].strip()

    def summary(self) -> dict:
        m = SUMMARY_RE.match(self.line)
        assert m, f"строка ИТОГ не по формату: {self.line!r}"
        keys = ("verdict", "picks", "jobs", "fail", "skips", "retries", "warnings", "hub")
        return {k: (v if k == "verdict" or v is None else int(v)) for k, v in zip(keys, m.groups())}

    def table_rows(self) -> list[str]:
        return [ln.strip() for ln in self.out.splitlines() if ln.strip().startswith("|")]

    def verdict_cell(self, net: str) -> str:
        """Последняя ячейка (итог) строки диска с сетью `net`."""
        hits = []
        for ln in self.table_rows():
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if len(cells) > COL_NET and cells[0].isdigit() and cells[COL_NET] == net:
                hits.append(cells[-1])
        assert len(hits) == 1, f"строк с сетью {net}: {len(hits)}\n{self.out[-2500:]}"
        return hits[0]


def is_fail(cell: str, key: str | None = None) -> bool:
    if not cell.startswith("FAIL"):
        return False
    if key is None:
        return True
    body = cell.split(":", 1)[1] if ":" in cell else ""
    return any(re.match(re.escape(key) + r"(?!\w)", r.strip()) for r in body.split(";"))


def is_hub_warning(cell: str) -> bool:
    """Предупреждение `~` с причиной «отказ hub: ...», не FAIL."""
    return (not cell.startswith("FAIL")) and cell.startswith(("PASS~", "~")) and REASON in cell


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
    return Result(proc.returncode, proc.stdout, proc.stderr)


class Case:
    """Один прогон: журналы обмена, диска, регистры и (необязательно) system.log в tmp_path."""

    def __init__(self, tmp_path: Path, *, prod: bool = False) -> None:
        self.tmp = tmp_path
        self.ex = Exchange()
        self.lay = Layout(prod)
        self.sys_lines: list[str] = []
        self.words = WORD  # значение --words (по слову на заливку)
        self.ex.connect(0.0)
        self.lay.init(0.5)
        self.lay.word(5.0, WORD)

    def disk_ok(self, t: float, letter: str, net: float, cell: int, seq: int) -> None:
        """Диск и его задание через 0.3 с."""
        self.lay.pick(t, letter, net, cell)
        self.ex.job(t + 0.3, seq, jargs(cell, net))

    def disk_no_job(self, t: float, letter: str, net: float, cell: int) -> None:
        self.lay.pick(t, letter, net, cell)

    def args(self, *, with_system: bool, system_text: str | None = None) -> list[str]:
        ex = self.tmp / "exchange.log"
        lay = self.tmp / "messages.log"
        regs = self.tmp / "registers.json"
        ex.write_text(self.ex.text(), encoding="utf-8")
        lay.write_text(self.lay.text(), encoding="utf-8")
        regs.write_text(json.dumps(REGS), encoding="utf-8")
        a = ["--exchange", str(ex), "--layout", str(lay), "--registers", str(regs), "--words", self.words]
        if with_system:
            sysf = self.tmp / "system.log"
            sysf.write_text(
                system_text if system_text is not None else "\n".join(self.sys_lines) + "\n",
                encoding="utf-8",
            )
            a += ["--layout-system", str(sysf)]
        return a

    def run(self, *, with_system: bool = True, extra: tuple[str, ...] = (), system_text: str | None = None) -> Result:
        return run_cli(self.args(with_system=with_system, system_text=system_text) + list(extra))


def lost_case(tmp_path: Path, *, prod: bool = False) -> Case:
    """Е 91.9 -> ячейка 3 с заданием (t=10), затем Р 30.0 -> ячейка 2 БЕЗ задания (t=20)."""
    c = Case(tmp_path, prod=prod)
    c.disk_ok(10.0, "Е", 91.9, 3, 60466)
    c.disk_no_job(20.0, "Р", 30.0, 2)
    return c


# ================================================================= A1: без флага поведение прежнее


def test_a1_without_layout_system_disk_without_job_is_lost_fail(tmp_path):
    res = lost_case(tmp_path).run(with_system=False)
    assert res.code == 1
    assert res.line == "ИТОГ: FAIL (взятий 2, заданий 1, FAIL 1, пропусков 0, повторов 0, предупреждений 0)"
    assert is_fail(res.verdict_cell("30.0"), "потеря")
    assert res.verdict_cell("91.9") == "PASS"
    assert "отказов hub" not in res.out


def test_a1_run1_with_one_job_block_removed_is_lost_fail(tmp_path):
    """Из реального прогона run1 убран блок CVT_JOB одного диска: без флага это потеря."""
    src = (FIXTURES / "run1_robot_exchange.txt").read_text(encoding="utf-8").splitlines()
    starts = [i for i, ln in enumerate(src) if "CMD_OPCODE = 32 (CVT_JOB)" in ln]
    assert len(starts) == 15
    # блок: CMD_SEQ (строка перед опкодом) ... ответ R с тем же RES_SEQ; режем от CMD_SEQ до CMD_FLAG и ответа
    first = starts[3] - 1
    seq = re.search(r"CMD_SEQ = (\d+)", src[first]).group(1)
    end = next(i for i in range(first, len(src)) if f"RES_SEQ = {seq}," in src[i])
    cut = src[:first] + src[end + 1 :]
    ex = tmp_path / "exchange.log"
    ex.write_text("\n".join(cut) + "\n", encoding="utf-8")
    res = run_cli(
        [
            "--exchange", str(ex),
            "--layout", str(FIXTURES / "run1_layout_messages.txt"),
            "--registers", str(FIXTURES / "registers.json"),
            "--zone-max-mm", "600",
        ]
    )  # fmt: skip
    assert res.code == 1
    assert res.line == "ИТОГ: FAIL (взятий 15, заданий 14, FAIL 1, пропусков 34, повторов 0, предупреждений 0)"
    assert "потеря" in res.out


# ================================================================= A2: отказ закрывает диск без задания


@pytest.mark.parametrize("refusal_dt", [0.028, 0.0, 5.0], ids=["plus-28ms", "same-timestamp", "plus-5s"])
def test_a2_matching_refusal_makes_lost_disk_a_warning_not_fail(tmp_path, refusal_dt):
    c = lost_case(tmp_path)
    c.sys_lines = [refusal_line(20.0 + refusal_dt, "Р", 2)]
    res = c.run()
    assert res.code == 0
    cell = res.verdict_cell("30.0")
    assert not is_fail(cell), cell
    assert is_hub_warning(cell), cell
    s = res.summary()
    assert (s["verdict"], s["fail"]) == ("PASS", 0)
    assert res.verdict_cell("91.9") == "PASS"


def test_a2_reason_is_text_after_colon_of_refusal_line(tmp_path):
    """Причина в таблице — текст после `): ` строки отказа, а не зашитая константа: другой текст -> другая причина."""
    c = lost_case(tmp_path)
    c.sys_lines = [refusal_line(20.028, "Р", 2, reason="инструмент не выбран: выберите инструмент")]
    res = c.run()
    assert res.code == 0
    cell = res.verdict_cell("30.0")
    assert not is_fail(cell)
    assert "отказ hub: инструмент не выбран: выберите инструмент" in cell
    assert "включите серво" not in cell


def test_a2_layout_line_in_production_format_without_word_layout_prefix(tmp_path):
    """Строка диска как в живом messages.log (`[layout] WordLayoutPlugin:` без `word_layout:`)."""
    c = lost_case(tmp_path, prod=True)
    c.sys_lines = [refusal_line(20.028, "Р", 2)]
    res = c.run()
    assert res.code == 0
    assert is_hub_warning(res.verdict_cell("30.0"))


# ================================================================= A3: поле «отказов hub K» в ИТОГ


def test_a3_summary_has_hub_field_and_warnings_include_refusal(tmp_path):
    """Пример из критериев: 3 взятия, 2 задания, 1 отказ -> предупреждений 1, отказов hub 1."""
    c = Case(tmp_path)
    c.disk_ok(10.0, "Е", 91.9, 3, 60466)
    c.disk_no_job(20.0, "Р", 30.0, 2)
    c.disk_ok(30.0, "Е", 60.0, 1, 60467)
    c.sys_lines = [refusal_line(20.028, "Р", 2)]
    res = c.run()
    assert res.code == 0
    assert res.line == (
        "ИТОГ: PASS (взятий 3, заданий 2, FAIL 0, пропусков 0, повторов 0, предупреждений 1, отказов hub 1)"
    )
    assert res.last_nonempty == res.line


def test_a3_without_layout_system_no_hub_field_old_format(tmp_path):
    c = Case(tmp_path)
    c.disk_ok(10.0, "Е", 91.9, 3, 60466)
    res = c.run(with_system=False)
    assert res.code == 0
    assert res.line == "ИТОГ: PASS (взятий 1, заданий 1, FAIL 0, пропусков 0, повторов 0, предупреждений 0)"
    assert "отказов hub" not in res.out


# ================================================================= A4: подходящей строки отказа нет -> FAIL


@pytest.mark.parametrize(
    ("letter", "cell", "t"),
    [
        ("М", 2, 20.028),  # другая буква, та же ячейка и время
        ("Р", 6, 20.028),  # та же буква, другая ячейка (Р есть и в ячейке 6), то же время
        ("Р", 2, 19.972),  # время отказа раньше строки диска на 28 мс
        ("Р", 2, 5.0),  # время отказа намного раньше
    ],
    ids=["other-letter", "other-cell", "earlier-28ms", "much-earlier"],
)
def test_a4_non_matching_refusal_keeps_lost_fail(tmp_path, letter, cell, t):
    c = lost_case(tmp_path)
    # посторонняя строка отказа (не совпадает с диском), плюс одна заведомо чужая другой буквы
    c.sys_lines = [refusal_line(t, letter, cell), refusal_line(21.0, "Щ", 7, no=192)]
    res = c.run()
    assert res.code == 1
    assert is_fail(res.verdict_cell("30.0"), "потеря")
    s = res.summary()
    assert (s["verdict"], s["fail"]) == ("FAIL", 1)
    assert res.verdict_cell("91.9") == "PASS"


# ================================================================= A5: один отказ закрывает один диск


def _two_same_cell_disks(tmp_path: Path) -> Case:
    c = Case(tmp_path)
    c.disk_ok(10.0, "Е", 91.9, 3, 60466)
    c.disk_no_job(20.0, "Р", 30.0, 2)
    # Ячейка занимается при выдаче строки диска и отказом hub не освобождается (word_layout/plugin.py):
    # вторая Р в ячейку 2 возможна только в НОВОЙ заливке слова. Правка лида 2026-11-22: слепой tester
    # поставил оба диска в одну заливку (неверная модель, существующий FAIL «ячейка»).
    c.lay.word(25.0, WORD)
    c.words = f"{WORD},{WORD}"
    c.disk_no_job(30.0, "Р", 40.0, 2)
    return c


def test_a5_one_refusal_closes_exactly_one_of_two_same_cell_disks(tmp_path):
    """Отказ между двумя дисками -> привязан к первому (A2: раньше следующего диска в ту же ячейку)."""
    c = _two_same_cell_disks(tmp_path)
    c.sys_lines = [refusal_line(20.028, "Р", 2)]
    res = c.run()
    assert res.code == 1
    assert is_hub_warning(res.verdict_cell("30.0"))
    assert is_fail(res.verdict_cell("40.0"), "потеря")
    s = res.summary()
    assert (s["verdict"], s["fail"], s["hub"]) == ("FAIL", 1, 1)


def test_a5_refusal_after_second_disk_binds_only_to_the_second(tmp_path):
    """Вытекает из A2: отказ позже второго диска первому уже не подходит (следующий диск в ячейку раньше отказа)."""
    c = _two_same_cell_disks(tmp_path)
    c.sys_lines = [refusal_line(30.028, "Р", 2)]
    res = c.run()
    assert res.code == 1
    assert is_fail(res.verdict_cell("30.0"), "потеря")
    assert is_hub_warning(res.verdict_cell("40.0"))
    s = res.summary()
    assert (s["verdict"], s["fail"], s["hub"]) == ("FAIL", 1, 1)


# ================================================================= A6: отказ без диска


def _note_lines(res: Result) -> list[str]:
    return [ln for ln in res.out.splitlines() if "отказ без диска" in ln]


def test_a6_unbound_refusal_is_a_note_and_does_not_change_exit_code(tmp_path):
    c = Case(tmp_path)
    c.disk_ok(10.0, "Е", 91.9, 3, 60466)
    c.sys_lines = [refusal_line(15.0, "Щ", 5)]  # такого диска нет
    res = c.run()
    assert res.code == 0
    assert res.line == (
        "ИТОГ: PASS (взятий 1, заданий 1, FAIL 0, пропусков 0, повторов 0, предупреждений 0, отказов hub 0)"
    )
    notes = _note_lines(res)
    assert len(notes) == 1, res.out
    assert "Щ" in notes[0] or re.search(r"ячейк\w*\W*5", notes[0]), notes[0]
    assert res.last_nonempty == res.line  # ИТОГ остаётся последней непустой строкой


def test_a6_unbound_refusal_does_not_turn_failing_run_into_other_code(tmp_path):
    plain_dir = tmp_path / "plain"
    plain_dir.mkdir()
    base = lost_case(plain_dir).run(with_system=False)
    c = lost_case(tmp_path)
    c.sys_lines = [refusal_line(15.0, "Щ", 5)]  # чужой отказ, потеря остаётся
    res = c.run()
    assert base.code == res.code == 1
    assert is_fail(res.verdict_cell("30.0"), "потеря")
    assert len(_note_lines(res)) == 1


# ================================================================= A7: посторонние строки system.log игнорируются

SYSTEM_NOISE = [
    "#180 2026-11-22 21:24:10,001 [WARNING] [layout] layout: что-то другое пошло не так",
    "#181 2026-11-22 21:24:11,002 [INFO] [layout] layout: [health] status → degraded: breaker open (robot_io.forward)",
    "",
    "   ",
    "###### мусор ?! \t |||",
    "#183 2026-11-22 21:2",  # обрезанная строка
    "hub отказ без номера и даты",
    "#184 2026-11-22 21:24:12,003 [ERROR] [layout] layout: [health] ResourceUnavailable @ robot_io.forward.send: "
    "таймаут ответа",
    "#185 не-дата не-время [WARNING] [layout] layout: [health] ResourceUnavailable @ robot_io.forward.refused: "
    "hub отказ (буква 'Р', ячейка 2",  # битая строка отказа: нет закрывающей скобки
]


def test_a7_unrelated_system_lines_are_ignored_no_error(tmp_path):
    c = Case(tmp_path)
    c.disk_ok(10.0, "Е", 91.9, 3, 60466)
    c.sys_lines = list(SYSTEM_NOISE)
    res = c.run()
    assert res.code == 0
    assert res.line == (
        "ИТОГ: PASS (взятий 1, заданий 1, FAIL 0, пропусков 0, повторов 0, предупреждений 0, отказов hub 0)"
    )
    assert "Traceback" not in res.both
    assert _note_lines(res) == []  # шум не принят за отказы


def test_a7_noise_around_a_real_refusal_does_not_hide_it(tmp_path):
    c = lost_case(tmp_path)
    c.sys_lines = SYSTEM_NOISE[:4] + [refusal_line(20.028, "Р", 2)] + SYSTEM_NOISE[4:]
    res = c.run()
    assert res.code == 0
    assert is_hub_warning(res.verdict_cell("30.0"))
    assert res.summary()["hub"] == 1
    assert "Traceback" not in res.both


# ================================================================= A8: неверный путь


def test_a8_wrong_layout_system_path_is_code_2_with_russian_message_and_flag_name(tmp_path):
    c = lost_case(tmp_path)
    args = c.args(with_system=False) + ["--layout-system", str(tmp_path / "no_such_system_91c2.log")]
    res = run_cli(args)
    assert res.code == 2
    assert "--layout-system" in res.both
    assert re.search("[а-яА-ЯёЁ]", res.both), res.both
    assert "Traceback" not in res.both


def test_a8_wrong_layout_system_path_text_hides_path_value(tmp_path):
    """README: тексты отказов кодов 2 и 3 без значений аргументов (путей); допущение: правило и для этого флага."""
    marker = "leakmark_system_7f3a.log"
    c = lost_case(tmp_path)
    res = run_cli(c.args(with_system=False) + ["--layout-system", str(tmp_path / marker)])
    assert res.code == 2
    assert marker not in res.both
    assert str(tmp_path) not in res.both


# ================================================================= A9: отчёт --out совпадает со stdout


@pytest.mark.parametrize("with_flag", [False, True], ids=["no-flag", "with-flag"])
def test_a9_out_report_has_same_rows_and_summary_as_stdout(tmp_path, with_flag):
    c = lost_case(tmp_path)
    c.sys_lines = [refusal_line(20.028, "Р", 2), refusal_line(15.0, "Щ", 5, no=192)]
    out_dir = tmp_path / "rep"
    out_dir.mkdir()
    out_path = out_dir / "audit.md"
    res = c.run(with_system=with_flag, extra=("--out", str(out_path)))
    text = out_path.read_text(encoding="utf-8")
    file_lines = [ln.strip() for ln in text.splitlines()]
    assert res.line in file_lines
    for row in res.table_rows():
        assert row in file_lines, row
    if with_flag:
        assert res.code == 0
        assert res.line == (
            "ИТОГ: PASS (взятий 2, заданий 1, FAIL 0, пропусков 0, повторов 0, предупреждений 1, отказов hub 1)"
        )
        assert any(_note_lines(res)) and all(n.strip() in file_lines for n in _note_lines(res))
    else:
        assert res.code == 1
        assert "отказов hub" not in text


# ================================================================= A10: run1 без отказов не меняется


RUN1_LINE = "ИТОГ: PASS (взятий 15, заданий 15, FAIL 0, пропусков 34, повторов 0, предупреждений 0)"
RUN1_LINE_HUB = "ИТОГ: PASS (взятий 15, заданий 15, FAIL 0, пропусков 34, повторов 0, предупреждений 0, отказов hub 0)"


def _run1(*extra: str) -> Result:
    return run_cli(
        [
            "--exchange", str(FIXTURES / "run1_robot_exchange.txt"),
            "--layout", str(FIXTURES / "run1_layout_messages.txt"),
            "--registers", str(FIXTURES / "registers.json"),
            "--zone-max-mm", "600",
            *extra,
        ]
    )  # fmt: skip


def test_a10_run1_with_empty_layout_system_same_table_and_summary_plus_hub_zero(tmp_path):
    empty = tmp_path / "system.log"
    empty.write_text("", encoding="utf-8")
    plain = _run1()
    withsys = _run1("--layout-system", str(empty))
    assert plain.code == 0
    assert plain.line == RUN1_LINE  # прежний формат без флага
    assert withsys.code == 0
    assert withsys.line == RUN1_LINE_HUB
    assert withsys.table_rows() == plain.table_rows()
    assert len(plain.table_rows()) > 15  # таблица не пуста: шапка и строки 15 взятий и пропусков
    assert withsys.last_nonempty == RUN1_LINE_HUB
