"""Слепая приёмка 2.4g.1: `scripts/memory/tags.py --check` и `scripts/memory/search.py`.

Источник истины — `plans/2026-10-04_atlas/tasks/2.4g.md`, раздел «2.4g.1», строки A1.1–A1.12 и
A2.1–A2.8. Скрипты зовутся ПОДПРОЦЕССОМ (контракт — CLI, не импорт). Исключение — A1.12: он
импортирует `scripts/validate.py`.

Правила этого файла:
- ожидаемые значения — литералы из спеки, не пересчёт из кода под тестом;
- у каждого «нет ошибки» в той же фикстуре лежит «плохой» файл-контроль, и сравнивается ПОЛНЫЙ
  набор ошибок: без контроля «нет ошибки» зеленеет и на пустом выводе;
- `_run` падает, если скрипта нет: `python <нет файла>` выходит с кодом 2, а это ровно тот код,
  что спека требует у `search.py` без аргументов (A2.3) — без стража тест зеленел бы на пустоте;
- в окружение подпроцесса НЕ попадают PYTHONUTF8/PYTHONIOENCODING: вывод обязан быть UTF-8
  по контракту (`sys.stdout.reconfigure`), а не по везению окружения прогона.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_MEMORY = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPTS_MEMORY.parents[1]
TAGS_PY = SCRIPTS_MEMORY / "tags.py"
SEARCH_PY = SCRIPTS_MEMORY / "search.py"
VALIDATE_PY = REPO_ROOT / "scripts" / "validate.py"

MEM = "docs/claude/memory"
TIMEOUT = 60

CODES = (
    "unknown-module",
    "unknown-mechanism",
    "unknown-role",
    "no-tag",
    "vocab-too-big",
    "desc-lang",
    "stray-role-lesson",
    "role-index-too-long",
)
_ERR_RE = re.compile(r"^(?P<path>[^:\n]+?): (?P<code>" + "|".join(CODES) + r")(?::[ ]?(?P<value>.*))?$")

# Описание, проходящее desc-lang: кириллица и латиница по >= 3 буквы.
GOOD_DESC = "фикстура fixture"


# --------------------------------------------------------------------------- запуск


class Result:
    def __init__(self, cp: subprocess.CompletedProcess):
        self.rc = cp.returncode
        self.out = cp.stdout.decode("utf-8")  # strict: не-UTF-8 вывод — провал теста
        self.err = cp.stderr.decode("utf-8", errors="replace")

    @property
    def lines(self) -> list[str]:
        return [ln for ln in self.out.splitlines() if ln.strip()]

    @property
    def errors(self) -> list[tuple[str, str, str]]:
        """(путь, код, значение) для каждой строки-ошибки; разделитель пути нормализован в «/»."""
        found = []
        for ln in self.out.splitlines():
            m = _ERR_RE.match(ln.rstrip("\r"))
            if m:
                found.append((m["path"].replace("\\", "/"), m["code"], m["value"] or ""))
        return found

    @property
    def pairs(self) -> set[tuple[str, str]]:
        return {(p, c) for p, c, _ in self.errors}

    def values(self, code: str) -> list[str]:
        return sorted(v for _, c, v in self.errors if c == code)

    def explain(self) -> str:
        return f"rc={self.rc}\n--- stdout ---\n{self.out}\n--- stderr ---\n{self.err}"


def _env(tmp_path: Path, *, extra: dict | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    # tmp здесь лежит внутри чужого git-репо (C:/Users/<user> — репо на main): без потолка git
    # поднимется выше и «найдёт» его.
    env["GIT_CEILING_DIRECTORIES"] = str(tmp_path.parent)
    env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = "Fixture"
    env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = "fixture@example.invalid"
    if extra:
        env.update(extra)
    return env


def _run(script: Path, args: list[str], *, cwd: Path, tmp_path: Path) -> Result:
    assert script.is_file(), f"missing script {script} (RED: механизм ещё не написан)"
    cp = subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(cwd),
        env=_env(tmp_path),
        capture_output=True,
        timeout=TIMEOUT,
    )
    return Result(cp)


def _git(args: list[str], *, cwd: Path, tmp_path: Path) -> str:
    cp = subprocess.run(
        ["git", "-c", "core.longpaths=true", "-c", "init.defaultBranch=main", *args],
        cwd=str(cwd),
        env=_env(tmp_path),
        capture_output=True,
        timeout=TIMEOUT,
    )
    assert cp.returncode == 0, f"git {args}: {cp.stderr.decode('utf-8', 'replace')}"
    return cp.stdout.decode("utf-8", "replace")


def check(root: Path, tmp_path: Path) -> Result:
    return _run(TAGS_PY, ["--check", "--root", str(root)], cwd=root, tmp_path=tmp_path)


def search(root: Path, tmp_path: Path, *args: str) -> Result:
    return _run(SEARCH_PY, [*args, "--root", str(root)], cwd=root, tmp_path=tmp_path)


# --------------------------------------------------------------------------- фикстуры


def write(root: Path, rel: str, text: str, *, crlf: bool = False) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    data = text.replace("\n", "\r\n") if crlf else text
    p.write_bytes(data.encode("utf-8"))  # write_bytes: на Windows write_text сам подменил бы \n
    return p


def modules_yaml(*ids: str) -> str:
    return "modules:\n" + "".join(f"  - id: {i}\n    path: {i}\n" for i in ids)


def tags_yaml(*ids: str) -> str:
    return "mechanisms:\n" + "".join(f'  - id: {i}\n    def: "def of {i}"\n' for i in ids)


def make_repo(
    root: Path,
    *,
    modules=("logger_module", "frontend_module"),
    roles=("tester", "developer"),
    mechanisms=("break-injection", "fixture-trap"),
) -> Path:
    """Фикстурный репо без уроков: раскладка корня из спеки."""
    root.mkdir(parents=True, exist_ok=True)
    write(root, "modules.yaml", modules_yaml(*modules))
    for r in roles:
        write(root, f".claude/agents/dev/{r}.md", f"# {r}\n")
    write(root, f"{MEM}/TAGS.yaml", tags_yaml(*mechanisms))
    write(root, f"{MEM}/MEMORY.md", "# index\n")
    return root


def fm(*lines: str, name: str = "x", desc: str | None = GOOD_DESC, body: str = "Body.\n") -> str:
    """Урок: frontmatter из `name`, `description` и переданных строк, затем тело."""
    head = [f"name: {name}"]
    if desc is not None:
        head.append(f"description: {desc}")
    return "---\n" + "\n".join([*head, *lines]) + "\n---\n" + body


def lesson(root: Path, fname: str, *lines: str, crlf: bool = False, **kw) -> Path:
    return write(root, f"{MEM}/{fname}", fm(*lines, **kw), crlf=crlf)


def init_git(root: Path, tmp_path: Path) -> None:
    _git(["init", "-q"], cwd=root, tmp_path=tmp_path)
    _git(["add", "-A"], cwd=root, tmp_path=tmp_path)
    _git(["commit", "-q", "-m", "fixture"], cwd=root, tmp_path=tmp_path)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path / "repo")


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Фикстурный репо для поиска: настоящий `git init` + коммит (cwd поиска — git-репо)."""
    root = make_repo(tmp_path / "repo")
    init_git(root, tmp_path)
    return root


