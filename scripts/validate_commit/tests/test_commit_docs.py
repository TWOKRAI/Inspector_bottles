"""Task 2.2 (commit-mechanism) — сторожа документов формата коммита v2 (D1-D7).

Независимого тестера у задачи нет (документы), сторожа пишет автор документов. Они держат то, что
`claude-kit upgrade` или чья-то правка могут тихо сломать: одна копия гайда, зеркало `project-rules`,
пример сообщения, который валидатор принимает без предупреждений, трейлеры одним блоком.

  D1  заглушка `docs/claude/COMMIT_GUIDE.md` — не больше 5 строк и указывает на `.claude/COMMIT_GUIDE.md`;
  D2  `project-rules/SKILL.md`: источник и зеркало равны байт-в-байт;
  D3  в `.gitmessage`, гайде и корневом `CLAUDE.md` нет «<=72» как лимита;
  D4  в гайде есть литералы привычек: `git commit -F`, `git merge --no-ff`, `ruff format`, `ruff check --fix`;
  D5  строка-шаблон `Layer:` в гайде и в `.gitmessage` — ровно 9 значений из `.claude/commit-layers.txt`;
  D6  пример из `.gitmessage` и помеченный пример из гайда: валидатор rc 0 без `WARNING`, git видит
      Why, Layer, Refs, Task, Co-Authored-By;
  D7  в `project-rules` §4 есть `git commit -F` и `Co-Authored-By`.
  D8  гайд: коммит слияния — `git commit -F <файл>` без `-- <пути>` (иначе partial commit during a merge).

Ожидаемые значения — литералы, не читаются из проверяемого кода. Валидатор запускается подпроцессом
с таймаутом из временного git-репозитория (ветка, разрешающаяся в план).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

GUIDE = REPO_ROOT / ".claude" / "COMMIT_GUIDE.md"
STUB = REPO_ROOT / "docs" / "claude" / "COMMIT_GUIDE.md"
GITMESSAGE = REPO_ROOT / ".gitmessage"
ROOT_CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
SKILL_SOURCE = REPO_ROOT / ".claude" / "plugins" / "dev" / "skills" / "project-rules" / "SKILL.md"
SKILL_MIRROR = REPO_ROOT / ".claude" / "skills" / "project-rules" / "SKILL.md"
VALIDATOR = REPO_ROOT / "scripts" / "validate_commit" / "validate_commit.py"
COMMIT_LAYERS = REPO_ROOT / ".claude" / "commit-layers.txt"

TIMEOUT = 120
BRANCH = "feat/commit-mechanism"
PLAN = "plans/2026-10-03_commit-mechanism/plan.md"
EXAMPLE_MARKER = "<!-- commit-example -->"
LAYERS = {"framework", "services", "plugins", "prototype", "docs", "scripts", "tests", "infra", "mixed"}
REQUIRED_TRAILERS = ("Why", "Layer", "Refs", "Task", "Co-Authored-By")

_LIMIT_72 = re.compile(r"(≤|<=)\s*72")
_LAYER_TEMPLATE = re.compile(r"^#?\s*Layer:\s*(.+\|.+)$", re.MULTILINE)


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


# --------------------------------------------------------------------------- process helpers


def _clean_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run(cmd: list[str], cwd: Path, stdin_data: bytes | None = None) -> tuple[int, str, str]:
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


def _git(repo: Path, *args: str) -> None:
    rc, out, err = _run(["git", *args], repo)
    assert rc == 0, f"git {' '.join(args)} rc={rc}\n{out}\n{err}"


@pytest.fixture(scope="module")
def plan_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Ветка feat/commit-mechanism, план на диске, список слоёв — литерал из 9 строк (не файл из дерева)."""
    repo = tmp_path_factory.mktemp("docs_repo")
    _git(repo, "init", "-q", "-b", BRANCH)
    _git(repo, "config", "user.name", "Tester")
    _git(repo, "config", "user.email", "tester@example.invalid")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "config", "commit.gpgsign", "false")
    layers_file = repo / ".claude" / "commit-layers.txt"
    layers_file.parent.mkdir(parents=True)
    layers_file.write_text("# layers\n" + "\n".join(sorted(LAYERS)) + "\n", encoding="utf-8", newline="\n")
    plan = repo / PLAN
    plan.parent.mkdir(parents=True)
    plan.write_text(f"# Plan: commit mechanism\n\n- **Ветка:** {BRANCH}\n", encoding="utf-8", newline="\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


# --------------------------------------------------------------------------- example extraction


def _gitmessage_example() -> str:
    """Строки после `ПРИМЕР` в `.gitmessage`, без префикса комментария `# `."""
    lines = _read(GITMESSAGE).splitlines()
    marker = [i for i, line in enumerate(lines) if "ПРИМЕР" in line]
    assert marker, ".gitmessage: нет строки-маркера ПРИМЕР"
    example: list[str] = []
    for line in lines[marker[0] + 1 :]:
        if line.startswith("# "):
            example.append(line[2:])
        elif line == "#":
            example.append("")
        else:
            pytest.fail(f".gitmessage: строка примера без префикса '# ': {line!r}")
    return "\n".join(example).strip("\n") + "\n"


def _guide_example() -> str:
    """Огороженный блок сразу после строки `<!-- commit-example -->` в гайде."""
    lines = _read(GUIDE).splitlines()
    marker = [i for i, line in enumerate(lines) if line.strip() == EXAMPLE_MARKER]
    assert len(marker) == 1, f"{GUIDE.name}: ожидается ровно один маркер {EXAMPLE_MARKER}, найдено {len(marker)}"
    index = marker[0] + 1
    assert index < len(lines) and lines[index].startswith("```"), "после маркера примера нет огороженного блока"
    block: list[str] = []
    for line in lines[index + 1 :]:
        if line.startswith("```"):
            return "\n".join(block) + "\n"
        block.append(line)
    pytest.fail("блок примера в гайде не закрыт")


def _git_trailer_keys(repo: Path, message: str) -> list[str]:
    rc, out, err = _run(
        ["git", "interpret-trailers", "--parse", "--no-divider"], repo, stdin_data=message.encode("utf-8")
    )
    assert rc == 0, f"git interpret-trailers rc={rc}\n{err}"
    return [line.split(":", 1)[0] for line in out.splitlines() if line and not line[0].isspace()]


def _skill_section_4(path: Path) -> str:
    text = _read(path)
    match = re.search(r"^## 4\..*?(?=^## 5\.)", text, re.DOTALL | re.MULTILINE)
    assert match, f"{path}: не найден раздел '## 4.' перед '## 5.'"
    return match.group(0)


# --------------------------------------------------------------------------- D1-D7


def test_d1_old_guide_is_a_pointer_stub() -> None:
    lines = _read(STUB).splitlines()
    assert len(lines) <= 5, f"заглушка длиннее 5 строк: {len(lines)}"
    assert ".claude/COMMIT_GUIDE.md" in _read(STUB), "заглушка не указывает на .claude/COMMIT_GUIDE.md"


def test_d2_project_rules_source_and_mirror_equal() -> None:
    assert SKILL_SOURCE.read_bytes() == SKILL_MIRROR.read_bytes(), (
        "project-rules/SKILL.md: источник и зеркало разошлись"
    )


@pytest.mark.parametrize("path", [GITMESSAGE, GUIDE, ROOT_CLAUDE_MD], ids=lambda p: p.name)
def test_d3_no_72_char_limit_wording(path: Path) -> None:
    hits = [line for line in _read(path).splitlines() if _LIMIT_72.search(line)]
    assert not hits, f"{path.name}: «72» подаётся как лимит: {hits[:3]}"


@pytest.mark.parametrize("literal", ["git commit -F", "git merge --no-ff", "ruff format", "ruff check --fix"])
def test_d4_guide_has_habit_literals(literal: str) -> None:
    assert literal in _read(GUIDE), f"в {GUIDE.name} нет литерала {literal!r}"


@pytest.mark.parametrize("path", [GUIDE, GITMESSAGE], ids=lambda p: p.name)
def test_d5_layer_template_lists_exactly_nine_layers(path: Path) -> None:
    file_layers = {
        line.strip() for line in _read(COMMIT_LAYERS).splitlines() if line.strip() and not line.startswith("#")
    }
    assert file_layers == LAYERS, f"commit-layers.txt: ожидалось 9 слоёв, найдено {sorted(file_layers)}"
    templates = _LAYER_TEMPLATE.findall(_read(path))
    assert templates, f"{path.name}: нет строки-шаблона 'Layer: a | b | ...'"
    listed = [value.strip() for value in templates[0].split("|")]
    assert len(listed) == 9 and set(listed) == LAYERS, f"{path.name}: слои {listed}"


@pytest.mark.parametrize("source", ["gitmessage", "guide"])
def test_d6_example_is_accepted_without_warning_and_trailers_are_one_block(plan_repo: Path, source: str) -> None:
    message = _gitmessage_example() if source == "gitmessage" else _guide_example()
    rc, _out, err = _run([sys.executable, str(VALIDATOR), "-"], plan_repo, stdin_data=message.encode("utf-8"))
    assert rc == 0, f"валидатор отклонил пример ({source}): rc={rc}\n{err}"
    assert "WARNING" not in err, f"валидатор предупредил о примере ({source}):\n{err}"
    keys = _git_trailer_keys(plan_repo, message)
    missing = [key for key in REQUIRED_TRAILERS if key not in keys]
    assert not missing, f"git не видит трейлеры {missing} в примере ({source}); видит {keys}"


@pytest.mark.parametrize("path", [SKILL_SOURCE, SKILL_MIRROR], ids=["source", "mirror"])
def test_d7_project_rules_section_4_names_habit_and_block(path: Path) -> None:
    section = _skill_section_4(path)
    assert "git commit -F" in section, "project-rules §4: нет 'git commit -F'"
    assert "Co-Authored-By" in section, "project-rules §4: нет 'Co-Authored-By'"


def test_d8_guide_names_merge_commit_without_pathspec() -> None:
    """Слияние с конфликтом: `git commit -F <файл>` БЕЗ `-- <пути>`, иначе `partial commit during a merge`."""
    text = _read(GUIDE)
    assert "без `-- <пути>`" in text, "в гайде нет правила 'без `-- <пути>`' для коммита слияния"
    assert "partial commit during a merge" in text, "в гайде нет текста ошибки 'partial commit during a merge'"
