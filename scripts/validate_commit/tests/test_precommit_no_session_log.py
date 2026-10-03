"""Task 1.1 (commit-mechanism) — приёмка: хук `session-log` убран, unstaged-правки переживают коммит.

Контракт (из ТЗ, не из реализации):
  * хук с id `session-log` (entry зовёт `pre-commit-session-log.sh`) удалён из
    `.pre-commit-config.yaml` и из seed-шаблона
    `.claude/plugins/lang-python/templates/pre-commit-config.template.yaml`;
  * остальные хуки остаются.

Почему это важно (причина воспроизведена ревьюером): хук дописывает и `git add`-ит
ОТСЛЕЖИВАЕМЫЙ журнал `docs/sessions/<сегодня YYYY-MM-DD>.md`, пока pre-commit держит
unstaged-правки в stash. Восстановление stash падает («patch does not apply»), коммит
обрывается даже при всех Passed, unstaged-правки теряются. Второй путь: журнал в индексе
+ коммит с pathspec.

Тесты 1-4 парсят YAML. Тесты 5-7 строят временный git-репозиторий (`git init` явно в
tmp_path: tmp у pytest может лежать внутри чужого репозитория), копируют НАСТОЯЩИЕ
`.pre-commit-config.yaml`, `pyproject.toml`, `.claude/hooks/git/pre-commit-session-log.sh`
из рабочего дерева по тем же относительным путям (рукописный конфиг проверял бы фикстуру),
ставят `pre-commit install`. Конфиг НЕ правится.

Окружение:
  * CRLF -> LF только при копировании трёх файлов: checkout на Windows отдаёт CRLF,
    а `bash script.sh` с CRLF падает по причине, не связанной с контрактом.
  * Глобальный/системный git-конфиг отключён (GIT_CONFIG_GLOBAL/NOSYSTEM), чтобы
    `core.hooksPath` пользователя не мешал `pre-commit install`; GIT_DIR/GIT_INDEX_FILE
    и подобные из окружения вычищены (тест может запускаться изнутри хука git).
  * Пропущенные хуки (SKIP=): ни одного. Список `_SKIP_IDS` пуст; `session-log`
    пропускать запрещено — тест 5-7 теряет смысл.
  * pre-commit не найден -> FAIL, не skip.
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]

PROJECT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
SEED_TEMPLATE = REPO_ROOT / ".claude" / "plugins" / "lang-python" / "templates" / "pre-commit-config.template.yaml"
HOOK_SCRIPT_REL = Path(".claude") / "hooks" / "git" / "pre-commit-session-log.sh"

TIMEOUT = 120

# Хуки, которые нельзя запустить во временном репозитории по причинам окружения.
# Пусто: все хуки pre-commit-стадии работают. НИКОГДА не добавлять `session-log`.
_SKIP_IDS: tuple[str, ...] = ()

_PROJECT_KEEP_IDS = {
    "trailing-whitespace",
    "end-of-file-fixer",
    "check-yaml",
    "check-toml",
    "check-merge-conflict",
    "check-added-large-files",
    "debug-statements",
    "ruff",
    "ruff-format",
    "pyright",
    "bandit",
}
_SEED_KEEP_IDS = _PROJECT_KEEP_IDS | {
    "check-json",
    "check-case-conflict",
    "mixed-line-ending",
    "gitleaks",
    "sentrux-check",
    "pip-audit",
}

_UNSTAGED_EDIT = "UNSTAGED_EDIT"
_WRAPUP_TEXT = "WRAPUP_TEXT"


# --------------------------------------------------------------------------- YAML helpers


def _load_hooks(path: Path) -> list[dict]:
    """Плоский список hook-словарей из `repos[*].hooks[*]`."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    hooks: list[dict] = []
    for repo in data["repos"]:
        hooks.extend(repo.get("hooks", []))
    return hooks


def _ids(path: Path) -> set[str]:
    return {h["id"] for h in _load_hooks(path)}


def _session_log_entries(path: Path) -> list[str]:
    return [h["entry"] for h in _load_hooks(path) if "pre-commit-session-log" in str(h.get("entry", ""))]


# --------------------------------------------------------------------------- git/pre-commit helpers


def _clean_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k != "PRE_COMMIT"}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if _SKIP_IDS:
        env["SKIP"] = ",".join(_SKIP_IDS)
    return env


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=_clean_env(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=TIMEOUT,
        check=False,
    )


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], repo)