def p(fname: str) -> str:
    return f"{MEM}/{fname}"


# =========================================================================== tags.py --check
# --- контроль фикстуры: пустой словарь без уроков / чистый урок -> 0


def test_baseline_clean_fixture_exits_0(repo, tmp_path):
    lesson(repo, "good.md", "module: logger_module", "mechanism: break-injection", "role: tester")
    r = check(repo, tmp_path)
    assert r.rc == 0, r.explain()
    assert r.errors == [], r.explain()


# --- A1.1


def test_a1_1_unknown_mechanism_reported_with_literal_value(repo, tmp_path):
    lesson(repo, "bad.md", "mechanism: no-such-mech")
    lesson(repo, "good.md", "mechanism: break-injection")
    r = check(repo, tmp_path)
    assert r.rc == 1, r.explain()
    assert "unknown-mechanism: 'no-such-mech'" in r.out, r.explain()
    assert r.pairs == {(p("bad.md"), "unknown-mechanism")}, r.explain()


def test_a1_1_vocab_comes_from_tags_yaml_not_hardcoded(tmp_path):
    root = make_repo(tmp_path / "repo", mechanisms=("only-this",))
    lesson(root, "known.md", "mechanism: only-this")
    lesson(root, "unknown.md", "mechanism: break-injection")  # валиден в другой фикстуре, тут нет
    r = check(root, tmp_path)
    assert r.pairs == {(p("unknown.md"), "unknown-mechanism")}, r.explain()
    assert r.values("unknown-mechanism") == ["'break-injection'"], r.explain()


# --- A1.2


def test_a1_2_unknown_module_reported_known_module_clean(repo, tmp_path):
    lesson(repo, "bad.md", "module: not_a_module")
    lesson(repo, "good.md", "module: logger_module")
    r = check(repo, tmp_path)
    assert r.rc == 1, r.explain()
    assert r.pairs == {(p("bad.md"), "unknown-module")}, r.explain()
    assert r.values("unknown-module") == ["'not_a_module'"], r.explain()


def test_a1_2_module_ids_come_from_modules_yaml_not_hardcoded(tmp_path):
    root = make_repo(tmp_path / "repo", modules=("alpha_module",))
    lesson(root, "known.md", "module: alpha_module")
    lesson(root, "unknown.md", "module: logger_module")
    r = check(root, tmp_path)
    assert r.pairs == {(p("unknown.md"), "unknown-module")}, r.explain()


# --- A1.3


def test_a1_3_unknown_role_reported_known_role_clean(repo, tmp_path):
    lesson(repo, "bad.md", "module: logger_module", "role: wizard")
    lesson(repo, "good.md", "module: logger_module", "role: tester")
    r = check(repo, tmp_path)
    assert r.rc == 1, r.explain()
    assert r.pairs == {(p("bad.md"), "unknown-role")}, r.explain()
    assert r.values("unknown-role") == ["'wizard'"], r.explain()


