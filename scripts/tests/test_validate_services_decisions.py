"""Task 7.1b-validate: `validate.py` красит сервис без DECISIONS.md.

`check_services` обходит литерал `SERVICES` (4 имени) и нового сервиса не видит;
`check_services_decisions` сканирует диск. Семь старых сервисов без файла — база
(печатаются как [MISS], не ошибка); новый сервис без файла — [FAIL] в `errors`.

Ожидаемые значения — литералы, не выводятся из проверяемого кода.
"""

from pathlib import Path

import pytest

from scripts import validate

BASELINE_SEVEN = [
    "control_panel",
    "dataset_gen",
    "documents",
    "hikvision_camera",
    "ml_inference",
    "ml_train",
    "phone_gateway",
]


@pytest.fixture(autouse=True)
def _clean_globals():
    """`validate.errors` / `validate.warnings` — модульные списки: чистим до и после."""
    validate.errors.clear()
    validate.warnings.clear()
    yield
    validate.errors.clear()
    validate.warnings.clear()


def _require_check():
    if not hasattr(validate, "check_services_decisions"):
        pytest.fail(
            "scripts/validate.py не содержит check_services_decisions: "
            "проверка «сервис без DECISIONS.md» ещё не написана (RED)"
        )
    return validate.check_services_decisions


def _make_service(root: Path, name: str, *, decisions: bool = False) -> None:
    svc = root / name
    svc.mkdir()
    (svc / "__init__.py").write_text("")
    if decisions:
        (svc / "DECISIONS.md").write_text("# ADR\n")


def test_new_service_without_decisions_is_red_old_seven_are_baseline(tmp_path):
    check = _require_check()
    for name in BASELINE_SEVEN:
        _make_service(tmp_path, name)
    _make_service(tmp_path, "newsvc")

    check(tmp_path)

    assert len(validate.errors) == 1
    assert "newsvc" in validate.errors[0]


def test_tests_and_underscore_dirs_are_not_services(tmp_path):
    check = _require_check()
    _make_service(tmp_path, "tests")
    _make_service(tmp_path, "_x")

    check(tmp_path)

    assert validate.errors == []


def test_baseline_service_with_decisions_is_ok_and_reported(tmp_path, capsys):
    check = _require_check()
    _make_service(tmp_path, "documents", decisions=True)

    check(tmp_path)

    assert validate.errors == []
    assert "baseline можно сократить" in capsys.readouterr().out


def test_real_services_tree_has_no_new_offenders():
    check = _require_check()

    check()

    assert validate.errors == []
