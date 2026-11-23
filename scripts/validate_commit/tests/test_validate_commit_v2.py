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

_REFS_INVALID = "Refs names no existing plan"
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
    Row(
        "V13",
        f"feat(x): y\n\n{_WHY}\nLayer: docs\nRefs: plans/queue/2026-10-06_queued.md\n",
        0,
        (_REFS_INVALID,),
        rc_true=1,
    ),
    Row(
        "V14",
        f"feat(x): y\n\n{_WHY}\nLayer: docs\nRefs: plans/2026-10-03_commit-mechanism/tasks/2.1.result.md\n",
        0,
        (_REFS_INVALID,),
        rc_true=1,
    ),
    Row(
        "V15",
        f"feat(x): y\n\n{_WHY}\nLayer: docs\nRefs: plans/nonexistent.md\n",
        0,
        (_REFS_INVALID,),
        rc_true=1,
    ),
    Row("V18", f"feat(x): y\n\n{_WHY}\nLayer: docs\n", 1, rc_true=1),
    Row(
        "V19",
        f"merge: слияние ветки\n\n{_WHY}\nLayer: docs\nRefs: plans/queue/2026-10-06_queued.md\n",
        0,
        ("WARNING",),
        rc_true=1,
    ),
    Row(
        "V20",
        f"feat(x): y\n\n{_WHY}\nLayer: docs\nRefs: plans/queue/2026-10-06_queued.md,\n    {PLAN}\n",
        0,
        absent_false=(_REFS_INVALID,),
        rc_true=0,
    ),
    Row(
        "V21",
        f"feat(x): y\n\n{_WHY}\nLayer: docs\nRefs: plans/./queue/2026-10-06_queued.md\n",
        0,
        (_REFS_INVALID,),
        rc_true=1,
    ),
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


# --------------------------------------------------------------------------- Task 7.1a: трейлер `Decision:`
#
# Контракт (ТЗ `plans/2026-11-06_atlas-passport/tasks/7.1a.md` + DESIGN лида): коммит, чей staged-дифф
# добавляет заголовок `## ADR-<MOD>-NNN` / `### ADR-<MOD>-NNN` в `*DECISIONS.md`, получает предупреждение
# с готовой строкой `Decision: ADR-...` (всегда предупреждение, и при STRICT); сам `Decision:` — известный
# трейлер, значение — ровно один id; id, которого нет ни в диффе, ни в индексе, — фаза 3.

_ADR_SUBJECT = "docs(x): записать решение"
_ADR_BASE = "# Решения\n\n## ADR-AB-001: старое решение\n\nТекст.\n"
_DECISIONS = "docs/DECISIONS.md"
_MALFORMED = "Decision: malformed value (expected ADR-<MOD>-NNN, one id per line)"


def _adr_repo(tmp_path: Path, base: str = _ADR_BASE) -> Path:
    """Чистый репозиторий (ветка main, плана нет): закоммичен `docs/DECISIONS.md` = base и список слоёв."""
    repo = _init_repo(tmp_path / "adr", "main")
    _write(repo / ".claude" / "commit-layers.txt", "# layers\n" + "\n".join(LAYERS) + "\n")
    _write(repo / _DECISIONS, base)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _stage_decisions(repo: Path, text: str, path: str = _DECISIONS) -> None:
    _write(repo / path, text)
    _git(repo, "add", path)


def _adr_message(*decisions: str, subject: str = _ADR_SUBJECT) -> str:
    lines = [_WHY, "Layer: docs", *decisions]
    return subject + "\n\n" + "\n".join(lines) + "\n"


def _add_line(*decisions: str) -> list[str]:
    return [f"Decision: {d}" for d in decisions]


