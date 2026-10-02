# ruff: noqa: E501  -- литералы заголовков и фикстуры планов взяты из живого дерева дословно
"""Правки по ревью кода plans_progress.py (итерация 1): каждая правка — свой красный тест.

Литералы заголовков скопированы из живых планов (telemetry-publish-control, letters-retrain,
lifecycle-stop-ownership, observation-port, observability-closure), а не из вывода парсера.
Ходим через CLI в subprocess (фикстуры conftest.py); исключение — проверка мёртвого кода.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SECTION = "## Порядок выполнения\n\n"


def plan_text(items: str) -> str:
    return "# План\n\n" + SECTION + items


def heading_plan(heading: str, body: str = "текст без признаков статуса\n") -> str:
    return "# План\n\n" + heading + "\n" + body


def out_of(cp) -> str:
    return cp.stdout + "\n" + cp.stderr


def finding_lines(out: str, code: str) -> list[str]:
    return [ln for ln in out.splitlines() if ln.startswith(code + " ")]


# =========================================================================== 1. статус в хвосте заголовка

TAIL_CASES = [
    # (заголовок дословно из живого плана, ожидаемый статус)
    ("#### Task 7.1 — ThrottleMiddleware: merge-путь + рантайм-мутабельность ✅ DONE", "done"),
    ("### Task 7.1 — каталог букв сима по замеру (только данные) — DONE 50df705f", "done"),
    ("### Task 7.1 — подпись всегда, ниже порога — с пометкой — DONE 5ed21461 + 87d50a0f", "done"),
    (
        "### Task 7.1 — чёрный фон под лентой — SUPERSEDED (2026-10-01) → `plans/layer-render` Task 1.1–1.3 (фон слоями: заливка + плитка с альфой)",
        "superseded",
    ),
    ("### Task 7.1 — ui_*-плоскость: доказательство парой (закрытие NA) — [x] ЗАКРЫТ 2026-07-22", "done"),
    ("### Task 7.1 — Потери видны снаружи, а не только в stderr умирающего процесса ✅ DONE 2026-09-26", "done"),
    (
        "### Task 7.1 — Сирот нет по построению: ребёнок не переживает родителя ✅ DONE 2026-09-25 (кроме Linux — отложено)",
        "done",
    ),
    ("### Task 7.1 ✅ `d6d6752c` — Фасад чисел — в порт; маршрутизация родом данных", "done"),
    ("### Task 7.1 — Единый источник endpoint-конфига  ✅ (9be0b852)", "done"),
    ("### Task 7.1 — Per-worker телеметрия (доп. запрос владельца) — DONE", "done"),
    ("### Task 7.1 — имя (ЗАКРЫТА 2026-08-03)", "done"),
    ("### Task 7.1 — имя **[x] СДЕЛАНА**", "done"),
    ("### Task 7.1 — имя — снята", "superseded"),
    ("### Task 7.1 — имя — отложена", "deferred"),
]


@pytest.mark.parametrize(("heading", "expected"), TAIL_CASES)
def test_status_in_heading_tail_outside_brackets(make_root, one_plan, statuses, heading, expected):
    root = make_root({"plans/2026-10-02_tail/plan.md": heading_plan(heading)})
    rec = one_plan(root, "2026-10-02_tail")
    assert statuses(rec) == {"7.1": expected}


def test_heading_tail_status_is_not_unmarked(make_root, one_plan):
    root = make_root({"plans/2026-10-02_tail/plan.md": heading_plan("### Task 7.1 — имя — DONE 50df705f")})
    assert one_plan(root, "2026-10-02_tail")["unmarked"] == 0


NOT_TAIL_CASES = [
    "### Task 7.1: проверить, что DONE ставится после записи",
    "### Task 7.1 — починить DONE-детектор",
    "### Task 7.1 — DONE: «переключает, но картинка не меняется на новую» (корень #2)",
    "### Task 7.1 — доделать закрытие плана и снятие флага",
]


@pytest.mark.parametrize("heading", NOT_TAIL_CASES)
def test_status_word_in_the_middle_of_a_title_is_not_a_status(make_root, one_plan, statuses, heading):
    root = make_root({"plans/2026-10-02_mid/plan.md": heading_plan(heading)})
    rec = one_plan(root, "2026-10-02_mid")
    assert statuses(rec) == {"7.1": "pending"}
    assert rec["unmarked"] == 1


def test_partial_mark_is_pending_not_deferred(make_root, one_plan, statuses):
    head = "### Task 7.1 — Персист runtime-дельты в PM + fan-out publisher-gate из watcher ⚠️ ЧАСТИЧНО (c0b6e01b: шаги 1-2-4; шаг 3 отложен)"
    root = make_root({"plans/2026-10-02_part/plan.md": heading_plan(head)})
    assert statuses(one_plan(root, "2026-10-02_part")) == {"7.1": "pending"}


def test_status_line_and_group_win_over_tail_mark(make_root, one_plan, statuses):
    text = "# План\n\n### Task 7.1 — имя ✅ DONE\n**Статус:** [PENDING]\n\n### Task 7.2 — имя [BLOCKED] ✅ DONE\n"
    root = make_root({"plans/2026-10-02_prio/plan.md": text})
    assert statuses(one_plan(root, "2026-10-02_prio")) == {"7.1": "pending", "7.2": "blocked"}


TELEMETRY_PUBLISH_CONTROL = """# telemetry-publish-control

