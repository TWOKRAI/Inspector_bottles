# ruff: noqa: E501  -- литералы-фикстуры планов в одну строку
"""Характеризация гейтов plans_ledger.py: contract_fingerprint, contract_files_fingerprint,
check_plan_gate, approve/amend, check_plan_contract.

Набор написан на СТАРОМ коде (до Task 1.0) и обязан остаться зелёным после правки,
кроме названных сдвигов. Каждый сдвиг помечен в тесте словом «СДВИГ 1.0» и описан в
итоге задачи (plans/2026-10-02_plans-progress-dashboard/tasks/1.0.result.md).

Модуль грузится из файла (scripts/plans_ledger.py — зеркало источника), в процессе:
гейты — функции без CLI, а subprocess тут ничего не добавляет.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
LEDGER_PATH = REPO_ROOT / "scripts" / "plans_ledger.py"
SOURCE_PATH = REPO_ROOT / ".claude" / "plugins" / "core" / "scripts" / "plans_ledger.py"


def _load_ledger():
    spec = importlib.util.spec_from_file_location("plans_ledger_under_test", LEDGER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[spec.name] = module  # dataclass(frozen) ищет модуль по имени
    spec.loader.exec_module(module)
    return module


L = _load_ledger()

# Task 4.1: каждый тест — в обоих режимах summarize_plan (корень без парсера / с копией парсера).
pytestmark = pytest.mark.parametrize("parser_mode", [False, True], ids=["legacy", "adapter"], indirect=True)


@pytest.fixture(autouse=True)
def _parser_in_tmp_roots(parser_mode, tmp_path, install_parser, capsys, ledger_fallback_markers):
    """«Адаптер»: копия парсера в оба корня, которые строят тесты ниже (`tmp_path` и `tmp_path/repo`).

    После теста: строка отката ledger в stderr (копия не загрузилась, analyze_plan упал) — провал.
    """
    if parser_mode:
        install_parser(tmp_path)
        install_parser(tmp_path / "repo")
    yield
    if parser_mode:
        err = capsys.readouterr().err
        bad = [m for m in ledger_fallback_markers if m in err]
        assert not bad, f"режим «адаптер», но ledger откатился в «прежний»: {err[-600:]!r}"


TODAY = "2026-10-02"
AMENDMENTS = (
    "| # | дата | почему | Δ задач | Δ бюджета |\n|---|---|---|---|---|\n| — | 2026-10-01 | открытие | — | — |\n"
)
FULL_FIELDS = "- **Files:** `a/b.py`\n- **Acceptance:** ok\n- **Handoff:** итог\n"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))


def _codes(findings) -> list[tuple[str, str]]:
    return sorted((f.code, f.detail) for f in findings)


# --------------------------------------------------------------------------- зеркало


def test_mirror_is_byte_identical_to_plugin_source():
    # без этого `plugin upgrade --apply` молча затрёт правку зеркала источником
    assert LEDGER_PATH.read_bytes() == SOURCE_PATH.read_bytes()


# --------------------------------------------------------------------------- contract_fingerprint


def test_fingerprint_literal_normalisation():
    # маркер на строке-задаче раздела срезан вместе с хвостом, пробелы и хвостовые пустые строки сняты
    text = "# P\n\n## Порядок выполнения\n\n- Task 1.1: a [DONE] (merge abc)   \n\n\n"
    assert L.contract_fingerprint(text) == _sha("# P\n\n## Порядок выполнения\n\n- Task 1.1: a")


def test_fingerprint_ignores_plan_status_value_but_not_trailing_fields():
    a = "# P\n\n- **Статус:** DRAFT · **Level:** Middle\n"
    b = "# P\n\n- **Статус:** ACTIVE · **Level:** Middle\n"
    c = "# P\n\n- **Статус:** ACTIVE · **Level:** Senior\n"
    assert L.contract_fingerprint(a) == L.contract_fingerprint(b)
    assert L.contract_fingerprint(b) != L.contract_fingerprint(c)


def test_fingerprint_ignores_bare_marker_flip_on_order_task_line():
    a = "# P\n\n## Порядок выполнения\n\n- Task 1.1: a [PENDING]\n"
    b = "# P\n\n## Порядок выполнения\n\n- Task 1.1: a [DONE] (merge 1234567)\n"
    assert L.contract_fingerprint(a) == L.contract_fingerprint(b)


def test_fingerprint_moves_on_task_title_change():
    a = "# P\n\n## Порядок выполнения\n\n- Task 1.1: a [PENDING]\n"
    b = "# P\n\n## Порядок выполнения\n\n- Task 1.1: b [PENDING]\n"
    assert L.contract_fingerprint(a) != L.contract_fingerprint(b)


def test_fingerprint_moves_on_added_task_line():
    a = "# P\n\n## Порядок выполнения\n\n- Task 1.1: a [PENDING]\n"
    b = a + "- Task 1.2: b [PENDING]\n"
    assert L.contract_fingerprint(a) != L.contract_fingerprint(b)


def test_fingerprint_keeps_marker_outside_the_order_section():
    a = "# P\n\n## Заметки\n\n- Task 1.1: a [PENDING]\n"
    b = "# P\n\n## Заметки\n\n- Task 1.1: a [DONE]\n"
    assert L.contract_fingerprint(a) != L.contract_fingerprint(b)


def test_fingerprint_keeps_marker_on_non_task_line_in_section():
    a = "# P\n\n## Порядок выполнения\n\n- правило: [PENDING]\n"
    b = "# P\n\n## Порядок выполнения\n\n- правило: [DONE]\n"
    assert L.contract_fingerprint(a) != L.contract_fingerprint(b)


def test_fingerprint_section_ends_at_same_level_heading():
    a = "# P\n\n## Порядок выполнения\n\n### Phase 1\n\n- Task 1.1: a [PENDING]\n\n## Риски\n\n- Task 9.9: z [PENDING]\n"
    b = "# P\n\n## Порядок выполнения\n\n### Phase 1\n\n- Task 1.1: a [DONE]\n\n## Риски\n\n- Task 9.9: z [PENDING]\n"
    c = a.replace("- Task 9.9: z [PENDING]", "- Task 9.9: z [DONE]")
    assert L.contract_fingerprint(a) == L.contract_fingerprint(b)
    assert L.contract_fingerprint(a) != L.contract_fingerprint(c)


def test_fingerprint_fenced_lines_are_verbatim():
    a = "# P\n\n## Порядок выполнения\n\n```\n- Task 1.1: a [PENDING]\n```\n"
    b = "# P\n\n## Порядок выполнения\n\n```\n- Task 1.1: a [DONE]\n```\n"
    assert L.contract_fingerprint(a) != L.contract_fingerprint(b)


# --------------------------------------------------------------------------- contract_files_fingerprint


def _phased_dir(tmp_path: Path) -> Path:
    d = tmp_path / "plans" / "2026-10-02_phased"
    _write(
        d,
        {
            "plan.md": "# P\n\n### Task 1.1 — a\n- [ ] a\n",
            "phase-2.md": "# Ф2\n\n### Task 2.1 — b\n- [ ] a\n",
            "phase-3-core.md": "# Ф3\n\n### Task 3.1 — c\n- [ ] a\n",
            "tasks/1.1.md": "# Task 1.1 — a\n- [ ] a\n",
            "tasks/1.1.result.md": "итог\n",
            "amendments.md": AMENDMENTS,
            "decisions.md": "решения\n",
        },
    )
    return d


def test_files_fingerprint_file_set(tmp_path):
    d = _phased_dir(tmp_path)
    _overall, files = L.contract_files_fingerprint(d)
    # СДВИГ 1.0: `phase-3-core.md` (фаза с суффиксом имени) входит в контракт после правки
    # `_PHASE_FILE_RE`; до правки набор был {plan.md, phase-2.md, tasks/1.1.md}.
    assert sorted(files) == ["phase-2.md", "phase-3-core.md", "plan.md", "tasks/1.1.md"]


def test_files_fingerprint_overall_is_hash_of_sorted_rel_sha_lines(tmp_path):
    d = _phased_dir(tmp_path)
    overall, files = L.contract_files_fingerprint(d)
    expected = _sha("\n".join(f"{rel}\t{files[rel]}" for rel in sorted(files)))
    assert overall == expected
    assert files["plan.md"] == L.contract_fingerprint((d / "plan.md").read_text(encoding="utf-8"))


def test_files_fingerprint_moves_on_added_task_file(tmp_path):
    d = _phased_dir(tmp_path)
    before, _ = L.contract_files_fingerprint(d)
    _write(d, {"tasks/1.2.md": "# Task 1.2 — b\n- [ ] a\n"})
    after, files = L.contract_files_fingerprint(d)
    assert before != after and "tasks/1.2.md" in files


def test_files_fingerprint_ignores_amendments_and_results(tmp_path):
    d = _phased_dir(tmp_path)
    before, _ = L.contract_files_fingerprint(d)
    _write(
        d,
        {
            "amendments.md": AMENDMENTS + "| 1 | 2026-10-02 | ADDED x | +1 | — |\n",
            "tasks/1.1.result.md": "другой итог\n",
        },
    )
    after, _ = L.contract_files_fingerprint(d)
    assert before == after


# --------------------------------------------------------------------------- check_plan_gate


def _gate(tmp_path: Path, name: str, text: str):
    p = tmp_path / "plans" / name
    _write(tmp_path / "plans", {name: text})
    return L.check_plan_gate(p)


def test_gate_no_budget(tmp_path):
    f = _gate(tmp_path, "2026-10-02_nb.md", "# P\n\nпроза\n")
    assert _codes(f) == [("NO_BUDGET", "no Budget/Бюджет section (## Budget or ## Бюджет)")]
    assert f[0].plan == "2026-10-02_nb.md"


def test_gate_open_task_missing_all_fields(tmp_path):
    f = _gate(tmp_path, "2026-10-02_inc.md", "# P\n\n## Бюджет\n\n1k\n\n### Task 1.1 — a\n- [ ] шаг\n")
    assert _codes(f) == [("TASK_INCOMPLETE", "Task 1.1: missing field(s): Files, Acceptance, Handoff")]


def test_gate_open_task_with_all_fields_is_clean(tmp_path):
    f = _gate(
        tmp_path, "2026-10-02_ok.md", "# P\n\n## Бюджет\n\n1k\n\n### Task 1.1 — a\n" + FULL_FIELDS + "- [ ] шаг\n"
    )
    assert f == []


def test_gate_russian_aliases_count(tmp_path):
    body = "- **Файлы:** `a.py`\n- **Приёмка:** ok\n- **Chain:** x\n"
    f = _gate(tmp_path, "2026-10-02_ru.md", "# P\n\n## Budget\n\n1k\n\n### Task 1.1 — a\n" + body)
    assert f == []


def test_gate_closed_task_by_checkboxes_is_exempt(tmp_path):
    f = _gate(tmp_path, "2026-10-02_cl.md", "# P\n\n## Бюджет\n\n1k\n\n### Task 1.1 — a\n- [x] шаг\n")
    assert f == []


def test_gate_closed_task_by_bare_done_marker_is_exempt(tmp_path):
    text = "# P\n\n## Бюджет\n\n1k\n\n## Порядок выполнения\n\n- Task 1.1: a [DONE]\n\n## Задачи\n\n### Task 1.1 — a\n- [ ] шаг\n"
    assert _gate(tmp_path, "2026-10-02_dm.md", text) == []


@pytest.mark.parametrize("marker", ["SKIPPED", "CANCELLED"])
def test_gate_skipped_or_cancelled_task_is_exempt(tmp_path, marker):
    text = f"# P\n\n## Бюджет\n\n1k\n\n## Порядок выполнения\n\n- Task 1.1: a [{marker}]\n\n## Задачи\n\n### Task 1.1 — a\n- [ ] шаг\n"
    assert _gate(tmp_path, f"2026-10-02_{marker.lower()}.md", text) == []


def test_gate_too_many_files(tmp_path):
    paths = " ".join(f"`d/f{i}.py`" for i in range(9))
    body = f"- **Files:** {paths}\n- **Acceptance:** ok\n- **Handoff:** итог\n"
    f = _gate(tmp_path, "2026-10-02_many.md", "# P\n\n## Бюджет\n\n1k\n\n### Task 1.1 — a\n" + body)
    assert _codes(f) == [("TASK_TOO_MANY_FILES", "Task 1.1: 9 paths in Files > 8 — split the task")]


def test_gate_dir_plan_labels_owning_file(tmp_path):
    d = tmp_path / "plans" / "2026-10-02_dir"
    _write(d, {"plan.md": "# P\n\n## Бюджет\n\n1k\n", "phase-2.md": "# Ф2\n\n### Task 2.1 — b\n- [ ] a\n"})
    f = L.check_plan_gate(d)
    assert [(x.code, x.plan, x.detail) for x in f] == [
        ("TASK_INCOMPLETE", "2026-10-02_dir/phase-2.md", "Task 2.1: missing field(s): Files, Acceptance, Handoff")
    ]


def test_gate_archive_is_exempt(tmp_path):
    p = tmp_path / "plans" / "_archive" / "2026-Q4" / "2026-10-02_x.md"
    _write(p.parent, {p.name: "# P\n\n### Task 1.1 — a\n- [ ] шаг\n"})
    assert L.check_plan_gate(p) == []


def test_gate_h4_task_heading(tmp_path):
    # СДВИГ 1.0: задача под `####` теперь видна гейту (набор из заголовков `#{2,6}`).
    # До правки `_TASK_HEADER_RE` требовал ровно `###`, и находки не было.
    text = "# P\n\n## Бюджет\n\n1k\n\n### Фаза 1\n\n#### Task 1.1 — a\n- [ ] шаг\n"
    f = _gate(tmp_path, "2026-10-02_h4.md", text)
    assert _codes(f) == [("TASK_INCOMPLETE", "Task 1.1: missing field(s): Files, Acceptance, Handoff")]


def test_gate_suffixed_id_is_its_own_task(tmp_path):
    # СДВИГ 1.0: `### Task 1.3a` — отдельная задача. До правки `(\d+\.\d+)(?!\d)` читал её
    # как `1.3` (дубль соседа), и неполная 1.3a пряталась за полной 1.3.
    text = "# P\n\n## Бюджет\n\n1k\n\n### Task 1.3 — a\n" + FULL_FIELDS + "\n### Task 1.3a — b\n- [ ] шаг\n"
    f = _gate(tmp_path, "2026-10-02_sfx.md", text)
    assert _codes(f) == [("TASK_INCOMPLETE", "Task 1.3a: missing field(s): Files, Acceptance, Handoff")]


# --------------------------------------------------------------------------- approve / amend / check_plan_contract


def _v2_plan(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    d = root / "plans" / "2026-10-02_v2"
    _write(
        d,
        {
            "plan.md": "# P\n\n## Бюджет\n\n1k\n\n## Порядок выполнения\n\n- Task 1.1: a [PENDING]\n- Task 1.2: b [PENDING]\n",
            "tasks/1.1.md": "# Task 1.1 — a\n" + FULL_FIELDS + "- [ ] шаг\n",
            "tasks/1.2.md": "# Task 1.2 — b\n" + FULL_FIELDS + "- [ ] шаг\n",
            "amendments.md": AMENDMENTS,
        },
    )
    return root, d


def _lock(d: Path) -> dict:
    return json.loads((d / "contract.lock").read_text(encoding="utf-8"))


def test_approve_writes_schema2_lock(tmp_path):
    root, d = _v2_plan(tmp_path)
    lock_path = L.approve_plan(root, "2026-10-02_v2", today=TODAY)
    assert lock_path == d / "contract.lock"
    lock = _lock(d)
    overall, files = L.contract_files_fingerprint(d)
    assert lock == {
        "schema": 2,
        "approved": TODAY,
        "approved_tasks": 2,
        "budgeted_tasks": 2,
        "amended_tasks": 2,
        "sha256": overall,
        "files": files,
        "amendments": 0,
        "last_amendment_number": 0,
    }
    assert sorted(files) == ["plan.md", "tasks/1.1.md", "tasks/1.2.md"]


def test_approve_refuses_single_file_plan(tmp_path):
    root = tmp_path / "repo"
    _write(root / "plans", {"2026-10-02_one.md": "# P\n"})
    with pytest.raises(L.ContractRefused, match="single file"):
        L.approve_plan(root, "2026-10-02_one.md", today=TODAY)


def test_approve_refuses_without_amendments(tmp_path):
    root, d = _v2_plan(tmp_path)
    (d / "amendments.md").unlink()
    with pytest.raises(L.ContractRefused, match="no amendments.md"):
        L.approve_plan(root, "2026-10-02_v2", today=TODAY)


def test_approve_twice_refuses_then_force(tmp_path):
    root, d = _v2_plan(tmp_path)
    L.approve_plan(root, "2026-10-02_v2", today=TODAY)
    with pytest.raises(L.ContractRefused, match="already has a contract.lock"):
        L.approve_plan(root, "2026-10-02_v2", today=TODAY)
    L.approve_plan(root, "2026-10-02_v2", today=TODAY, force=True)


def test_contract_clean_after_bare_marker_flip(tmp_path):
    root, d = _v2_plan(tmp_path)
    L.approve_plan(root, "2026-10-02_v2", today=TODAY)
    plan = d / "plan.md"
    plan.write_bytes(plan.read_bytes().replace(b"a [PENDING]", b"a [DONE] (merge 1234567)"))
    assert L.check_plan_contract(d) == []


def test_contract_drift_on_title_edit(tmp_path):
    root, d = _v2_plan(tmp_path)
    L.approve_plan(root, "2026-10-02_v2", today=TODAY)
    plan = d / "plan.md"
    plan.write_bytes(plan.read_bytes().replace(b"Task 1.2: b", b"Task 1.2: b2"))
    f = L.check_plan_contract(d)
    assert [x.code for x in f] == ["CONTRACT_DRIFT"]
    assert f[0].detail.startswith("changed plan.md after approval (2026-10-02)")


def _add_task_1_3(d: Path) -> None:
    plan = d / "plan.md"
    plan.write_bytes(plan.read_bytes() + "- Task 1.3: c [PENDING]\n".encode("utf-8"))
    _write(d, {"tasks/1.3.md": "# Task 1.3 — c\n" + FULL_FIELDS})


def test_contract_scope_grew_past_125_percent(tmp_path):
    root, d = _v2_plan(tmp_path)
    L.approve_plan(root, "2026-10-02_v2", today=TODAY)
    _add_task_1_3(d)
    codes = sorted(x.code for x in L.check_plan_contract(d))
    assert codes == ["CONTRACT_DRIFT", "SCOPE_GREW"]


def test_task_file_without_order_item_does_not_grow_scope(tmp_path):
    # СДВИГ 1.0 (правило набора N1): план с пунктами раздела — набор = пункты. Новый
    # `tasks/1.3.md` без пункта id не добавляет: SCOPE_GREW молчит, CONTRACT_DRIFT ловит файл.
    # До правки набор шёл из заголовков, и тот же файл давал SCOPE_GREW (3 > 1.25 × 2).
    root, d = _v2_plan(tmp_path)
    L.approve_plan(root, "2026-10-02_v2", today=TODAY)
    _write(d, {"tasks/1.3.md": "# Task 1.3 — c\n" + FULL_FIELDS})
    f = L.check_plan_contract(d)
    assert [x.code for x in f] == ["CONTRACT_DRIFT"]
    assert "added tasks/1.3.md" in f[0].detail


def test_amend_refreshes_lock(tmp_path):
    root, d = _v2_plan(tmp_path)
    L.approve_plan(root, "2026-10-02_v2", today=TODAY)
    _add_task_1_3(d)
    _write(d, {"amendments.md": AMENDMENTS + "| 1 | 2026-10-02 | ADDED Task 1.3 | +1 | +10k |\n"})
    L.amend_plan(root, "2026-10-02_v2", today=TODAY)
    lock = _lock(d)
    assert (lock["approved_tasks"], lock["amended_tasks"], lock["budgeted_tasks"]) == (2, 3, 3)
    assert (lock["amendments"], lock["last_amendment_number"]) == (1, 1)
    assert L.check_plan_contract(d) == []


def test_amend_refuses_without_new_row(tmp_path):
    root, d = _v2_plan(tmp_path)
    L.approve_plan(root, "2026-10-02_v2", today=TODAY)
    with pytest.raises(L.ContractRefused, match="no new amendment row"):
        L.amend_plan(root, "2026-10-02_v2", today=TODAY)


def test_amend_refuses_row_without_verb(tmp_path):
    root, d = _v2_plan(tmp_path)
    L.approve_plan(root, "2026-10-02_v2", today=TODAY)
    _write(d, {"amendments.md": AMENDMENTS + "| 1 | 2026-10-02 | просто так | — | — |\n"})
    with pytest.raises(L.ContractRefused, match="row 1: почему must name"):
        L.amend_plan(root, "2026-10-02_v2", today=TODAY)


# --------------------------------------------------------------------------- авторские: опасности механизма Task 1.0
# Каждый тест называет место, где именно этот разбор может сломаться.

SEC = "# P\n\n## Порядок выполнения\n\n"
SEC_BUDGET = "# P\n\n## Бюджет\n\n1k\n\n## Порядок выполнения\n\n"


def _summary(tmp_path: Path, text: str, name: str = "2026-10-02_h.md"):
    _write(tmp_path / "plans", {name: text})
    s = L.summarize_plan(L.discover_plan_files(tmp_path / "plans" / name))
    return s.done, s.counted, s.dropped, s.unknown


def test_status_inside_code_span_is_a_quote(tmp_path):
    assert _summary(tmp_path, SEC + "- Task 1.1: правка `[DONE]` в тексте [PENDING]\n") == (0, 1, 0, 0)


def test_nested_link_inside_status_group(tmp_path):
    # группа до ПАРНОЙ `]`: ссылка внутри не обрывает статус
    text = SEC + "- Task 1.1: a [DONE 2026-10-02 — см. [контракт](x.md); ok]\n"
    assert _summary(tmp_path, text) == (1, 1, 0, 0)


def test_link_before_status_is_skipped(tmp_path):
    # первая группа — ссылка без слова набора; статус — следующая группа
    text = SEC + "- Task 1.1: см. [`gui`](../gui/plan.md) [PENDING] (после [план](y.md))\n"
    assert _summary(tmp_path, text) == (0, 1, 0, 0)


def test_status_word_not_first_in_group(tmp_path):
    assert _summary(tmp_path, SEC + "- Task 5.3: a [5.3a DONE 2026-09-23, ok]\n") == (1, 1, 0, 0)


def test_status_word_glued_to_dash_is_not_status(tmp_path):
    # `[DONE-ish]` — не статус; пункт без слова набора -> `?` (не в знаменателе)
    text = SEC + "- Task 1.1: a [DONE]\n- Task 1.2: b [PENDING]\n- Task 1.3: c [DONE-ish]\n"
    assert _summary(tmp_path, text) == (1, 2, 0, 1)


def test_unclosed_group_runs_to_end_of_item(tmp_path):
    text = SEC + "- Task 6.3: окно [DEFERRED — после GUI-загрузки\n  generic-приложений\n- Task 6.4: b [PENDING]\n"
    assert _summary(tmp_path, text) == (0, 1, 1, 0)


def test_status_on_continuation_line(tmp_path):
    text = SEC + "- Task 1.0: длинное название\n  продолжение **[DONE]** `eecba231`\n- Task 1.1: b [PENDING]\n"
    assert _summary(tmp_path, text) == (1, 2, 0, 0)


def test_blank_line_ends_the_item(tmp_path):
    # статус после пустой строки уже не принадлежит пункту
    text = SEC + "- Task 1.1: a\n\n[DONE]\n"
    assert _summary(tmp_path, text) == (0, 0, 0, 1)


def test_item_outside_section_is_a_reference(tmp_path):
    text = "# P\n\n## Связи\n\n- **Task 0.1** — ЗАМЕНЕНА [DONE]\n\n## Порядок выполнения\n\n- Task 1.1: a [PENDING]\n"
    assert _summary(tmp_path, text) == (0, 1, 0, 0)


def test_section_ends_at_same_level_heading(tmp_path):
    text = SEC + "### Phase 1\n\n- Task 1.1: a [DONE]\n\n## Риски\n\n- Task 9.9: b [PENDING]\n"
    assert _summary(tmp_path, text) == (1, 1, 0, 0)


def test_section_named_poryadok_alone(tmp_path):
    # `## Порядок` — раздел; `## Порядок и окна` — нет
    assert _summary(tmp_path, "# P\n\n## Порядок\n\n- Task 1.1: a [DONE]\n") == (1, 1, 0, 0)
    other = "# P\n\n## Порядок и окна\n\n- Task 1.1: a [DONE]\n"
    assert _summary(tmp_path, other, "2026-10-02_w.md") == (0, 0, 0, 0)


def test_struck_task_and_snyata_are_superseded(tmp_path):
    text = SEC + "- ~~Task 1.1~~: a\n- Task 1.2: b — СНЯТА\n- Task 1.3: c [PENDING]\n"
    assert _summary(tmp_path, text) == (0, 1, 2, 0)


def test_in_progress_and_blocked_are_open(tmp_path):
    text = SEC + "- Task 1.1: a [IN PROGRESS]\n- Task 1.2: b [BLOCKED, частично]\n"
    assert _summary(tmp_path, text) == (0, 2, 0, 0)


def test_id_prefixes_do_not_leak_in_marker_lookup():
    text = SEC + "- Task 1b.2b-pre: a [DONE]\n- Task 1b.2a: b [DONE]\n- Task 1b.2: c\n- Task 1.3a: d [DONE]\n"
    assert L.task_order_marker(text, "1b.2b-pre") == "DONE"
    assert L.task_order_marker(text, "1b.2b") is None
    assert L.task_order_marker(text, "1b.2") is None
    assert L.task_order_marker(text, "1.3") is None
    assert L.task_order_marker(text, "1.3a") == "DONE"


def test_id_end_punctuation_and_atomic_id():
    text = "### Task 1.2: a\n### Task 1.3a — b\n#### Task T1, c\n## Task 2.1~~\n"
    assert L.extract_task_ids(text) == ["1.2", "1.3a", "T1", "2.1"]
    # `1.3a)` не откатывается к префиксу `1`; кириллица в id не читается вовсе
    assert L.extract_task_ids("### Task 1.3a) a\n### Task 2б.1 — b\n") == []
    # H1 — только в файле задачи
    assert L.extract_task_ids("# Task 1.1 — a\n") == []
    assert L.extract_task_ids("# Task 1.1 — a\n", in_task_file=True) == ["1.1"]


def test_old_marker_words_are_returned_as_written():
    # публичный task_order_marker отдаёт слово как в тексте: SKIPPED не переименован
    text = SEC + "- Task 1.1: a [SKIPPED]\n- Task 1.2: b [CANCELLED]\n"
    assert (L.task_order_marker(text, "1.1"), L.task_order_marker(text, "1.2")) == ("SKIPPED", "CANCELLED")


def test_unknown_item_keeps_plan_from_done(tmp_path):
    # `?` не в знаменателе, но план с ним не «готов» (close не архивирует молча)
    _write(tmp_path / "plans", {"2026-10-02_u.md": SEC + "- Task 1.1: a [DONE]\n- Task 1.2: b\n"})
    s = L.summarize_plan(L.discover_plan_files(tmp_path / "plans" / "2026-10-02_u.md"))
    assert (s.done, s.counted, s.unknown, s.open_tasks) == (1, 1, 1, ["1.2"])
    assert L._is_done(s, None) is False


def test_fingerprint_cuts_tailed_marker_and_letter_ids():
    # TRAP 3: хвост `[DONE … ]` и id `1b.2a` вырезаются; флип статуса не даёт CONTRACT_DRIFT
    a = SEC + "- Task 1b.2a: a [PENDING]\n- Task 1.1: b [PENDING] (после 1.0)\n"
    b = (
        SEC
        + "- Task 1b.2a: a [DONE 2026-10-02 — `abc1234`; 5 тестов]\n- Task 1.1: b [DONE 2026-10-02, merge [x](y)] (после 1.0)\n"
    )
    assert L.contract_fingerprint(a) == L.contract_fingerprint(b)


def test_fingerprint_keeps_title_text_before_a_quoted_marker():
    # статус в обратных кавычках — часть названия; правка названия двигает отпечаток
    a = SEC + "- Task 1.1: замена `[DONE]` [PENDING]\n"
    b = SEC + "- Task 1.1: замена `[DONE]` и ещё [PENDING]\n"
    assert L.contract_fingerprint(a) != L.contract_fingerprint(b)


def test_gate_on_item_task_without_heading_reads_nested_fields(tmp_path):
    ok = SEC_BUDGET + "- Task 1.1: a [PENDING]\n  - **Files:** `a.py`\n  - **Acceptance:** ok\n  - **Handoff:** x\n"
    assert _gate(tmp_path, "2026-10-02_g1.md", ok) == []
    bad = SEC_BUDGET + "- Task 1.1: a [PENDING]\n- Task 1.2: b [DONE]\n"
    expected = [("TASK_INCOMPLETE", "Task 1.1: missing field(s): Files, Acceptance, Handoff")]
    assert _codes(_gate(tmp_path, "2026-10-02_g2.md", bad)) == expected


def test_phase_files_sorted_by_number_then_name(tmp_path):
    d = tmp_path / "plans" / "2026-10-02_ph"
    names = ("phase-10.md", "phase-2.md", "phase-1b-x.md", "phase-1.md", "phase-2.result.md")
    _write(d, {"plan.md": "# P\n", **{n: "x" for n in names}})
    got = [p.name for p in L.discover_plan_files(d)]
    assert got == ["plan.md", "phase-1.md", "phase-1b-x.md", "phase-2.md", "phase-10.md"]


def test_task_files_natural_order(tmp_path):
    d = tmp_path / "plans" / "2026-10-02_tf"
    _write(d, {"plan.md": "# P\n", **{f"tasks/{i}.md": "x" for i in ("1.10", "1.2", "1b.2a", "1.2a", "notes")}})
    assert [p.stem for p in L.discover_plan_files(d)[1:]] == ["1.2", "1.2a", "1.10", "1b.2a", "notes"]
