"""Task 3.0 (commit-mechanism) — слепая приёмка грамматики id в трейлере `Task:` валидатора (REDS 1 и сторожа).

Источник ожидаемых значений — только `plans/2026-10-03_commit-mechanism/tasks/3.0.md`: DESIGN п. 1-2, REDS 1,
ACCEPTANCE (сторожа). Значения — литералы из ТЗ, не вычисляются из кода. Код читался лишь ради формы вызова
(`validate(text, allowed_layers, plan_path)` и CLI `validate_commit.py -`).

Что проверяется:
  * REDS 1: восемь значений `Task:` по новой грамматике НЕ дают предупреждения «Task is not <slug>#<id>»
    (сейчас красные: валидатор их отвергает);
  * сторожа: семь значений принимаются, пятнадцать отвергаются (зелёные и до, и после реализации);
  * под `STRICT = True` (временная копия валидатора, одна текстовая замена) принятое значение даёт rc 0, отвергнутое —
    rc 1 (подпроцесс, timeout);
  * обе копии валидатора (`scripts/…` и шаблон `lang-python`) проходят одну и ту же таблицу; модули грузятся по пути
    через importlib, исходник регуляркой не читается (копии отформатированы разными форматтерами).

Предупреждение «absent» само по себе доказывает мало (его может не быть из-за того, что проверка не сработала).
Якорь существования — сторожа-отказы той же таблицы: на них предупреждение обязано быть, и они зелёные сейчас.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

COPIES = {
    "scripts": REPO_ROOT / "scripts" / "validate_commit" / "validate_commit.py",
    "template": REPO_ROOT
    / ".claude"
    / "plugins"
    / "lang-python"
    / "templates"
    / "validate_commit"
    / "validate_commit.py",
}

TIMEOUT = 60
LAYERS = {"framework", "services", "plugins", "prototype", "docs", "scripts", "tests", "infra", "mixed"}
_TASK_FORMAT = "Task is not <slug>#<id>"

# --- таблицы из ТЗ (литералы) ------------------------------------------------------------------------------------
# REDS 1: красные сейчас.
REDS_ACCEPT = [
    "gui-service#1b.2d",
    "gui-service#1b.2d-2",
    "x#1b.2b-pre",
    "x#1.3h-c-fix",
    "x#F8-4",
    "x#T2-j2",
    "x#T2-k",
    "x#2v.2",
]
# ACCEPTANCE, сторожа: зелёные и до, и после.
GUARD_ACCEPT = [
    "atlas#0.4",
    "commit-mechanism#2.1",
    "x#1.3a",
    "x#T4.0",
    "x#AU1",
    "x#5.10f",
    "x#1.2.3",
]
GUARD_REJECT = [
    "x#2в.2",  # кириллическая `в`
    "x#Т.1",  # кириллическая `Т`
    "x#T2.K",
    "x#5.10.f",
    "x#D.3",
    "x#ABCD1",
    "x#1.1–1.3",  # en dash
    "x#1.1-1.3",
    "x#1.1/1.2",
    "X#1.1",
    "x#",
    "#1.1",
    "x#1.3ab",
    "x#2026-09-25",
    "x#1234",
]


def _pid(value: str) -> str:
    """ASCII-имя параметра: кириллица и тире видны как escape."""
    return value.encode("unicode_escape").decode("ascii") or "<empty>"


def _message(value: str) -> str:
    return (
        "test(plans): проверка грамматики id\n\n"
        "Why: проверка грамматики id в трейлере Task\n"
        "Layer: tests\n"
        f"Task: {value}\n"
    )


# --- загрузка модулей по пути ------------------------------------------------------------------------------------


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module", params=sorted(COPIES), ids=sorted(COPIES))
def validator(request):
    return _load(f"validate_commit_t30_{request.param}", COPIES[request.param])


@pytest.fixture(scope="module")
def clean_repo() -> Path:
    """Пустой git-репозиторий в системном temp (не внутри рабочего дерева): плана и конфигов слоёв в нём нет."""
    root = Path(tempfile.mkdtemp(prefix="t30_validator_"))
    subprocess.run(["git", "init", "-q", "-b", "scratch"], cwd=root, check=True, timeout=TIMEOUT, capture_output=True)
    return root


@pytest.fixture(autouse=True)
def _cwd_in_clean_repo(clean_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(clean_repo)


def _warnings(validator, value: str) -> list[str]:
    result = validator.validate(_message(value), allowed_layers=set(LAYERS), plan_path=None)
    return list(result.warnings)


def _task_warning(validator, value: str) -> bool:
    return any(_TASK_FORMAT in w for w in _warnings(validator, value))


# --- STRICT: временная копия валидатора --------------------------------------------------------------------------


def _strict_copy(source: Path, target_dir: Path) -> Path:
    text = source.read_bytes().decode("utf-8")
    count = text.count("STRICT = False")
    assert count == 1, f"{source}: нужна ровно одна строка 'STRICT = False', найдено {count}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "validate_commit.py"
    target.write_bytes(text.replace("STRICT = False", "STRICT = True").encode("utf-8"))
    return target


@pytest.fixture(scope="module", params=sorted(COPIES), ids=sorted(COPIES))
def strict_validator(request, tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _strict_copy(COPIES[request.param], tmp_path_factory.mktemp(f"strict_{request.param}"))


def _strict_rc(strict_script: Path, repo: Path, value: str) -> tuple[int, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    proc = subprocess.run(
        [sys.executable, str(strict_script), "-"],
        cwd=repo,
        env=env,
        input=_message(value).encode("utf-8"),
        capture_output=True,
        timeout=TIMEOUT,
        check=False,
    )
    return proc.returncode, proc.stderr.decode("utf-8", "replace")


# --- REDS 1: значения по новой грамматике принимаются ------------------------------------------------------------


@pytest.mark.parametrize("value", REDS_ACCEPT, ids=_pid)
def test_reds1_value_in_new_grammar_gives_no_task_warning(validator, value):
    assert not _task_warning(validator, value), _warnings(validator, value)


@pytest.mark.parametrize("value", REDS_ACCEPT, ids=_pid)
def test_reds1_value_in_new_grammar_passes_under_strict(strict_validator, clean_repo, value):
    rc, err = _strict_rc(strict_validator, clean_repo, value)
    assert rc == 0, err


# --- сторожа: принимаются --------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", GUARD_ACCEPT, ids=_pid)
def test_guard_accepted_value_gives_no_task_warning(validator, value):
    assert not _task_warning(validator, value), _warnings(validator, value)


@pytest.mark.parametrize("value", GUARD_ACCEPT, ids=_pid)
def test_guard_accepted_value_passes_under_strict(strict_validator, clean_repo, value):
    rc, err = _strict_rc(strict_validator, clean_repo, value)
    assert rc == 0, err


# --- сторожа: отвергаются (они же якорь существования проверки) -------------------------------------------------


@pytest.mark.parametrize("value", GUARD_REJECT, ids=_pid)
def test_guard_rejected_value_gives_task_warning(validator, value):
    assert _task_warning(validator, value), _warnings(validator, value)


@pytest.mark.parametrize("value", GUARD_REJECT, ids=_pid)
def test_guard_rejected_value_fails_under_strict(strict_validator, clean_repo, value):
    rc, err = _strict_rc(strict_validator, clean_repo, value)
    assert rc == 1, err
    assert _TASK_FORMAT in err, err
