"""Task 1.3 (commit-mechanism) — приёмка: bandit не сканирует docs/reviews/**; гейт тестов выключен.

Контракт (из ТЗ `plans/2026-10-03_commit-mechanism/tasks/1.3.md`, не из реализации):
  * `exclude` хука bandit в `.pre-commit-config.yaml` И в seed-шаблоне
    `.claude/plugins/lang-python/templates/pre-commit-config.template.yaml` совпадает с
    `docs/reviews/<что-угодно>.py` (каждая копия отдельно);
  * остальной код остаётся под сканом: `multiprocess_framework/modules/`, `Services/`,
    `Plugins/`, `multiprocess_prototype/` НЕ попадают в exclude;
  * гейт тестов валидатора коммитов выключен: код в стейдже без `Tested:` не отклоняется
    сообщением `Gated code staged without tests`.

Тесты:
  1-3  парсят YAML (pyyaml); `exclude` применяется как `re.search` по POSIX-пути (так делает pre-commit);
  4, 6 временный git-репозиторий с НАСТОЯЩИМИ `.pre-commit-config.yaml` и `pyproject.toml`
       (копии из рабочего дерева по тем же путям; рукописный конфиг проверял бы фикстуру);
       `pre-commit run bandit --files <путь>`. Тест 6 — контроль живости к 4: тот же файл
       вне исключения (`Services/…`) обязан давать rc != 0, иначе rc == 0 в тесте 4
       ничего не доказывает;
  5    временный репозиторий с НАСТОЯЩИМИ `.claude/modes/_stack.md` и
       `scripts/validate_commit/validate_commit.py`; в индексе `src/a.py` (путь, на который
       гейт смотрит сегодня). Валидатор вызывается так же, как хук commit-msg:
       `python scripts/validate_commit/validate_commit.py <файл-сообщения>` с cwd = корень репо.
       Ветка во временном репо — `main`: плана с таким именем нет, `Refs:` не требуется.

Окружение (как в 1.1): git изолирован от глобального/системного конфига, `GIT_*` вычищены;
вывод процессов — во временные ФАЙЛЫ (не pipe), `timeout=120`; pre-commit через
`sys.executable -m pre_commit`, нет pre-commit -> FAIL, не skip; CRLF -> LF только при
копировании. Пропущенные хуки (SKIP=): ни одного.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]

PROJECT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
SEED_TEMPLATE = REPO_ROOT / ".claude" / "plugins" / "lang-python" / "templates" / "pre-commit-config.template.yaml"
STACK_REL = Path(".claude") / "modes" / "_stack.md"
VALIDATOR_REL = Path("scripts") / "validate_commit" / "validate_commit.py"

TIMEOUT = 120

_INJECTION_SCRIPT = 'import subprocess\n\nsubprocess.run(["git", "status"])\n'
_GATE_PHRASE = "Gated code staged without tests"
_COMMIT_MESSAGE = "feat(x): y\n\nWhy: z\nLayer: tests\n"


# --------------------------------------------------------------------------- helpers


def _bandit_exclude(path: Path) -> str:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    excludes = [h["exclude"] for repo in data["repos"] for h in repo.get("hooks", []) if h.get("id") == "bandit"]
    assert len(excludes) == 1, f"expected exactly one bandit hook with exclude in {path.name}, got {excludes!r}"
    return excludes[0]


def _clean_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "PRE_COMMIT"}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    # Вывод — во временные файлы, не в pipe: убитый по таймауту процесс не оставляет
    # внуков, держащих pipe, и тест падает по TimeoutExpired, а не висит.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=_clean_env(),
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            timeout=TIMEOUT,
            check=False,
        )
        out.seek(0)
        err.seek(0)
        return subprocess.CompletedProcess(
            cmd,
            proc.returncode,
            out.read().decode("utf-8", errors="replace"),
            err.read().decode("utf-8", errors="replace"),
        )


def _git_ok(repo: Path, *args: str) -> str:
    proc = _run(["git", *args], repo)
    assert proc.returncode == 0, f"git {' '.join(args)} rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    return proc.stdout


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _copy_real(src: Path, dst: Path) -> None:
    """Копия настоящего файла без правок; только CRLF -> LF (единый вид как на Linux/macOS)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes().replace(b"\r\n", b"\n"))


