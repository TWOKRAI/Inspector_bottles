"""Task 1.2 (commit-mechanism) — приёмка: хуки правки живы на Windows и видят то же, что pre-commit.

Контракт (из ТЗ `plans/2026-10-03_commit-mechanism/tasks/1.2.md`, ред. 4, не из реализации):
  * `rev` ruff в `.pre-commit-config.yaml` и в seed-шаблоне равен версии ruff из `uv.lock`;
  * `autoformat-python.sh` на Windows доходит до ruff (дефект `\\r` в разборе входа),
    ищет ruff в `.venv` корня репозитория раньше PATH, идёт в порядке pre-commit
    (`check --fix --unfixable F401` -> `format` -> `check --no-fix`), печатает остаток
    ruff в JSON `hookSpecificOutput.additionalContext` на stdout, всегда rc=0;
  * новый `autofix-text.sh` для не-Python файлов повторяет pre-commit-hooks v5.0.0
    (`trailing-whitespace --markdown-linebreak-ext=md`, затем `end-of-file-fixer`)
    байт в байт и пропускает: `.py`, `docs/claude/frozen/`, `robot/`, двоичные, > 1 MiB,
    файлы вне ближайшего репозитория внутри `CLAUDE_PROJECT_DIR`, symlink;
  * `autofix-text.sh` зарегистрирован в `plugin.json` и `settings.json` вторым элементом
    той же группы `Edit|Write`, что и `doc-size-guard.sh`.

Тесты:
  1  разбор `uv.lock` (tomllib) и обоих конфигов;
  2, 3  JSON с остатком ruff (E501) и тишина на чистом файле — пара: тест 3 зелёный на
        старом хуке и смысла вне пары с тестом 2 не имеет;
  4  порядок как в pre-commit: пограничная фикстура (вызов ровно 121 символ с `f"x"`) после
     хука проходит настоящие `pre-commit run ruff` и `ruff-format` без правок;
  5  только Windows: прямой сторож дефекта `\\r`, без pre-commit и сети;
  6  ruff берётся из `.venv` репозитория, а не из PATH, где лежит подмена (по эффекту);
  7  оракул: хук vs настоящие `pre-commit run trailing-whitespace` / `end-of-file-fixer`;
  8  пропуски (`.py`, frozen, robot, двоичный, > 1 MiB, второй репозиторий, вложенный
     репозиторий, symlink) + положительный контроль в том же прогоне;
  9  регистрация.

Запуск хука: `bash` — Git Bash (не из System32/WindowsApps, иначе WSL); хук по абсолютному пути
из проверяемого дерева; вход — `json.dumps` на stdin; cwd = временный репо;
`CLAUDE_PROJECT_DIR` = временный репо; PATH = `dirname(sys.executable)` + PATH; без
`CLAUDE_PYTHON_BIN`; HOME/PRE_COMMIT_HOME не подменяются. Git изолирован от глобального
конфига (GIT_CONFIG_GLOBAL/NOSYSTEM), `GIT_*` вычищены. Вывод процессов — во временные ФАЙЛЫ,
`timeout=120`. Нет pre-commit -> FAIL, не skip. CRLF -> LF только при копировании конфигов.
Тесты 4 и 7 после смены `rev` в первый раз требуют сети (ruff v0.15.14 в кэше pre-commit может
отсутствовать): сетевой сбой — не регрессия.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import warnings
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]

PROJECT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
SEED_TEMPLATE = REPO_ROOT / ".claude" / "plugins" / "lang-python" / "templates" / "pre-commit-config.template.yaml"
UV_LOCK = REPO_ROOT / "uv.lock"
AUTOFORMAT_HOOK = REPO_ROOT / ".claude" / "plugins" / "lang-python" / "hooks" / "autoformat-python.sh"
AUTOFIX_TEXT_HOOK = REPO_ROOT / ".claude" / "plugins" / "core" / "hooks" / "autofix-text.sh"
PYTHON_BIN_SH = REPO_ROOT / ".claude" / "plugins" / "core" / "hooks" / "_lib" / "python-bin.sh"
PLUGIN_JSON = REPO_ROOT / ".claude" / "plugins" / "core" / ".claude-plugin" / "plugin.json"
SETTINGS_JSON = REPO_ROOT / ".claude" / "settings.json"

TIMEOUT = 120
IS_WINDOWS = sys.platform == "win32"

_SETTINGS_AUTOFIX_COMMAND = 'bash "${CLAUDE_PROJECT_DIR}"/.claude/plugins/core/hooks/autofix-text.sh'
_PLUGIN_AUTOFIX_COMMAND = "${CLAUDE_PLUGIN_ROOT}/hooks/autofix-text.sh"


# --------------------------------------------------------------------------- process helpers


def _clean_env() -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items() if not k.startswith("GIT_") and k not in ("PRE_COMMIT", "CLAUDE_PYTHON_BIN")
    }
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run_raw(
    cmd: list[str],
    cwd: Path,
    env: dict[str, str] | None = None,
    stdin_data: bytes | None = None,
) -> tuple[int, bytes, bytes]:
    """Запуск с выводом во временные файлы (не pipe): таймаут не виснет на внуках."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err, tempfile.TemporaryFile() as inp:
        if stdin_data is not None:
            inp.write(stdin_data)
            inp.seek(0)
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=env if env is not None else _clean_env(),
            stdin=inp if stdin_data is not None else subprocess.DEVNULL,
            stdout=out,
            stderr=err,
            timeout=TIMEOUT,
            check=False,
        )
        out.seek(0)
        err.seek(0)
        return proc.returncode, out.read(), err.read()


