"""Task 2.1 (commit-mechanism) — приёмка валидатора v2 в обеих копиях (REDS V1-V17 + сторожа G1-G4).

Контракт (из ТЗ `plans/2026-10-03_commit-mechanism/tasks/2.1.md`, ред. 3, не из реализации):
  * модульная константа `STRICT = False` в обеих копиях валидатора; всё, что в таблице помечено
    «WARN -> ERR в фазе 3», при `STRICT = False` — предупреждение (stderr, rc 0), при `True` — ошибка (rc 1);
  * слияния больше не пропускаются целиком; тип `merge` разрешён, без scope; `Merge branch ...` — WARN;
  * scope допускает точку; длина первой строки: WARN после 72 и после 100, отказа нет;
  * `Refs:` при ветке, разрешающейся в план, обязателен и подходит любой существующий план
    (не `plans/queue/`, не `*.result.md`);
  * сторожа: копии равны по AST (G1), `.claude/commit-layers.txt` — ровно 9 слоёв (G2), v2 принимает всё,
    что принимал v1 на 200 реальных сообщениях (G3), поток `git merge --no-ff --no-commit` + `GIT_EDITOR=true
    git commit` доходит до коммита и печатает предупреждение (G4).

Метод: валидатор запускается ПОДПРОЦЕССОМ (`python <путь> -`, сообщение на stdin) из временного git-репозитория
с известной веткой и `plans/`; сверяются rc и литеральные подстроки stderr. Колонка `STRICT = True` — копия
валидатора с текстовой заменой `STRICT = False` -> `STRICT = True` (замена обязана произойти ровно один раз —
иначе тест ПАДАЕТ с понятным сообщением, не пропускается; пока константы нет, вся колонка красная по построению).
Окружение: git изолирован от глобального конфига, `GIT_*` вычищены, вывод процессов — во временные файлы,
`timeout=120`. Таблицу V проходят обе копии (параметр `copy`).
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
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
COMMIT_LAYERS = REPO_ROOT / ".claude" / "commit-layers.txt"
STACK_MD = REPO_ROOT / ".claude" / "modes" / "_stack.md"

TIMEOUT = 120
PINNED_SHA = "2f16381ff"
BRANCH = "feat/commit-mechanism"
PLAN = "plans/2026-10-03_commit-mechanism/plan.md"
LAYERS = ["framework", "services", "plugins", "prototype", "docs", "scripts", "tests", "infra", "mixed"]

_WHY = "Why: проверка того, что валидатор принимает полное сообщение"
_FULL = f"{_WHY}\nLayer: docs\nRefs: {PLAN}\n"
_NO_LAYER = f"{_WHY}\nRefs: {PLAN}\n"


# --------------------------------------------------------------------------- process helpers


def _clean_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run_raw(
    cmd: list[str],
    cwd: Path,
    *,
    stdin_data: bytes | None = None,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    env = _clean_env()
    if extra_env:
        env.update(extra_env)
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err, tempfile.TemporaryFile() as inp:
        if stdin_data is not None:
            inp.write(stdin_data)
            inp.seek(0)
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            stdin=inp if stdin_data is not None else subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            timeout=TIMEOUT,
            check=False,
        )
        out.seek(0)
        err.seek(0)
        return proc.returncode, out.read().decode("utf-8", "replace"), err.read().decode("utf-8", "replace")


def _git(repo: Path, *args: str, extra_env: dict[str, str] | None = None) -> str:
    rc, out, err = _run_raw(["git", *args], repo, extra_env=extra_env)
    assert rc == 0, f"git {' '.join(args)} rc={rc}\n{out}\n{err}"
    return out


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _init_repo(path: Path, branch: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", branch)
    _git(path, "config", "user.name", "Tester")
    _git(path, "config", "user.email", "tester@example.invalid")
    _git(path, "config", "core.autocrlf", "false")
    _git(path, "config", "commit.gpgsign", "false")
    return path


def _run_validator(validator: Path, repo: Path, message: str) -> tuple[int, str]:
    rc, _out, err = _run_raw([sys.executable, str(validator), "-"], repo, stdin_data=message.encode("utf-8"))
    return rc, err


def _strict_copy(source: Path, target_dir: Path) -> Path:
    text = source.read_bytes().decode("utf-8")
    count = text.count("STRICT = False")
    assert count == 1, f"{source.name}: expected exactly one 'STRICT = False' to replace, found {count}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "validate_commit.py"
    target.write_bytes(text.replace("STRICT = False", "STRICT = True").encode("utf-8"))
    return target


# --------------------------------------------------------------------------- repo for the V-table


@pytest.fixture(scope="module")
def v_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Ветка feat/commit-mechanism, планы на диске, список слоёв — литерал из 9 строк (не файл из дерева)."""
    repo = _init_repo(tmp_path_factory.mktemp("vrepo"), BRANCH)
    _write(repo / ".claude" / "commit-layers.txt", "# layers\n" + "\n".join(LAYERS) + "\n")
    _write(repo / PLAN, f"# Plan: commit mechanism\n\n- **Ветка:** {BRANCH}\n")
    _write(repo / "plans" / "2026-10-03_commit-mechanism" / "tasks" / "2.1.result.md", "# result\n")
    _write(repo / "plans" / "2026-10-05_other-plan" / "plan.md", "# Plan: other\n\n- **Ветка:** feat/other-plan\n")
    _write(repo / "plans" / "queue" / "2026-10-06_queued.md", "# queued\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _subject(length: int, prefix: str = "docs(x): ") -> str:
    """Первая строка ровно `length` символов, описание кириллицей."""
    body = ("тест слова " * 20)[: length - len(prefix)]
    if body.endswith(" "):
        body = body[:-1] + "я"
    line = prefix + body
    assert len(line) == length
    return line


@dataclass(frozen=True)
class Row:
    id: str
    message: str
    rc_false: int
    present_false: tuple[str, ...] = ()
    absent_false: tuple[str, ...] = ()
    rc_true: int = 0


ROWS = [
    Row("V1", f"feat(x): y\n\n{_FULL}", 0, absent_false=("WARNING",), rc_true=0),
    Row("V2", f"feat(task-5.5): y\n\n{_FULL}", 0, absent_false=("WARNING",), rc_true=0),
    Row("V3", f"merge: Task 5.3 — слияние ветки\n\n{_FULL}", 0, absent_false=("WARNING",), rc_true=0),
    Row("V4", "merge: слияние без трейлеров\n", 0, ("merge commit without Why/Layer/Refs",), rc_true=1),
    Row("V5", f"merge(scope): слияние\n\n{_FULL}", 1, rc_true=1),
    Row("V6", "Merge branch 'x' into main\n", 0, ("default git merge text",), rc_true=1),
    Row("V7", "Merge remote-tracking branch 'origin/x'\n", 0, ("default git merge text",), rc_true=1),
    Row("V8", f"feat(x): y\n\n{_NO_LAYER}", 0, ("Layer missing",), rc_true=1),
    Row("V9", f"feat(x): y\n\n{_WHY}\nLayer: tools\nRefs: {PLAN}\n", 0, ("Layer not in list",), rc_true=1),
    Row("V10", f"{_subject(73)}\n\n{_FULL}", 0, ("subject longer than 72",), ("subject longer than 100",), 0),
    Row("V11", f"{_subject(101)}\n\n{_FULL}", 0, ("subject longer than 100",), rc_true=0),
    Row("V12", f"feat(x): y\n\n{_WHY}\nLayer: docs\nRefs: plans/2026-10-05_other-plan/plan.md\n", 0, rc_true=0),
    Row("V13", f"feat(x): y\n\n{_WHY}\nLayer: docs\nRefs: plans/queue/2026-10-06_queued.md\n", 1, rc_true=1),
    Row(
        "V14",
        f"feat(x): y\n\n{_WHY}\nLayer: docs\nRefs: plans/2026-10-03_commit-mechanism/tasks/2.1.result.md\n",
        1,
        rc_true=1,
    ),
    Row("V15", f"feat(x): y\n\n{_WHY}\nLayer: docs\nRefs: plans/nonexistent.md\n", 1, rc_true=1),
    Row("V16a", 'Revert "feat: x"\n', 0, rc_true=0),
    Row("V16b", "fixup! feat: x\n", 0, rc_true=0),
    Row("V17", f"wip: x\n\n{_FULL}", 1, rc_true=1),
]


_PARAMS = [pytest.param(row, copy, id=f"{row.id}-{copy}") for row in ROWS for copy in COPIES]


# --------------------------------------------------------------------------- V1-V17, STRICT = False


@pytest.mark.parametrize(("row", "copy"), _PARAMS)
def test_v_table_non_strict(row: Row, copy: str, v_repo: Path) -> None:
    rc, err = _run_validator(COPIES[copy], v_repo, row.message)

    assert rc == row.rc_false, f"rc={rc}, expected {row.rc_false}\n{err}"
    for needle in row.present_false:
        assert needle in err, f"{needle!r} not in stderr:\n{err}"
    for needle in row.absent_false:
        assert needle not in err, f"{needle!r} unexpectedly in stderr:\n{err}"


# --------------------------------------------------------------------------- V1-V17, STRICT = True


@pytest.mark.parametrize(("row", "copy"), _PARAMS)
def test_v_table_strict(row: Row, copy: str, v_repo: Path, tmp_path: Path) -> None:
    validator = _strict_copy(COPIES[copy], tmp_path / "strict")  # падает, пока константы нет

    rc, err = _run_validator(validator, v_repo, row.message)

    assert rc == row.rc_true, f"rc={rc}, expected {row.rc_true}\n{err}"


# --------------------------------------------------------------------------- G1-G2


def test_g1_validator_copies_are_equal_by_ast() -> None:
    dumps = {name: ast.dump(ast.parse(path.read_bytes().decode("utf-8"))) for name, path in COPIES.items()}
    lengths = {name: len(dump) for name, dump in dumps.items()}
    assert dumps["scripts"] == dumps["template"], f"copies differ by AST (ast.dump lengths: {lengths})"


def test_g2_commit_layers_has_exactly_the_nine_layers() -> None:
    lines = [line.strip() for line in COMMIT_LAYERS.read_text(encoding="utf-8").splitlines()]
    layers = [line for line in lines if line and not line.startswith("#")]
    assert sorted(layers) == sorted(LAYERS), f"layers: {layers}"


# --------------------------------------------------------------------------- G3: v2 accepts everything v1 accepted


@pytest.fixture(scope="module")
def g3_context(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list[str]]:
    """tmp-репо на `main` без plans/ + сообщения, которые принимает v1 (из закреплённого SHA)."""
    base = tmp_path_factory.mktemp("g3")
    v1_bytes = subprocess.run(
        ["git", "show", f"{PINNED_SHA}:scripts/validate_commit/validate_commit.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        timeout=TIMEOUT,
        check=False,
    )
    assert v1_bytes.returncode == 0, f"git show {PINNED_SHA} failed: {v1_bytes.stderr!r}"
    v1 = base / "v1" / "validate_commit.py"
    v1.parent.mkdir()
    v1.write_bytes(v1_bytes.stdout)

    log = subprocess.run(
        ["git", "log", "-200", "--format=%B%x00", PINNED_SHA],
        cwd=REPO_ROOT,
        capture_output=True,
        timeout=TIMEOUT,
        check=False,
    )
    assert log.returncode == 0, f"git log {PINNED_SHA} failed: {log.stderr!r}"
    messages = [m.lstrip("\n") for m in log.stdout.decode("utf-8", "replace").split("\x00")]
    messages = [m for m in messages if m.strip()]
    assert len(messages) == 200, f"expected 200 messages, got {len(messages)}"

    repo = _init_repo(base / "repo", "main")
    (repo / ".claude" / "modes").mkdir(parents=True)
    (repo / ".claude" / "commit-layers.txt").write_bytes(COMMIT_LAYERS.read_bytes())
    (repo / ".claude" / "modes" / "_stack.md").write_bytes(STACK_MD.read_bytes())
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")

    accepted = [m for m in messages if _run_validator(v1, repo, m)[0] == 0]
    return repo, accepted


@pytest.mark.parametrize("copy", list(COPIES))
def test_g3_v2_accepts_every_message_v1_accepted(copy: str, g3_context: tuple[Path, list[str]]) -> None:
    repo, accepted = g3_context
    # премисса не пуста: среди принятых есть и `Merge ...` по умолчанию, и `merge: ...`
    assert any(m.startswith("Merge ") for m in accepted), "no default 'Merge ...' message among accepted"
    assert any(m.startswith("merge: ") for m in accepted), "no 'merge: ...' message among accepted"

    rejected = []
    for message in accepted:
        rc, err = _run_validator(COPIES[copy], repo, message)
        if rc != 0:
            rejected.append(f"{message.splitlines()[0][:70]!a} -> rc={rc}: {err.strip()[:200]!a}")
    assert rejected == [], f"{len(rejected)} of {len(accepted)} accepted messages are rejected by v2:\n" + "\n".join(
        rejected[:10]
    )


# --------------------------------------------------------------------------- G4: merge flow through the real hook


def test_g4_merge_flow_commit_created_and_warns(tmp_path: Path) -> None:
    validator = COPIES["scripts"]
    repo = _init_repo(tmp_path / "repo", "main")
    _write(repo / "a.txt", "a\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "checkout", "-q", "-b", "x")
    _write(repo / "b.txt", "b\n")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-q", "-m", "x work")
    _git(repo, "checkout", "-q", "main")
    _write(repo / "c.txt", "c\n")
    _git(repo, "add", "c.txt")
    _git(repo, "commit", "-q", "-m", "main work")

    hook = repo / ".git" / "hooks" / "commit-msg"
    hook.write_text(
        f'#!/bin/sh\nexec "{Path(sys.executable).as_posix()}" "{validator.as_posix()}" "$1"\n',
        encoding="utf-8",
        newline="\n",
    )
    hook.chmod(0o755)

    _git(repo, "merge", "--no-ff", "--no-commit", "x")
    (repo / ".git" / "MERGE_MSG").write_text("merge: слияние x без трейлеров\n", encoding="utf-8", newline="\n")
    rc, out, err = _run_raw(["git", "commit"], repo, extra_env={"GIT_EDITOR": "true"})

    assert rc == 0, f"git commit rc={rc}\n{out}\n{err}"
    parents = _git(repo, "rev-list", "--parents", "-n", "1", "HEAD").split()
    assert len(parents) == 3, f"HEAD is not a merge commit: {parents}"
    assert "merge commit without Why/Layer/Refs" in err, f"stderr:\n{err}"