def test_a1_3_roles_come_from_agents_dir_not_hardcoded(tmp_path):
    root = make_repo(tmp_path / "repo", roles=("only_role",))
    lesson(root, "known.md", "module: logger_module", "role: only_role")
    lesson(root, "unknown.md", "module: logger_module", "role: tester")
    r = check(root, tmp_path)
    assert r.pairs == {(p("unknown.md"), "unknown-role")}, r.explain()


# --- A1.4


def test_a1_4_lesson_without_module_and_mechanism_is_no_tag(repo, tmp_path):
    lesson(repo, "bare.md")
    lesson(repo, "role_only.md", "role: tester")  # role — не тег темы
    lesson(repo, "good.md", "module: logger_module")
    r = check(repo, tmp_path)
    assert r.rc == 1, r.explain()
    assert r.pairs == {(p("bare.md"), "no-tag"), (p("role_only.md"), "no-tag")}, r.explain()


def test_a1_4_file_without_frontmatter_is_no_tag(repo, tmp_path):
    write(repo, p("plain.md"), "Just text, mechanism: no-such-mech\n")
    lesson(repo, "good.md", "module: logger_module")
    r = check(repo, tmp_path)
    assert r.rc == 1, r.explain()
    assert r.pairs == {(p("plain.md"), "no-tag")}, r.explain()


def test_a1_4_empty_value_means_key_absent(repo, tmp_path):
    lesson(repo, "empty.md", "module:", "mechanism:")
    lesson(repo, "good.md", "module: logger_module")
    r = check(repo, tmp_path)
    assert r.pairs == {(p("empty.md"), "no-tag")}, r.explain()


def test_a1_4_non_lesson_files_are_not_checked(repo, tmp_path):
    # MEMORY.md, ARCHIVE.md, CRAFT*.md и подкаталоги — не уроки: без frontmatter они не no-tag
    write(repo, p("ARCHIVE.md"), "archive\n")
    write(repo, p("CRAFT-x.md"), "craft\n")
    write(repo, p("sub/deep.md"), "deep\n")
    lesson(repo, "bare.md")  # контроль: настоящий урок без тегов виден
    r = check(repo, tmp_path)
    assert r.pairs == {(p("bare.md"), "no-tag")}, r.explain()


# --- A1.5


def test_a1_5_31_mechanisms_is_vocab_too_big(tmp_path):
    ids = tuple(f"mech-{i:02d}" for i in range(31))
    root = make_repo(tmp_path / "repo", mechanisms=ids)
    lesson(root, "good.md", "mechanism: mech-00")
    r = check(root, tmp_path)
    assert r.rc == 1, r.explain()
    assert [c for _, c, _ in r.errors] == ["vocab-too-big"], r.explain()
    assert "TAGS.yaml" in r.out, r.explain()


def test_a1_5_30_mechanisms_is_allowed(tmp_path):
    ids = tuple(f"mech-{i:02d}" for i in range(30))
    root = make_repo(tmp_path / "repo", mechanisms=ids)
    lesson(root, "good.md", "mechanism: mech-29")  # последний из 30 известен
    lesson(root, "bad.md", "mechanism: mech-30")  # 31-й, в словаре его нет: проверка живая
    r = check(root, tmp_path)
    assert r.pairs == {(p("bad.md"), "unknown-mechanism")}, r.explain()


# --- A1.6


def test_a1_6_nested_under_metadata_checked_like_top_level(repo, tmp_path):
    lesson(repo, "nested_bad.md", "metadata:", "  mechanism: no-such-mech")
    lesson(repo, "nested_good.md", "metadata:", "  mechanism: break-injection", "  module: logger_module")
    lesson(repo, "nested_mod.md", "metadata:", "  module: not_a_module")
    lesson(repo, "nested_role.md", "module: logger_module", "metadata:", "  role: wizard")
    r = check(repo, tmp_path)
    assert r.pairs == {
        (p("nested_bad.md"), "unknown-mechanism"),
        (p("nested_mod.md"), "unknown-module"),
        (p("nested_role.md"), "unknown-role"),
    }, r.explain()


def test_a1_6_same_key_in_both_places_both_values_checked(repo, tmp_path):
    lesson(repo, "both_one_bad.md", "mechanism: break-injection", "metadata:", "  mechanism: no-such-mech")
    lesson(repo, "both_two_bad.md", "mechanism: no-such-a", "metadata:", "  mechanism: no-such-b")
    lesson(repo, "both_good.md", "mechanism: break-injection", "metadata:", "  mechanism: fixture-trap")
    r = check(repo, tmp_path)
    assert r.pairs == {
        (p("both_one_bad.md"), "unknown-mechanism"),
        (p("both_two_bad.md"), "unknown-mechanism"),
    }, r.explain()
    assert r.values("unknown-mechanism") == ["'no-such-a'", "'no-such-b'", "'no-such-mech'"], r.explain()


