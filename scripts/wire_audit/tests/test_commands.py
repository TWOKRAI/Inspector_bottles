"""Тесты журнала команд ``wire_commands.md``: расшифровка по литералам живого прогона, повторы, номера строк.

Литералы — из ``data/chain_check/letter_robot_sim/20261122T164022Z/run1`` (CMD_SEQ 57111 и 57113, строки журнала
обмена 509–523 и 543–558). Ожидаемые значения записаны вручную, не считаются кодом под тестом.
"""

# ruff: noqa: E501 - ожидаемые строки отчёта длинные по природе
from __future__ import annotations

import json

import pytest

from scripts.wire_audit import __main__ as cli
from scripts.wire_audit import commands, core

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
    "word_gap_slots": 1,
    "p_pick_rz_deg": -100.0,
    "p_pick_rz_source": "robot_param_get_all",
}
WORD = "ПЕРЕМИРИЕ"
STAMP = "2026-11-22 19:42:03,934"


class Log:
    """Журнал обмена: строки ``#<файл> <время> [INFO] S.d.d.e.robot_main: #<n> <текст>``; ведущий номер сквозной."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.n = 0

    def raw(self, text: str, inner: int | None = None) -> None:
        self.n += 1
        shown = self.n if inner is None else inner
        self.lines.append(f"#{self.n + 50} {STAMP} [INFO] S.d.d.e.robot_main: #{shown} {text}")

    def block(self, seq: int, op: str, code: int, args: list[int], *, reply: bool = True, status: int = 1) -> None:
        self.raw(f"in W* CMD_SEQ = {seq}")
        self.raw(f"in W* CMD_OPCODE = {code} ({op})")
        self.raw(f"in W* CMD_ARGC = {len(args)}")
        for i, word in enumerate(args):
            self.raw(f"in W* CMD_ARGS[{i}] = {word}")
        self.raw("in W CMD_FLAG = 1")
        if reply:
            self.raw(f"out R RES_SEQ..+12 RES_SEQ = {seq}, RES_STATUS = {status}, RES_ERRNO = 0 (ОК)")

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


JOB_57111 = [15912, 0, 4606, 62111, 64216, 3, 3200, 4400, 64216, 64764]
JOB_57113 = [19316, 0, 4553, 62106, 64216, 3, 3200, 61136, 64216, 63601]


def layout_text(disks: list[str]) -> str:
    head = [
        "#1 2026-11-22 19:40:26,562 [INFO] [-] logger_manager: LoggerManager initialized",
        f"#2 2026-11-22 19:41:00,000 [INFO] [layout] word_layout: WordLayoutPlugin: слово '{WORD}' (источник: регистр)",
    ]
    rows = [
        f"#{i + 3} 2026-11-22 19:42:0{i}.000 [INFO] [layout] word_layout: WordLayoutPlugin: {text}".replace(
            ".000", ",000"
        )
        for i, text in enumerate(disks)
    ]
    return "\n".join(head + rows) + "\n"


PICK_57111 = "диск 'Е' 337.2° → ячейка 8: взять(460.6,-342.5) → положить x320.0 y440.0 z-132.0 r22.8° [1/9]"
PICK_57113 = "диск 'П' 93.5° → ячейка 0: взять(455.3,-343.0) → положить x320.0 y-440.0 z-132.0 r-93.5° [2/9]"


def two_jobs() -> tuple[Log, str]:
    log = Log()
    log.lines = [f"#51 {STAMP} [INFO] S.d.d.e.robot_main: #1  connect ok"]
    log.n = 1
    log.block(57111, "CVT_JOB", 32, JOB_57111)  # строки 2-16
    log.block(57113, "CVT_JOB", 32, JOB_57113)  # строки 17-31
    return log, layout_text([PICK_57111, PICK_57113])


def render(log: Log, layout: str, **kw) -> str:
    result = core.audit(log.text(), layout, REGS, words=[WORD], zone_max_mm=600.0, **kw)
    return commands.render_commands(log.text(), layout, REGS, result)


def test_signed_word_literals():
    assert [commands.signed_word(w) for w in (62111, 64764, 32767, 32768, 0, 65535)] == [
        -3425,
        -772,
        32767,
        -32768,
        0,
        -1,
    ]


def test_cvt_job_57111_is_decoded_to_the_millimetre_from_live_words():
    log, layout = two_jobs()
    text = render(log, layout)
    assert "CMD_SEQ 57111 · Задание конвейера (CVT_JOB)      robot_exchange.log:2–16" in text
    assert "  Взять:    x 460,6 y −342,5 z −132,0 мм" in text
    assert "  Положить: x 320,0 y 440,0 z −132,0 мм   поворот −77,2°" in text
    assert "  Флаги 3 (бит0 = pick z задан, бит1 = укладка задана), ecap 15912 (энкодер ленты, не мм)" in text
    assert "  Ответ:    RES_SEQ 57111 = CMD_SEQ ✓   статус 1 (ОК)" in text


def test_calc_table_shows_source_calculation_expected_and_wire_word():
    log, layout = two_jobs()
    text = render(log, layout)
    assert "| ARGS[2] | pick x | 460,6 мм (layout «взять») | 460,6×10=4606 → &0xFFFF | 4606 | 4606 | ✓ |" in text
    assert "| ARGS[3] | pick y | −342,5 мм (layout «взять») | −342,5×10=−3425 → +65536 | 62111 | 62111 | ✓ |" in text
    assert "| ARGS[7] | place y | 440,0 мм (first_y −440,0 + 8×шаг 110,0 по 90,0°; ячейка 8 слова ПЕРЕМИРИЕ) |" in text
    assert "| ARGS[9] | rz | −77,2° = P_PICK_RZ −100,0 (с робота: robot_param_get_all) + доворот 22,8° |" in text
    assert "−77,2×10=−772 → +65536 | 64764 | 64764 | ✓ |" in text
    assert (
        "| ARGS[0], ARGS[1] | ecap | энкодер ленты | не считается: нет независимого источника | — | 15912, 0 | — |"
        in text
    )


def test_job_57113_rz_beyond_minus_180_goes_on_the_wire_as_is_and_is_counted():
    log, layout = two_jobs()
    text = render(log, layout)
    assert "  Положить: x 320,0 y −440,0 z −132,0 мм   поворот −193,5°" in text
    assert "−193,5×10=−1935 → +65536 | 63601 | 63601 | ✓ |" in text
    assert (
        "Поворот rz: у 1 из 2 заданий |rz| > 180° (например −193,5°); на провод идёт как есть, не свёрнут к +166,5°."
        in text
    )


def test_summary_row_per_disk_with_letter_marked_not_sent_to_robot():
    log, layout = two_jobs()
    text = render(log, layout)
    assert "| буква (на ПК, роботу не передаётся) |" in text
    assert "| 460,6, −342,5 | 320,0, 440,0 | −77,2 | PASS |" in text


def test_line_numbers_are_physical_lines_of_the_file_including_older_incarnation():
    old = [f"#{i} {STAMP} [INFO] S.d.d.e.robot_main: #{i} in W 0x1204 = 1" for i in range(1, 6)]
    log, layout = two_jobs()
    text = "\n".join(old) + "\n" + log.text()
    recs = commands.parse_commands(text)
    blocks = [r for r in recs if r.kind == "cmd"]
    assert [(r.seq, r.first, r.last) for r in blocks] == [(57111, 7, 21), (57113, 22, 36)]


@pytest.mark.parametrize(
    ("word", "mark"),
    [
        (4606, "✓"),
        (4607, "≈ (допуск ±1 из-за округления журнала)"),
        (4605, "≈ (допуск ±1 из-за округления журнала)"),
        (4608, "✗"),
    ],
)
def test_one_word_tolerance_is_marked_and_two_words_are_a_mismatch(word, mark):
    log = Log()
    log.lines = [f"#51 {STAMP} [INFO] S.d.d.e.robot_main: #1  connect ok"]
    log.n = 1
    log.block(57111, "CVT_JOB", 32, [15912, 0, word, 62111, 64216, 3, 3200, 4400, 64216, 64764])
    text = render(log, layout_text([PICK_57111]))
    assert f"| 4606 | {word} | {mark} |" in text


def test_negative_word_and_one_word_tolerance_on_the_signed_side():
    log = Log()
    log.lines = [f"#51 {STAMP} [INFO] S.d.d.e.robot_main: #1  connect ok"]
    log.n = 1
    log.block(57111, "CVT_JOB", 32, [15912, 0, 4606, 62112, 64216, 3, 3200, 4400, 64216, 64764])
    text = render(log, layout_text([PICK_57111]))
    assert "−342,5×10=−3425 → +65536 | 62111 | 62112 | ≈ (допуск ±1 из-за округления журнала) |" in text


def test_unknown_opcode_has_raw_words_and_no_decoding():
    log = Log()
    log.lines = [f"#51 {STAMP} [INFO] S.d.d.e.robot_main: #1  connect ok"]
    log.n = 1
    log.block(70001, "FOO_BAR", 99, [7, 65535])
    text = render(log, layout_text([]))
    assert "CMD_SEQ 70001 · FOO_BAR (FOO_BAR)" in text
    assert "слова: ARGS[0]=7, ARGS[1]=65535" in text
    assert "расшифровки нет (опкод FOO_BAR); сырые слова: ARGS[0]=7, ARGS[1]=65535" in text
    assert "ПРОВЕРКА: не проверяется аудитом координат" in text


def test_sc_run_servo_stop_req_and_connect_params_table():
    log = Log()
    log.lines = [f"#51 {STAMP} [INFO] S.d.d.e.robot_main: #1  connect ok"]
    log.n = 1
    log.block(100, "PARAM_SET", 80, [0, 80])
    log.block(101, "PARAM_SET", 80, [25, 64536])
    log.block(102, "SC_RUN", 48, [1, 1, 0, 0, 0, 0])
    log.block(103, "SERVO", 65, [0])
    log.block(104, "PARAM_SET", 80, [1, 30])  # после первой другой команды — обычный блок
    log.raw("in W STOP_REQ = 5")
    log.raw("in W STOP_REQ = 10")
    text = render(log, layout_text([]))
    assert "## Параметры при подключении" in text
    assert "| 0 | P_SPD_DEFAULT | 80 | 1 (ОК) | robot_exchange.log:2–8 |" in text
    assert "| 25 | P_PICK_RZ | 64536 | 1 (ОК) | robot_exchange.log:9–15 |" in text
    assert "№1 · 19:42:03,934 · CMD_SEQ 102 · Запуск сценария (SC_RUN)" in text
    assert "  Сценарий: count 1, sc_id 1, offset 0, spd_pct 0, accel 0, accur 0" in text
    assert "  Серво: on 0 (ВЫКЛ)" in text
    assert "№3 · 19:42:03,934 · CMD_SEQ 104 · Запись параметра (PARAM_SET)" in text
    assert "  Параметр P_SPD_JOG = 30 (сырое слово)" in text
    assert "  Запись STOP_REQ = 5: номер стопа 1, уровень SOFT (мягкий) (n = номер×4 + уровень)" in text
    assert "  Запись STOP_REQ = 10: номер стопа 2, уровень HARD (жёсткий) (n = номер×4 + уровень)" in text
    assert text.count("ПРОВЕРКА: не проверяется аудитом координат") == 5  # SC_RUN, SERVO, PARAM_SET, 2 STOP_REQ


def test_unknown_param_id_is_shown_as_id_n():
    log = Log()
    log.lines = [f"#51 {STAMP} [INFO] S.d.d.e.robot_main: #1  connect ok"]
    log.n = 1
    log.block(100, "PARAM_SET", 80, [999, 5])
    text = render(log, layout_text([]))
    assert "| 999 | id 999 | 5 | 1 (ОК) |" in text


def test_repeat_line_is_attached_to_the_register_write_and_shown_as_count():
    log = Log()
    log.lines = [f"#51 {STAMP} [INFO] S.d.d.e.robot_main: #1  connect ok"]
    log.n = 1
    log.raw("in W 0x1204 = 1", inner=500)  # физическая строка 2
    log.raw("… ×17", inner=500)  # строка 3
    text = render(log, layout_text([]))
    assert (
        "служебная запись регистра 0x1204 = 1, повтор записи 17 раз (не команда роботу)   robot_exchange.log:2–3"
        in text
    )


def test_disks_without_command_standard_reasons_are_normal_and_other_reason_is_flagged():
    log = Log()
    log.lines = [f"#51 {STAMP} [INFO] S.d.d.e.robot_main: #1  connect ok"]
    log.n = 1
    disks = [
        "диск 'А' 4.2° → пропуск: нет в слове 'ПЕРЕМИРИЕ'",
        "диск 'Е' 60.3° → пропуск: ячейки 'Е' заняты (1, 3, 8)",
        "диск 'И' 30.1° → пропуск: уверенность ниже порога (И 0.33 < 0.50)",
        "диск '?' 0.0° → пропуск: нет предсказания",
    ]
    text = render(log, layout_text(disks))
    section = text.split("## Диски без команды")[1].splitlines()
    assert any(
        "диск «А» (роботу не передаётся), сеть 4,2° · буквы «А» нет в слове «ПЕРЕМИРИЕ» — ячейки по плану нет; почему не выдан: нет в слове 'ПЕРЕМИРИЕ' · команды роботу нет — штатно · layout/messages.log:3"
        in s
        for s in section
    )
    assert any(
        "ячейки 'Е' заняты (1, 3, 8) · команды роботу нет — штатно · layout/messages.log:4" in s for s in section
    )
    assert any(
        "уверенность ниже порога (И 0.33 < 0.50) · команды роботу нет — штатно · layout/messages.log:5" in s
        for s in section
    )
    assert any(
        "нет предсказания · ⚠ проверить: причина пропуска не из списка штатных · layout/messages.log:6" in s
        for s in section
    )


def test_sim_lines_in_origin_block_when_sim_files_are_given():
    log, layout = two_jobs()
    objects = [
        {
            "object_id": "obj-11",
            "class_name": "Е",
            "angle_deg": 330.0,
            "lateral_px": -13.2,
            "t": "2026-11-22 19:42:00,000",
        }
    ]
    result = core.audit(log.text(), layout, REGS, words=[WORD], zone_max_mm=600.0, sim_objects=objects, sim_journal=[])
    text = commands.render_commands(log.text(), layout, REGS, result, [])
    assert "метка сима: obj-11 «Е» угол 330,0°, lateral −13,2 px; сим принял seq ✗" in text


def test_cli_writes_wire_commands_next_to_out_and_links_it_in_audit_header(tmp_path, capsys):
    log, layout = two_jobs()
    (tmp_path / "ex.log").write_text(log.text(), encoding="utf-8")
    (tmp_path / "lay.log").write_text(layout, encoding="utf-8")
    (tmp_path / "regs.json").write_text(json.dumps(REGS), encoding="utf-8")
    argv = [
        "--exchange",
        str(tmp_path / "ex.log"),
        "--layout",
        str(tmp_path / "lay.log"),
        "--registers",
        str(tmp_path / "regs.json"),
        "--words",
        WORD,
    ]
    assert cli.main([*argv, "--out", str(tmp_path / "audit.md")]) == 0
    assert (tmp_path / "wire_commands.md").read_text(encoding="utf-8").startswith("# Журнал команд ПК → робот")
    assert "Журнал команд роботу (построчно, с расшифровкой): wire_commands.md" in (tmp_path / "audit.md").read_text(
        encoding="utf-8"
    )
    other = tmp_path / "no_out"
    other.mkdir()
    capsys.readouterr()
    assert cli.main(argv) == 0
    assert "wire_commands.md" not in capsys.readouterr().out


def _regs_for_plan() -> core.Regs:
    return core.load_registers(REGS)


def test_plan_for_word_peremirie_matches_hand_computed_literals():
    text = "\n".join(commands.plan_section(["ПЕРЕМИРИЕ"], _regs_for_plan()))
    expected = [
        "| 0 | П | 320,0 | −440,0 | −132,0 | 3200 · 61136 · 64216 | −100,0° → 64536 |",
        "| 1 | Е | 320,0 | −330,0 | −132,0 | 3200 · 62236 · 64216 | −100,0° → 64536 |",
        "| 2 | Р | 320,0 | −220,0 | −132,0 | 3200 · 63336 · 64216 | −100,0° → 64536 |",
        "| 3 | Е | 320,0 | −110,0 | −132,0 | 3200 · 64436 · 64216 | −100,0° → 64536 |",
        "| 4 | М | 320,0 | 0,0 | −132,0 | 3200 · 0 · 64216 | −100,0° → 64536 |",
        "| 5 | И | 320,0 | 110,0 | −132,0 | 3200 · 1100 · 64216 | −100,0° → 64536 |",
        "| 6 | Р | 320,0 | 220,0 | −132,0 | 3200 · 2200 · 64216 | −100,0° → 64536 |",
        "| 7 | И | 320,0 | 330,0 | −132,0 | 3200 · 3300 · 64216 | −100,0° → 64536 |",
        "| 8 | Е | 320,0 | 440,0 | −132,0 | 3200 · 4400 · 64216 | −100,0° → 64536 |",
    ]
    for line in expected:
        assert line in text
    assert "ПЛАН СЛОВА «ПЕРЕМИРИЕ» (заливка 1): ячейка → буква → куда класть" in text
    assert (
        "Буква встречается несколько раз (Е: ячейки 1, 3, 8; Р: ячейки 2, 6; И: ячейки 5, 7) — диск берёт первую свободную из них."
        in text
    )
    assert "P_PICK_RZ (−100,0°, с робота: robot_param_get_all) + доворот" in text


def test_plan_for_short_word_mir_uses_cells_0_to_2_with_the_same_pitch():
    text = "\n".join(commands.plan_section(["МИР"], _regs_for_plan()))
    assert "| 0 | М | 320,0 | −440,0 | −132,0 | 3200 · 61136 · 64216 | −100,0° → 64536 |" in text
    assert "| 1 | И | 320,0 | −330,0 | −132,0 | 3200 · 62236 · 64216 | −100,0° → 64536 |" in text
    assert "| 2 | Р | 320,0 | −220,0 | −132,0 | 3200 · 63336 · 64216 | −100,0° → 64536 |" in text
    assert "| 3 |" not in text


def test_repeated_word_in_third_fill_is_a_reference_to_the_first():
    text = "\n".join(commands.plan_section(["ПЕРЕМИРИЕ", "МИР", "ПЕРЕМИРИЕ"], _regs_for_plan()))
    assert "ПЛАН СЛОВА «ПЕРЕМИРИЕ» (заливка 3): как в заливке 1" in text
    assert text.count("ячейка → буква → куда класть") == 2


def test_plan_section_is_first_in_file_after_the_cheat_sheet():
    log, layout = two_jobs()
    text = render(log, layout)
    assert text.index("## Как читать") < text.index("## ПЛАН СЛОВА") < text.index("## Сводка")


def test_job_block_shows_plan_against_fact_and_mismatch_is_marked():
    log, layout = two_jobs()
    ok = render(log, layout)
    assert (
        "ПО ПЛАНУ: ячейка 8, буква Е → положить x 320,0, y 440,0, z −132,0 (из плана слова); ФАКТ на проводе: x 320,0, y 440,0, z −132,0 → ✓"
        in ok
    )
    bad = Log()
    bad.lines = [f"#51 {STAMP} [INFO] S.d.d.e.robot_main: #1  connect ok"]
    bad.n = 1
    bad.block(
        57111, "CVT_JOB", 32, [15912, 0, 4606, 62111, 64216, 3, 3100, 4400, 64216, 64764]
    )  # x на 10 мм меньше (привязка идёт по y)
    text = render(bad, layout_text([PICK_57111]))
    assert "ФАКТ на проводе: x 310,0, y 440,0, z −132,0 → ✗" in text


def test_plan_shifted_by_one_cell_would_not_match_the_wire():
    """Страховка инъекции: факт 57111 лежит на ячейке 8 (y 440,0), а не на соседней (y 330,0)."""
    log, layout = two_jobs()
    text = render(log, layout)
    assert "→ ✓" in text and "положить x 320,0, y 330,0" not in text
