"""Task 3.0 (commit-mechanism) — слепая приёмка единой грамматики id: контракт, plans_progress, plans_ledger, паритет.

Источник ожидаемых значений — только `plans/2026-10-03_commit-mechanism/tasks/3.0.md`: DESIGN п. 1 (строка-эталон),
п. 4, 6, 7, Module contract, REDS 2-10, ACCEPTANCE (сторожа). Значения — литералы из ТЗ, не вычисляются из кода.
Код читался лишь ради формы вызова: `analyze_plan(name, main, plan_dir, rel, archived)` + `build_findings([plan])`
у plans_progress, `extract_task_ids(text)` у plans_ledger, `validate(text, allowed_layers, plan_path)` у валидатора.

Все пять носителей грузятся через importlib по пути (копии отформатированы разными форматтерами, исходник регуляркой
не читается): две копии `validate_commit.py`, `plans_progress.py`, две копии `plans_ledger.py`.

Состав (REDS из ТЗ — красные до реализации; сторожа — зелёные и до, и после):
  * REDS 2: пять строк равны литералу п. 1;
  * REDS 3-7: plans_progress (id `1.2.3`, `ABC1`, не-id `1.3ab`, зависимость `1.2.3`, не-id `T2.K` / `5.10.g`);
  * REDS 8, 10: `plans_ledger.extract_task_ids` в обеих копиях;
  * REDS 9: паритет по одной таблице id (REDS + сторожа ТЗ) между пятью носителями + `TASK_ID_UNPARSED` для отвергнутых;
  * сторожа plans_progress из ACCEPTANCE и ловушка ТЗ «`Task 1.4.` в конце фразы остаётся id `1.4`»
    (ТЗ называет её в TRAPS и в п. 3 про ledger; в списке сторожей ACCEPTANCE её нет — это дополнение тестера).
Таблица паритета дополнена четырьмя граничными id (`123`, `1.1234`, `ABC123`, `1.2.3.4`) прямо из строки-эталона п. 1
(до трёх цифр в первом числе, любое число цифр в сегментах, префикс до трёх букв, много сегментов) — их нет ни в REDS,
ни в сторожах ТЗ; это дополнение тестера.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

VALIDATORS = {
    "scripts": REPO_ROOT / "scripts" / "validate_commit" / "validate_commit.py",
    "template": REPO_ROOT
    / ".claude"
    / "plugins"
    / "lang-python"
    / "templates"
    / "validate_commit"
    / "validate_commit.py",
}
PROGRESS_PATH = REPO_ROOT / "scripts" / "plans_progress" / "plans_progress.py"
LEDGERS = {
    "scripts": REPO_ROOT / "scripts" / "plans_ledger.py",
    "plugin": REPO_ROOT / ".claude" / "plugins" / "core" / "scripts" / "plans_ledger.py",
}

TIMEOUT = 60
LAYERS = {"framework", "services", "plugins", "prototype", "docs", "scripts", "tests", "infra", "mixed"}
_TASK_FORMAT = "Task is not <slug>#<id>"
UNPARSED = "TASK_ID_UNPARSED"

# DESIGN п. 1: строка-эталон (литерал из ТЗ).
GRAMMAR = r"[A-Z]{0,3}[0-9]{1,3}[a-z]?(?:\.[0-9]+[a-z]?)*(?:-[a-z0-9]+)*"

# Таблица id: REDS 1 + сторожа ACCEPTANCE (часть после `x#`) + REDS 3-4, 7-8, 10 + четыре граничных (см. docstring).
ACCEPT_IDS = [
    # REDS 1
    "1b.2d",
    "1b.2d-2",
    "1b.2b-pre",
    "1.3h-c-fix",
    "F8-4",
    "T2-j2",
    "T2-k",
    "2v.2",
    # сторожа: принимаются
    "0.4",
    "2.1",
    "1.3a",
    "T4.0",
    "AU1",
    "5.10f",
    "1.2.3",
    # REDS 3, 4, 8: `1.2.3`, `ABC1`
    "ABC1",
    # граничные из строки-эталона п. 1 (дополнение тестера)
    "123",
    "1.1234",
    "ABC123",
    "1.2.3.4",
]
REJECT_IDS = [
    "2в.2",  # кириллическая `в`
    "Т.1",  # кириллическая `Т`
    "T2.K",
    "5.10.f",
    "D.3",
    "ABCD1",
    "1.1–1.3",  # en dash
    "1.1-1.3",
    "1.1/1.2",
    "1.3ab",
    "2026-09-25",
    "1234",
    "5.10.g",  # REDS 7, 10
]


def _pid(value: str) -> str:
    return value.encode("unicode_escape").decode("ascii")


# --------------------------------------------------------------------------------------------- загрузка по пути


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def pp():
    return _load("plans_progress_t30_acceptance", PROGRESS_PATH)


@pytest.fixture(scope="module", params=sorted(LEDGERS), ids=sorted(LEDGERS))
def ledger(request):
    return _load(f"plans_ledger_t30_{request.param}", LEDGERS[request.param])


@pytest.fixture(scope="module", params=sorted(VALIDATORS), ids=sorted(VALIDATORS))
def validator(request):
    return _load(f"validate_commit_t30_parity_{request.param}", VALIDATORS[request.param])


@pytest.fixture(scope="module")
def all_ledgers():
    return {k: _load(f"plans_ledger_t30_all_{k}", p) for k, p in LEDGERS.items()}


@pytest.fixture(scope="module")
def all_validators():
    return {k: _load(f"validate_commit_t30_all_{k}", p) for k, p in VALIDATORS.items()}


@pytest.fixture(scope="module")
def clean_repo() -> Path:
    """Пустой git-репозиторий в системном temp: у валидатора нет плана и конфига слоёв."""
    root = Path(tempfile.mkdtemp(prefix="t30_parity_"))
    subprocess.run(["git", "init", "-q", "-b", "scratch"], cwd=root, check=True, timeout=TIMEOUT, capture_output=True)
    return root


# ----------------------------------------------------------------------------------------- вызовы носителей


ORDER_HEAD = "# План\n\n## Порядок выполнения\n\n"


def _analyze(pp_mod, tmp_path: Path, text: str):
    main = tmp_path / "plan.md"
    main.write_text(text, encoding="utf-8")
    return pp_mod.analyze_plan("t30", main, None, "plans/t30.md", False)


def _item_plan(item_line: str) -> str:
    return ORDER_HEAD + item_line + "\n"


def _task_ids(plan) -> list[str]:
    return [t.id for t in plan.tasks]


def _finding_codes(pp_mod, plan) -> list[str]:
    return [f.code for f in pp_mod.build_findings([plan])]


def _validator_accepts(validator_mod, value: str) -> bool:
    message = (
        "test(plans): проверка грамматики id\n\n"
        "Why: проверка грамматики id в трейлере Task\n"
        "Layer: tests\n"
        f"Task: {value}\n"
    )
    result = validator_mod.validate(message, allowed_layers=set(LAYERS), plan_path=None)
    return not any(_TASK_FORMAT in w for w in result.warnings)


def _ledger_ids(ledger_mod, task_id: str) -> list[str]:
    return ledger_mod.extract_task_ids(f"### Task {task_id} — t")


# ---------------------------------------------------------------------------------------- REDS 2: контракт


def test_contract_validator_task_id_pattern_equals_literal(validator):
    assert validator.TASK_ID_PATTERN == GRAMMAR


def test_contract_plans_progress_id_pattern_equals_literal(pp):
    assert pp.ID_PATTERN == GRAMMAR


def test_contract_plans_ledger_task_id_equals_literal(ledger):
    assert ledger._TASK_ID == GRAMMAR


# --------------------------------------------------------------------- REDS 3-7: plans_progress, id и находки


def test_reds3_progress_reads_three_segment_id_as_task(pp, tmp_path):
    plan = _analyze(pp, tmp_path, _item_plan("- Task 1.2.3: t [PENDING]"))
    assert _task_ids(plan) == ["1.2.3"]


def test_reds3_progress_three_segment_id_gives_no_unparsed_finding(pp, tmp_path):
    plan = _analyze(pp, tmp_path, _item_plan("- Task 1.2.3: t [PENDING]"))
    assert UNPARSED not in _finding_codes(pp, plan)


def test_reds4_progress_reads_three_letter_prefix_id_as_task(pp, tmp_path):
    plan = _analyze(pp, tmp_path, _item_plan("- Task ABC1: t [PENDING]"))
    assert _task_ids(plan) == ["ABC1"]


def test_reds5_progress_two_letter_segment_is_unparsed_finding(pp, tmp_path):
    plan = _analyze(pp, tmp_path, _item_plan("- Task 1.3ab: t [PENDING]"))
    assert UNPARSED in _finding_codes(pp, plan)


def test_reds5_progress_two_letter_segment_gives_no_task(pp, tmp_path):
    plan = _analyze(pp, tmp_path, _item_plan("- Task 1.3ab: t [PENDING]"))
    assert _task_ids(plan) == []


def test_reds6_progress_reads_three_segment_id_in_after_clause(pp, tmp_path):
    plan = _analyze(pp, tmp_path, _item_plan("- Task 9.9: x [PENDING] (после 1.2.3)"))
    assert [t.after for t in plan.tasks] == [["1.2.3"]]


def test_reds7_progress_item_with_letter_segment_is_unparsed_finding(pp, tmp_path):
    plan = _analyze(pp, tmp_path, _item_plan("- Task T2.K: t [PENDING]"))
    assert UNPARSED in _finding_codes(pp, plan)


def test_reds7_progress_item_with_letter_segment_is_not_read_as_prefix_task(pp, tmp_path):
    plan = _analyze(pp, tmp_path, _item_plan("- Task T2.K: t [PENDING]"))
    assert "T2" not in _task_ids(plan)


def test_reds7_progress_heading_with_letter_segment_is_unparsed_finding(pp, tmp_path):
    plan = _analyze(pp, tmp_path, "# План\n\n#### Task 5.10.g\n\n**Статус:** PENDING\n")
    assert UNPARSED in _finding_codes(pp, plan)


def test_reds7_progress_heading_with_letter_segment_is_not_read_as_prefix_task(pp, tmp_path):
    plan = _analyze(pp, tmp_path, "# План\n\n#### Task 5.10.g\n\n**Статус:** PENDING\n")
    assert "5.10" not in _task_ids(plan)


# ------------------------------------------------------------------- сторожа plans_progress (ACCEPTANCE + ловушка)


@pytest.mark.parametrize("task_id", ["1b.2d-2", "5.10f"])
def test_guard_progress_reads_id_as_task(pp, tmp_path, task_id):
    plan = _analyze(pp, tmp_path, _item_plan(f"- Task {task_id}: t [PENDING]"))
    assert _task_ids(plan) == [task_id]


@pytest.mark.parametrize("line", ["- Task Т.1: t [PENDING]", "- Task 1234: t [PENDING]"], ids=["cyrillic-T.1", "1234"])
def test_guard_progress_not_an_id_is_unparsed_finding(pp, tmp_path, line):
    plan = _analyze(pp, tmp_path, _item_plan(line))
    assert UNPARSED in _finding_codes(pp, plan)


def test_trap_progress_item_sentence_end_dot_stays_id_1_4(pp, tmp_path):
    plan = _analyze(pp, tmp_path, _item_plan("- Task 1.4. x [PENDING]"))
    assert _task_ids(plan) == ["1.4"]


def test_trap_progress_heading_sentence_end_dot_stays_id_1_4(pp, tmp_path):
    plan = _analyze(pp, tmp_path, "# План\n\n### Task 1.4. x\n\n**Статус:** PENDING\n")
    assert _task_ids(plan) == ["1.4"]


# ----------------------------------------------------------------------- REDS 8, 10: plans_ledger.extract_task_ids


def test_reds8_ledger_reads_three_segment_id(ledger):
    assert ledger.extract_task_ids("### Task 1.2.3 — x") == ["1.2.3"]


def test_reds8_ledger_reads_three_letter_prefix_id(ledger):
    assert ledger.extract_task_ids("### Task ABC1 — x") == ["ABC1"]


def test_reds10_ledger_letter_segment_after_prefix_id_is_not_an_id(ledger):
    assert ledger.extract_task_ids("### Task T2.K — t") == []


def test_reds10_ledger_letter_segment_after_two_numbers_is_not_an_id(ledger):
    assert ledger.extract_task_ids("### Task 5.10.g — t") == []


def test_trap_ledger_heading_sentence_end_dot_stays_id_1_4(ledger):
    assert ledger.extract_task_ids("### Task 1.4. x") == ["1.4"]


# ---------------------------------------------------------------------------------------- REDS 9: паритет


def _verdicts(pp_mod, validators: dict, ledgers: dict, repo: Path, tmp_path: Path, task_id: str) -> dict:
    plan = _analyze(pp_mod, tmp_path, _item_plan(f"- Task {task_id}: t [PENDING]"))
    out: dict = {f"validator[{k}]": _validator_accepts(m, f"x#{task_id}") for k, m in sorted(validators.items())}
    out["plans_progress"] = _task_ids(plan)
    out.update({f"ledger[{k}]": _ledger_ids(m, task_id) for k, m in sorted(ledgers.items())})
    return out


def _expected(validators: dict, ledgers: dict, task_id: str, accepted: bool) -> dict:
    out: dict = {f"validator[{k}]": accepted for k in sorted(validators)}
    out["plans_progress"] = [task_id] if accepted else []
    out.update({f"ledger[{k}]": [task_id] if accepted else [] for k in sorted(ledgers)})
    return out


@pytest.mark.parametrize("task_id", ACCEPT_IDS, ids=_pid)
def test_parity_accepted_id_is_an_id_in_all_five_carriers(
    pp, all_validators, all_ledgers, clean_repo, tmp_path, task_id, monkeypatch
):
    monkeypatch.chdir(clean_repo)
    got = _verdicts(pp, all_validators, all_ledgers, clean_repo, tmp_path, task_id)
    assert got == _expected(all_validators, all_ledgers, task_id, True)


@pytest.mark.parametrize("task_id", REJECT_IDS, ids=_pid)
def test_parity_rejected_id_is_not_an_id_in_any_carrier(
    pp, all_validators, all_ledgers, clean_repo, tmp_path, task_id, monkeypatch
):
    monkeypatch.chdir(clean_repo)
    got = _verdicts(pp, all_validators, all_ledgers, clean_repo, tmp_path, task_id)
    assert got == _expected(all_validators, all_ledgers, task_id, False)


@pytest.mark.parametrize("task_id", REJECT_IDS, ids=_pid)
def test_parity_rejected_id_gives_unparsed_finding_in_progress(pp, tmp_path, task_id):
    plan = _analyze(pp, tmp_path, _item_plan(f"- Task {task_id}: t [PENDING]"))
    assert UNPARSED in _finding_codes(pp, plan)


@pytest.mark.parametrize("task_id", ACCEPT_IDS, ids=_pid)
def test_parity_accepted_id_gives_no_unparsed_finding_in_progress(pp, tmp_path, task_id):
    plan = _analyze(pp, tmp_path, _item_plan(f"- Task {task_id}: t [PENDING]"))
    assert UNPARSED not in _finding_codes(pp, plan)