def test_a1_6_nested_tag_satisfies_no_tag(repo, tmp_path):
    lesson(repo, "nested.md", "metadata:", "  type: feedback", "  module: logger_module")
    lesson(repo, "bare.md", "metadata:", "  type: feedback")
    r = check(repo, tmp_path)
    assert r.pairs == {(p("bare.md"), "no-tag")}, r.explain()


# --- A1.7


def test_a1_7_crlf_file_unknown_mechanism_value_has_no_carriage_return(repo, tmp_path):
    lesson(repo, "crlf_bad.md", "mechanism: no-such-mech", crlf=True)
    lesson(repo, "crlf_good.md", "module: logger_module", "mechanism: break-injection", crlf=True)
    raw = (repo / MEM / "crlf_bad.md").read_bytes()
    assert b"\r\n" in raw  # фикстура и вправду CRLF
    r = check(repo, tmp_path)
    assert r.rc == 1, r.explain()
    assert r.pairs == {(p("crlf_bad.md"), "unknown-mechanism")}, r.explain()
    assert r.values("unknown-mechanism") == ["'no-such-mech'"], r.explain()  # не 'no-such-mech\\r'


def test_a1_7_crlf_fences_and_description_are_recognised(repo, tmp_path):
    # без снятия \r строка '---\r' не равна '---': frontmatter не найден -> ложный no-tag/desc-lang
    lesson(repo, "crlf_good.md", "module: logger_module", crlf=True)
    lesson(repo, "lf_bare.md")  # контроль: no-tag вообще выдаётся
    r = check(repo, tmp_path)
    assert r.pairs == {(p("lf_bare.md"), "no-tag")}, r.explain()


# --- A1.8


@pytest.mark.parametrize("form", ["no-such-mech", '"no-such-mech"', "[no-such-mech]", '["no-such-mech"]'])
def test_a1_8_mechanism_value_forms_unknown_are_equivalent(repo, tmp_path, form):
    lesson(repo, "bad.md", f"mechanism: {form}")
    r = check(repo, tmp_path)
    assert r.values("unknown-mechanism") == ["'no-such-mech'"], r.explain()


@pytest.mark.parametrize("form", ["break-injection", '"break-injection"', "[break-injection]", '["break-injection"]'])
def test_a1_8_mechanism_value_forms_known_are_clean(repo, tmp_path, form):
    lesson(repo, "good.md", f"mechanism: {form}")
    lesson(repo, "bad.md", "mechanism: no-such-mech")  # контроль: проверка живая
    r = check(repo, tmp_path)
    assert r.pairs == {(p("bad.md"), "unknown-mechanism")}, r.explain()


@pytest.mark.parametrize(
    "form",
    [
        "logger_module, not_a_module",
        "[logger_module, not_a_module]",
        '["logger_module", "not_a_module"]',
        '[ "logger_module" ,  "not_a_module" ]',
        "logger_module,not_a_module",
    ],
)
def test_a1_8_two_module_values_one_unknown_gives_exactly_one_error(repo, tmp_path, form):
    lesson(repo, "pair.md", f"module: {form}")
    r = check(repo, tmp_path)
    assert r.rc == 1, r.explain()
    assert r.values("unknown-module") == ["'not_a_module'"], r.explain()
    assert len(r.errors) == 1, r.explain()


def test_a1_8_two_known_module_values_are_clean(repo, tmp_path):
    lesson(repo, "pair.md", "module: logger_module, frontend_module")
    lesson(repo, "pair2.md", "module: [logger_module, frontend_module]")
    lesson(repo, "bad.md", "module: not_a_module")  # контроль
    r = check(repo, tmp_path)
    assert r.pairs == {(p("bad.md"), "unknown-module")}, r.explain()


# --- A1.9


@pytest.mark.parametrize("desc", ["fixture: a trap", "фикстура fixture: a trap"])
def test_a1_9_unescaped_colon_in_description_does_not_hide_tags(repo, tmp_path, desc):
    lesson(repo, "trap.md", "mechanism: no-such-mech", desc=desc)
    r = check(repo, tmp_path)
    assert "unknown-mechanism" in [c for _, c, _ in r.errors], r.explain()
    assert (p("trap.md"), "no-tag") not in r.pairs, r.explain()
    assert r.values("unknown-mechanism") == ["'no-such-mech'"], r.explain()


def test_a1_9_colon_description_with_valid_tags_is_clean(repo, tmp_path):
    lesson(repo, "trap.md", "module: logger_module", desc="фикстура fixture: a trap")
    lesson(repo, "bad.md", "mechanism: no-such-mech")  # контроль
    r = check(repo, tmp_path)
    assert r.pairs == {(p("bad.md"), "unknown-mechanism")}, r.explain()


# --- A1.10


def test_a1_10_russian_only_description_is_desc_lang(repo, tmp_path):
    lesson(repo, "ru.md", "module: logger_module", desc="только русский текст")
    lesson(repo, "good.md", "module: logger_module", desc="фикстура fixture")
    r = check(repo, tmp_path)
    assert r.rc == 1, r.explain()
    assert r.pairs == {(p("ru.md"), "desc-lang")}, r.explain()


