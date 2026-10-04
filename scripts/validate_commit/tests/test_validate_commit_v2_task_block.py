"""Task 2.1 ред. 6 (commit-mechanism) — приёмка трейлера `Task:` и «трейлеры одним блоком» (T1-T11).

Контракт (из ТЗ `plans/2026-10-03_commit-mechanism/tasks/2.1.md`, секция «Ред. 6», DESIGN (i)-(l) и таблица кодов,
не из реализации; реализации на момент написания нет):
  * `Task:` — известный трейлер, необязателен в обоих режимах; значение — один id на строку по грамматике
    `<slug>#<id>`; не по грамматике — W-TASK-FORMAT (подстрока `Task is not <slug>#<id>`),
    WARN при `STRICT = False`, ERR (rc 1) при `STRICT = True`;
  * один блок: оракул — `git interpret-trailers --parse` на тексте без строк `#`; известные ключи сообщения, которых git
    не видит, — W-TRAILERS-SPLIT (подстрока `trailers git does not see`, дальше имена ключей), WARN -> ERR в фазе 3;
    правило одно для обычных коммитов и `merge:`.

Метод — как в `test_validate_commit_v2.py`: валидатор запускается ПОДПРОЦЕССОМ (`python <путь> -`, сообщение на
stdin) из временного git-репозитория на ветке, которая разрешается в план. Колонка `STRICT = True` — копия валидатора
с текстовой заменой `STRICT = False` -> `STRICT = True` (ровно одна замена, иначе тест падает). Обе копии валидатора
проходят всю таблицу. Ожидаемые значения — литералы из ТЗ. T11 зовёт `git interpret-trailers --parse` сам, не
валидатор, и сверяет результат с ЛИТЕРАЛЬНЫМ набором ключей, которых git не видит (не вычисляет его из валидатора).

Допущения, которых в ТЗ нет дословно (если одно из них неверно — это находка о ТЗ, а не о тесте):
  * список ключей W-TRAILERS-SPLIT идёт на той же строке stderr после подстроки `trailers git does not see`;
  * ключи, которые git видит, в этот список не попадают (T8: `Layer`/`Refs` не перечислены).
"""

from __future__ import annotations

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

TIMEOUT = 60
BRANCH = "feat/commit-mechanism"
PLAN = "plans/2026-10-03_commit-mechanism/plan.md"
LAYERS = ["framework", "services", "plugins", "prototype", "docs", "scripts", "tests", "infra", "mixed"]

_SPLIT = "trailers git does not see"
_TASK_FORMAT = "Task is not <slug>#<id>"
_WHY = "Why: проверка трейлера Task и единого блока трейлеров"
_LAYER = "Layer: docs"
_REFS = f"Refs: {PLAN}"
_CAB = "Co-Authored-By: Claude <noreply@anthropic.com>"
_BLOCK = f"{_WHY}\n{_LAYER}\n{_REFS}\n"  # «блок» из ТЗ: Why, Layer, Refs подряд
_TASK_OK = "Task: commit-mechanism#2.1\n"

# Ключи, по которым T11 сверяет оракул: все четыре заведомо известные валидатору трейлера.
_KEYS = ("Why", "Layer", "Refs", "Task")


# --------------------------------------------------------------------------- process helpers


def _clean_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run_raw(cmd: list[str], cwd: Path, *, stdin_data: bytes | None = None) -> tuple[int, str, str]:
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err, tempfile.TemporaryFile() as inp:
        if stdin_data is not None:
            inp.write(stdin_data)
            inp.seek(0)
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=_clean_env(),
            stdin=inp if stdin_data is not None else subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            timeout=TIMEOUT,
            check=False,
        )
        out.seek(0)
        err.seek(0)
        return proc.returncode, out.read().decode("utf-8", "replace"), err.read().decode("utf-8", "replace")


def _git(repo: Path, *args: str) -> str:
    rc, out, err = _run_raw(["git", *args], repo)
    assert rc == 0, f"git {' '.join(args)} rc={rc}\n{out}\n{err}"
    return out


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


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