#### Task 0.1 — ThrottleMiddleware: merge-путь + рантайм-мутабельность ✅ DONE
#### Task 1.1 — Контракт `TelemetryPublishConfig` (schema) ✅ DONE
#### Task 1.2 — Publisher-gate в heartbeat ✅ DONE
#### Task 1.3 — Конфиг-плумбинг до ребёнка ✅ DONE
#### Task 2.1 — `build_throttle_rules` из конфига ✅ DONE
#### Task 3.1 — Hot-reload телеметрии единым путём ✅ DONE
#### Task 3.2 — backend_ctl команда `telemetry.*` ✅ DONE
#### Task 3.3 — Fan-out на всех детей ✅ DONE
#### Task 4.1 — GUI: тумблеры/частота метрик ✅ DONE
#### Task 4.2 — ADR + memory ✅ DONE
"""

LETTERS_RETRAIN = """# letters-retrain

### Task 0.1 — чёрный фон под лентой — SUPERSEDED (2026-10-01) → `plans/layer-render` Task 1.1–1.3 (фон слоями: заливка + плитка с альфой)
текст

### Task 0.2 — каталог букв сима по замеру (только данные) — DONE 50df705f
текст

### Task 0.3 — подпись всегда, ниже порога — с пометкой — DONE 5ed21461 + 87d50a0f
текст

