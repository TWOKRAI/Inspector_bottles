"""Приёмочные тесты формы итога: `lint-result`, хвосты `pack`, находка `RESULT_FORM`, хук (Task 1.9a, RED до кода).

Purpose: слепые тесты по REDS «Tester» брифа plans/2026-10-04_atlas/tasks/1.9a.md: шаблон итога -> парсер -> 7 разделов,
    реальный итог k0#1.1 (линт и хвосты на пине 2bdd5aaa1), три формы раздела в хвостах `pack`, четыре сообщения
    линта и коды выхода CLI, находка RESULT_FORM в `--json` и `check`, хук PostToolUse `lint-result.sh`.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Ожидаемые значения — литералы из DESIGN и ACCEPTANCE брифа. Весь stdout сравнивается списком строк (`splitlines()`),
stderr — строкой. Вызовы main() идут через `atlas` conftest (поток с дедлайном), git и bash — через дедлайн/timeout.
Модули Атласа импортируются ВНУТРИ функций (store — только для подмены базы пина); проверяются CLI и хук.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.atlas.tests.conftest import GitRepo, RepoFactory, run_with_deadline

__all__: list[str] = []

_ROOT = Path(__file__).resolve().parents[3]
_PIN = "2bdd5aaa15094a30c26009fb5c6a15d9ded6f32f"
_PINNED = ("--ref", _PIN, "--main-ref", _PIN)
_REFS = ("--ref", "main", "--main-ref", "main")
_TEMPLATE = _ROOT / ".claude" / "plugins" / "dev" / "templates" / "task-result.md"
_HOOK = _ROOT / ".claude" / "plugins" / "dev" / "hooks" / "lint-result.sh"
_K0_RESULT = "plans/2026-10-07_k0-framework-quality/tasks/1.1.result.md"

_REQUIRED = ("Сделано", "Осталось", "Не проверено", "Файлы", "SHA", "Инъекции", "Кому передано")
_NEXT_BRIEF = "Для следующего брифа"

# тело абзаца «**Не проверено:**» (стр. 12 итога k0#1.1 на пине) целиком: текст после маркера и пробела
_K0_UNCHECKED = (
    "I5: RED 3 тоже зовёт `getattr` — прогноз не учёл. `*args/**kwargs` в RED 3 допустимы без default "
    "(шире DESIGN 5). Ключи `_IFACE_PARAMS` не сверены с `_MEMBERS` (nit; в 1.4). RED 7 требует deepcopy. "
    "`process_module/tests` целиком не гонял (О3). Откат инъекций — записью исходного текста, не Edit. "
    "Layer: test (в `commit-layers.txt` — `tests`; бриф — `framework`)."
)

_INJECTIONS = (
    "## Инъекции\n| инъекция | предсказано красных | наблюдалось | тест |\n|---|---|---|---|\n| нет | 0 | 0 | — |\n\n"
)
_GOOD_CHUNKS: dict[str, str] = {
    "Сделано": "## Сделано\n- сделано\n\n",
    "Осталось": "## Осталось\n- нет\n\n",
    "Не проверено": "## Не проверено\n- не гонял Windows\n\n",
    "Файлы": "## Файлы\n- a.py — правка\n\n",
    "SHA": "## SHA\n- abc1234 тема\n\n",
    "Инъекции": _INJECTIONS,
    "Кому передано": "## Кому передано\n- лиду\n",
}


def _result_text(**override: str | None) -> str:
    """Итог из 7 разделов; override[имя с _ вместо пробела] = сырой текст раздела или None (раздела нет)."""
    parts = ["# Task 1.1 — итог\n\n"]
    for name in _REQUIRED:
        key = name.replace(" ", "_")
        chunk = override.get(key, _GOOD_CHUNKS[name]) if key in override else _GOOD_CHUNKS[name]
        if chunk is not None:
            parts.append(chunk)
    return "".join(parts)


GOOD_RESULT = _result_text()
BAD_RESULT = _result_text(Осталось=None, Файлы=None)  # нет «## Осталось» и «## Файлы»


def _outside_git(tmp_path: Path, mp: pytest.MonkeyPatch) -> Path:
    """Каталог вне git-репо: потолок поиска .git — родитель; предусловие проверяется утверждением."""
    mp.setenv("GIT_CEILING_DIRECTORIES", tmp_path.parent.as_posix())
    outside = tmp_path / "outside"
    outside.mkdir()
    proc = run_with_deadline(
        lambda: subprocess.run(
            ["git", "-C", str(outside), "rev-parse", "--show-toplevel"], capture_output=True, check=False
        )
    )
    assert proc.returncode != 0, "предусловие: каталог теста внутри git-репо"
    return outside


# ---------------------------------------------------------------- 1. шаблон -> парсер -> 7 разделов


def _template_block() -> list[str]:
    lines = _TEMPLATE.read_text(encoding="utf-8").splitlines()
    start = lines.index("````markdown")
    end = lines.index("````", start + 1)
    return lines[start + 1 : end]


def test_template_parses_to_seven_required_sections(
    tmp_path: Path, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    block = _template_block()
    for name in (*_REQUIRED, _NEXT_BRIEF):
        assert f"## {name}" in block, name
    outside = _outside_git(tmp_path, monkeypatch)
    (outside / "template.result.md").write_text("\n".join(block) + "\n", encoding="utf-8")
    res = atlas(GitRepo(outside), "lint-result", "template.result.md")
    assert (res.code, res.out.splitlines(), res.err) == (0, ["lint-result: нарушений 0"], "")


# ---------------------------------------------------------------- 2. реальный итог k0#1.1


def test_lint_result_on_k0_1_1_lists_missing_sections(atlas: Any) -> None:
    res = atlas(GitRepo(_ROOT), "lint-result", _K0_RESULT)
    assert res.code == 1, res.out + res.err
    assert res.err == ""
    assert res.out.splitlines() == [
        "  раздел «Сделано» абзацем «**Сделано:**», нужен «## Сделано»",
        "  нет раздела «## Осталось»",
        "  раздел «Не проверено» абзацем «**Не проверено:**», нужен «## Не проверено»",
        "  нет раздела «## Файлы»",
        "  раздел «SHA» абзацем «**SHA:**», нужен «## SHA»",
        "  нет раздела «## Инъекции»",
        "  нет раздела «## Кому передано»",
        "lint-result: нарушений 7",
    ]


# ---------------------------------------------------------------- 3. pack на пине показывает «Не проверено» k0#1.1


def _git_text(*args: str) -> tuple[int, str]:
    proc = run_with_deadline(lambda: subprocess.run(["git", "-C", str(_ROOT), *args], capture_output=True, check=False))
    return proc.returncode, proc.stdout.decode("utf-8", "replace").strip()


def test_pack_k0_1_2_prints_not_verified_of_1_1(tmp_path: Path, atlas: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    code, shallow = _git_text("rev-parse", "--is-shallow-repository")
    assert (code, shallow) == (0, "false"), "клон неполный: выполнить `git fetch --unshallow` перед тестом"
    code, kind = _git_text("cat-file", "-t", _PIN)
    assert (code, kind) == (0, "commit"), f"коммит {_PIN} не разрешается в этом клоне"
    # свежая база: data/atlas.sqlite checkout кэширует сборки по sha и отпечатку и скрыл бы дефект
    from scripts.atlas import store

    real = store.connect
    fresh = tmp_path / "atlas.sqlite"
    monkeypatch.setattr("scripts.atlas.store.connect", lambda _path: real(fresh))

    res = atlas(GitRepo(_ROOT), "pack", "k0-framework-quality#1.2", *_PINNED)
    assert (res.code, res.err) == (0, ""), res.err
    lines = res.out.splitlines()
    head = lines.index("  k0-framework-quality#1.1 (done):")
    block: list[str] = []
    for line in lines[head + 1 :]:
        if not line.startswith("    "):
            break
        block.append(line)
    assert "    Не проверено:" in block
    at = block.index("    Не проверено:")
    assert block[at + 1] == "      " + _K0_UNCHECKED
    assert [line for line in lines if "итог без разделов формы 0.7" in line] == []


# ---------------------------------------------------------------- 4. три формы раздела в хвостах pack


def _new_repo(factory: RepoFactory, name: str) -> GitRepo:
    repo = factory.create(name)
    exclude = repo.path / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("data/\n", encoding="utf-8")
    return repo


_MODULES = (
    'version: 1\nmodules:\n  - id: m\n    paths: ["m/"]\n    layer: framework\n    tier: null\n    docs: []\n'
    "    parent: null\n"
)


def _plan(*rows: str) -> str:
    return "# Alpha\n\n## Порядок выполнения\n\n" + "".join(f"- Task {row}\n" for row in rows)


def _commit(repo: GitRepo, mp: pytest.MonkeyPatch, stamp: str, subject: str, *trailers: str) -> str:
    full = f"{stamp}T10:00:00+0000"
    mp.setenv("GIT_AUTHOR_DATE", full)
    mp.setenv("GIT_COMMITTER_DATE", full)
    message = subject + ("\n\n" + "\n".join(trailers) if trailers else "")
    return repo.commit(message)


def _tail_block(lines: list[str], task: str) -> list[str]:
    """Строки блока хвостов задачи `task` (alpha#1.1): после заголовка с отступом 2, отступ >= 4."""
    heading = next(index for index, line in enumerate(lines) if line.startswith(f"  {task} ("))
    block: list[str] = []
    for line in lines[heading + 1 :]:
        if not line.startswith("    "):
            break
        block.append(line)
    return block


def test_section_bold_colon_form_is_a_tail(
    repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _new_repo(repo_factory, "tails")
    done = "[DONE 2026-10-01]"
    repo.write("modules.yaml", _MODULES)
    repo.write(
        "plans/2026-10-01_alpha/plan.md",
        _plan(f"1.1: one {done}", f"1.2: two {done}", f"1.3: three {done}", "1.4: four [PENDING]"),
    )
    tasks = "plans/2026-10-01_alpha/tasks/"
    repo.write(tasks + "1.1.result.md", "# Итог 1.1\n\n**Осталось:** x\n")
    repo.write(tasks + "1.2.result.md", "# Итог 1.2\n\n## Для следующего брифа\n- нота\n")
    repo.write(
        tasks + "1.3.result.md",
        "# Итог 1.3\n\n## Для следующего брифа\n- в\n\n## Не проверено\n- б\n\n## Осталось\n- а\n",
    )
    _commit(repo, monkeypatch, "2026-09-30", "init")
    for task, path, day in (
        ("1.1", "m/a.py", "01"),
        ("1.2", "m/b.py", "02"),
        ("1.3", "m/c.py", "03"),
        ("1.4", "m/d.py", "04"),
    ):
        repo.write(path, f"x = '2026-10-{day}'\n")
        _commit(repo, monkeypatch, f"2026-10-{day}", f"task {task}", f"Task: alpha#{task}")

    res = atlas(repo, "pack", "alpha#1.4", *_REFS)
    assert (res.code, res.err) == (0, ""), res.err
    lines = res.out.splitlines()
    assert any(line.startswith("Хвосты прошлых задач плана (") for line in lines)
    assert _tail_block(lines, "alpha#1.1") == ["    Осталось:", "      x"]
    assert _tail_block(lines, "alpha#1.2") == ["    Для следующего брифа:", "      - нота"]
    assert _tail_block(lines, "alpha#1.3") == [
        "    Осталось:",
        "      - а",
        "    Не проверено:",
        "      - б",
        "    Для следующего брифа:",
        "      - в",
    ]
    assert [line for line in lines if "итог без разделов формы 0.7" in line] == []


# ---------------------------------------------------------------- 5. сообщения lint-result и коды выхода


def test_lint_result_messages(tmp_path: Path, atlas: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    outside = _outside_git(tmp_path, monkeypatch)
    target = GitRepo(outside)

    def lint(label: str, text: str) -> tuple[int, list[str], str]:
        (outside / f"{label}.result.md").write_text(text, encoding="utf-8")
        res = atlas(target, "lint-result", f"{label}.result.md")
        return res.code, res.out.splitlines(), res.err

    # 1. нет ни в какой форме
    assert lint("missing", _result_text(Осталось=None)) == (
        1,
        ["  нет раздела «## Осталось»", "lint-result: нарушений 1"],
        "",
    )
    # 2. только абзацем: маркер печатается как в файле (формы `**T.**` и `**T:**`)
    assert lint("paragraph", _result_text(Сделано="**Сделано.** x\n\n", Осталось="**Осталось:** y\n\n")) == (
        1,
        [
            "  раздел «Сделано» абзацем «**Сделано.**», нужен «## Сделано»",
            "  раздел «Осталось» абзацем «**Осталось:**», нужен «## Осталось»",
            "lint-result: нарушений 2",
        ],
        "",
    )
    # 3. `## T` без непустых строк: пустое тело и тело из пробелов
    for label, body in (("empty", "\n"), ("blank", "   \n\n")):
        assert lint(label, _result_text(Файлы=f"## Файлы\n{body}")) == (
            1,
            ["  пустой раздел «## Файлы»: пишут «нет»", "lint-result: нарушений 1"],
            "",
        ), label
    # 4. «## Не проверено» не бывает «нет»: `- нет` и голое `нет`
    for label, body in (("dash-none", "- нет"), ("bare-none", "нет")):
        assert lint(label, _result_text(Не_проверено=f"## Не проверено\n{body}\n\n")) == (
            1,
            ["  «## Не проверено» не бывает «нет»", "lint-result: нарушений 1"],
            "",
        ), label
    # 5. несколько нарушений: по строке на раздел, порядок REQUIRED, не порядок в файле
    assert lint(
        "several",
        _result_text(
            Сделано="**Сделано:** x\n\n",
            Файлы="## Файлы\n\n",
            Не_проверено="## Не проверено\n- нет\n\n",
            Кому_передано=None,
        ),
    ) == (
        1,
        [
            "  раздел «Сделано» абзацем «**Сделано:**», нужен «## Сделано»",
            "  «## Не проверено» не бывает «нет»",
            "  пустой раздел «## Файлы»: пишут «нет»",
            "  нет раздела «## Кому передано»",
            "lint-result: нарушений 4",
        ],
        "",
    )
    # 6. чистый файл
    assert lint("clean", GOOD_RESULT) == (0, ["lint-result: нарушений 0"], "")
    # 7. нет файла: stderr с путём как дал вызывающий, exit 2, stdout пуст
    res = atlas(target, "lint-result", "no-such.result.md")
    assert (res.code, res.out, res.err) == (2, "", "lint-result: нет файла no-such.result.md\n")
    # 8. `--ref` с lint-result: exit 2 по правилу «нужна ровно одна форма», а не по argparse «invalid choice»
    res = atlas(target, "--ref", "main", "lint-result", "clean.result.md")
    assert res.code == 2
    assert res.out == ""
    forms = [line for line in res.err.splitlines() if "нужна ровно одна форма" in line]
    assert len(forms) == 1, res.err
    assert "lint-result" in forms[0]
    assert "нет файла" not in res.err


# ---------------------------------------------------------------- 6. находка RESULT_FORM


def test_result_form_finding(repo_factory: RepoFactory, atlas: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _new_repo(repo_factory, "finding")
    repo.write("modules.yaml", _MODULES)
    repo.write("plans/2026-10-01_alpha/plan.md", _plan("1.1: one [DONE 2026-10-01]", "1.2: two [DONE 2026-10-01]"))
    repo.write("plans/2026-10-01_alpha/tasks/1.2.result.md", GOOD_RESULT)
    _commit(repo, monkeypatch, "2026-10-01", "base")
    repo.git("checkout", "-q", "-b", "feat")
    repo.write("plans/2026-10-01_alpha/tasks/1.1.result.md", BAD_RESULT)
    _commit(repo, monkeypatch, "2026-10-02", "feat: bad result")

    res = atlas(repo, "--json", "--ref", "feat", "--main-ref", "main")
    assert (res.code, res.err) == (0, ""), res.err
    found = [f for f in json.loads(res.out)["findings"] if f["code"] == "RESULT_FORM"]
    assert found == [
        {
            "code": "RESULT_FORM",
            "severity": "warning",
            "node": "result:alpha#1.1",
            "detail": "Осталось,Файлы",
            "message": "Итог не по форме 0.7: нет раздела «## Осталось»; нет раздела «## Файлы»",
            "source": "plans/2026-10-01_alpha/tasks/1.1.result.md",
        }
    ]

    res = atlas(repo, "check")
    assert res.code == 0, res.out + res.err
    lines = res.out.splitlines()
    assert "warning RESULT_FORM result:alpha#1.1 Осталось,Файлы" in lines
    assert [line for line in lines if "RESULT_FORM" in line and "result:alpha#1.2" in line] == []
    assert lines[-1].startswith("atlas check: 0 new blocking, ")


# ---------------------------------------------------------------- 7. хук lint-result.sh


def _git_bash() -> str:
    """Git Bash, а не WSL-`bash` из System32 (subprocess подхватывает тот первым)."""
    git = shutil.which("git")
    for parent in Path(git).resolve().parents if git else []:
        if (parent / "bin" / "bash.exe").is_file():
            return str(parent / "bin" / "bash.exe")
    return "bash"  # POSIX-машина


def _run_hook(cwd: Path, payload: dict[str, Any]) -> subprocess.CompletedProcess[bytes]:
    env = dict(os.environ)
    env["CLAUDE_PYTHON_BIN"] = sys.executable
    env["PYTHONUTF8"] = "1"
    return subprocess.run(
        [_git_bash(), _HOOK.as_posix()],
        input=json.dumps(payload).encode("utf-8"),
        cwd=str(cwd),
        env=env,
        capture_output=True,
        timeout=90,
        check=False,
    )


def test_hook_lints_result_write(tmp_path: Path) -> None:
    tasks = tmp_path / "plans" / "2026-10-04_alpha" / "tasks"
    tasks.mkdir(parents=True)
    bad, good, other = tasks / "bad.result.md", tasks / "good.result.md", tasks / "1.1.md"
    bad.write_text(BAD_RESULT, encoding="utf-8")
    good.write_text(GOOD_RESULT, encoding="utf-8")
    other.write_text(BAD_RESULT, encoding="utf-8")  # плохое содержимое, но не `*.result.md`

    def write(path: Path) -> dict[str, Any]:
        return {"tool_name": "Write", "tool_input": {"file_path": path.as_posix(), "content": path.read_text("utf-8")}}

    def edit(path: Path) -> dict[str, Any]:
        return {
            "tool_name": "Edit",
            "tool_input": {"file_path": path.as_posix(), "old_string": "итог", "new_string": "итог"},
        }

    for label, payload in (("Write", write(bad)), ("Edit", edit(bad))):
        proc = _run_hook(tmp_path, payload)
        err = proc.stderr.decode("utf-8", "replace")
        assert proc.returncode == 2, f"{label}: exit {proc.returncode}, stderr: {err}"
        assert "нет раздела «## Осталось»" in err, f"{label}: {err}"
        assert "не по форме 0.7 (.claude/plugins/dev/templates/task-result.md):" in err, f"{label}: {err}"
    for label, payload in (("good Write", write(good)), ("good Edit", edit(good)), ("not a result", write(other))):
        proc = _run_hook(tmp_path, payload)
        assert (proc.returncode, proc.stdout, proc.stderr) == (0, b"", b""), f"{label}: {proc.stderr!r}"