def _git_ok(repo: Path, *args: str) -> str:
    proc = _git(repo, *args)
    assert proc.returncode == 0, f"git {' '.join(args)} rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    return proc.stdout


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _append(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _copy_real(src: Path, dst: Path) -> None:
    """Копия настоящего файла без правок; только CRLF -> LF (см. докстринг модуля)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes().replace(b"\r\n", b"\n"))


@pytest.fixture(scope="module", autouse=False)
def _pre_commit_available() -> None:
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pre_commit", "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover - environment
        pytest.fail(f"pre-commit is not runnable: {exc!r}")
    if proc.returncode != 0:
        pytest.fail(f"pre-commit is not runnable (rc={proc.returncode}): {proc.stdout}{proc.stderr}")


def _make_repo(tmp_path: Path, *, journal_in_first_commit: bool) -> tuple[Path, str, Path]:
    """Временный репозиторий с настоящим конфигом.

    Первый коммит делается ДО `pre-commit install` (хуков ещё нет, поэтому `--no-verify`
    не нужен): a.py, b.py, настоящие конфиг/pyproject/скрипт и, опционально,
    журнал `docs/sessions/<сегодня>.md`. Затем ставится `pre-commit install`.
    Возвращает (repo, today, journal_path).
    """
    today = datetime.date.today().isoformat()
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_ok(repo, "init", "-q")
    _git_ok(repo, "config", "user.name", "Tester")
    _git_ok(repo, "config", "user.email", "tester@example.invalid")
    _git_ok(repo, "config", "core.autocrlf", "false")
    _git_ok(repo, "config", "commit.gpgsign", "false")

    _copy_real(PROJECT_CONFIG, repo / ".pre-commit-config.yaml")
    _copy_real(REPO_ROOT / "pyproject.toml", repo / "pyproject.toml")
    _copy_real(REPO_ROOT / HOOK_SCRIPT_REL, repo / HOOK_SCRIPT_REL)
    _write(repo / "a.py", "x = 1\n")
    _write(repo / "b.py", "y = 1\n")
    journal = repo / "docs" / "sessions" / f"{today}.md"
    to_add = [".pre-commit-config.yaml", "pyproject.toml", HOOK_SCRIPT_REL.as_posix(), "a.py", "b.py"]
    if journal_in_first_commit:
        _write(journal, f"# {today}\n\nfirst entry\n")
        to_add.append(journal.relative_to(repo).as_posix())
    _git_ok(repo, "add", *to_add)
    _git_ok(repo, "commit", "-q", "-m", "init")

    install = _run([sys.executable, "-m", "pre_commit", "install"], repo)
    assert install.returncode == 0, f"pre-commit install rc={install.returncode}\n{install.stdout}\n{install.stderr}"
    return repo, today, journal


# --------------------------------------------------------------------------- 1-4: YAML contract


def test_project_config_has_no_session_log_hook() -> None:
    ids = _ids(PROJECT_CONFIG)
    assert ids, "parsed zero hooks from the project config"
    assert "session-log" not in ids
    assert _session_log_entries(PROJECT_CONFIG) == []


def test_seed_template_has_no_session_log_hook() -> None:
    ids = _ids(SEED_TEMPLATE)
    assert ids, "parsed zero hooks from the seed template"
    assert "session-log" not in ids
    assert _session_log_entries(SEED_TEMPLATE) == []


def test_project_config_keeps_other_hooks() -> None:
    ids = _ids(PROJECT_CONFIG)
    assert _PROJECT_KEEP_IDS <= ids, f"missing: {sorted(_PROJECT_KEEP_IDS - ids)}"
    assert "session-log" not in ids


def test_seed_template_keeps_other_hooks() -> None:
    ids = _ids(SEED_TEMPLATE)
    assert _SEED_KEEP_IDS <= ids, f"missing: {sorted(_SEED_KEEP_IDS - ids)}"
    assert "session-log" not in ids


# --------------------------------------------------------------------------- 5-7: real commits


@pytest.mark.usefixtures("_pre_commit_available")
def test_unstaged_edits_survive_commit_with_dirty_journal(tmp_path: Path) -> None:
    repo, _today, journal = _make_repo(tmp_path, journal_in_first_commit=True)

    _append(repo / "a.py", "x = 2\n")
    _git_ok(repo, "add", "a.py")
    _append(repo / "b.py", f"# {_UNSTAGED_EDIT}\n")  # unstaged
    _append(journal, f"{_WRAPUP_TEXT}\n")  # unstaged

    proc = _git(repo, "commit", "-m", "x")

    assert proc.returncode == 0, f"commit rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    assert _git_ok(repo, "rev-list", "--count", "HEAD").strip() == "2"
    assert _UNSTAGED_EDIT in (repo / "b.py").read_text(encoding="utf-8")
    assert _WRAPUP_TEXT in journal.read_text(encoding="utf-8")


@pytest.mark.usefixtures("_pre_commit_available")
def test_pathspec_commit_with_staged_journal_keeps_unstaged_edits(tmp_path: Path) -> None:
    repo, _today, journal = _make_repo(tmp_path, journal_in_first_commit=True)

    _append(journal, f"{_WRAPUP_TEXT}\n")
    _git_ok(repo, "add", journal.relative_to(repo).as_posix())  # journal edit STAGED
    _append(repo / "a.py", "x = 2\n")
    _git_ok(repo, "add", "a.py")
    _append(repo / "b.py", f"# {_UNSTAGED_EDIT}\n")  # unstaged

    proc = _git(repo, "commit", "-m", "x", "a.py")

    assert proc.returncode == 0, f"commit rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    assert _UNSTAGED_EDIT in (repo / "b.py").read_text(encoding="utf-8")


@pytest.mark.usefixtures("_pre_commit_available")
def test_ordinary_commit_does_not_carry_journal(tmp_path: Path) -> None:
    repo, _today, journal = _make_repo(tmp_path, journal_in_first_commit=False)
    _write(journal, f"# journal\n\n{_WRAPUP_TEXT}\n")  # exists, untracked
    _append(repo / "a.py", "x = 2\n")
    _git_ok(repo, "add", "a.py")

    proc = _git(repo, "commit", "-m", "x")

    assert proc.returncode == 0, f"commit rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    assert _git_ok(repo, "rev-list", "--count", "HEAD").strip() == "2"
    stat = _git_ok(repo, "show", "--stat", "--format=", "HEAD")
    assert "a.py" in stat  # anchor: HEAD is the new commit, not the initial one
    assert "docs/sessions" not in stat