### Task 0.4 — базовая линия текущей сети на исправленном симе
текст
"""


def test_live_telemetry_publish_control_is_ten_of_ten(make_root, one_plan):
    root = make_root({"plans/telemetry-publish-control.md": TELEMETRY_PUBLISH_CONTROL})
    rec = one_plan(root, "telemetry-publish-control")
    assert (rec["done"], rec["total"], rec["unmarked"]) == (10, 10, 0)


def test_live_letters_retrain_is_two_of_three_with_one_superseded(make_root, one_plan, statuses):
    root = make_root({"plans/letters-retrain/plan.md": LETTERS_RETRAIN})
    rec = one_plan(root, "letters-retrain")
    assert (rec["done"], rec["total"], rec["dropped"], rec["unmarked"]) == (2, 3, 1, 1)
    assert statuses(rec) == {"0.1": "superseded", "0.2": "done", "0.3": "done", "0.4": "pending"}


def test_live_lifecycle_stop_ownership_task_16_is_done(make_root, one_plan, statuses):
    head = "### Task 1.6 — Потери видны снаружи, а не только в stderr умирающего процесса ✅ DONE 2026-09-26"
    root = make_root({"plans/lifecycle-stop-ownership.md": heading_plan(head)})
    assert statuses(one_plan(root, "lifecycle-stop-ownership")) == {"1.6": "done"}


# =========================================================================== 2. --check на пустом корне


def test_check_missing_root_exits_2_with_message(tmp_path, progress):
    cp = progress(tmp_path / "нет_такого_корня", "--check")
    assert cp.returncode == 2, out_of(cp)[:400]
    assert "нет_такого_корня" in out_of(cp)


def test_check_root_without_plans_dir_exits_2(tmp_path, progress):
    (tmp_path / "empty").mkdir()
    cp = progress(tmp_path / "empty", "--check")
    assert cp.returncode == 2, out_of(cp)[:400]


def test_check_zero_live_plans_exits_2(make_root, progress):
    root = make_root({"plans/_archive/2026-Q4/2026-10-01_old/plan.md": plan_text("- Task 1.1: a [DONE]\n")})
    cp = progress(root, "--check")
    assert cp.returncode == 2, out_of(cp)[:400]


def test_check_summary_prints_number_of_checked_plans(make_root, progress):
    root = make_root(
        {
            "plans/2026-10-02_a/plan.md": plan_text("- Task 1.1: a [PENDING]\n"),
            "plans/2026-10-02_b/plan.md": plan_text("- Task 1.1: a [PENDING]\n"),
            "plans/_archive/2026-Q4/2026-10-01_old/plan.md": plan_text("- Task 1.1: a [DONE]\n"),
        }
    )
    cp = progress(root, "--check")
    assert cp.returncode == 0
    assert "проверено планов 2" in cp.stdout, cp.stdout[-300:]


# =========================================================================== 3. UNCLOSED_FENCE

FENCE_PLAN = "- Task 1.1 [DONE]\n```\n- Task 1.2 [PENDING]\n- Task 1.3 [PENDING]\n"


def _order(order_md, **tiers):
    return order_md(**tiers)


def test_unclosed_fence_blocks_for_tier_41(make_root, progress, order_md):
    root = make_root(
        {
            "plans/2026-10-02_fence/plan.md": plan_text(FENCE_PLAN),
            "plans/queue/ORDER.md": order_md(tier41=["2026-10-02_fence"]),
        }
    )
    cp = progress(root, "--check")
    assert cp.returncode == 1, out_of(cp)[:500]
    assert any("2026-10-02_fence" in ln for ln in finding_lines(out_of(cp), "UNCLOSED_FENCE")), out_of(cp)[:500]
    assert any("blocking" in ln for ln in finding_lines(out_of(cp), "UNCLOSED_FENCE"))


def test_unclosed_fence_is_info_for_tier_43_and_unlisted(make_root, progress, order_md):
    root = make_root(
        {
            "plans/p-closed/plan.md": plan_text(FENCE_PLAN),
            "plans/p-free/plan.md": plan_text(FENCE_PLAN),
            "plans/queue/ORDER.md": order_md(tier43=["p-closed"]),
        }
    )
    cp = progress(root, "--check")
    assert cp.returncode == 0, out_of(cp)[:500]
    names = [ln.split()[1] for ln in finding_lines(out_of(cp), "UNCLOSED_FENCE")]
    assert sorted(names) == ["p-closed", "p-free"]


def test_closed_fence_gives_no_finding(make_root, progress):
    text = plan_text("- Task 1.1: a [DONE]\n\n```\nкод\n```\n\n- Task 1.2: b [PENDING]\n")
    root = make_root({"plans/2026-10-02_ok/plan.md": text})
    assert not finding_lines(out_of(progress(root, "--check")), "UNCLOSED_FENCE")


def test_unclosed_fence_in_phase_file_is_named(make_root, progress):
    root = make_root(
        {
            "plans/2026-10-02_ph/plan.md": plan_text("- Task 1.1: a [PENDING]\n"),
            "plans/2026-10-02_ph/phase-1.md": "# Ф1\n\n```\nне закрыт\n",
        }
    )
    assert finding_lines(out_of(progress(root, "--check")), "UNCLOSED_FENCE")


def test_unclosed_fence_baseline_key_is_plan_and_code(make_root, progress, order_md, tmp_path):
    root = make_root(
        {
            "plans/2026-10-02_fence/plan.md": plan_text(FENCE_PLAN),
            "plans/queue/ORDER.md": order_md(tier41=["2026-10-02_fence"]),
        }
    )
    base = tmp_path / "base.txt"
    base.write_text("2026-10-02_fence:UNCLOSED_FENCE\n", encoding="utf-8")
    assert progress(root, "--check", "--baseline", str(base)).returncode == 0


# =========================================================================== 4. tasks/<id>.md без статуса


def test_task_file_without_any_status_is_unmarked(make_root, one_plan, progress):
    root = make_root(
        {
            "plans/2026-10-02_tdir/plan.md": "# План без списка\n",
            "plans/2026-10-02_tdir/tasks/1.1.md": "# Task 1.1 — a\n\nпроза без статуса\n",
            "plans/2026-10-02_tdir/tasks/1.2.md": "# Task 1.2 — b\n\n**Статус:** [DONE]\n",
            "plans/2026-10-02_tdir/tasks/1.3.md": "# Task 1.3 — c\n\n- [ ] шаг\n",
        }
    )
    assert one_plan(root, "2026-10-02_tdir")["unmarked"] == 1
    lines = finding_lines(out_of(progress(root, "--check")), "NO_STATUS_MARK")
    assert any("1 из 3" in ln for ln in lines), lines


# =========================================================================== 5. TASK_ID_UNPARSED

CYR_HEADING = "### Task Т.1 — выпилить читателя полностью (напр. из phase-1-2)\n**Level:** Senior+\n"


def test_cyrillic_task_id_in_heading_is_reported_not_blocking(make_root, progress, order_md):
    root = make_root(
        {
            "plans/2026-10-02_cyr/plan.md": plan_text("- Task 1.1: a [PENDING]\n"),
            "plans/2026-10-02_cyr/phase-1-2-address-and-removal.md": "# Ф1\n\n" + CYR_HEADING,
            "plans/queue/ORDER.md": order_md(tier41=["2026-10-02_cyr"]),
        }
    )
    cp = progress(root, "--check")
    lines = finding_lines(out_of(cp), "TASK_ID_UNPARSED")
    assert any("2026-10-02_cyr" in ln and "info" in ln for ln in lines), out_of(cp)[:500]
    assert cp.returncode == 0


def test_cyrillic_task_id_in_list_item_is_reported(make_root, progress):
    root = make_root({"plans/2026-10-02_cyr/plan.md": plan_text("- Task 1.1: a [DONE]\n- Task Т.2: б [DONE]\n")})
    assert finding_lines(out_of(progress(root, "--check")), "TASK_ID_UNPARSED")


def test_valid_ids_give_no_unparsed_finding(make_root, progress):
    root = make_root({"plans/2026-10-02_ok/plan.md": plan_text("- Task 1.1: a [DONE]\n- Task T1: b [DONE]\n")})
    assert not finding_lines(out_of(progress(root, "--check")), "TASK_ID_UNPARSED")


# =========================================================================== 6. служебные *.result-*.md


def test_result_files_are_not_plans(make_root, plans_json):
    root = make_root(
        {
            "plans/2026-10-02_real.md": plan_text("- Task 1.1: a [DONE]\n"),
            "plans/2026-10-02_real.result-1.1.md": plan_text("- Task 1.1: a [DONE]\n"),
            "plans/2026-10-02_real.result-2.md": plan_text("- Task 1.1: a [DONE]\n"),
            "plans/_archive/2026-Q4/2026-10-01_old.result-1.0.md": plan_text("- Task 1.1: a [DONE]\n"),
        }
    )
    assert set(plans_json(root)) == {"2026-10-02_real"}


# =========================================================================== 7. не UTF-8


def test_cp1251_file_gives_not_utf8_finding(make_root, progress):
    root = make_root({"plans/2026-10-02_ok/plan.md": plan_text("- Task 1.1: a [DONE]\n")})
    bad = root / "plans" / "2026-10-02_cp" / "plan.md"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(("# План\n\n" + SECTION + "- Task 1.1: задача [DONE]\n").encode("cp1251"))
    cp = progress(root, "--check")
    lines = finding_lines(out_of(cp), "NOT_UTF8")
    assert any("2026-10-02_cp" in ln and "info" in ln for ln in lines), out_of(cp)[:500]
    assert not any("2026-10-02_ok" in ln for ln in lines)
    assert cp.returncode == 0


# =========================================================================== 8. база не найдена


def test_missing_baseline_file_exits_2_with_message(make_root, progress, tmp_path):
    root = make_root({"plans/2026-10-02_ok/plan.md": plan_text("- Task 1.1: a [PENDING]\n")})
    cp = progress(root, "--check", "--baseline", str(tmp_path / "нет_базы.txt"))
    assert cp.returncode == 2, out_of(cp)[:400]
    assert "база не найдена" in out_of(cp) and "нет_базы.txt" in out_of(cp)


def test_broken_baseline_stays_exit_1_when_a_blocking_finding_exists(make_root, progress, order_md, tmp_path):
    root = make_root(
        {
            "plans/2026-10-02_empty/plan.md": "# Пустой\n",
            "plans/queue/ORDER.md": order_md(tier41=["2026-10-02_empty"]),
        }
    )
    base = tmp_path / "broken.txt"
    base.write_bytes(b"\xff\xfe\x00\x01 not a key\n")
    assert progress(root, "--check", "--baseline", str(base)).returncode == 1


# =========================================================================== 9. мёртвый код


def test_dead_names_are_gone():
    path = Path(__file__).resolve().parents[1] / "plans_progress.py"
    spec = importlib.util.spec_from_file_location("pp_dead_check", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["pp_dead_check"] = mod
    spec.loader.exec_module(mod)
    assert not hasattr(mod, "STATUS_ORDER")
    assert "checkbox" not in mod.Item.__dataclass_fields__