def test_a1_10_english_only_description_is_desc_lang(repo, tmp_path):
    lesson(repo, "en.md", "module: logger_module", desc="only english text")
    lesson(repo, "good.md", "module: logger_module", desc="фикстура fixture")
    r = check(repo, tmp_path)
    assert r.pairs == {(p("en.md"), "desc-lang")}, r.explain()


@pytest.mark.parametrize(
    ("desc", "ok"),
    [
        ("фик fix", True),  # ровно 3 + 3 — граница проходит
        ("фи fix", False),  # кириллицы 2 < 3
        ("фик fi", False),  # латиницы 2 < 3
        ("ё-ё-ё fix", False),  # одиночные буквы не складываются в слово
        ("Ёлка Tree", True),  # Ё в диапазоне, заглавные
    ],
    ids=["3+3-pass", "cyr2-fail", "lat2-fail", "single-letters-fail", "yo-capitals-pass"],
)
def test_a1_10_desc_lang_threshold_is_three_letters_per_script(repo, tmp_path, desc, ok):
    lesson(repo, "edge.md", "module: logger_module", desc=desc)
    lesson(repo, "ctl.md", "module: logger_module", desc="только русский")  # контроль: desc-lang живой
    r = check(repo, tmp_path)
    expected = {(p("ctl.md"), "desc-lang")} | (set() if ok else {(p("edge.md"), "desc-lang")})
    assert r.pairs == expected, r.explain()


def test_a1_10_description_under_metadata_is_checked(repo, tmp_path):
    lesson(repo, "nested_ru.md", "module: logger_module", "metadata:", "  description: только русский", desc=None)
    lesson(repo, "nested_ok.md", "module: logger_module", "metadata:", "  description: фикстура fixture", desc=None)
    r = check(repo, tmp_path)
    assert r.pairs == {(p("nested_ru.md"), "desc-lang")}, r.explain()


# --- A1.11


def test_a1_11_stray_file_in_role_memory_dir(repo, tmp_path):
    write(repo, ".claude/agent-memory/tester/x.md", "stray lesson\n")
    write(repo, ".claude/agent-memory/developer/MEMORY.md", "one\n")  # контроль: MEMORY.md — не stray
    r = check(repo, tmp_path)
    assert r.rc == 1, r.explain()
    assert r.pairs == {(".claude/agent-memory/tester/x.md", "stray-role-lesson")}, r.explain()


def test_a1_11_role_index_of_three_nonempty_lines_is_ok(repo, tmp_path):
    # три непустых + пустые строки: пустые не считаются
    write(repo, ".claude/agent-memory/tester/MEMORY.md", "\n- a\n\n- b\n\n\n- c\n\n")
    write(repo, ".claude/agent-memory/developer/MEMORY.md", "- a\n- b\n- c\n- d\n")  # контроль: 4 — ошибка
    r = check(repo, tmp_path)
    assert r.pairs == {(".claude/agent-memory/developer/MEMORY.md", "role-index-too-long")}, r.explain()


def test_a1_11_role_index_of_four_nonempty_lines_is_too_long(repo, tmp_path):
    write(repo, ".claude/agent-memory/tester/MEMORY.md", "- a\n- b\n\n- c\n- d\n")
    r = check(repo, tmp_path)
    assert r.rc == 1, r.explain()
    assert r.pairs == {(".claude/agent-memory/tester/MEMORY.md", "role-index-too-long")}, r.explain()


def test_a1_11_role_index_with_crlf_counts_lines_not_carriage_returns(repo, tmp_path):
    write(repo, ".claude/agent-memory/tester/MEMORY.md", "- a\n- b\n- c\n", crlf=True)
    write(repo, ".claude/agent-memory/developer/MEMORY.md", "- a\n- b\n- c\n- d\n", crlf=True)
    r = check(repo, tmp_path)
    assert r.pairs == {(".claude/agent-memory/developer/MEMORY.md", "role-index-too-long")}, r.explain()


# --- A1.12 (к 2.4g.3; до него — xfail strict)

_EXISTING_CHECKS = (
    "check_imports",
    "check_no_syspath",
    "check_init_files",
    "check_interfaces",
    "check_status_files",
    "check_readme_files",
    "check_services",
    "check_adr_sync",
    "check_plans_progress",
)


@pytest.mark.xfail(strict=True, reason="wired in 2.4g.3")
def test_a1_12_validate_main_fails_on_memory_tag_error(tmp_path, monkeypatch, capsys):
    root = make_repo(tmp_path / "repo")
    lesson(root, "bad.md", "mechanism: no-such-mech")

    spec = importlib.util.spec_from_file_location("validate_under_test", VALIDATE_PY)
    validate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validate)

    monkeypatch.setattr(validate, "BASE", root)
    monkeypatch.setattr(validate, "errors", [])
    monkeypatch.setattr(validate, "warnings", [])
    # пустышки — ровно девять проверок, что есть в validate.py сегодня; проверку памяти, которую
    # 2.4g.3 добавит под любым именем, НЕ глушим: она и есть предмет теста
    for name in _EXISTING_CHECKS:
        assert hasattr(validate, name), f"validate.py потерял {name}: обнови список пустышек"
        monkeypatch.setattr(validate, name, lambda *a, **k: None)
    assert validate.main() == 1
    capsys.readouterr()