def _init_repo(tmp_path: Path) -> Path:
    """`git init -b main` явно в tmp_path (pytest tmp может лежать внутри чужого репо)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_ok(repo, "init", "-q", "-b", "main")
    _git_ok(repo, "config", "user.name", "Tester")
    _git_ok(repo, "config", "user.email", "tester@example.invalid")
    _git_ok(repo, "config", "core.autocrlf", "false")
    _git_ok(repo, "config", "commit.gpgsign", "false")
    return repo


@pytest.fixture(scope="module")
def _pre_commit_available() -> None:
    try:
        proc = _run([sys.executable, "-m", "pre_commit", "--version"], REPO_ROOT)
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover - environment
        pytest.fail(f"pre-commit is not runnable: {exc!r}")
    if proc.returncode != 0:
        pytest.fail(f"pre-commit is not runnable (rc={proc.returncode}): {proc.stdout}{proc.stderr}")


def _bandit_on_file(tmp_path: Path, rel_path: str) -> subprocess.CompletedProcess[str]:
    """Настоящие конфиг+pyproject во временном репо, скрипт-инъекция по `rel_path`, `pre-commit run bandit`."""
    repo = _init_repo(tmp_path)
    _copy_real(PROJECT_CONFIG, repo / ".pre-commit-config.yaml")
    _copy_real(REPO_ROOT / "pyproject.toml", repo / "pyproject.toml")
    _write(repo / rel_path, _INJECTION_SCRIPT)
    _git_ok(repo, "add", ".pre-commit-config.yaml", "pyproject.toml", rel_path)
    return _run([sys.executable, "-m", "pre_commit", "run", "bandit", "--files", rel_path], repo)


# --------------------------------------------------------------------------- 1-3: YAML contract


def test_project_bandit_excludes_docs_reviews() -> None:
    exclude = _bandit_exclude(PROJECT_CONFIG)
    assert re.search(exclude, "docs/reviews/2026-10-03_inject_x.py"), f"exclude {exclude!r} does not match"


def test_seed_template_bandit_excludes_docs_reviews() -> None:
    exclude = _bandit_exclude(SEED_TEMPLATE)
    assert re.search(exclude, "docs/reviews/2026-10-03_inject_x.py"), f"exclude {exclude!r} does not match"


def test_bandit_exclude_keeps_code_scanned() -> None:
    still_scanned = [
        "multiprocess_framework/modules/a.py",
        "Services/a.py",
        "Plugins/a.py",
        "multiprocess_prototype/a.py",
    ]
    wrongly_hidden = {}
    for config in (PROJECT_CONFIG, SEED_TEMPLATE):
        exclude = _bandit_exclude(config)
        matched = [p for p in still_scanned if re.search(exclude, p)]
        if matched:
            wrongly_hidden[f"{config.name}: {exclude!r}"] = matched
    assert wrongly_hidden == {}, f"exclude hides code that must stay scanned: {wrongly_hidden}"


# --------------------------------------------------------------------------- 4, 6: bandit hook live


@pytest.mark.usefixtures("_pre_commit_available")
def test_bandit_hook_skips_injection_script_in_docs_reviews(tmp_path: Path) -> None:
    proc = _bandit_on_file(tmp_path, "docs/reviews/inject.py")
    assert proc.returncode == 0, f"bandit rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}"


@pytest.mark.usefixtures("_pre_commit_available")
def test_bandit_hook_still_fails_on_code(tmp_path: Path) -> None:
    """Контроль живости к тесту 4: тот же файл вне исключения даёт находки bandit."""
    proc = _bandit_on_file(tmp_path, "Services/inject.py")
    assert proc.returncode != 0, f"bandit did not flag the injection script\n{proc.stdout}\n{proc.stderr}"


# --------------------------------------------------------------------------- 5: tests gate off


def test_tests_gate_is_off_for_staged_code(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _copy_real(REPO_ROOT / STACK_REL, repo / STACK_REL)
    _copy_real(REPO_ROOT / VALIDATOR_REL, repo / VALIDATOR_REL)
    _git_ok(repo, "add", STACK_REL.as_posix(), VALIDATOR_REL.as_posix())
    _git_ok(repo, "commit", "-q", "-m", "init")  # хуков в репо нет -> валидатор не вмешивается

    _write(repo / "src" / "a.py", "x = 1\n")
    _git_ok(repo, "add", "src/a.py")
    message = tmp_path / "COMMIT_MSG"
    _write(message, _COMMIT_MESSAGE)

    proc = _run([sys.executable, str(repo / VALIDATOR_REL), str(message)], repo)

    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"validator rc={proc.returncode}\n{output}"
    assert _GATE_PHRASE not in output
