"""Экзамен K0: десять вопросов разведки на пине (Task 1.6c, блок A, RED до кода).

Purpose: ответы Атласа на вопросы брифов K0 1.1/1.2 читаются из вывода `ref` как строки-литералы целиком
    (`line in lines`); засчитано >= 8 из 10, строки 9 и 10 заранее не закрыты (нужна функция атомарной записи
    фреймворка и чтение тела функции) и в тесте только описаны.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Пин 857a0248fc554493d40816f19295ffb68763a373 (ADR-175 принята), `--ref <пин> --main-ref <пин>`. Реестр пина
строится на СВЕЖЕЙ базе в каталоге pytest (module-scoped). Нужен полный клон: предусловие — утверждение, не skip.
Все литералы — из раздела «Эталонные выводы» брифа plans/2026-10-04_atlas/tasks/1.6c.md
(M = multiprocess_framework/modules).

Строка 9 (кто пишет наблюдаемый файл, observability_companion.py): не закрыто, статикой нет — нужна функция
атомарной записи фреймворка (П4, другая задача). Строка 10 (как пишет save_to_file: на месте или подменой):
не закрыто, статикой нет — нужно чтение тела (data_schema_module/serialization/converter.py:292). Ассертов на
отсутствие ответа нет.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest

from scripts.atlas.tests.conftest import GitRepo, run_with_deadline

__all__: list[str] = []

_ROOT = Path(__file__).resolve().parents[3]
_PIN = "857a0248fc554493d40816f19295ffb68763a373"
_PINNED = ("--ref", _PIN, "--main-ref", _PIN)
_M = "multiprocess_framework/modules"
_CHECKED: list[bool] = []
_CACHE: dict[tuple[str, ...], list[str]] = {}


def _git(*args: str) -> tuple[int, str]:
    import subprocess

    proc = run_with_deadline(lambda: subprocess.run(["git", "-C", str(_ROOT), *args], capture_output=True, check=False))
    return proc.returncode, proc.stdout.decode("utf-8", "replace").strip()


def _preconditions() -> None:
    if _CHECKED:
        return
    code, shallow = _git("rev-parse", "--is-shallow-repository")
    assert (code, shallow) == (0, "false"), "клон неполный: выполнить `git fetch --unshallow` перед тестом"
    code, kind = _git("cat-file", "-t", _PIN)
    assert (code, kind) == (0, "commit"), f"коммит {_PIN} не разрешается в этом клоне"
    _CHECKED.append(True)


@pytest.fixture(scope="module")
def pin_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("pin") / "atlas.sqlite"


@pytest.fixture
def pinned(monkeypatch: pytest.MonkeyPatch, pin_db: Path) -> GitRepo:
    _preconditions()
    from scripts.atlas import store

    real = store.connect
    monkeypatch.setattr("scripts.atlas.store.connect", lambda _path: real(pin_db))
    return GitRepo(_ROOT)


def _ref(atlas: Any, pinned: GitRepo, *argv: str) -> list[str]:
    key = tuple(argv)
    if key not in _CACHE:
        res = atlas(pinned, "ref", *argv, *_PINNED)
        assert res.code == 0, res.err
        assert res.err == ""
        _CACHE[key] = res.out.splitlines()
    return _CACHE[key]


def _header_before(lines: list[str], index: int) -> str:
    """Ближайшая строка без отступа выше строки index (заголовок интерфейса)."""
    for at in range(index - 1, -1, -1):
        if lines[at] and not lines[at].startswith(" "):
            return lines[at]
    return ""


# ---------------------------------------------------------------- строки 1-8: каждая — набор литералов


def row1(lines: list[str]) -> bool:
    impl = f"    ConfigManager — явно — {_M}/config_module/core/config_manager.py:29"
    if impl not in lines:
        return False
    at = lines.index(impl)
    return (
        "  вид: ABC; базы: IBaseManager, ABC; абстрактных 16 (своих 7)" in lines
        and "  вид: Protocol, runtime_checkable; базы: Protocol; абстрактных 1 (своих 1)" in lines
        and lines[at - 1] == "  реализации (1):"
        and _header_before(lines, at).startswith("IConfigManager — ")
    )


def row2(lines: list[str]) -> bool:
    impl = f"    Config — структурно — {_M}/config_module/core/config.py:27"
    if impl not in lines:
        return False
    at = lines.index(impl)
    return lines[at - 1] == "  реализации (1):" and _header_before(lines, at).startswith("IConfig — ")


def row3(lines: list[str]) -> bool:
    return "  __call__(key: str, old_value: Any, new_value: Any) -> None  :17" in lines


def row4(lines: list[str]) -> bool:
    return (
        "  унаследованные абстрактные от IBaseManager (9): attach_adapter, detach_adapter, get_adapter,"
        " get_debug_info, get_stats, has_adapter, initialize, list_adapters, shutdown"
    ) in lines


def row5(lines: list[str]) -> bool:
    return (
        f"{_M}/config_module/tools/watcher.py" in lines
        and "  ConfigFileWatcher — Hot-reload: следит за файлом, обновляет Config при изменении — :141" in lines
        and "    start() -> None  :163" in lines
    )


def row6(lines: list[str]) -> bool:
    return f"    {_M}/config_module/tests/test_watcher.py:12  импорт, тестов 8" in lines


def row7(lines: list[str]) -> bool:
    path = f"{_M}/process_module/managers/observability_reload.py"
    return (
        "ConfigFileWatcher — вне модуля 3, тестов 8, файлов 1" in lines
        and f"  {path}:92  импорт" in lines
        and f"  {path}:2305  импорт" in lines
        and f"  {path}:2341  вызов" in lines
    )


def row8(lines: list[str]) -> bool:
    path = f"{_M}/app_module/orchestrator.py"
    return (
        "start_observability_watcher — вне модуля 4, тестов 3, файлов 1" in lines
        and f"  {path}:166  вызов" in lines
        and f"  {path}:223  вызов" in lines
        and f"  {path}:134  импорт" in lines
        and f"  {path}:201  импорт" in lines
    )


_ROWS: dict[int, tuple[Callable[[list[str]], bool], tuple[str, ...]]] = {
    1: (row1, ("config_module",)),
    2: (row2, ("config_module",)),
    3: (row3, ("config_module",)),
    4: (row4, ("config_module",)),
    5: (row5, ("config_module", "--symbol", "ConfigFileWatcher")),
    6: (row6, ("config_module", "--symbol", "ConfigFileWatcher")),
    7: (row7, ("config_module", "--symbol", "ConfigFileWatcher")),
    8: (row8, ("process_module", "--symbol", "start_observability_watcher")),
}


@pytest.mark.parametrize("number", sorted(_ROWS))
def test_exam_row_is_closed(number: int, pinned: GitRepo, atlas: Any) -> None:
    check, argv = _ROWS[number]
    lines = _ref(atlas, pinned, *argv)
    assert check(lines), f"строка экзамена {number} не закрыта"


def test_exam_score_is_at_least_eight_of_ten(pinned: GitRepo, atlas: Any) -> None:
    closed = [number for number, (check, argv) in sorted(_ROWS.items()) if check(_ref(atlas, pinned, *argv))]
    # строки 9 и 10 заранее не закрыты (см. docstring модуля); приёмка: все 1-8
    assert len(closed) >= 8, f"закрыто {closed} из 10"
    assert closed == [1, 2, 3, 4, 5, 6, 7, 8]