# =========================================================================== search.py


def _words_lesson(root, fname, desc, *lines, **kw):
    return lesson(root, fname, *lines, desc=desc, name=fname[:-3], **kw)


def _split(line: str) -> tuple[str, str]:
    path, sep, desc = line.partition(" — ")
    assert sep, f"строка не '<путь> — <description>': {line!r}"
    return path, desc


def _names(r: Result) -> list[str]:
    return [Path(_split(ln)[0]).name for ln in r.lines]


# --- A2.1


def test_a2_1_rank_is_number_of_matched_words_not_filename_order(git_repo, tmp_path):
    _words_lesson(git_repo, "a_one.md", "фикстура alpha only", "module: logger_module")
    _words_lesson(git_repo, "z_both.md", "фикстура alpha and beta", "module: logger_module")
    r = search(git_repo, tmp_path, "alpha", "beta")
    assert r.rc == 0, r.explain()
    assert _names(r) == ["z_both.md", "a_one.md"], r.explain()


def test_a2_1_equal_rank_ties_break_by_filename(git_repo, tmp_path):
    for n in ("c_tie.md", "a_tie.md", "b_tie.md"):
        _words_lesson(git_repo, n, "фикстура tiebreak", "module: logger_module")
    r = search(git_repo, tmp_path, "tiebreak")
    assert _names(r) == ["a_tie.md", "b_tie.md", "c_tie.md"], r.explain()


def test_a2_1_line_format_is_absolute_path_dash_description(git_repo, tmp_path):
    _words_lesson(git_repo, "one.md", "фикстура needle", "module: logger_module")
    r = search(git_repo, tmp_path, "needle")
    assert len(r.lines) == 1, r.explain()
    path, desc = _split(r.lines[0])
    assert Path(path).is_absolute(), r.explain()
    assert Path(path).samefile(git_repo / MEM / "one.md"), r.explain()
    assert desc == "фикстура needle", r.explain()


def test_a2_1_match_is_or_case_insensitive_substring_over_name_description_tags_filename(git_repo, tmp_path):
    lesson(git_repo, "by_name.md", "module: logger_module", name="uniqname", desc=GOOD_DESC)
    lesson(git_repo, "by_desc.md", "module: logger_module", name="n2", desc="фикстура uniqdesc")
    lesson(git_repo, "by_tag.md", "mechanism: uniqtag", name="n3", desc=GOOD_DESC)
    lesson(git_repo, "uniqfile.md", "module: logger_module", name="n4", desc=GOOD_DESC)
    lesson(git_repo, "miss.md", "module: logger_module", name="n5", desc=GOOD_DESC)  # контроль: не совпадает
    r = search(git_repo, tmp_path, "UNIQNAME", "uniqDesc", "uniqta", "UniqFile")
    assert sorted(_names(r)) == ["by_desc.md", "by_name.md", "by_tag.md", "uniqfile.md"], r.explain()


def test_a2_1_crlf_lesson_description_is_printed_without_carriage_return(git_repo, tmp_path):
    _words_lesson(git_repo, "crlf.md", "фикстура crlfneedle", "module: logger_module", crlf=True)
    r = search(git_repo, tmp_path, "crlfneedle")
    assert len(r.lines) == 1, r.explain()
    assert "\r" not in r.out.replace("\r\n", "\n"), r.explain()
    assert _split(r.lines[0])[1] == "фикстура crlfneedle", r.explain()


# --- A2.2


def test_a2_2_default_limit_is_eight_lines(git_repo, tmp_path):
    for i in range(1, 13):
        _words_lesson(git_repo, f"l{i:02d}.md", "фикстура manyneedle", "module: logger_module")
    r = search(git_repo, tmp_path, "manyneedle")
    assert r.rc == 0, r.explain()
    assert _names(r) == [f"l{i:02d}.md" for i in range(1, 9)], r.explain()


def test_a2_2_explicit_limit_three(git_repo, tmp_path):
    for i in range(1, 13):
        _words_lesson(git_repo, f"l{i:02d}.md", "фикстура manyneedle", "module: logger_module")
    r = search(git_repo, tmp_path, "manyneedle", "--limit", "3")
    assert _names(r) == ["l01.md", "l02.md", "l03.md"], r.explain()


def test_a2_2_limit_larger_than_default_raises_the_cap(git_repo, tmp_path):
    for i in range(1, 13):
        _words_lesson(git_repo, f"l{i:02d}.md", "фикстура manyneedle", "module: logger_module")
    r = search(git_repo, tmp_path, "manyneedle", "--limit", "20")
    assert len(r.lines) == 12, r.explain()


