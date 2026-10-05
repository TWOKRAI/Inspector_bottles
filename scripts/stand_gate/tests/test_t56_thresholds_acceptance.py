"""Task 5.6, часть A: слепая приёмка скрипта `python -m scripts.stand_gate` (чёрный ящик).

Написано ДО реализации, из «CLI (литерал)», «Определения», «Acceptance criteria (tester)»
плана `plans/transport-single-policy/phase-5.md` и схемы `docs/reviews/2026-10-03_phase5-stand-w2/`.
Скрипт зовётся подпроцессом `python -m scripts.stand_gate --from-json ...`, cwd = корень
дерева. Проверяется код выхода (0/1/2) и строки `FAIL <имя порога>: ...` в stdout.

ЗАКРЕПЛЁННЫЕ ПОДСТРОКИ ИМЁН ПОРОГОВ (регистр не важен; в тексте плана имена не литеральные,
подстроки выбраны мной по словам плана; строка `FAIL` должна содержать подстроку):

  queue_data_evicted           порог «rs.queue_data_evicted == 0» (s0, s2, pause.after)
  errors_delivery_failed       порог «rs.errors_delivery_failed == 0»
  born | formula | формул      формула по процессу born(P) - drops(P) == 0 (processor, inspector)
  neighbor | neighbour | сосед | handled
                               формула соседей handled(N) - own_in(N) - born(processor) == 0
  ledger | учёт | учет         учёт решателя 0 <= (I+N) - F <= 0.005 * F
  dup                          дубли trace_id в журнале == 0
  stale_restore                Σ not_inspected_stale_restore <= 0.001 * F
  lag  (+ "inspector")         lag@inspector за окно: s1 - s0 <= 100  (кейс D100)
  lag                          Σ lag_dropped_items у processor <= 0.01 * F (выключен --no-throughput-gate)
  verdict | вердикт            V >= 0.9 * (F - N)  (кейс D100)
  rss                          pause.rss1 - pause.rss0 <= 1 МиБ  (кейс P10)
  frame_stale_drops | stale_drops
                               старт: s0 rs.frame_stale_drops == 0 у процессов под every
  drain                        pause.drain_s <= 0.1  (кейс P10)
  NOT_MEASURED                 литерал в stdout при pause.drain_poll_period_s > 0.1 (код 1)

ЛИТЕРАЛЫ из фикстур (пересчитаны мной по JSON, не кодом скрипта):
  green_D100: F=3974 (camera_before_pause: source_producer_camera_service.cycles), I=3505,
              N=477, (I+N)-F=+8, V=3505, 0.9*(F-N)=3147.3, Σ lag_dropped_items processor=464
              (0.01*F=39.74), 0.005*F=19.87, 0.001*F=3.974, lag@inspector s1-s0 = 9-0 = 9,
              dup=0; start_s=12.94; actuation_fired_items=3969.
  green_P10:  F=4169, I=2480, N=1699, (I+N)-F=+10, Σ lag processor=1683, rss0=234274816,
              rss1=228274176 (Δ=-6000640), drain_s=0.05, drain_poll_period_s=0.02.
  red_E0_old: F=4938, I=3186, N=1686, (I+N)-F=-66, Σ stale_restore=73 (0.001*F=4.938),
              queue_data_evicted: processor=100, inspector=45; соседи: inspector
              1687-61-1665=-39, renderer 1637-0-1665=-28.

ДОГОВОРЁННОСТИ ТЕСТОВ (что я ИНТЕРПРЕТИРОВАЛ, а не прочёл буквально):
  * «мутация ОДНОГО ключа»: там, где одиночная мутация ломает соседний порог (формула
    born/drops, формулы соседей), граничные тесты stale_restore и lag используют согласованную
    мутацию из нескольких ключей (см. `_bump_inspector_stale_restore`, `_set_processor_lag`),
    иначе граница недостижима изолированно. Это названо в докстрингах.
  * «процессы под every» = processor и inspector (профиль quick: `extras.overflow: every`
    на них); renderer/storage — под latest. JSON этого не сообщает: top-level `overflow: every`
    один на кейс.
  * Все прогоны получают `--out-dir <tmp>`, чтобы не писать `reports/stand/` в дерево.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
FIX = Path(__file__).resolve().parent / "fixtures"

# --- подстроки имён порогов (см. докстринг модуля) --------------------------------
EVICTED = "queue_data_evicted"
DELIVERY = "errors_delivery_failed"
FORMULA = ("born", "formula", "формул")
NEIGHBOR = ("neighbor", "neighbour", "сосед", "handled")
LEDGER = ("ledger", "учёт", "учет")
DUP = "dup"
STALE_RESTORE = "stale_restore"
LAG = "lag"
VERDICT = ("verdict", "вердикт")
RSS = "rss"
STALE_START = ("frame_stale_drops", "stale_drops")
DRAIN = "drain"
NOT_MEASURED = "NOT_MEASURED"


# --- обвязка ---------------------------------------------------------------------
def _load(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def _put(d: dict, dotted: str, value: Any) -> None:
    """Записать значение по пути через точку; промежуточные ключи обязаны существовать."""
    *head, last = dotted.split(".")
    cur = d
    for part in head:
        cur = cur[part]
    assert last in cur, f"путь {dotted!r} не существует в фикстуре — тест написан неверно"
    cur[last] = value


def _get(d: dict, dotted: str) -> Any:
    cur = d
    for part in dotted.split("."):
        cur = cur[part]
    return cur


def _write(tmp_path: Path, data: dict, name: str = "case.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _run(tmp_path: Path, paths: list[Path], *flags: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    env["PYTHONIOENCODING"] = "utf-8"
    env["QT_QPA_PLATFORM"] = "offscreen"
    cmd = [
        sys.executable,
        "-m",
        "scripts.stand_gate",
        "--from-json",
        *[str(p) for p in paths],
        *flags,
        "--out-dir",
        str(tmp_path / "out"),
    ]
    try:
        res = subprocess.run(
            cmd,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
    except subprocess.TimeoutExpired:  # pragma: no cover - зависание = провал, не повисший прогон
        pytest.fail("scripts.stand_gate не завершился за 60 с (--from-json не должен поднимать стенд)")
    assert "No module named" not in res.stderr, f"пакет scripts.stand_gate отсутствует: {res.stderr.strip()[-300:]}"
    return res


def _gate(
    tmp_path: Path,
    base: str,
    edits: dict[str, Any] | None = None,
    *,
    throughput_gate: bool = False,
) -> subprocess.CompletedProcess:
    """Прогнать скрипт на фикстуре `base` с мутациями `edits` (путь через точку -> значение)."""
    data = _load(base)
    for dotted, value in (edits or {}).items():
        _put(data, dotted, value)
    flags = () if throughput_gate else ("--no-throughput-gate",)
    return _run(tmp_path, [_write(tmp_path, data)], *flags)


def _fail_lines(res: subprocess.CompletedProcess) -> list[str]:
    return [ln.strip() for ln in res.stdout.splitlines() if ln.strip().startswith("FAIL")]


def _needle_hit(line: str, needle: str | tuple[str, ...]) -> bool:
    low = line.lower()
    alts = (needle,) if isinstance(needle, str) else needle
    return any(a.lower() in low for a in alts)


def _assert_red(res: subprocess.CompletedProcess, *needles: str | tuple[str, ...]) -> None:
    """Код 1 и хотя бы одна строка `FAIL ...`, в которой есть ВСЕ needles (каждый — либо
    подстрока, либо кортеж альтернатив)."""
    ctx = f"\n--- rc={res.returncode}\n--- stdout:\n{res.stdout}\n--- stderr:\n{res.stderr}"
    assert res.returncode == 1, f"ожидался код 1{ctx}"
    lines = _fail_lines(res)
    assert lines, f"нет строки `FAIL ...` в stdout{ctx}"
    assert any(all(_needle_hit(ln, n) for n in needles) for ln in lines), (
        f"ни одна строка FAIL не содержит {needles}{ctx}"
    )


def _assert_green(res: subprocess.CompletedProcess) -> None:
    ctx = f"\n--- rc={res.returncode}\n--- stdout:\n{res.stdout}\n--- stderr:\n{res.stderr}"
    assert res.returncode == 0, f"ожидался код 0{ctx}"
    assert not _fail_lines(res), f"код 0, но в stdout есть строка FAIL{ctx}"


def _bump_inspector_stale_restore(edits: dict[str, Any], k: int) -> dict[str, Any]:
    """Согласованно добавить k «stale_restore» у inspector в D100, не ломая формулы.

    born(inspector) растёт на k (own_in), поэтому drops растёт на k (lag_dropped_items той же
    воркер-записи) и handled(inspector) растёт на k (формула соседей): ни одна другая
    формула не двигается, остаётся только порог stale_restore.
    """
    edits["s2.inspector.workers.data_receiver.not_inspected_stale_restore"] = k
    edits["s2.inspector.workers.data_receiver.lag_dropped_items"] = 10 + k
    edits["s2.inspector.workers.pipeline_executor.not_inspected_handled"] = 477 + k
    return edits


def _set_processor_lag(edits: dict[str, Any], lag: int) -> dict[str, Any]:
    """Согласованно выставить Σ lag_dropped_items у processor (D100: было 464) = lag.

    Уменьшение на delta сдвигает born и drops processor на delta (формула по процессу
    цела) и handled у inspector и renderer на delta (формула соседей цела).
    """
    delta = 464 - lag
    edits["s2.processor.workers.data_receiver.lag_dropped_items"] = lag
    edits["s2.processor.workers.data_receiver.not_inspected_lag"] = lag
    edits["s2.inspector.workers.pipeline_executor.not_inspected_handled"] = 477 - delta
    edits["s2.renderer.workers.pipeline_executor.not_inspected_handled"] = 467 - delta
    return edits


# =================================================================================
# Коды выхода и зелёные фикстуры
# =================================================================================
def test_green_D100_exits_0_with_no_throughput_gate(tmp_path):
    _assert_green(_gate(tmp_path, "green_D100"))


def test_green_P10_exits_0_with_no_throughput_gate(tmp_path):
    _assert_green(_gate(tmp_path, "green_P10"))


def test_two_green_files_in_one_call_exit_0(tmp_path):
    """`--from-json PATH ...` — несколько путей через пробел (форма из CLI-литерала)."""
    res = _run(
        tmp_path,
        [FIX / "green_D100.json", FIX / "green_P10.json"],
        "--no-throughput-gate",
    )
    _assert_green(res)


def test_green_plus_red_file_in_one_call_exits_1_and_names_evicted(tmp_path):
    res = _run(
        tmp_path,
        [FIX / "green_D100.json", FIX / "red_E0_old.json"],
        "--no-throughput-gate",
    )
    _assert_red(res, EVICTED)


def test_green_D100_without_no_throughput_gate_fails_on_processor_lag(tmp_path):
    """464 > 0.01 * 3974 = 39.74: без флага порог lag включён."""
    res = _gate(tmp_path, "green_D100", throughput_gate=True)
    _assert_red(res, LAG, "464")


def test_green_P10_without_no_throughput_gate_fails_on_processor_lag(tmp_path):
    """1683 > 0.01 * 4169 = 41.69."""
    res = _gate(tmp_path, "green_P10", throughput_gate=True)
    _assert_red(res, LAG, "1683")


# =================================================================================
# red_E0_old: настоящие потери
# =================================================================================
def test_red_E0_old_exits_1(tmp_path):
    res = _gate(tmp_path, "red_E0_old")
    assert res.returncode == 1, res.stdout + res.stderr


def test_red_E0_old_names_queue_data_evicted(tmp_path):
    _assert_red(_gate(tmp_path, "red_E0_old"), EVICTED)


def test_red_E0_old_names_solver_ledger(tmp_path):
    """(3186 + 1686) - 4938 = -66 < 0: решатель потерял кадры."""
    _assert_red(_gate(tmp_path, "red_E0_old"), LEDGER)


def test_red_E0_old_solver_ledger_line_shows_the_fact_minus_66(tmp_path):
    """`FAIL <имя>: <факт> vs <порог>` — факт учёта = -66 (интерпретация: ASCII-минус)."""
    _assert_red(_gate(tmp_path, "red_E0_old"), LEDGER, "-66")


def test_red_E0_old_names_stale_restore(tmp_path):
    """Σ stale_restore = 31 + 42 = 73 > 0.001 * 4938 = 4.938."""
    _assert_red(_gate(tmp_path, "red_E0_old"), STALE_RESTORE)


def test_red_E0_old_names_neighbor_formula(tmp_path):
    """inspector: 1687 - 61 - 1665 = -39; renderer: 1637 - 0 - 1665 = -28."""
    _assert_red(_gate(tmp_path, "red_E0_old"), NEIGHBOR)


# =================================================================================
# Формула по процессу: born(P) - drops(P) == 0 на s2 (D100: processor 467/467, inspector 11/11)
# =================================================================================
@pytest.mark.parametrize(
    "dotted, value",
    [
        # drops processor 467 -> 472 при born 467 (+5 lag_dropped_items)
        ("s2.processor.workers.data_receiver.lag_dropped_items", 469),
        # drops inspector 11 -> 16
        ("s2.inspector.workers.data_receiver.lag_dropped_items", 15),
        # born inspector 11 -> 10: слагаемое rs.not_inspected_door входит в born
        ("s2.inspector.rs.not_inspected_door", 0),
        # drops inspector 11 -> 10: слагаемое rs.frame_stale_drops входит в drops
        ("s2.inspector.rs.frame_stale_drops", 0),
        # drops inspector 11 -> 12: frame_torn_reads входит в drops
        ("s2.inspector.rs.frame_torn_reads", 1),
        # drops inspector 11 -> 12: frame_restore_failures входит в drops
        ("s2.inspector.rs.frame_restore_failures", 1),
    ],
    ids=[
        "processor_lag_dropped_items_plus5",
        "inspector_lag_dropped_items_plus5",
        "inspector_door_term_removed_from_born",
        "inspector_stale_drops_term_removed_from_drops",
        "inspector_torn_reads_added_to_drops",
        "inspector_restore_failures_added_to_drops",
    ],
)
def test_per_process_formula_violation_exits_1(tmp_path, dotted, value):
    _assert_red(_gate(tmp_path, "green_D100", {dotted: value}), FORMULA)


# =================================================================================
# Формула соседей: handled(N) - own_in(N) - born(processor) == 0 для inspector и renderer
# =================================================================================
@pytest.mark.parametrize(
    "dotted, value",
    [
        # inspector: 478 - 10 - 467 = +1
        ("s2.inspector.workers.pipeline_executor.not_inspected_handled", 478),
        # renderer: 466 - 0 - 467 = -1
        ("s2.renderer.workers.pipeline_executor.not_inspected_handled", 466),
    ],
    ids=["inspector_handled_plus1", "renderer_handled_minus1"],
)
def test_neighbor_formula_violation_exits_1(tmp_path, dotted, value):
    """handled не входит в формулу по процессу, поэтому нарушена только формула соседей."""
    _assert_red(_gate(tmp_path, "green_D100", {dotted: value}), NEIGHBOR)


# =================================================================================
# rs.queue_data_evicted == 0 и rs.errors_delivery_failed == 0 (s0, s2; в P10 ещё pause.after)
# =================================================================================
_COUNTER_SITES_D100 = [
    "s0.processor",
    "s0.camera_0",
    "s2.inspector",
    "s2.storage",
]
_COUNTER_SITES_P10 = ["pause.after.processor", "pause.after.renderer"]


@pytest.mark.parametrize("site", _COUNTER_SITES_D100)
def test_queue_data_evicted_nonzero_exits_1_D100(tmp_path, site):
    _assert_red(_gate(tmp_path, "green_D100", {f"{site}.rs.queue_data_evicted": 1}), EVICTED)


@pytest.mark.parametrize("site", _COUNTER_SITES_P10)
def test_queue_data_evicted_nonzero_in_pause_after_exits_1_P10(tmp_path, site):
    _assert_red(_gate(tmp_path, "green_P10", {f"{site}.rs.queue_data_evicted": 1}), EVICTED)


@pytest.mark.parametrize("site", _COUNTER_SITES_D100)
def test_errors_delivery_failed_nonzero_exits_1_D100(tmp_path, site):
    _assert_red(_gate(tmp_path, "green_D100", {f"{site}.rs.errors_delivery_failed": 1}), DELIVERY)


@pytest.mark.parametrize("site", _COUNTER_SITES_P10)
def test_errors_delivery_failed_nonzero_in_pause_after_exits_1_P10(tmp_path, site):
    _assert_red(_gate(tmp_path, "green_P10", {f"{site}.rs.errors_delivery_failed": 1}), DELIVERY)


# =================================================================================
# Учёт решателя: 0 <= (I + N) - F <= 0.005 * F;  F берётся из camera_before_pause
# D100: I=3505, N=477, F=3974, сейчас +8, верхняя граница 19.87
# =================================================================================
@pytest.mark.parametrize(
    "n_value, expect_green",
    [
        (469, True),  # (3505 + 469) - 3974 = 0 : нижняя граница включена
        (468, False),  # -1
        (488, True),  # +19 <= 19.87
        (489, False),  # +20 > 19.87
    ],
    ids=["lower_edge_0_ok", "below_zero_minus1", "upper_19_ok", "upper_20_fails"],
)
def test_solver_ledger_boundaries(tmp_path, n_value, expect_green):
    res = _gate(tmp_path, "green_D100", {"rc_s2.result.total_not_inspected": n_value})
    if expect_green:
        _assert_green(res)
    else:
        _assert_red(res, LEDGER)


def test_solver_ledger_takes_F_from_camera_before_pause(tmp_path):
    """cycles +100 -> F = 4074, (I+N)-F = -92: F читается из camera_before_pause."""
    res = _gate(
        tmp_path,
        "green_D100",
        {"camera_before_pause.workers.source_producer_camera_service.cycles": 4074},
    )
    _assert_red(res, LEDGER)


def test_solver_ledger_ignores_camera_after_pause(tmp_path):
    """После worker.pause_all камера не отвечает: camera_after_pause в F не участвует."""
    data = _load("green_D100")
    data["camera_after_pause"] = {
        "workers": {"source_producer_camera_service": {"cycles": 999999}},
        "rs": {},
        "rs_all": {},
        "queues": {},
    }
    _assert_green(_run(tmp_path, [_write(tmp_path, data)], "--no-throughput-gate"))


def test_solver_ledger_finds_the_nested_dict_with_total_inspected(tmp_path):
    """rc_s2 обёрнут драйвером — искать вложенный dict с ключом total_inspected на любой глубине."""
    data = _load("green_D100")
    inner = data["rc_s2"]["result"]
    data["rc_s2"] = {"envelope": {"extra_wrapper": {"payload": inner}}, "success": True}
    _assert_green(_run(tmp_path, [_write(tmp_path, data)], "--no-throughput-gate"))


def test_duplicate_trace_id_in_journal_exits_1(tmp_path):
    _assert_red(_gate(tmp_path, "green_D100", {"journal.dup": 1}), DUP)


# =================================================================================
# stale_restore: Σ_P Σ_workers not_inspected_stale_restore <= 0.001 * F  (D100: 3.974 -> 3 ok, 4 fails)
# Согласованная мутация у inspector (см. _bump_inspector_stale_restore).
# =================================================================================
def test_stale_restore_3_is_within_0_001_F(tmp_path):
    res = _gate(tmp_path, "green_D100", _bump_inspector_stale_restore({}, 3))
    _assert_green(res)


def test_stale_restore_4_exceeds_0_001_F(tmp_path):
    res = _gate(tmp_path, "green_D100", _bump_inspector_stale_restore({}, 4))
    _assert_red(res, STALE_RESTORE)


# =================================================================================
# Lag processor: Σ lag_dropped_items <= 0.01 * F  (D100: 39.74 -> 39 ok, 40 fails), порог включён
# Согласованная мутация (см. _set_processor_lag).
# =================================================================================
def test_processor_lag_39_is_within_0_01_F_with_throughput_gate(tmp_path):
    res = _gate(tmp_path, "green_D100", _set_processor_lag({}, 39), throughput_gate=True)
    _assert_green(res)


def test_processor_lag_40_exceeds_0_01_F_with_throughput_gate(tmp_path):
    res = _gate(tmp_path, "green_D100", _set_processor_lag({}, 40), throughput_gate=True)
    _assert_red(res, LAG)


# =================================================================================
# Вердикты (кейс D100): V >= 0.9 * (F - N) = 0.9 * 3497 = 3147.3
# =================================================================================
def test_verdicts_3148_meet_the_90_percent_floor(tmp_path):
    _assert_green(_gate(tmp_path, "green_D100", {"journal.verdicts": 3148}))


def test_verdicts_3147_are_below_the_90_percent_floor(tmp_path):
    _assert_red(_gate(tmp_path, "green_D100", {"journal.verdicts": 3147}), VERDICT)


def test_verdict_floor_is_not_applied_outside_D100_for_P10(tmp_path):
    """Область порога — кейс D100 (transit_ms > 0). У P10 V=0 не должен краснеть по вердиктам.
    Интерпретация «только D100» — по формулировке «Вердикты при transit_ms > 0 (кейс D100)»."""
    res = _gate(tmp_path, "green_P10", {"journal.verdicts": 0})
    assert not any(_needle_hit(ln, VERDICT) for ln in _fail_lines(res)), res.stdout


def test_verdict_floor_is_not_applied_to_case_E(tmp_path):
    """D100 с transit_ms=0 и без pause — это кейс E: порог вердиктов не действует."""
    res = _gate(tmp_path, "green_D100", {"transit_ms": 0, "journal.verdicts": 0})
    _assert_green(res)


# =================================================================================
# lag@inspector за окно (D100, гейт 5.2): Σ not_inspected_lag(s1) - то же на s0 <= 100
# =================================================================================
_INSP_LAG = "workers.data_receiver.not_inspected_lag"


def test_inspector_window_lag_100_is_within_limit(tmp_path):
    _assert_green(_gate(tmp_path, "green_D100", {f"s1.inspector.{_INSP_LAG}": 100}))


def test_inspector_window_lag_101_exceeds_limit(tmp_path):
    res = _gate(tmp_path, "green_D100", {f"s1.inspector.{_INSP_LAG}": 101})
    _assert_red(res, LAG, "inspector")


def test_inspector_window_lag_subtracts_s0_baseline(tmp_path):
    """s1=150 при s0=50 — окно 100, зелёное; абсолютное чтение s1 дало бы 150 > 100."""
    edits = {f"s0.inspector.{_INSP_LAG}": 50, f"s1.inspector.{_INSP_LAG}": 150}
    _assert_green(_gate(tmp_path, "green_D100", edits))


def test_inspector_window_lag_101_over_s0_baseline_exceeds_limit(tmp_path):
    edits = {f"s0.inspector.{_INSP_LAG}": 50, f"s1.inspector.{_INSP_LAG}": 151}
    _assert_red(_gate(tmp_path, "green_D100", edits), LAG, "inspector")


def test_inspector_window_lag_is_not_applied_to_case_E(tmp_path):
    """Кейс E (transit_ms=0, без pause): окно lag@inspector не проверяется (область — D100)."""
    res = _gate(tmp_path, "green_D100", {"transit_ms": 0, f"s1.inspector.{_INSP_LAG}": 5000})
    _assert_green(res)


# =================================================================================
# P10: ΔRSS <= 1 МиБ = 1048576 байт; rss0 = 234274816
# =================================================================================
def test_pause_rss_growth_of_exactly_1_mib_is_within_limit(tmp_path):
    _assert_green(_gate(tmp_path, "green_P10", {"pause.rss1": 234274816 + 1048576}))


def test_pause_rss_growth_of_1_mib_plus_1_byte_exceeds_limit(tmp_path):
    _assert_red(_gate(tmp_path, "green_P10", {"pause.rss1": 234274816 + 1048577}), RSS)


# =================================================================================
# P10: дренаж  drain_s <= 0.1;  drain_poll_period_s > 0.1 -> NOT_MEASURED (код 1)
# =================================================================================
def test_drain_of_exactly_0_1_s_is_within_limit(tmp_path):
    _assert_green(_gate(tmp_path, "green_P10", {"pause.drain_s": 0.1}))


def test_drain_of_0_11_s_exceeds_limit(tmp_path):
    _assert_red(_gate(tmp_path, "green_P10", {"pause.drain_s": 0.11}), DRAIN)


def test_slow_drain_is_a_measured_fail_not_not_measured(tmp_path):
    """Опрос быстрый (0.02 с), дренаж 0.2 с: это FAIL, а не NOT_MEASURED."""
    res = _gate(tmp_path, "green_P10", {"pause.drain_s": 0.2})
    _assert_red(res, DRAIN)
    assert NOT_MEASURED not in res.stdout, res.stdout


def test_poll_period_of_exactly_0_1_s_is_still_measured(tmp_path):
    """Граница строгая: NOT_MEASURED только при > 0.1."""
    _assert_green(_gate(tmp_path, "green_P10", {"pause.drain_poll_period_s": 0.1}))


def test_poll_period_above_0_1_s_is_not_measured_and_exits_1(tmp_path):
    """drain_s = 0.05 остаётся зелёным по порогу; код 1 даёт только NOT_MEASURED."""
    res = _gate(tmp_path, "green_P10", {"pause.drain_poll_period_s": 0.11})
    ctx = f"\nrc={res.returncode}\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"
    assert res.returncode == 1, ctx
    assert NOT_MEASURED in res.stdout, ctx
    assert any(DRAIN in ln.lower() for ln in res.stdout.splitlines() if NOT_MEASURED in ln), (
        "строка с NOT_MEASURED должна называть дренаж" + ctx
    )


# =================================================================================
# Старт (s0): rs.frame_stale_drops == 0 у процессов под every (processor, inspector)
# =================================================================================
@pytest.mark.parametrize("proc", ["processor", "inspector"])
def test_start_stale_drops_under_every_exit_1(tmp_path, proc):
    res = _gate(tmp_path, "green_D100", {f"s0.{proc}.rs.frame_stale_drops": 1})
    _assert_red(res, STALE_START)


@pytest.mark.parametrize("proc", ["renderer", "storage"])
def test_start_stale_drops_under_latest_are_report_only(tmp_path, proc):
    """Под latest число в отчёте без порога: 50 дропов на s0 не краснят прогон."""
    _assert_green(_gate(tmp_path, "green_D100", {f"s0.{proc}.rs.frame_stale_drops": 50}))


# =================================================================================
# Код 2: сбой прогона
# =================================================================================
def test_json_without_s2_exits_2(tmp_path):
    data = _load("green_D100")
    del data["s2"]
    res = _run(tmp_path, [_write(tmp_path, data)], "--no-throughput-gate")
    assert res.returncode == 2, res.stdout + res.stderr


@pytest.mark.parametrize("key", ["rc_s2", "camera_before_pause", "journal"])
def test_json_without_other_required_inputs_exits_2(tmp_path, key):
    """Интерпретация «нет обязательного ключа»: F, I, N и журнал нужны для порогов."""
    data = _load("green_D100")
    del data[key]
    res = _run(tmp_path, [_write(tmp_path, data)], "--no-throughput-gate")
    assert res.returncode == 2, res.stdout + res.stderr


def test_nonexistent_json_path_exits_2(tmp_path):
    res = _run(tmp_path, [tmp_path / "no_such_file.json"], "--no-throughput-gate")
    assert res.returncode == 2, res.stdout + res.stderr


def test_malformed_json_exits_2(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    res = _run(tmp_path, [bad], "--no-throughput-gate")
    assert res.returncode == 2, res.stdout + res.stderr


# =================================================================================
# Отчёт (интерпретация): числа «в отчёте, без порога» попадают в файл --out-dir
# =================================================================================
def test_report_file_carries_lag_and_actuation_numbers(tmp_path):
    """Интерпретация: при --from-json скрипт тоже пишет .md в --out-dir. Под
    --no-throughput-gate lag (464) и actuation_fired_items (3969) стоят в отчёте без порога."""
    res = _gate(tmp_path, "green_D100")
    _assert_green(res)
    reports = sorted((tmp_path / "out").glob("*.md"))
    assert reports, f"в {tmp_path / 'out'} нет .md-отчёта"
    text = "\n".join(p.read_text(encoding="utf-8") for p in reports)
    assert "464" in text, "число lag processor (464) не в отчёте"
    assert "3969" in text, "actuation_fired_items (3969) не в отчёте"


# Страж собственной корректности: тест-копии фикстур не рассинхронизированы с литералами выше.
def test_fixture_literals_used_by_this_file_are_still_true():
    d = _load("green_D100")
    assert _get(d, "camera_before_pause.workers.source_producer_camera_service.cycles") == 3974
    assert _get(d, "rc_s2.result.total_inspected") == 3505
    assert _get(d, "rc_s2.result.total_not_inspected") == 477
    assert _get(d, "s2.processor.workers.data_receiver.lag_dropped_items") == 464
    assert _get(d, "s2.inspector.workers.pipeline_executor.not_inspected_handled") == 477
    assert _get(d, "s2.renderer.workers.pipeline_executor.not_inspected_handled") == 467
    p = _load("green_P10")
    assert _get(p, "pause.rss0") == 234274816
    assert _get(p, "pause.drain_poll_period_s") == 0.02