def _run(cmd: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    rc, out, err = _run_raw(cmd, cwd, env)
    return subprocess.CompletedProcess(cmd, rc, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"))


def _git_ok(repo: Path, *args: str) -> str:
    proc = _run(["git", *args], repo)
    assert proc.returncode == 0, f"git {' '.join(args)} rc={proc.returncode}\n{proc.stdout}\n{proc.stderr}"
    return proc.stdout


def _find_git_bash() -> str:
    """`bash` из PATH, но не WSL-заглушка (System32 / WindowsApps)."""
    candidates: list[str] = []
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        for name in ("bash.exe", "bash"):
            candidate = Path(directory) / name
            if directory and candidate.is_file():
                candidates.append(str(candidate))
    for candidate in candidates:
        low = candidate.lower().replace("/", "\\")
        if "\\windows\\system32\\" in low or "\\windowsapps\\" in low:
            continue
        return candidate
    pytest.fail(f"no Git Bash on PATH (only WSL/none): {candidates}")


def _hook_env(repo: Path, first_in_path: Path | None = None) -> dict[str, str]:
    env = _clean_env()
    parts = [str(Path(sys.executable).parent), env.get("PATH", "")]
    if first_in_path is not None:
        parts.insert(0, str(first_in_path))
    env["PATH"] = os.pathsep.join(parts)
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    return env


def _run_hook(
    hook: Path,
    repo: Path,
    file_path: Path,
    *,
    tool_name: str = "Edit",
    first_in_path: Path | None = None,
) -> tuple[int, str, str]:
    payload = json.dumps({"tool_name": tool_name, "tool_input": {"file_path": str(file_path)}})
    rc, out, err = _run_raw(
        [_find_git_bash(), str(hook)],
        repo,
        _hook_env(repo, first_in_path),
        stdin_data=payload.encode("utf-8"),
    )
    return rc, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


def _copy_real(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes().replace(b"\r\n", b"\n"))


def _init_repo(path: Path, *, configs: bool = False) -> Path:
    """`git init -b main` явно (pytest tmp может лежать внутри чужого репозитория)."""
    path.mkdir(parents=True, exist_ok=True)
    _git_ok(path, "init", "-q", "-b", "main")
    _git_ok(path, "config", "user.name", "Tester")
    _git_ok(path, "config", "user.email", "tester@example.invalid")
    _git_ok(path, "config", "core.autocrlf", "false")
    _git_ok(path, "config", "commit.gpgsign", "false")
    if configs:
        _copy_real(PROJECT_CONFIG, path / ".pre-commit-config.yaml")
        _copy_real(REPO_ROOT / "pyproject.toml", path / "pyproject.toml")
    return path


@pytest.fixture(scope="module")
def _pre_commit_available() -> None:
    try:
        rc, out, err = _run_raw([sys.executable, "-m", "pre_commit", "--version"], REPO_ROOT)
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover - environment
        pytest.fail(f"pre-commit is not runnable: {exc!r}")
    if rc != 0:
        pytest.fail(f"pre-commit is not runnable (rc={rc}): {out!r}{err!r}")


def _ruff_concise(repo: Path, name: str) -> subprocess.CompletedProcess[str]:
    return _run(
        [sys.executable, "-m", "ruff", "check", name, "--no-fix", "--output-format", "concise", "--quiet"], repo
    )


def _hook_ruff_rev(config: Path) -> str:
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    revs = [r["rev"] for r in data["repos"] if "ruff-pre-commit" in r["repo"]]
    assert len(revs) == 1, f"expected one ruff-pre-commit repo in {config.name}, got {revs}"
    return revs[0].removeprefix("v")


# --------------------------------------------------------------------------- 1: rev == lockfile


def test_ruff_rev_matches_lockfile() -> None:
    lock = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    versions = [p["version"] for p in lock["package"] if p["name"] == "ruff"]
    assert len(versions) == 1, f"expected exactly one ruff package in uv.lock, got {versions}"
    lock_version = versions[0]
    assert _hook_ruff_rev(PROJECT_CONFIG) == lock_version, "project config rev != uv.lock"
    assert _hook_ruff_rev(SEED_TEMPLATE) == lock_version, "seed template rev != uv.lock"


# --------------------------------------------------------------------------- 2, 3: autoformat output


def test_autoformat_reports_e501_in_additional_context(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", configs=True)
    target = repo / "a.py"
    target.write_bytes(b'x = "' + b"a" * 130 + b'"\n')

    precheck = _ruff_concise(repo, "a.py")  # без E501 на фикстуре тест ничего не доказывает
    assert precheck.returncode == 1 and "E501" in precheck.stdout, (
        f"fixture has no E501\n{precheck.stdout}{precheck.stderr}"
    )

    rc, out, err = _run_hook(AUTOFORMAT_HOOK, repo, target, tool_name="Write")

    assert rc == 0, f"hook rc={rc}\n{err}"
    assert out.strip(), f"hook printed nothing on stdout (stderr: {err!r})"
    context = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "a.py" in context
    assert ":1:121:" in context
    assert "E501" in context


def test_autoformat_silent_when_clean(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", configs=True)
    target = repo / "a.py"
    target.write_bytes(b"x = 1\n")

    rc, out, err = _run_hook(AUTOFORMAT_HOOK, repo, target, tool_name="Write")

    assert rc == 0, f"hook rc={rc}\n{err}"
    assert out == ""


# --------------------------------------------------------------------------- 4: same order as pre-commit


def _boundary_fixture() -> bytes:
    """Вызов ровно 121 символ с `f"x"` (после снятия `f` — 120), определения выше, неформатированный код."""
    prefix = "print(aaa, bbb, "
    name = "n" * (121 - len(prefix) - len(', f"x")'))
    source = "aaa = 1\nbbb = 2\nx=1;y=2\n" + name + " = 3\n" + prefix + name + ', f"x")\n'
    assert len(source.splitlines()[-1]) == 121
    return source.encode("utf-8")


@pytest.mark.usefixtures("_pre_commit_available")
def test_autoformat_output_passes_precommit_ruff_hooks(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", configs=True)
    target = repo / "a.py"
    target.write_bytes(_boundary_fixture())

    rc, _out, err = _run_hook(AUTOFORMAT_HOOK, repo, target, tool_name="Write")
    assert rc == 0, f"hook rc={rc}\n{err}"

    _git_ok(repo, "add", "a.py")
    after_hook = target.read_bytes()
    ruff = _run([sys.executable, "-m", "pre_commit", "run", "ruff", "--files", "a.py"], repo)
    fmt = _run([sys.executable, "-m", "pre_commit", "run", "ruff-format", "--files", "a.py"], repo)

    assert ruff.returncode == 0, f"pre-commit ruff rc={ruff.returncode}\n{ruff.stdout}{ruff.stderr}"
    assert fmt.returncode == 0, f"pre-commit ruff-format rc={fmt.returncode}\n{fmt.stdout}{fmt.stderr}"
    assert target.read_bytes() == after_hook, "pre-commit rewrote the file the hook left"


# --------------------------------------------------------------------------- 5: CRLF from python (Windows)


@pytest.mark.skipif(sys.platform != "win32", reason="defect is Windows-only: python prints CRLF")
def test_autoformat_works_with_crlf_python_output(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", configs=True)
    # достижимость: на этой машине $PY из python-bin.sh действительно печатает CRLF
    rc, out, err = _run_raw(
        [_find_git_bash(), "-c", 'source "$1"; $PY -c "print(1)"', "_", PYTHON_BIN_SH.as_posix()],
        repo,
        _hook_env(repo),
    )
    assert out == b"1\r\n", f"reachability probe: rc={rc} out={out!r} err={err!r}"

    target = repo / "a.py"
    target.write_bytes(b"x=1;y=2\n")
    hook_rc, _hook_out, hook_err = _run_hook(AUTOFORMAT_HOOK, repo, target, tool_name="Write")

    assert hook_rc == 0, f"hook rc={hook_rc}\n{hook_err}"
    assert target.read_bytes() == b"x = 1\ny = 2\n"


# --------------------------------------------------------------------------- 6: venv ruff beats PATH


def test_autoformat_prefers_venv_ruff_over_path(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", configs=True)
    exe = "ruff.exe" if IS_WINDOWS else "ruff"
    real_ruff = Path(sys.executable).parent / exe
    if not real_ruff.is_file():
        found = shutil.which("ruff")
        assert found, "no real ruff to copy"
        real_ruff = Path(found)
    venv_bin = repo / ".venv" / ("Scripts" if IS_WINDOWS else "bin")
    venv_bin.mkdir(parents=True)
    shutil.copy(real_ruff, venv_bin / exe)

    fake_dir = tmp_path / "fakebin"
    fake_dir.mkdir()
    shutil.copy(sys.executable, fake_dir / exe)  # на PATH первый "ruff", который ruff не умеет

    target = repo / "a.py"
    target.write_bytes(b"x=1;y=2\n")
    rc, _out, err = _run_hook(AUTOFORMAT_HOOK, repo, target, tool_name="Write", first_in_path=fake_dir)

    assert rc == 0, f"hook rc={rc}\n{err}"
    assert target.read_bytes() == b"x = 1\ny = 2\n"


def test_autoformat_respects_force_exclude(tmp_path: Path) -> None:
    """`extend-exclude = [".claude/"]` из настоящего pyproject.toml действует на явно переданный файл."""
    repo = _init_repo(tmp_path / "repo", configs=True)
    target = repo / ".claude" / "x.py"
    target.parent.mkdir()
    original = b'x=1;y=2\nx = "' + b"a" * 130 + b'"\n'
    target.write_bytes(original)

    rc, out, err = _run_hook(AUTOFORMAT_HOOK, repo, target, tool_name="Write")

    assert rc == 0, f"hook rc={rc}\n{err}"
    assert target.read_bytes() == original
    assert out == "", f"hook reported on an excluded file: {out!r}"


def test_autoformat_finds_main_venv_from_worktree(tmp_path: Path) -> None:
    """CLAUDE_PROJECT_DIR = worktree без своего .venv: ruff берётся из .venv главного дерева, не из PATH."""
    repo = _init_repo(tmp_path / "repo", configs=True)
    exe = "ruff.exe" if IS_WINDOWS else "ruff"
    real_ruff = Path(sys.executable).parent / exe
    if not real_ruff.is_file():
        found = shutil.which("ruff")
        assert found, "no real ruff to copy"
        real_ruff = Path(found)
    venv_bin = repo / ".venv" / ("Scripts" if IS_WINDOWS else "bin")
    venv_bin.mkdir(parents=True)
    shutil.copy(real_ruff, venv_bin / exe)
    _git_ok(repo, "add", "pyproject.toml")
    _git_ok(repo, "commit", "-q", "-m", "init")
    worktree = tmp_path / "wt"
    _git_ok(repo, "worktree", "add", "-q", str(worktree), "-b", "wt-branch")
    assert not (worktree / ".venv").exists(), "the worktree must not have its own .venv"

    fake_dir = tmp_path / "fakebin"
    fake_dir.mkdir()
    shutil.copy(sys.executable, fake_dir / exe)  # на PATH первый "ruff", который ruff не умеет

    target = worktree / "w.py"
    target.write_bytes(b"x=1;y=2\n")
    rc, _out, err = _run_hook(AUTOFORMAT_HOOK, worktree, target, tool_name="Write", first_in_path=fake_dir)

    assert rc == 0, f"hook rc={rc}\n{err}"
    assert target.read_bytes() == b"x = 1\ny = 2\n"


# --------------------------------------------------------------------------- 7: oracle for autofix-text

_ORACLE_CASES: list[tuple[str, bytes]] = [
    ("c00.txt", b"a \n"),
    ("c01.txt", b"a\t\n"),
    ("c02.md", b"a  \n"),
    ("c03.txt", b"a  \n"),
    ("c04.txt", b"a\r\nb"),
    ("c05.txt", b"a\n\r\n"),
    ("c06.md", b"\t  \n"),
    ("c07.txt", b"a\x0b\n"),
    ("c08.MD", b"a  \n"),
    ("c09.markdown", b"a  \n"),
    ("c10.txt", b"a\xc2\xa0\n"),
    ("c11.txt", b"a  \r"),
    ("c12.txt", b"\xef\xbb\xbfa \n"),
    ("c13.txt", b""),
    ("c14.txt", b"\n"),
    ("c15.txt", b"a\n\n\n"),
]
# Литералы ожидаемого результата рядом с оракулом (проверяют сам оракул).
_ORACLE_LITERALS = {
    "c04.txt": b"a\r\nb\n",
    "c06.md": b"",
    "c09.markdown": b"a\n",
}


@pytest.mark.usefixtures("_pre_commit_available")
def test_autofix_text_matches_precommit_fixers(tmp_path: Path) -> None:
    oracle_repo = _init_repo(tmp_path / "oracle", configs=True)
    hook_repo = _init_repo(tmp_path / "hook", configs=True)
    for name, data in _ORACLE_CASES:
        (oracle_repo / name).write_bytes(data)
        (hook_repo / name).write_bytes(data)
    names = [name for name, _ in _ORACLE_CASES]
    _git_ok(oracle_repo, "add", *names)
    # pre-commit run принимает ОДИН id хука; код возврата 1 = "файлы изменены" — не ошибка
    for hook_id in ("trailing-whitespace", "end-of-file-fixer"):
        proc = _run([sys.executable, "-m", "pre_commit", "run", hook_id, "--files", *names], oracle_repo)
        assert "Traceback" not in proc.stdout + proc.stderr, f"{hook_id} crashed\n{proc.stdout}{proc.stderr}"

    oracle = {name: (oracle_repo / name).read_bytes() for name in names}
    for name, literal in _ORACLE_LITERALS.items():
        assert oracle[name] == literal, f"oracle itself disagrees with the literal for {name}: {oracle[name]!r}"

    problems: list[str] = []
    for name in names:
        rc, out, err = _run_hook(AUTOFIX_TEXT_HOOK, hook_repo, hook_repo / name)
        got = (hook_repo / name).read_bytes()
        if rc != 0 or out != "":
            problems.append(f"{name}: hook rc={rc} stdout={out!r} stderr={err[:200]!r}")
        if got != oracle[name]:
            original = dict(_ORACLE_CASES)[name]
            problems.append(f"{name}: input={original!r} hook={got!r} pre-commit={oracle[name]!r}")
    assert problems == [], "\n".join(problems)


# --------------------------------------------------------------------------- 8: skips


def _snapshot(path: Path) -> tuple[bytes, int]:
    return path.read_bytes(), path.stat().st_mtime_ns


def test_autofix_text_skips_py_frozen_robot_binary_outside(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    trailing = b"a \n"

    # положительный контроль: обычный .md обязан измениться, иначе пропуски ничего не доказывают
    control = repo / "ctrl.md"
    control.write_bytes(trailing)
    rc, out, err = _run_hook(AUTOFIX_TEXT_HOOK, repo, control)
    assert rc == 0, f"control: hook rc={rc}\n{err}"
    assert control.read_bytes() == b"a\n", f"control .md was not fixed: {control.read_bytes()!r}"

    skipped: dict[str, Path] = {}

    def make(rel: str, data: bytes) -> Path:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        skipped[rel] = path
        return path

    make("skip.py", trailing)
    make("docs/claude/frozen/f.md", trailing)
    make("robot/r.md", trailing)
    make("bin.txt", b"a \n\x00\x01\n")
    make("big.txt", trailing + b"x" * (1024 * 1024 + 1 - len(trailing)))  # ровно 1 MiB + 1 байт

    other = _init_repo(tmp_path / "other")  # ВТОРОЙ репозиторий: "вне CLAUDE_PROJECT_DIR"
    outside = other / "o.md"
    outside.write_bytes(trailing)
    skipped["<other repo>/o.md"] = outside

    nested = repo / "nested"
    _init_repo(nested)  # свой .git внутри CLAUDE_PROJECT_DIR: ближайший .git -> robot/ относительно него
    make("nested/robot/z.md", trailing)

    link = repo / "link.md"
    link_target = repo / "link_target.md"
    link_target.write_bytes(trailing)
    symlink_made = True
    try:
        os.symlink(link_target, link)
    except OSError as exc:
        symlink_made = False
        warnings.warn(f"symlink case skipped (cannot create symlink here): {exc!r}", stacklevel=1)

    before = {rel: _snapshot(path) for rel, path in skipped.items()}
    if symlink_made:
        before["link.md -> link_target.md"] = _snapshot(link_target)
        skipped["link.md -> link_target.md"] = link_target

    problems: list[str] = []
    runs = [(rel, path) for rel, path in skipped.items() if rel != "link.md -> link_target.md"]
    if symlink_made:
        runs.append(("link.md -> link_target.md", link))
    for rel, path in runs:
        rc, out, err = _run_hook(AUTOFIX_TEXT_HOOK, repo, path)
        if rc != 0 or out != "":
            problems.append(f"{rel}: hook rc={rc} stdout={out!r} stderr={err[:200]!r}")
    for rel, path in skipped.items():
        if _snapshot(path) != before[rel]:
            problems.append(f"{rel}: bytes or mtime changed ({before[rel][0][:20]!r} -> {path.read_bytes()[:20]!r})")

    assert problems == [], "\n".join(problems)


# --------------------------------------------------------------------------- 9: registration


def _group_with_guard(path: Path) -> dict:
    groups = json.loads(path.read_text(encoding="utf-8"))["hooks"]["PostToolUse"]
    found = [g for g in groups if any("doc-size-guard.sh" in h.get("command", "") for h in g.get("hooks", []))]
    assert len(found) == 1, (
        f"expected exactly one PostToolUse group with doc-size-guard.sh in {path.name}, got {len(found)}"
    )
    return found[0]


def test_text_hook_registered_in_both_places() -> None:
    settings_group = _group_with_guard(SETTINGS_JSON)
    plugin_group = _group_with_guard(PLUGIN_JSON)

    assert settings_group["matcher"] == "Edit|Write"
    assert plugin_group["matcher"] == "Edit|Write"
    settings_hooks = settings_group["hooks"]
    plugin_hooks = plugin_group["hooks"]
    assert len(settings_hooks) >= 2 and len(plugin_hooks) >= 2, "autofix-text.sh is not the second element"
    assert settings_hooks[1]["command"] == _SETTINGS_AUTOFIX_COMMAND
    assert settings_hooks[1]["type"] == "command"
    assert settings_hooks[1]["timeout"] == 10
    assert plugin_hooks[1]["command"] == _PLUGIN_AUTOFIX_COMMAND
    assert plugin_hooks[1]["type"] == "command"