# --- A2.3


def test_a2_3_no_match_prints_exactly_none_exit_0(git_repo, tmp_path):
    _words_lesson(git_repo, "one.md", "фикстура present", "module: logger_module")
    r = search(git_repo, tmp_path, "absentword")
    assert r.rc == 0, r.explain()
    assert r.out.strip() == "none", r.explain()


def test_a2_3_none_only_when_nothing_matches(git_repo, tmp_path):
    _words_lesson(git_repo, "one.md", "фикстура present", "module: logger_module")
    r = search(git_repo, tmp_path, "present")
    assert r.rc == 0 and r.out.strip() != "none", r.explain()
    assert _names(r) == ["one.md"], r.explain()


def test_a2_3_no_word_no_filter_no_list_exits_2(git_repo, tmp_path):
    _words_lesson(git_repo, "one.md", "фикстура present", "module: logger_module")
    r = search(git_repo, tmp_path)
    assert r.rc == 2, r.explain()


def test_a2_3_limit_alone_is_not_a_query_exits_2(git_repo, tmp_path):
    _words_lesson(git_repo, "one.md", "фикстура present", "module: logger_module")
    r = search(git_repo, tmp_path, "--limit", "3")
    assert r.rc == 2, r.explain()


# --- A2.4


def _worktree_setup(tmp_path: Path) -> tuple[Path, Path]:
    main = make_repo(tmp_path / "main")
    _words_lesson(main, "shared.md", "фикстура shared main-desc", "module: logger_module")
    init_git(main, tmp_path)
    wt = tmp_path / "wt"
    _git(["worktree", "add", "-q", str(wt), "-b", "side"], cwd=main, tmp_path=tmp_path)
    return main, wt


def test_a2_4_lesson_only_in_main_tree_found_from_worktree_with_absolute_main_path(tmp_path):
    main, wt = _worktree_setup(tmp_path)
    # урок появляется в main ПОСЛЕ ветвления: в дереве worktree его нет
    _words_lesson(main, "only_main.md", "фикстура onlymainneedle", "module: logger_module")
    _git(["add", "-A"], cwd=main, tmp_path=tmp_path)
    _git(["commit", "-q", "-m", "lesson"], cwd=main, tmp_path=tmp_path)
    assert not (wt / MEM / "only_main.md").exists()  # фикстура — устаревшее дерево, как в проде

    r = _run(SEARCH_PY, ["onlymainneedle"], cwd=wt, tmp_path=tmp_path)
    assert r.rc == 0, r.explain()
    assert len(r.lines) == 1, r.explain()
    path, _ = _split(r.lines[0])
    assert Path(path).is_absolute(), r.explain()
    assert Path(path).exists(), r.explain()  # читается из cwd worktree
    assert Path(path).samefile(main / MEM / "only_main.md"), r.explain()


def test_a2_4_same_name_different_description_main_tree_wins(tmp_path):
    main, wt = _worktree_setup(tmp_path)
    _words_lesson(wt, "shared.md", "фикстура shared worktree-desc", "module: logger_module")
    r = _run(SEARCH_PY, ["shared"], cwd=wt, tmp_path=tmp_path)
    assert r.rc == 0, r.explain()
    assert len(r.lines) == 1, r.explain()
    path, desc = _split(r.lines[0])
    assert desc == "фикстура shared main-desc", r.explain()
    assert Path(path).samefile(main / MEM / "shared.md"), r.explain()
    assert not Path(path).samefile(wt / MEM / "shared.md"), r.explain()


def test_a2_4_lesson_only_in_worktree_is_not_found(tmp_path):
    main, wt = _worktree_setup(tmp_path)
    _words_lesson(wt, "only_wt.md", "фикстура onlywtneedle", "module: logger_module")
    r = _run(SEARCH_PY, ["onlywtneedle"], cwd=wt, tmp_path=tmp_path)
    assert r.rc == 0, r.explain()
    assert r.out.strip() == "none", r.explain()
    # контроль: тот же запрос из main находит main-урок — скрипт запустился и читает корень
    ctl = _run(SEARCH_PY, ["shared"], cwd=wt, tmp_path=tmp_path)
    assert _names(ctl) == ["shared.md"], ctl.explain()


def test_a2_4_search_from_main_checkout_without_root_option(tmp_path):
    main, _wt = _worktree_setup(tmp_path)
    r = _run(SEARCH_PY, ["shared"], cwd=main, tmp_path=tmp_path)
    assert r.rc == 0, r.explain()
    assert Path(_split(r.lines[0])[0]).samefile(main / MEM / "shared.md"), r.explain()


# --- A2.5


def test_a2_5_role_filter_drops_lessons_without_that_role_even_if_words_match(git_repo, tmp_path):
    _words_lesson(git_repo, "t.md", "фикстура roleneedle", "module: logger_module", "role: tester")
    _words_lesson(git_repo, "none_role.md", "фикстура roleneedle", "module: logger_module")
    _words_lesson(git_repo, "dev.md", "фикстура roleneedle", "module: logger_module", "role: developer")
    r = search(git_repo, tmp_path, "roleneedle", "--role", "tester")
    assert _names(r) == ["t.md"], r.explain()