@pytest.fixture(scope="module")
def v_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Ветка feat/commit-mechanism, план на диске, список слоёв — литерал из 9 строк."""
    repo = tmp_path_factory.mktemp("trepo")
    _git(repo, "init", "-q", "-b", BRANCH)
    _git(repo, "config", "user.name", "Tester")
    _git(repo, "config", "user.email", "tester@example.invalid")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "config", "commit.gpgsign", "false")
    _write(repo / ".claude" / "commit-layers.txt", "# layers\n" + "\n".join(LAYERS) + "\n")
    _write(repo / PLAN, f"# Plan: commit mechanism\n\n- **Ветка:** {BRANCH}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


# --------------------------------------------------------------------------- the T-table


@dataclass(frozen=True)
class Row:
    id: str
    message: str
    rc_true: int  # колонка STRICT = True
    # колонка STRICT = False: rc всегда 0 во всех строках ТЗ
    present: tuple[str, ...] = ()  # подстроки, обязанные быть в stderr
    absent: tuple[str, ...] = ()  # подстроки, которых быть не должно
    split_keys: tuple[str, ...] = ()  # ключи, обязанные стоять в списке W-TRAILERS-SPLIT (после подстроки)
    not_listed: tuple[str, ...] = ()  # ключи, которых в этом списке быть не должно (git их видит)
    git_missing: frozenset[str] = frozenset()  # T11: ключи из _KEYS, которых git НЕ видит (литерал)


def _msg(*parts: str, subject: str = "feat(x): y") -> str:
    return f"{subject}\n\n" + "".join(parts)


_T4_VALUES = [
    ("a", "2.1"),
    ("b", "commit-mechanism 2.1"),
    ("c", "Commit-Mechanism#2.1"),
    ("d", "x#2.1, x#2.2"),
    ("e", "x#"),
]
_T3_VALUES = [("a", "atlas#1.3a"), ("b", "atlas#K1.1"), ("c", "atlas#P1.1")]

ROWS: list[Row] = [
    # T1: блок + Task + CAB, без пустых строк
    Row("T1", _msg(_BLOCK, _TASK_OK, _CAB, "\n"), 0, absent=("WARNING",)),
    # T2: как T1, но пустая строка перед CAB
    Row(
        "T2",
        _msg(_BLOCK, _TASK_OK, "\n", _CAB, "\n"),
        1,
        present=(_SPLIT,),
        split_keys=("Why", "Layer", "Refs", "Task"),
        git_missing=frozenset({"Why", "Layer", "Refs", "Task"}),
    ),
    # T3: значения Task по одному в строке (по строке на значение + одно сообщение с тремя строками)
    *[
        Row(f"T3{suffix}", _msg(_BLOCK, f"Task: {value}\n", _CAB, "\n"), 0, absent=("WARNING",))
        for suffix, value in _T3_VALUES
    ],
    Row(
        "T3-multi",
        _msg(_BLOCK, *[f"Task: {value}\n" for _s, value in _T3_VALUES], _CAB, "\n"),
        0,
        absent=("WARNING",),
    ),
    # T4: значение не по грамматике — W-TASK-FORMAT
    *[
        Row(
            f"T4{suffix}",
            _msg(_BLOCK, f"Task: {value}\n", _CAB, "\n"),
            1,
            present=(_TASK_FORMAT,),
            absent=(_SPLIT,),
        )
        for suffix, value in _T4_VALUES
    ],
    # T5: блок + CAB без Task
    Row("T5", _msg(_BLOCK, _CAB, "\n"), 0, absent=("WARNING",)),
    # T6: Why с переносом БЕЗ отступа внутри блока — git не видит ни одного трейлера
    Row(
        "T6",
        _msg(f"{_WHY}\nпродолжение значения без отступа\n{_LAYER}\n{_REFS}\n", _CAB, "\n"),
        1,
        present=(_SPLIT,),
        split_keys=("Why", "Layer", "Refs"),
        git_missing=frozenset({"Why", "Layer", "Refs"}),
    ),
    # T7: Why с переносом и отступом в 4 пробела — git видит все, значение склеено
    Row(
        "T7",
        _msg(f"{_WHY}\n    продолжение значения с отступом\n{_LAYER}\n{_REFS}\n", _CAB, "\n"),
        0,
        absent=("WARNING",),
    ),
    # T8: Why сразу под темой отдельным абзацем, тело, затем Layer/Refs + CAB
    Row(
        "T8",
        _msg(f"{_WHY}\n\nтело сообщения в отдельном абзаце\n\n{_LAYER}\n{_REFS}\n", _CAB, "\n"),
        1,
        present=(_SPLIT,),
        split_keys=("Why",),
        not_listed=("Layer", "Refs"),
        git_missing=frozenset({"Why"}),
    ),
    # T9: merge: x + блок + CAB одним блоком / с пустой строкой перед CAB
    Row("T9-one-block", _msg(_BLOCK, _CAB, "\n", subject="merge: x"), 0, absent=("WARNING",)),
    Row(
        "T9-split",
        _msg(_BLOCK, "\n", _CAB, "\n", subject="merge: x"),
        1,
        present=(_SPLIT,),
        split_keys=("Why", "Layer", "Refs"),
        git_missing=frozenset({"Why", "Layer", "Refs"}),
    ),
    # T10: строка `# комментарий` внутри блока
    Row(
        "T10",
        _msg(f"{_WHY}\n{_LAYER}\n# комментарий внутри блока\n{_REFS}\n", _CAB, "\n"),
        0,
        absent=(_SPLIT,),
    ),
]

_PARAMS = [pytest.param(row, copy, id=f"{row.id}-{copy}") for row in ROWS for copy in COPIES]
_SPLIT_PARAMS = [pytest.param(row, copy, id=f"{row.id}-{copy}") for row in ROWS if row.split_keys for copy in COPIES]


def _split_listing(stderr: str) -> tuple[str, str]:
    """(хвост stderr от подстроки W-TRAILERS-SPLIT, остаток ЭТОЙ строки) — оба пустые, если подстроки нет."""
    index = stderr.find(_SPLIT)
    if index < 0:
        return "", ""
    tail = stderr[index:]
    return tail, tail.splitlines()[0]


# --------------------------------------------------------------------------- STRICT = False


@pytest.mark.parametrize(("row", "copy"), _PARAMS)
def test_t_table_non_strict(row: Row, copy: str, v_repo: Path) -> None:
    rc, err = _run_validator(COPIES[copy], v_repo, row.message)

    assert rc == 0, f"rc={rc}, expected 0\n{err}"
    for needle in row.present:
        assert needle in err, f"{needle!r} not in stderr:\n{err}"
    for needle in row.absent:
        assert needle not in err, f"{needle!r} unexpectedly in stderr:\n{err}"


@pytest.mark.parametrize(("row", "copy"), _SPLIT_PARAMS)
def test_split_warning_names_the_keys_git_does_not_see(row: Row, copy: str, v_repo: Path) -> None:
    _rc, err = _run_validator(COPIES[copy], v_repo, row.message)

    tail, _line = _split_listing(err)
    assert tail, f"{_SPLIT!r} not in stderr:\n{err}"
    for key in row.split_keys:
        assert key in tail, f"key {key!r} not listed after {_SPLIT!r}:\n{err}"


@pytest.mark.parametrize(("row", "copy"), [p for p in _SPLIT_PARAMS if p.values[0].not_listed])
def test_split_warning_does_not_list_keys_git_sees(row: Row, copy: str, v_repo: Path) -> None:
    _rc, err = _run_validator(COPIES[copy], v_repo, row.message)

    tail, line = _split_listing(err)
    assert tail, f"{_SPLIT!r} not in stderr (nothing to check the listing of):\n{err}"
    for key in row.not_listed:
        assert key not in line, f"key {key!r} git sees is wrongly listed on the split line: {line!r}"


# --------------------------------------------------------------------------- STRICT = True


@pytest.mark.parametrize(("row", "copy"), _PARAMS)
def test_t_table_strict(row: Row, copy: str, v_repo: Path, tmp_path: Path) -> None:
    validator = _strict_copy(COPIES[copy], tmp_path / "strict")

    rc, err = _run_validator(validator, v_repo, row.message)

    assert rc == row.rc_true, f"rc={rc}, expected {row.rc_true}\n{err}"


# --------------------------------------------------------------------------- T11: the oracle is git itself


def _git_trailer_keys(message: str, cwd: Path) -> set[str]:
    """Ключи, которые видит `git interpret-trailers --parse` на тексте без строк `#` (как оракул в DESIGN (j))."""
    text = "".join(line for line in message.splitlines(keepends=True) if not line.startswith("#"))
    rc, out, err = _run_raw(["git", "interpret-trailers", "--parse"], cwd, stdin_data=text.encode("utf-8"))
    assert rc == 0, f"git interpret-trailers rc={rc}\n{err}"
    keys: set[str] = set()
    for line in out.splitlines():
        if line[:1].isspace() or ":" not in line:  # продолжение значения
            continue
        keys.add(line.split(":", 1)[0].strip())
    return keys


@pytest.mark.parametrize("row", [pytest.param(row, id=row.id) for row in ROWS])
def test_t11_git_sees_exactly_the_known_keys_the_table_says(row: Row, v_repo: Path) -> None:
    present_in_message = {key for key in _KEYS if any(ln.startswith(f"{key}:") for ln in row.message.splitlines())}
    seen = _git_trailer_keys(row.message, v_repo)

    missing = present_in_message - seen
    assert missing == set(row.git_missing), (
        f"git does not see {sorted(missing)}, the table says {sorted(row.git_missing)}; git saw {sorted(seen)}"
    )