@pytest.mark.parametrize("copy", list(COPIES))
def test_added_adr_without_decision_warns_with_ready_line(copy: str, tmp_path: Path) -> None:
    repo = _adr_repo(tmp_path)
    _stage_decisions(repo, _ADR_BASE + "\n## ADR-AB-002: новое\n\nТекст.\n\n## ADR-AB-003: ещё новое\n\nТекст.\n")

    rc, err = _run_validator(COPIES[copy], repo, _adr_message())

    assert rc == 0, err
    assert "`Decision: ADR-AB-002`" in err and "`Decision: ADR-AB-003`" in err, err
    assert "ADR-AB-001" not in err, err  # старый заголовок дифф не затронул
    assert err.count("this commit adds") == 2, err  # по строке на id

    rc_ok, err_ok = _run_validator(COPIES[copy], repo, _adr_message(*_add_line("ADR-AB-002", "ADR-AB-003")))
    assert rc_ok == 0 and err_ok == "", err_ok  # с `Decision:` на оба id - тишина

    rc_one, err_one = _run_validator(COPIES[copy], repo, _adr_message(*_add_line("ADR-AB-002")))
    assert rc_one == 0 and "`Decision: ADR-AB-003`" in err_one and "ADR-AB-002" not in err_one, err_one


@pytest.mark.parametrize("copy", list(COPIES))
def test_decision_optional_without_adr_diff(copy: str, tmp_path: Path) -> None:
    repo = _adr_repo(tmp_path)
    _write(repo / "notes.txt", "заметка\n")
    _git(repo, "add", "notes.txt")

    rc, err = _run_validator(COPIES[copy], repo, _adr_message("Decision: ADR-AB-001"))

    assert rc == 0, err
    assert "Unknown trailer" not in err, err
    assert "not found in the index" not in err, err

    rc_none, err_none = _run_validator(COPIES[copy], repo, _adr_message())
    assert rc_none == 0 and "Decision" not in err_none, err_none  # без диффа ADR трейлер не обязателен


@pytest.mark.parametrize("copy", list(COPIES))
def test_decision_unknown_id_is_phase3_warning(copy: str, tmp_path: Path) -> None:
    repo = _adr_repo(tmp_path)
    _write(repo / "notes.txt", "заметка\n")
    _git(repo, "add", "notes.txt")
    message = _adr_message("Decision: ADR-AB-009")

    rc, err = _run_validator(COPIES[copy], repo, message)
    assert rc == 0, err
    assert "Decision: ADR-AB-009 not found in the index" in err, err

    strict = _strict_copy(COPIES[copy], tmp_path / "strict")
    rc_strict, err_strict = _run_validator(strict, repo, message)
    assert rc_strict == 1, err_strict
    assert "Decision: ADR-AB-009 not found in the index" in err_strict, err_strict


@pytest.mark.parametrize("copy", list(COPIES))
def test_added_adr_warning_stays_warning_under_strict(copy: str, tmp_path: Path) -> None:
    # Страж: зелёный и до правки (правила нет), и после; красный, если шаг по ошибке пойдёт через _phase3.
    repo = _adr_repo(tmp_path)
    _stage_decisions(repo, _ADR_BASE + "\n## ADR-AB-002: новое\n\nТекст.\n")

    strict = _strict_copy(COPIES[copy], tmp_path / "strict")
    rc, err = _run_validator(strict, repo, _adr_message())

    assert rc == 0, err


@pytest.mark.parametrize("copy", list(COPIES))
def test_header_edit_is_not_a_new_adr(copy: str, tmp_path: Path) -> None:
    repo = _adr_repo(tmp_path)
    # ADR-AB-001: правка заголовка (id и в `-`, и в `+`) - не новый ADR; ADR-AB-002 - новый.
    _stage_decisions(repo, _ADR_BASE.replace("старое решение", "переименованное решение") + "\n## ADR-AB-002: новое\n")

    rc, err = _run_validator(COPIES[copy], repo, _adr_message())

    assert rc == 0, err
    assert "`Decision: ADR-AB-002`" in err, err
    assert "ADR-AB-001" not in err, err


@pytest.mark.parametrize("copy", list(COPIES))
def test_h3_adr_heading_counts(copy: str, tmp_path: Path) -> None:
    repo = _adr_repo(tmp_path)
    _stage_decisions(repo, _ADR_BASE + "\n### ADR-PM-059: решение третьего уровня\n\nТекст.\n")

    rc, err = _run_validator(COPIES[copy], repo, _adr_message())

    assert rc == 0, err
    assert "`Decision: ADR-PM-059`" in err, err


