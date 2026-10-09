"""Приёмочные тесты видов `ref` и `index` на пине origin/main (Task 1.6b, RED до кода).

Purpose: числа и строки `ref` и `index` на реальной истории checkout (пин 158fa7a75): справочник router_module и
    app_module, 198 заголовков интерфейсов по 45 модулям, индекс проекта из 133 строк.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Реестр пина строится на СВЕЖЕЙ базе в каталоге pytest (module-scoped): data/atlas.sqlite checkout кэширует сборки
по sha и отпечатку и скрыл бы дефект. Нужен полный клон: предусловие проверяется утверждением, не skip. HEAD
checkout здесь не строится (решение лида О12).
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, run_with_deadline

__all__: list[str] = []

_ROOT = Path(__file__).resolve().parents[3]
_PIN = "158fa7a75ba54ca71aab320898daae0e95ba5f6b"
_PINNED = ("--ref", _PIN, "--main-ref", _PIN)
_CHECKED: list[bool] = []
_HEADER = "# Индекс проекта — собран командой `python -m scripts.atlas index --write`, руками не править"
_ROUTER = "multiprocess_framework/modules/router_module/interfaces.py"
_APP = "multiprocess_framework/modules/app_module/interfaces.py"


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
    """Корень checkout; store.connect открывает общую свежую базу модуля — пин строится один раз."""
    _preconditions()
    from scripts.atlas import store

    real = store.connect
    monkeypatch.setattr("scripts.atlas.store.connect", lambda _path: real(pin_db))
    return GitRepo(_ROOT)


def _ok(res: Any) -> list[str]:
    assert res.code == 0, res.err
    assert res.err == ""
    return res.out.splitlines()


def _sql(db: Path, query: str) -> list[tuple[Any, ...]]:
    con = sqlite3.connect(db)
    try:
        return con.execute(query).fetchall()
    finally:
        con.close()


_SEND = "  send(message: Message | Dict[str, Any]) -> Dict[str, Any]  :42"
# Запись, оканчивающаяся на «тестов », сравнивается по префиксу: честное число тестов (1.6c) заранее не известно
_ROUTER_ORDER = [
    f"IMessageChannel — Контракт для любого типа канала сообщений — {_ROUTER}:173 — тестов ",
    f"IRouterManager — Контракт менеджера маршрутизации сообщений — {_ROUTER}:21 — тестов 0",
    "  manager_name -> str  :26",
    _SEND,
    "    Синхронная отправка",
    "  register_route(key: str, channel_name: str | None, strategy: Any = None, efficiency: int = 0,"
    " tags: List[str] | None = None) -> bool  :111",
]


@pytest.mark.slow
def test_ref_on_origin_main_pin(pinned: GitRepo, atlas: Any, pin_db: Path) -> None:
    lines = _ok(atlas(pinned, "ref", "router_module", *_PINNED))
    assert len(lines) > 63, "к выводу 1.6b добавлены вид, реализации, «Код модуля» и «Кто использует»"
    assert lines[0] == f"Справочник модуля router_module — {_ROUTER}, интерфейсов 2"
    position = 0
    for expected in _ROUTER_ORDER:
        rest = lines[position:]
        found = [
            i
            for i, line in enumerate(rest)
            if (line.startswith(expected) if expected.endswith("тестов ") else line == expected)
        ]
        assert found, f"нет строки (или она раньше предыдущей): {expected!r}"
        position += found[0] + 1
    at = lines.index(_SEND)
    assert lines[at + 1] == "    Синхронная отправка"

    lines = _ok(atlas(pinned, "ref", "app_module", *_PINNED))
    header = next(line for line in lines if line.startswith("ManifestStoreProtocol — "))
    assert f" — {_APP}:119 — тестов " in header  # честное число (1.6c) не больше прежнего счёта по слову (6)
    read_raw = lines.index("  read_raw() -> Dict[str, Any]  :122")
    assert lines[read_raw + 1] == "    нет описания"
    update = lines.index("  update(updates: Mapping[str, Any]) -> Dict[str, Any]  :124")
    assert lines[update + 1] == "    нет описания"
    assert read_raw < update

    modules = sorted(
        row[0]
        for row in _sql(pin_db, "SELECT DISTINCT substr(id, 1, instr(id, ':') - 1) FROM nodes WHERE kind = 'interface'")
    )
    assert len(modules) == 45
    header_re = re.compile(r"^(?!\s)(.+) — (\S+/interfaces\.py):\d+ — тестов (\d+)(?:, пример \S+)?$")
    headers = 0
    zero_tests: set[str] = set()
    for module_id in modules:
        for line in _ok(atlas(pinned, "ref", module_id, *_PINNED)):
            found = header_re.match(line)
            if found is None:
                continue
            headers += 1
            if found.group(3) == "0":
                name = re.match(r"[A-Za-z_]\w*", line)
                assert name is not None, line
                zero_tests.add(f"interface:{module_id}:{name.group(0)}")
    assert headers == 198
    oracle = {
        row[0]
        for row in _sql(
            pin_db,
            "SELECT node FROM findings WHERE code = 'INTERFACE_WITHOUT_TEST'"
            " AND build_id = (SELECT MAX(build_id) FROM builds)",
        )
    }
    assert len(oracle) == 95
    # честный счёт (по использованию) не больше счёта по слову: честное нулевое множество включает находку
    assert zero_tests >= oracle


_PIN_API = {
    "router_module": "  IRouterManager (21), IMessageChannel (9)",
    "message_module": "  IMessage (12)",
    "app_module": (
        "  ManifestStoreProtocol (2), BlueprintLoader (0), LauncherFactory (0), ProcDictsBuilder (0),"
        " StateBootstrap (0), … ещё 1"
    ),
    "data_schema_module": (
        "  HasBuild, IAsyncRegisterStorage, IAsyncSchemaStorage, IDataConverter, IDataValidator, … ещё 12"
    ),
    "worker_module": "  IWorkerManager (22), IWorkerRegistry (8), IWorkerLifecycle (4), WorkerStatus, WorkerType",
}


def test_index_on_origin_main_pin(pinned: GitRepo, atlas: Any) -> None:
    lines = _ok(atlas(pinned, "index", *_PINNED))
    assert len(lines) == 133
    assert len(lines) <= 200
    assert lines[0] == _HEADER

    from scripts.atlas.modules import parse_modules

    code, text = _git("show", f"{_PIN}:modules.yaml")
    assert code == 0
    ids = [row["id"] for row in parse_modules(text)]
    assert len(ids) == 87
    module_lines = [line for line in lines[1:] if not line.startswith("  ")]
    assert module_lines == [f"{module_id} — нет purpose в modules.yaml" for module_id in ids]
    assert sum(1 for line in lines if line.startswith("  ")) == 45

    for module_id, api in _PIN_API.items():
        at = lines.index(f"{module_id} — нет purpose в modules.yaml")
        assert lines[at + 1] == api, module_id