def test_a2_5_filter_alone_is_a_valid_query(git_repo, tmp_path):
    _words_lesson(git_repo, "t.md", "фикстура one", "module: logger_module", "role: tester")
    _words_lesson(git_repo, "dev.md", "фикстура two", "module: logger_module", "role: developer")
    r = search(git_repo, tmp_path, "--role", "tester")
    assert r.rc == 0, r.explain()
    assert _names(r) == ["t.md"], r.explain()


def test_a2_5_filters_combine_as_and(git_repo, tmp_path):
    _words_lesson(
        git_repo, "both.md", "фикстура x", "module: logger_module", "role: tester", "mechanism: break-injection"
    )
    _words_lesson(git_repo, "role_only.md", "фикстура x", "module: frontend_module", "role: tester")
    _words_lesson(git_repo, "mod_only.md", "фикстура x", "module: logger_module", "role: developer")
    r = search(git_repo, tmp_path, "--role", "tester", "--module", "logger_module")
    assert _names(r) == ["both.md"], r.explain()
    r2 = search(git_repo, tmp_path, "--mechanism", "break-injection", "--role", "tester")
    assert _names(r2) == ["both.md"], r2.explain()


def test_a2_5_role_under_metadata_is_matched(git_repo, tmp_path):
    _words_lesson(git_repo, "nested.md", "фикстура x", "metadata:", "  role: tester", "  module: logger_module")
    _words_lesson(git_repo, "other.md", "фикстура x", "module: logger_module")
    r = search(git_repo, tmp_path, "--role", "tester")
    assert _names(r) == ["nested.md"], r.explain()


# --- A2.6


def test_a2_6_list_prints_all_lessons_and_excludes_non_lessons(git_repo, tmp_path):
    for i in range(1, 6):
        _words_lesson(git_repo, f"les{i}.md", "фикстура listed", "module: logger_module")
    write(git_repo, p("CRAFT-x.md"), fm("module: logger_module", desc="фикстура listed"))
    write(git_repo, p("ARCHIVE.md"), fm("module: logger_module", desc="фикстура listed"))
    write(git_repo, p("sub/deep.md"), fm("module: logger_module", desc="фикстура listed"))
    r = search(git_repo, tmp_path, "--list")
    assert r.rc == 0, r.explain()
    assert _names(r) == [f"les{i}.md" for i in range(1, 6)], r.explain()


def test_a2_6_craft_and_index_files_are_not_found_by_word_either(git_repo, tmp_path):
    _words_lesson(git_repo, "real.md", "фикстура craftword", "module: logger_module")
    write(git_repo, p("CRAFT-x.md"), fm("module: logger_module", desc="фикстура craftword"))
    write(git_repo, p("MEMORY.md"), "craftword in index\n")
    r = search(git_repo, tmp_path, "craftword")
    assert _names(r) == ["real.md"], r.explain()


# --- A2.7


def test_a2_7_non_ascii_description_survives_pipe_without_utf8_env(git_repo, tmp_path):
    _words_lesson(git_repo, "arrow.md", "фикстура a → b", "module: logger_module")
    env = _env(tmp_path)
    assert "PYTHONUTF8" not in env and "PYTHONIOENCODING" not in env
    r = search(git_repo, tmp_path, "arrow")
    assert r.rc == 0, r.explain()
    assert "→" in r.out, r.explain()
    assert _split(r.lines[0])[1] == "фикстура a → b", r.explain()


def test_a2_7_check_output_with_non_ascii_value_is_utf8(repo, tmp_path):
    lesson(repo, "ru.md", "mechanism: нет-такого")
    r = check(repo, tmp_path)
    assert r.rc == 1, r.explain()
    assert r.values("unknown-mechanism") == ["'нет-такого'"], r.explain()


# --- A2.8


def test_a2_8_module_filter_matches_prefix_before_slash_not_arbitrary_prefix(git_repo, tmp_path):
    _words_lesson(git_repo, "widgets.md", "фикстура x", "module: frontend_module/widgets")
    _words_lesson(git_repo, "plain.md", "фикстура x", "module: frontend_module")
    _words_lesson(git_repo, "short.md", "фикстура x", "module: frontend")
    r = search(git_repo, tmp_path, "--module", "frontend_module")
    assert sorted(_names(r)) == ["plain.md", "widgets.md"], r.explain()
    r2 = search(git_repo, tmp_path, "--module", "frontend")
    assert _names(r2) == ["short.md"], r2.explain()


def test_a2_8_module_list_value_matches_any_element(git_repo, tmp_path):
    _words_lesson(git_repo, "multi.md", "фикстура x", "module: [logger_module, frontend_module/widgets]")
    _words_lesson(git_repo, "other.md", "фикстура x", "module: logger_module_x")
    r = search(git_repo, tmp_path, "--module", "frontend_module")
    assert _names(r) == ["multi.md"], r.explain()