@pytest.mark.parametrize("copy", list(COPIES))
def test_merge_commit_skips_added_adr_rule(copy: str, tmp_path: Path) -> None:
    repo = _adr_repo(tmp_path)
    _stage_decisions(repo, _ADR_BASE + "\n## ADR-AB-002: новое\n")

    rc_plain, err_plain = _run_validator(COPIES[copy], repo, _adr_message())
    rc_merge, err_merge = _run_validator(COPIES[copy], repo, _adr_message(subject="merge: слияние ветки"))

    assert rc_plain == 0 and "`Decision: ADR-AB-002`" in err_plain, err_plain
    assert rc_merge == 0, err_merge
    assert "Decision" not in err_merge, err_merge


@pytest.mark.parametrize("value", ["ADR-1, ADR-2", "ADR-AB-001, ADR-AB-002"])
@pytest.mark.parametrize("copy", list(COPIES))
def test_malformed_decision_value_is_not_echoed(copy: str, value: str, tmp_path: Path) -> None:
    # Второе значение начинается с правильного id: префиксное совпадение его бы пропустило, fullmatch - нет.
    repo = _adr_repo(tmp_path)

    rc, err = _run_validator(COPIES[copy], repo, _adr_message(f"Decision: {value}"))

    assert rc == 0, err
    assert _MALFORMED in err, err
    for token in value.split(", "):
        assert token not in err, err  # значение в вывод не попадает


# Дополнительные сторожа автора (сверх списка REDS лида).


@pytest.mark.parametrize("copy", list(COPIES))
def test_decision_for_adr_added_by_this_commit_is_accepted(copy: str, tmp_path: Path) -> None:
    repo = _adr_repo(tmp_path)
    _stage_decisions(repo, _ADR_BASE + "\n## ADR-AB-002: новое\n")

    rc, err = _run_validator(COPIES[copy], repo, _adr_message("Decision: ADR-AB-002"))

    assert rc == 0 and err == "", err


@pytest.mark.parametrize("copy", list(COPIES))
def test_decision_id_that_only_prefixes_an_indexed_id_is_not_found(copy: str, tmp_path: Path) -> None:
    repo = _adr_repo(tmp_path, base="# Решения\n\n## ADR-AB-0012: длинный номер\n")
    _write(repo / "notes.txt", "заметка\n")
    _git(repo, "add", "notes.txt")

    rc, err = _run_validator(COPIES[copy], repo, _adr_message("Decision: ADR-AB-001"))

    assert rc == 0, err
    assert "Decision: ADR-AB-001 not found in the index" in err, err


@pytest.mark.parametrize("copy", list(COPIES))
def test_adr_heading_outside_decisions_file_is_ignored(copy: str, tmp_path: Path) -> None:
    repo = _adr_repo(tmp_path)
    _stage_decisions(repo, "# Заметка\n\n## ADR-AB-002: не в DECISIONS\n", path="docs/notes.md")

    rc, err = _run_validator(COPIES[copy], repo, _adr_message())

    assert rc == 0 and "Decision" not in err, err


@pytest.mark.parametrize("copy", list(COPIES))
def test_decision_id_only_in_worktree_edit_is_not_in_the_index(copy: str, tmp_path: Path) -> None:
    # Дерево != индекс: заголовок ADR-AB-555 лежит только в неподготовленной правке рабочего дерева.
    # Коммит пути notes.txt (`git commit -F msg -- notes.txt`) его не берёт, значит, в индексе его нет.
    repo = _adr_repo(tmp_path)
    _write(repo / _DECISIONS, _ADR_BASE + "\n## ADR-AB-555: только в рабочем дереве\n")  # не git add
    _write(repo / "notes.txt", "заметка\n")
    _git(repo, "add", "notes.txt")

    rc, err = _run_validator(COPIES[copy], repo, _adr_message("Decision: ADR-AB-555"))

    assert rc == 0, err
    assert "Decision: ADR-AB-555 not found in the index" in err, err
