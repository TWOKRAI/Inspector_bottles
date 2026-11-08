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


def _make_service(root: Path, name: str, *, decisions: bool = False, init: bool = True) -> None:
    svc = root / name
    svc.mkdir()
    if init:
        (svc / "__init__.py").write_text("")
    if decisions:
        (svc / "DECISIONS.md").write_text("# ADR\n")


def test_new_service_without_decisions_is_red_old_seven_are_baseline(tmp_path):
    check = _require_check()
    for name in BASELINE_SEVEN:
        _make_service(tmp_path, name)
    _make_service(tmp_path, "newsvc")

    check(tmp_path)

    assert validate.errors == ["  [FAIL] Нет DECISIONS.md: Services/newsvc"]


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

    out = capsys.readouterr().out
    assert validate.errors == []
    assert out.splitlines()[-1] == "  [OK] baseline можно сократить: documents"
    assert "[MISS]" not in out
    assert "[FAIL]" not in out


def test_baseline_service_without_decisions_prints_miss_not_error(tmp_path, capsys):
    check = _require_check()
    _make_service(tmp_path, "documents")

    check(tmp_path)

    out = capsys.readouterr().out
    assert validate.errors == []
    assert out.splitlines()[-1] == "  [MISS] baseline: нет DECISIONS.md: Services/documents"
    assert "[FAIL]" not in out


def test_dir_without_init_is_not_a_service(tmp_path, capsys):
    check = _require_check()
    _make_service(tmp_path, "plain_dir", init=False)
    _make_service(tmp_path, "documents", init=False)  # имя из базы, но не пакет

    check(tmp_path)

    out = capsys.readouterr().out
    assert validate.errors == []
    assert "[FAIL]" not in out
    assert "[MISS]" not in out
    assert "plain_dir" not in out
    assert "documents" not in out


def test_baseline_only_shrinks():
    _require_check()
    # Инвариант: новые имена в базу не добавляют, она только сокращается.
    assert validate.SERVICES_WITHOUT_DECISIONS <= set(BASELINE_SEVEN)


def test_services_root_is_read_at_call_time(tmp_path, monkeypatch, capsys):
    check = _require_check()
    _make_service(tmp_path, "newsvc")
    monkeypatch.setattr(validate, "SERVICES_ROOT", tmp_path)

    check()
    out_default = capsys.readouterr().out
    errors_default = list(validate.errors)
    validate.errors.clear()
    check(tmp_path)
    out_explicit = capsys.readouterr().out

    assert errors_default == ["  [FAIL] Нет DECISIONS.md: Services/newsvc"]
    assert out_default == out_explicit
    assert validate.errors == errors_default


def test_main_runs_decisions_check_and_returns_red(tmp_path, monkeypatch, capsys):
    _require_check()
    _make_service(tmp_path, "newsvc")
    monkeypatch.setattr(validate, "SERVICES_ROOT", tmp_path)
    # Все прочие проверки — заглушки: иначе они читают реальное дерево, а не tmp.
    stubbed = [
        name
        for name in dir(validate)
        if name.startswith("check_") and name not in ("check_header", "check_services_decisions")
    ]
    assert "check_services" in stubbed  # заглушки действительно охватывают проверки main()
    for name in stubbed:
        monkeypatch.setattr(validate, name, lambda *a, **k: None)

    rc = validate.main()

    assert rc == 1
    assert "  [FAIL] Нет DECISIONS.md: Services/newsvc" in capsys.readouterr().out


def test_real_services_tree_has_no_new_offenders():
    check = _require_check()

    check()

    assert validate.errors == []
