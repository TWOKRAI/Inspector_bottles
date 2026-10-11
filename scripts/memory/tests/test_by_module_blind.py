"""Слепая приёмка 2.4j: сгенерированный индекс уроков `search.py --by-module` (BY-MODULE*.md).

Источник истины — `plans/2026-10-04_atlas/tasks/2.4j.md`: раздел «Контракт» и «Acceptance criteria».
Реализации тестер не видел. `search.py` зовётся ПОДПРОЦЕССОМ (контракт — CLI); `validate.py`
грузится по пути, как в test_memory_acceptance.py (A1.12).

Правила файла:
- ожидаемые значения — литералы из спеки (имена уроков, слоёв, заголовков, граница 80/81 и
  80000/80001), не пересчёт из кода под тестом. Единственное исключение — реальные данные: там
  ожидание строится по самим урокам через `_lessons.read_lesson` (тот самый единый парсер, спека
  запрещает второй), а не по выводу `--by-module`;
- в окружение подпроцесса НЕ попадают PYTHONUTF8/PYTHONIOENCODING: UTF-8 и LF в файлах обязаны быть
  по контракту, а не по везению окружения прогона;
- cwd подпроцесса — пустой каталог вне git-репо: всё, что зовётся с `--root`, не имеет права читать
  ни cwd, ни main checkout; тесты «без --root» поднимают настоящий git worktree в tmp;
- ничего не пишется в дерево, в котором запущены тесты.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_MEMORY = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
SEARCH_PY = SCRIPTS_MEMORY / "search.py"
TAGS_PY = SCRIPTS_MEMORY / "tags.py"
LESSONS_PY = SCRIPTS_MEMORY / "_lessons.py"
VALIDATE_PY = REPO_ROOT / "scripts" / "validate.py"

MEM = "docs/claude/memory"
TIMEOUT = 60
MAX_FILE_BYTES = 80000  # из спеки

HUB = "BY-MODULE.md"
MECH = "BY-MODULE-mechanism.md"
LAYERS = ("framework", "services", "plugins", "prototype", "tools", "other")  # порядок хаба из спеки


def layer_file(layer: str) -> str:
    return f"BY-MODULE-{layer}.md"


# --------------------------------------------------------------------------- запуск


class Result:
    def __init__(self, cp: subprocess.CompletedProcess):
        self.rc = cp.returncode
        self.out = cp.stdout.decode("utf-8")  # strict: не-UTF-8 вывод — провал теста
        self.err = cp.stderr.decode("utf-8", errors="replace").replace(
            chr(13) + chr(10), chr(10)
        )  # текстовый stderr Windows

    @property
    def lines(self) -> list[str]:
        return [ln for ln in self.out.splitlines() if ln.strip()]

    def explain(self) -> str:
        return f"rc={self.rc}\n--- stdout ---\n{self.out}\n--- stderr ---\n{self.err}"


def _env(tmp_path: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    # tmp лежит внутри чужого git-репо (C:/Users/<user>): без потолка git поднимется выше и найдёт его.
    env["GIT_CEILING_DIRECTORIES"] = str(tmp_path.parent)
    env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = "Fixture"
    env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = "fixture@example.invalid"
    return env


def run_search(args: list[str], *, cwd: Path, tmp_path: Path) -> Result:
    assert SEARCH_PY.is_file(), f"missing script {SEARCH_PY}"
    cp = subprocess.run(
        [sys.executable, str(SEARCH_PY), *args],
        cwd=str(cwd),
        env=_env(tmp_path),
        capture_output=True,
        timeout=TIMEOUT,
    )
    return Result(cp)


def _neutral_cwd(tmp_path: Path) -> Path:
    cwd = tmp_path / "neutral_cwd"
    cwd.mkdir(exist_ok=True)
    return cwd


def bm(root: Path, tmp_path: Path, *flags: str) -> Result:
    """`search.py --by-module <flags> --root <root>` из пустого cwd вне репо."""
    return run_search(["--by-module", *flags, "--root", str(root)], cwd=_neutral_cwd(tmp_path), tmp_path=tmp_path)


def write_ok(root: Path, tmp_path: Path) -> Result:
    r = bm(root, tmp_path, "--write")
    assert r.rc == 0, r.explain()
    return r


def _git(args: list[str], *, cwd: Path, tmp_path: Path) -> str:
    cp = subprocess.run(
        ["git", "-c", "core.longpaths=true", "-c", "core.autocrlf=false", "-c", "init.defaultBranch=main", *args],
        cwd=str(cwd),
        env=_env(tmp_path),
        capture_output=True,
        timeout=TIMEOUT,
    )
    assert cp.returncode == 0, f"git {args}: {cp.stderr.decode('utf-8', 'replace')}"
    return cp.stdout.decode("utf-8", "replace")


# --------------------------------------------------------------------------- фикстуры


def write_bytes(root: Path, rel: str, data: bytes) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)  # write_bytes: на Windows write_text сам подменил бы \n
    return p


def lesson(
    root: Path,
    fname: str,
    *,
    desc: str = "",
    module: tuple[str, ...] | list[str] = (),
    mechanism: tuple[str, ...] | list[str] = (),
    body: str = "Body.\n",
    crlf: bool = False,
    frontmatter: bool = True,
) -> Path:
    if frontmatter:
        esc = desc.replace("\\", "\\\\").replace('"', '\\"')
        head = ["---", f"name: {fname[:-3]}", f'description: "{esc}"']
        if module:
            head.append("module: [" + ", ".join(module) + "]")
        if mechanism:
            head.append("mechanism: [" + ", ".join(mechanism) + "]")
        head += ["metadata:", "  type: feedback", "---"]
        text = "\n".join(head) + "\n" + body
    else:
        text = body
    if crlf:
        text = text.replace("\n", "\r\n")
    return write_bytes(root, f"{MEM}/{fname}", text.encode("utf-8"))


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def index_names(root: Path) -> list[str]:
    return sorted(p.name for p in (root / MEM).glob("BY-MODULE*.md"))


# Литеральная фикстура: шесть уроков, все слои кроме prototype, урок с двумя module одного слоя,
# с двумя module одного слоя через алиас-значения, с двумя mechanism, без mechanism, без module.
MAIN_LESSONS = [
    ("alpha-lesson.md", "альфа alpha", ["logger_module"], ["fixture-trap"]),
    (
        "beta-lesson.md",
        "бета beta",
        ["frontend_module/widgets", "logger_module"],
        ["fixture-trap", "break-injection"],
    ),
    ("gamma-tool.md", "гамма gamma", ["scripts/atlas"], ["break-injection"]),
    ("delta-svc.md", "дельта delta", ["services"], []),
    ("eps-plug.md", "эпсилон epsilon", ["plugins_shared", "plugins"], ["fixture-trap"]),
    ("zeta-nomod.md", "дзета zeta", [], ["break-injection"]),
]
MAIN_STEMS = sorted(f[:-3] for f, *_ in MAIN_LESSONS)


def build_main(root: Path, *, noise: bool = False, crlf: bool = False) -> Path:
    for fname, desc, module, mech in MAIN_LESSONS:
        lesson(root, fname, desc=desc, module=module, mechanism=mech, crlf=crlf)
    write_bytes(root, f"{MEM}/MEMORY.md", "# index\n".encode())
    if noise:
        # всё это НЕ уроки: CRAFT*, MEMORY, ARCHIVE, подкаталог, не-.md
        lesson(root, "CRAFT-extra.md", desc="шум noise", module=["tools"], mechanism=["noise-mech"])
        lesson(root, "ARCHIVE.md", desc="шум noise", module=["tools"], mechanism=["noise-mech"])
        lesson(root, "_archive/old-lesson.md", desc="шум noise", module=["tools"], mechanism=["noise-mech"])
        write_bytes(root, f"{MEM}/notes.txt", b"module: [tools]\n")
    return root


@pytest.fixture
def main_repo(tmp_path: Path) -> Path:
    return build_main(tmp_path / "repo")


def item(stem: str, desc: str | None) -> str:
    return f"- [{stem}]({stem}.md)" + (f" — {desc}" if desc else "")


# ожидаемые разделы слоёв для MAIN_LESSONS — литералы из спеки
A = item("alpha-lesson", "альфа alpha")
B = item("beta-lesson", "бета beta")
G = item("gamma-tool", "гамма gamma")
D = item("delta-svc", "дельта delta")
E = item("eps-plug", "эпсилон epsilon")
Z = item("zeta-nomod", "дзета zeta")

MAIN_LAYER_SECTIONS = {
    "framework": [("frontend_module/widgets (1)", [B]), ("logger_module (2)", [A, B])],
    "services": [("services (1)", [D])],
    "plugins": [("plugins (1)", [E]), ("plugins_shared (1)", [E])],
    "tools": [("scripts/atlas (1)", [G])],
    "other": [("(без module) (1)", [Z])],
}
MAIN_MECH_SECTIONS = [
    (
        "break-injection (3)",
        ["- [beta-lesson](beta-lesson.md)", "- [gamma-tool](gamma-tool.md)", "- [zeta-nomod](zeta-nomod.md)"],
    ),
    (
        "fixture-trap (3)",
        ["- [alpha-lesson](alpha-lesson.md)", "- [beta-lesson](beta-lesson.md)", "- [eps-plug](eps-plug.md)"],
    ),
    ("(без mechanism) (1)", ["- [delta-svc](delta-svc.md)"]),
]
# (слой, модулей, уроков) — по слоям, где есть уроки, в порядке хаба
MAIN_HUB_ROWS = [
    ("framework", "2", "2"),
    ("services", "1", "1"),
    ("plugins", "2", "1"),
    ("tools", "1", "1"),
    ("other", "0", "1"),
]
MAIN_FILE_NAMES = sorted([HUB, MECH, *(layer_file(row[0]) for row in MAIN_HUB_ROWS)])


# --------------------------------------------------------------------------- разбор сгенерированного


def read_text(root: Path, name: str) -> str:
    return (root / MEM / name).read_bytes().decode("utf-8")  # strict


def sections(text: str) -> list[tuple[str, list[str]]]:
    """[(заголовок без `## `, [строки `- ...` раздела])] в порядке файла."""
    out: list[tuple[str, list[str]]] = []
    for ln in text.split("\n"):
        if ln.startswith("## "):
            out.append((ln[3:], []))
        elif ln.startswith("- ") and out:
            out[-1][1].append(ln)
    return out


def _plain(cell: str) -> str:
    m = re.fullmatch(r"\[(.+?)\]\((.+?)\)", cell)
    return m.group(1) if m else cell


def hub_rows(text: str) -> tuple[list[str] | None, list[list[str]]]:
    """(ячейки строки-шапки, строки данных) таблицы хаба; ссылка в ячейке сводится к её тексту."""
    header, rows = None, []
    for ln in text.split("\n"):
        if not ln.startswith("|"):
            continue
        cells = [_plain(c.strip()) for c in ln.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", c) for c in cells):
            continue
        if header is None:
            header = cells
        else:
            rows.append(cells)
    return header, rows


def expected_layer(v: str) -> str:
    """Таблица слоёв из спеки, переписанная вручную (не код под тестом)."""
    seg = v.split("/")[0]
    if seg == "services":
        return "services"
    if seg in ("plugins", "plugins_shared"):
        return "plugins"
    if seg == "prototype":
        return "prototype"
    if seg in ("tools", "scripts"):
        return "tools"
    return "framework"


# --------------------------------------------------------------------------- CLI: режимы и коды выхода


def test_write_prints_wrote_n_files_and_exits_0(main_repo, tmp_path):
    r = bm(main_repo, tmp_path, "--write")
    assert r.rc == 0, r.explain()
    assert r.lines == ["wrote 7 files"], r.explain()  # хаб + 5 слоёв + mechanism


def test_write_creates_exactly_the_expected_file_set(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    assert index_names(main_repo) == MAIN_FILE_NAMES


def test_write_then_check_is_clean(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    r = bm(main_repo, tmp_path, "--check")
    assert r.rc == 0, r.explain()
    assert r.lines == [], r.explain()


@pytest.mark.parametrize(
    "flags",
    [
        ["--by-module"],
        ["--by-module", "--write", "--check"],
        ["--write"],
        ["--check"],
        ["--write", "--check"],
    ],
    ids=["by-module-alone", "write+check", "write-without-by-module", "check-without-by-module", "write+check-without"],
)
def test_bad_flag_combinations_exit_2_and_write_nothing(main_repo, tmp_path, flags):
    before = snapshot(main_repo)
    r = run_search([*flags, "--root", str(main_repo)], cwd=_neutral_cwd(tmp_path), tmp_path=tmp_path)
    assert r.rc == 2, r.explain()
    assert "unrecognized arguments" not in r.err, (
        r.explain()
    )  # флаги должны быть известны, ошибка — от argparse-проверки
    assert snapshot(main_repo) == before
    assert not r.out.startswith("wrote"), r.explain()


def test_search_without_by_module_is_unchanged(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)  # индекс на диске не должен ни попасть в выдачу, ни испортить её
    r = run_search(["--list", "--root", str(main_repo)], cwd=_neutral_cwd(tmp_path), tmp_path=tmp_path)
    assert r.rc == 0, r.explain()
    names = sorted(ln.split(" — ")[0].rsplit("/", 1)[1] for ln in r.lines)
    assert names == [f"{s}.md" for s in MAIN_STEMS]
    r = run_search(["zeta", "--root", str(main_repo)], cwd=_neutral_cwd(tmp_path), tmp_path=tmp_path)
    assert r.rc == 0, r.explain()
    assert [ln.split(" — ")[0].rsplit("/", 1)[1] for ln in r.lines] == ["zeta-nomod.md"], r.explain()


# --------------------------------------------------------------------------- корень по умолчанию (worktree)


def _worktree_pair(tmp_path: Path) -> tuple[Path, Path]:
    main = tmp_path / "main_checkout"
    lesson(main, "shared-lesson.md", desc="общий shared", module=["tools"], mechanism=["fixture-trap"])
    write_bytes(main, f"{MEM}/MEMORY.md", b"# index\n")
    _git(["init", "-q"], cwd=main, tmp_path=tmp_path)
    _git(["add", "-A"], cwd=main, tmp_path=tmp_path)
    _git(["commit", "-q", "-m", "fixture"], cwd=main, tmp_path=tmp_path)
    wt = tmp_path / "linked_worktree"
    _git(["worktree", "add", "-q", "-b", "wt-branch", str(wt)], cwd=main, tmp_path=tmp_path)
    lesson(wt, "wt-only.md", desc="только worktree wt", module=["tools"], mechanism=["fixture-trap"])
    return main, wt


@pytest.mark.parametrize("sub", ["", "docs"], ids=["from-toplevel", "from-subdir"])
def test_default_root_is_the_current_worktree_not_main_checkout(tmp_path, sub):
    main, wt = _worktree_pair(tmp_path)
    cwd = wt / sub if sub else wt
    r = run_search(["--by-module", "--write"], cwd=cwd, tmp_path=tmp_path)
    assert r.rc == 0, r.explain()
    assert r.lines == ["wrote 3 files"], r.explain()  # хаб + tools + mechanism
    assert index_names(wt) == sorted([HUB, layer_file("tools"), MECH])
    assert "[wt-only](wt-only.md)" in read_text(wt, layer_file("tools"))
    assert index_names(main) == [], "индекс записан в main checkout"
    r = run_search(["--by-module", "--check"], cwd=cwd, tmp_path=tmp_path)
    assert r.rc == 0, r.explain()


def test_default_root_check_looks_at_the_current_tree_only(tmp_path):
    main, wt = _worktree_pair(tmp_path)
    assert run_search(["--by-module", "--write"], cwd=wt, tmp_path=tmp_path).rc == 0
    # main checkout без индекса: проверка из него — missing, а не зелёное по соседнему дереву
    r = run_search(["--by-module", "--check"], cwd=main, tmp_path=tmp_path)
    assert r.rc == 1, r.explain()
    assert sorted(r.lines) == sorted([f"missing: {HUB}", f"missing: {layer_file('tools')}", f"missing: {MECH}"]), (
        r.explain()
    )
    assert index_names(main) == []


# --------------------------------------------------------------------------- содержимое файлов


def test_hub_notice_header_table_and_mechanism_link(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    text = read_text(main_repo, HUB)
    assert any(ln.startswith("# ") for ln in text.split("\n")), "в хабе нет заголовка"
    assert "Сгенерировано: `python scripts/memory/search.py --by-module --write`; не править вручную" in text
    header, rows = hub_rows(text)
    assert header == ["слой", "файл", "модулей", "уроков"]
    assert [(r[0], r[2], r[3]) for r in rows] == MAIN_HUB_ROWS
    assert [r[1] for r in rows] == [layer_file(r[0]) for r in MAIN_HUB_ROWS]
    assert MECH in text


@pytest.mark.parametrize("layer", list(MAIN_LAYER_SECTIONS))
def test_layer_file_sections_and_lines(main_repo, tmp_path, layer):
    write_ok(main_repo, tmp_path)
    assert sections(read_text(main_repo, layer_file(layer))) == MAIN_LAYER_SECTIONS[layer]


def test_mechanism_file_sections_and_lines(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    assert sections(read_text(main_repo, MECH)) == MAIN_MECH_SECTIONS


def test_mechanism_lines_have_no_description(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    items = [ln for _, lines in sections(read_text(main_repo, MECH)) for ln in lines]
    assert items and all(" — " not in ln for ln in items)


def test_lesson_with_two_modules_is_under_both_and_counted_once_in_hub(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    secs = dict(sections(read_text(main_repo, layer_file("plugins"))))
    assert E in secs["plugins (1)"] and E in secs["plugins_shared (1)"]
    _, rows = hub_rows(read_text(main_repo, HUB))
    plugins = next(r for r in rows if r[0] == "plugins")
    assert (plugins[2], plugins[3]) == ("2", "1")  # 2 значения module, 1 разный урок


def test_lesson_with_two_mechanisms_is_under_both(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    secs = dict(sections(read_text(main_repo, MECH)))
    beta = "- [beta-lesson](beta-lesson.md)"
    assert beta in secs["break-injection (3)"] and beta in secs["fixture-trap (3)"]


def test_lesson_with_modules_in_two_layers_is_in_both_layer_files(tmp_path):
    root = tmp_path / "repo"
    lesson(root, "cross.md", desc="кросс cross", module=["services", "tools"], mechanism=["m"])
    write_ok(root, tmp_path)
    assert index_names(root) == sorted([HUB, MECH, layer_file("services"), layer_file("tools")])
    line = item("cross", "кросс cross")
    assert sections(read_text(root, layer_file("services"))) == [("services (1)", [line])]
    assert sections(read_text(root, layer_file("tools"))) == [("tools (1)", [line])]
    _, rows = hub_rows(read_text(root, HUB))
    assert [(r[0], r[2], r[3]) for r in rows] == [("services", "1", "1"), ("tools", "1", "1")]


def test_noise_files_are_not_lessons(tmp_path):
    root = build_main(tmp_path / "repo", noise=True)
    r = write_ok(root, tmp_path)
    assert r.lines == ["wrote 7 files"], r.explain()
    assert sections(read_text(root, layer_file("tools"))) == MAIN_LAYER_SECTIONS["tools"]
    assert sections(read_text(root, MECH)) == MAIN_MECH_SECTIONS
    assert "noise" not in "".join(read_text(root, n) for n in index_names(root))


def test_lessons_without_frontmatter_or_module_go_to_other(tmp_path):
    root = tmp_path / "repo"
    lesson(root, "nofm.md", frontmatter=False, body="# просто текст\n")
    lesson(root, "empty-mod.md", desc="пусто empty", mechanism=["x"])
    r = write_ok(root, tmp_path)
    assert r.lines == ["wrote 3 files"], r.explain()  # хаб + other + mechanism
    assert index_names(root) == sorted([HUB, MECH, layer_file("other")])
    assert sections(read_text(root, layer_file("other"))) == [
        ("(без module) (2)", ["- [empty-mod](empty-mod.md) — пусто empty", "- [nofm](nofm.md)"])
    ]
    assert sections(read_text(root, MECH)) == [
        ("x (1)", ["- [empty-mod](empty-mod.md)"]),
        ("(без mechanism) (1)", ["- [nofm](nofm.md)"]),
    ]
    header, rows = hub_rows(read_text(root, HUB))
    assert [(r[0], r[1], r[2], r[3]) for r in rows] == [("other", layer_file("other"), "0", "2")]


def test_without_mechanism_section_is_last_even_after_late_sorting_names(tmp_path):
    root = tmp_path / "repo"
    lesson(root, "late.md", desc="поздний late", module=["tools"], mechanism=["zzz-last"])
    lesson(root, "bare.md", desc="голый bare", module=["tools"])
    write_ok(root, tmp_path)
    assert [h for h, _ in sections(read_text(root, MECH))] == ["zzz-last (1)", "(без mechanism) (1)"]


def test_no_without_mechanism_section_when_every_lesson_has_one(tmp_path):
    root = tmp_path / "repo"
    lesson(root, "one.md", desc="один one", module=["tools"], mechanism=["m"])
    write_ok(root, tmp_path)
    assert [h for h, _ in sections(read_text(root, MECH))] == ["m (1)"]


# --------------------------------------------------------------------------- слой по таблице


@pytest.mark.parametrize(
    ("module", "layer"),
    [
        ("services", "services"),
        ("services/sub", "services"),
        ("plugins", "plugins"),
        ("plugins_shared", "plugins"),
        ("plugins/x", "plugins"),
        ("plugins_shared/sub", "plugins"),
        ("prototype", "prototype"),
        ("prototype/gui", "prototype"),
        ("tools", "tools"),
        ("scripts", "tools"),
        ("scripts/atlas", "tools"),
        ("tools/x", "tools"),
        ("frontend_module/widgets", "framework"),
        ("process_module/generic", "framework"),
        ("framework_meta", "framework"),
        ("logger_module", "framework"),
        ("scripts_old", "framework"),
        ("services_x", "framework"),
        ("plugin", "framework"),
        ("prototypes", "framework"),
    ],
)
def test_layer_by_module_value(tmp_path, module, layer):
    root = tmp_path / "repo"
    lesson(root, "only.md", desc="один one", module=[module], mechanism=["m"])
    write_ok(root, tmp_path)
    assert index_names(root) == sorted([HUB, MECH, layer_file(layer)])
    assert sections(read_text(root, layer_file(layer))) == [(f"{module} (1)", [item("only", "один one")])]


def test_module_sections_are_sorted_by_value(tmp_path):
    root = tmp_path / "repo"
    for i, mod in enumerate(
        ["process_module/generic", "logger_module", "framework_meta", "frontend_module/widgets", "frontend_module"]
    ):
        lesson(root, f"l{i}.md", desc="д d", module=[mod], mechanism=["m"])
    write_ok(root, tmp_path)
    heads = [h for h, _ in sections(read_text(root, layer_file("framework")))]
    assert heads == [
        "framework_meta (1)",
        "frontend_module (1)",
        "frontend_module/widgets (1)",
        "logger_module (1)",
        "process_module/generic (1)",
    ]


def test_mechanism_sections_are_sorted_by_value(tmp_path):
    root = tmp_path / "repo"
    lesson(root, "l.md", desc="д d", module=["tools"], mechanism=["zeta-mech", "alpha-mech", "mid-mech"])
    write_ok(root, tmp_path)
    assert [h for h, _ in sections(read_text(root, MECH))] == ["alpha-mech (1)", "mid-mech (1)", "zeta-mech (1)"]


# --------------------------------------------------------------------------- описание


D80 = "0123456789" * 8
D81 = D80 + "X"


@pytest.mark.parametrize(
    ("desc", "expected_tail"),
    [
        ("abc", " — abc"),
        (D80, f" — {D80}"),
        (D81, " — " + "0123456789" * 7 + "012345678" + "…"),
        ("я" * 80, " — " + "я" * 80),
        ("я" * 81, " — " + "я" * 79 + "…"),
        ("a" * 78 + " " + "b" * 10, " — " + "a" * 78 + " " + "…"),  # первые 79 символов дословно, без rstrip
        ("", ""),
    ],
    ids=["short", "exactly-80", "81-truncated", "cyr-80", "cyr-81", "space-at-79", "empty"],
)
def test_description_truncation_boundary(tmp_path, desc, expected_tail):
    root = tmp_path / "repo"
    lesson(root, "d-lesson.md", desc=desc, module=["tools"], mechanism=["m"])
    write_ok(root, tmp_path)
    assert sections(read_text(root, layer_file("tools"))) == [
        ("tools (1)", [f"- [d-lesson](d-lesson.md){expected_tail}"])
    ]


def test_truncated_description_is_exactly_80_chars(tmp_path):
    root = tmp_path / "repo"
    lesson(root, "d-lesson.md", desc=D81, module=["tools"], mechanism=["m"])
    write_ok(root, tmp_path)
    (line,) = sections(read_text(root, layer_file("tools")))[0][1]
    desc = line.split(" — ", 1)[1]
    assert (len(desc), desc[-1]) == (80, "…")


# --------------------------------------------------------------------------- детерминизм и формат


def test_two_writes_are_byte_identical(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    first = {n: (main_repo / MEM / n).read_bytes() for n in index_names(main_repo)}
    r = write_ok(main_repo, tmp_path)
    assert r.lines == ["wrote 7 files"]
    assert {n: (main_repo / MEM / n).read_bytes() for n in index_names(main_repo)} == first


def test_output_does_not_depend_on_lesson_creation_order(tmp_path):
    a = build_main(tmp_path / "a")
    b = tmp_path / "b"
    for fname, desc, module, mech in reversed(MAIN_LESSONS):
        lesson(b, fname, desc=desc, module=module, mechanism=mech)
    write_bytes(b, f"{MEM}/MEMORY.md", b"# index\n")
    write_ok(a, tmp_path)
    write_ok(b, tmp_path)
    assert {n: (a / MEM / n).read_bytes() for n in index_names(a)} == {
        n: (b / MEM / n).read_bytes() for n in index_names(b)
    }


@pytest.mark.parametrize("crlf_lessons", [False, True], ids=["lf-lessons", "crlf-lessons"])
@pytest.mark.parametrize("name", MAIN_FILE_NAMES)
def test_file_format_lf_utf8_no_bom_one_final_newline_no_dates(tmp_path, name, crlf_lessons):
    root = build_main(tmp_path / "repo", crlf=crlf_lessons)
    write_ok(root, tmp_path)
    data = (root / MEM / name).read_bytes()
    assert b"\r" not in data
    assert not data.startswith(b"\xef\xbb\xbf")
    assert data.endswith(b"\n") and not data.endswith(b"\n\n")
    text = data.decode("utf-8")
    assert not re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}:\d{2}", text), "в сгенерированном файле дата или время"


def test_crlf_lessons_produce_same_bytes_as_lf_lessons(tmp_path):
    lf, crlf = build_main(tmp_path / "lf"), build_main(tmp_path / "crlf", crlf=True)
    write_ok(lf, tmp_path)
    write_ok(crlf, tmp_path)
    assert {n: (lf / MEM / n).read_bytes() for n in index_names(lf)} == {
        n: (crlf / MEM / n).read_bytes() for n in index_names(crlf)
    }


# --------------------------------------------------------------------------- --check: что считается устаревшим


def _first_ascii_letter(data: bytes) -> int:
    return next(i for i, b in enumerate(data) if chr(b).isalpha() and b < 128)


def _mut_append(data: bytes) -> bytes:
    return data + b" "


def _mut_flip(data: bytes) -> bytes:
    i = _first_ascii_letter(data)
    return data[:i] + (b"Z" if data[i : i + 1] != b"Z" else b"Y") + data[i + 1 :]


def _mut_crlf(data: bytes) -> bytes:
    return data.replace(b"\n", b"\r\n")


@pytest.mark.parametrize("mutate", [_mut_append, _mut_flip, _mut_crlf], ids=["append-byte", "change-byte", "crlf"])
@pytest.mark.parametrize("name", MAIN_FILE_NAMES)
def test_check_flags_any_changed_generated_file_as_stale(main_repo, tmp_path, name, mutate):
    write_ok(main_repo, tmp_path)
    p = main_repo / MEM / name
    p.write_bytes(mutate(p.read_bytes()))
    r = bm(main_repo, tmp_path, "--check")
    assert r.rc == 1, r.explain()
    assert r.lines == [f"stale: {name}"], r.explain()


@pytest.mark.parametrize("name", MAIN_FILE_NAMES)
def test_check_flags_deleted_file_as_missing(main_repo, tmp_path, name):
    write_ok(main_repo, tmp_path)
    (main_repo / MEM / name).unlink()
    r = bm(main_repo, tmp_path, "--check")
    assert r.rc == 1, r.explain()
    assert r.lines == [f"missing: {name}"], r.explain()


@pytest.mark.parametrize("extra", ["BY-MODULE-x.md", "BY-MODULE-nosuchlayer.md", "BY-MODULEjunk.md"])
def test_check_flags_foreign_file_as_extra(main_repo, tmp_path, extra):
    write_ok(main_repo, tmp_path)
    write_bytes(main_repo, f"{MEM}/{extra}", b"# hand made\n")
    r = bm(main_repo, tmp_path, "--check")
    assert r.rc == 1, r.explain()
    assert r.lines == [f"extra: {extra}"], r.explain()


@pytest.mark.parametrize("name", ["BY-MODULE-x.txt", "BY-MODULE.md.bak"])
def test_check_ignores_files_that_are_not_by_module_md(main_repo, tmp_path, name):
    write_ok(main_repo, tmp_path)
    write_bytes(main_repo, f"{MEM}/{name}", b"junk\n")
    r = bm(main_repo, tmp_path, "--check")
    assert r.rc == 0, r.explain()


def test_check_lines_are_one_per_file_in_name_order(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    p = main_repo / MEM / layer_file("framework")
    p.write_bytes(p.read_bytes() + b" ")
    (main_repo / MEM / layer_file("tools")).unlink()
    write_bytes(main_repo, f"{MEM}/BY-MODULE-zzz.md", b"x\n")
    r = bm(main_repo, tmp_path, "--check")
    assert r.rc == 1, r.explain()
    assert r.lines == ["stale: BY-MODULE-framework.md", "missing: BY-MODULE-tools.md", "extra: BY-MODULE-zzz.md"], (
        r.explain()
    )


def test_check_description_edit_makes_only_its_layer_stale(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    lesson(
        main_repo,
        "alpha-lesson.md",
        desc="другое описание changed",
        module=["logger_module"],
        mechanism=["fixture-trap"],
    )
    r = bm(main_repo, tmp_path, "--check")
    assert r.rc == 1, r.explain()
    assert r.lines == ["stale: BY-MODULE-framework.md"], r.explain()


def test_check_description_edit_in_tools_lesson_makes_only_tools_stale(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    lesson(main_repo, "gamma-tool.md", desc="иное other", module=["scripts/atlas"], mechanism=["break-injection"])
    r = bm(main_repo, tmp_path, "--check")
    assert r.rc == 1, r.explain()
    assert r.lines == ["stale: BY-MODULE-tools.md"], r.explain()


def test_check_body_edit_is_not_stale(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    for fname, desc, module, mech in MAIN_LESSONS:
        lesson(
            main_repo, fname, desc=desc, module=module, mechanism=mech, body="Совсем другое тело.\nSecond body line.\n"
        )
    r = bm(main_repo, tmp_path, "--check")
    assert r.rc == 0, r.explain()


def test_check_mechanism_edit_makes_only_mechanism_file_stale(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    lesson(main_repo, "alpha-lesson.md", desc="альфа alpha", module=["logger_module"], mechanism=["break-injection"])
    r = bm(main_repo, tmp_path, "--check")
    assert r.rc == 1, r.explain()
    assert r.lines == [f"stale: {MECH}"], r.explain()


def test_check_module_edit_within_layer_makes_only_that_layer_stale(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    lesson(main_repo, "gamma-tool.md", desc="гамма gamma", module=["scripts/other"], mechanism=["break-injection"])
    r = bm(main_repo, tmp_path, "--check")
    assert r.rc == 1, r.explain()
    assert r.lines == ["stale: BY-MODULE-tools.md"], r.explain()


def test_check_lesson_moved_to_another_layer(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    lesson(main_repo, "gamma-tool.md", desc="гамма gamma", module=["services"], mechanism=["break-injection"])
    r = bm(main_repo, tmp_path, "--check")
    assert r.rc == 1, r.explain()
    assert sorted(r.lines) == sorted(
        [f"extra: {layer_file('tools')}", f"stale: {layer_file('services')}", f"stale: {HUB}"]
    ), r.explain()


def test_check_new_lesson_in_existing_layer(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    lesson(main_repo, "new-one.md", desc="новый new", module=["logger_module"], mechanism=["fixture-trap"])
    r = bm(main_repo, tmp_path, "--check")
    assert r.rc == 1, r.explain()
    assert sorted(r.lines) == sorted([f"stale: {layer_file('framework')}", f"stale: {HUB}", f"stale: {MECH}"]), (
        r.explain()
    )


def test_check_first_lesson_of_a_new_layer_is_missing(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    lesson(main_repo, "proto-new.md", desc="прото proto", module=["prototype/gui"], mechanism=["fixture-trap"])
    r = bm(main_repo, tmp_path, "--check")
    assert r.rc == 1, r.explain()
    assert f"missing: {layer_file('prototype')}" in r.lines, r.explain()
    assert sorted(r.lines) == sorted([f"missing: {layer_file('prototype')}", f"stale: {HUB}", f"stale: {MECH}"]), (
        r.explain()
    )


def test_check_deleted_lesson_orphans_its_layer_file_as_extra(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    (main_repo / MEM / "delta-svc.md").unlink()  # единственный урок слоя services
    r = bm(main_repo, tmp_path, "--check")
    assert r.rc == 1, r.explain()
    assert f"extra: {layer_file('services')}" in r.lines, r.explain()


def test_generated_file_with_lesson_frontmatter_is_not_a_lesson(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    lesson(main_repo, "BY-MODULE-x.md", desc="притворяется pretender", module=["tools"], mechanism=["m"])
    r = bm(main_repo, tmp_path, "--check")
    assert r.rc == 1, r.explain()
    assert r.lines == ["extra: BY-MODULE-x.md"], r.explain()  # а не stale у tools/mechanism из-за «урока»


# --------------------------------------------------------------------------- --write: чистка и границы записи


def test_write_removes_every_foreign_by_module_md_and_check_is_clean(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    write_bytes(main_repo, f"{MEM}/BY-MODULE-x.md", b"x\n")
    write_bytes(main_repo, f"{MEM}/BY-MODULEjunk.md", b"x\n")
    write_bytes(main_repo, f"{MEM}/BY-MODULE-nosuchlayer.md", b"x\n")
    r = write_ok(main_repo, tmp_path)
    assert r.lines == ["wrote 7 files"], r.explain()
    assert index_names(main_repo) == MAIN_FILE_NAMES
    assert bm(main_repo, tmp_path, "--check").rc == 0


def test_write_removes_layer_file_of_a_layer_that_lost_all_lessons(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    (main_repo / MEM / "delta-svc.md").unlink()
    r = write_ok(main_repo, tmp_path)
    assert r.lines == ["wrote 6 files"], r.explain()
    assert layer_file("services") not in index_names(main_repo)
    assert bm(main_repo, tmp_path, "--check").rc == 0


def test_write_repairs_every_kind_of_drift(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    good = {n: (main_repo / MEM / n).read_bytes() for n in index_names(main_repo)}
    (main_repo / MEM / HUB).write_bytes(b"corrupt\n")
    (main_repo / MEM / layer_file("tools")).unlink()
    write_ok(main_repo, tmp_path)
    assert {n: (main_repo / MEM / n).read_bytes() for n in index_names(main_repo)} == good


def test_write_touches_only_by_module_files(tmp_path):
    root = build_main(tmp_path / "repo", noise=True)
    write_bytes(root, "modules.yaml", b"modules: []\n")
    write_bytes(root, "other_dir/keep.md", b"keep\n")
    before = {k: v for k, v in snapshot(root).items() if not k.startswith(f"{MEM}/BY-MODULE")}
    write_ok(root, tmp_path)
    after = {k: v for k, v in snapshot(root).items() if not k.startswith(f"{MEM}/BY-MODULE")}
    assert after == before
    assert sorted(p.name for p in (root / MEM).iterdir() if p.is_file()) == sorted(
        {p.name for p in (root / MEM).iterdir() if p.is_file() and not p.name.startswith("BY-MODULE")}
        | set(MAIN_FILE_NAMES)
    )


@pytest.mark.parametrize("mode", ["--write", "--check"])
def test_nothing_is_written_outside_root_or_into_cwd(tmp_path, mode):
    root = build_main(tmp_path / "repo")
    outside = tmp_path / "outside"
    write_bytes(outside, "docs/claude/memory/BY-MODULE.md", b"foreign\n")
    write_bytes(outside, "sibling.txt", b"s\n")
    out_before = snapshot(outside)
    cwd = _neutral_cwd(tmp_path)
    r = run_search(["--by-module", mode, "--root", str(root)], cwd=cwd, tmp_path=tmp_path)
    assert r.rc in (0, 1), r.explain()
    assert snapshot(outside) == out_before
    assert list(cwd.iterdir()) == []
    if mode == "--check":
        assert index_names(root) == [], "--check записал файлы"


def test_check_does_not_modify_the_tree_even_when_everything_is_stale(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    p = main_repo / MEM / HUB
    p.write_bytes(p.read_bytes() + b" ")
    write_bytes(main_repo, f"{MEM}/BY-MODULE-x.md", b"x\n")
    (main_repo / MEM / MECH).unlink()
    before = snapshot(main_repo)
    assert bm(main_repo, tmp_path, "--check").rc == 1
    assert snapshot(main_repo) == before


# --------------------------------------------------------------------------- сгенерированные файлы — не уроки


def test_generated_files_are_not_in_search_list(main_repo, tmp_path):
    write_ok(main_repo, tmp_path)
    r = run_search(["--list", "--root", str(main_repo)], cwd=_neutral_cwd(tmp_path), tmp_path=tmp_path)
    assert r.rc == 0, r.explain()
    assert len(r.lines) == 6
    assert "BY-MODULE" not in r.out


def test_hand_made_by_module_named_file_is_not_a_lesson_for_search(tmp_path):
    root = build_main(tmp_path / "repo")
    lesson(root, "BY-MODULE-x.md", desc="притворяется pretender", module=["tools"], mechanism=["m"])
    r = run_search(["--list", "--root", str(root)], cwd=_neutral_cwd(tmp_path), tmp_path=tmp_path)
    assert r.rc == 0, r.explain()
    assert len(r.lines) == 6 and "BY-MODULE" not in r.out, r.explain()
    r = run_search(["pretender", "--root", str(root)], cwd=_neutral_cwd(tmp_path), tmp_path=tmp_path)
    assert r.lines == ["none"], r.explain()


def _tag_repo(root: Path) -> Path:
    """Репо, проходящее tags.py --check: раскладка корня и словари — как в test_memory_acceptance.make_repo."""
    write_bytes(
        root,
        "modules.yaml",
        (
            b"modules:\n  - id: logger_module\n    path: logger_module\n"
            b"  - id: frontend_module\n    path: frontend_module\n"
        ),
    )
    for role in ("tester", "developer"):
        write_bytes(root, f".claude/agents/dev/{role}.md", f"# {role}\n".encode())
    write_bytes(
        root,
        f"{MEM}/TAGS.yaml",
        (
            b'mechanisms:\n  - id: break-injection\n    def: "def of break-injection"\n'
            b'  - id: fixture-trap\n    def: "def of fixture-trap"\n'
        ),
    )
    write_bytes(root, f"{MEM}/MEMORY.md", b"# index\n")
    lesson(root, "l-one.md", desc="фикстура fixture", module=["logger_module"], mechanism=["fixture-trap"])
    lesson(root, "l-two.md", desc="фикстура fixture", module=["frontend_module"], mechanism=["break-injection"])
    return root


def _tags_check(root: Path, tmp_path: Path) -> Result:
    cp = subprocess.run(
        [sys.executable, str(TAGS_PY), "--check", "--root", str(root)],
        cwd=str(_neutral_cwd(tmp_path)),
        env=_env(tmp_path),
        capture_output=True,
        timeout=TIMEOUT,
    )
    return Result(cp)


def test_tags_check_control_a_hand_made_non_lesson_file_is_flagged(tmp_path):
    root = _tag_repo(tmp_path / "repo")
    assert _tags_check(root, tmp_path).rc == 0
    write_bytes(root, f"{MEM}/zz-hand-made.md", b"# no frontmatter\n")
    assert _tags_check(root, tmp_path).rc == 1  # контроль: без исключения BY-MODULE такой файл красит tags.py


def test_tags_check_ignores_generated_index_files(tmp_path):
    root = _tag_repo(tmp_path / "repo")
    write_ok(root, tmp_path)
    assert index_names(root) == sorted([HUB, MECH, layer_file("framework")])
    r = _tags_check(root, tmp_path)
    assert r.rc == 0, r.explain()
    assert r.lines == [], r.explain()


def test_tags_check_ignores_by_module_named_file_without_frontmatter(tmp_path):
    root = _tag_repo(tmp_path / "repo")
    write_bytes(root, f"{MEM}/BY-MODULE-handmade.md", b"# no frontmatter\n")
    r = _tags_check(root, tmp_path)
    assert r.rc == 0, r.explain()


# --------------------------------------------------------------------------- реальные данные


def _load_lessons_module():
    spec = importlib.util.spec_from_file_location("lessons_oracle", LESSONS_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_HEAD = re.compile(r"^(?P<value>.+) \((?P<n>\d+)\)$")
_ITEM = re.compile(r"^- \[(?P<stem>[^\]]+)\]\((?P<file>[^)]+)\)")


_CACHE: dict = {}


def _real_tree(tmp_path_factory):
    if "real" in _CACHE:
        return _CACHE["real"]
    tmp = tmp_path_factory.mktemp("real")
    root = tmp / "real_repo"
    shutil.copytree(REPO_ROOT / MEM, root / MEM)
    r = write_ok(root, tmp)
    list_cp = run_search(["--list", "--root", str(root)], cwd=_neutral_cwd(tmp), tmp_path=tmp)
    assert list_cp.rc == 0, list_cp.explain()
    stems = [ln.split(" — ")[0].rsplit("/", 1)[1][:-3] for ln in list_cp.lines]
    _CACHE["real"] = (root, tmp, r, stems)
    return _CACHE["real"]


def test_real_data_every_file_within_the_size_limit(tmp_path_factory):
    real_tree = _real_tree(tmp_path_factory)
    root, _, r, _ = real_tree
    names = index_names(root)
    assert HUB in names and MECH in names
    assert set(names) <= {HUB, MECH, *(layer_file(lay) for lay in LAYERS)}
    for n in names:
        size = len((root / MEM / n).read_bytes())
        assert size <= MAX_FILE_BYTES, f"{n}: {size} байт"
    assert r.lines == [f"wrote {len(names)} files"]


def test_real_data_layer_files_cover_exactly_the_listed_lessons(tmp_path_factory):
    real_tree = _real_tree(tmp_path_factory)
    root, _, _, stems = real_tree
    assert len(stems) == len(set(stems)) and stems
    covered = set()
    for lay in LAYERS:
        if (root / MEM / layer_file(lay)).is_file():
            for _, lines in sections(read_text(root, layer_file(lay))):
                for ln in lines:
                    m = _ITEM.match(ln)
                    assert m and m["file"] == m["stem"] + ".md", ln
                    covered.add(m["stem"])
    assert covered == set(stems)


def test_real_data_line_count_is_sum_of_max_1_and_module_count(tmp_path_factory):
    real_tree = _real_tree(tmp_path_factory)
    root, _, _, stems = real_tree
    lessons = _load_lessons_module()
    expected = sum(max(1, len(lessons.read_lesson(root / MEM / f"{s}.md")["module"])) for s in stems)
    actual = sum(
        len(lines)
        for lay in LAYERS
        if (root / MEM / layer_file(lay)).is_file()
        for _, lines in sections(read_text(root, layer_file(lay)))
    )
    assert actual == expected


def test_real_data_every_module_value_sits_in_its_layer_file_in_sorted_order(tmp_path_factory):
    real_tree = _real_tree(tmp_path_factory)
    root, _, _, _ = real_tree
    lessons = _load_lessons_module()
    for lay in LAYERS:
        p = root / MEM / layer_file(lay)
        if not p.is_file():
            continue
        heads = [h for h, _ in sections(p.read_bytes().decode("utf-8"))]
        values = []
        for h in heads:
            m = _HEAD.match(h)
            assert m, h
            values.append(m["value"])
        if lay == "other":
            assert values == ["(без module)"]
            continue
        assert values == sorted(values) and len(values) == len(set(values))
        assert all(expected_layer(v) == lay for v in values), f"{lay}: {values}"
        for h, lines in sections(p.read_bytes().decode("utf-8")):
            assert int(_HEAD.match(h)["n"]) == len(lines)
            names = [_ITEM.match(ln)["file"] for ln in lines]
            assert names == sorted(names), h
    # каждое значение module: из уроков встречается заголовком
    all_values = set()
    for stem in real_tree[3]:
        all_values |= set(lessons.read_lesson(root / MEM / f"{stem}.md")["module"])
    seen = {
        _HEAD.match(h)["value"]
        for lay in LAYERS
        if lay != "other" and (root / MEM / layer_file(lay)).is_file()
        for h, _ in sections(read_text(root, layer_file(lay)))
    }
    assert seen == all_values


def test_real_data_mechanism_file_covers_every_lesson_and_mechanism(tmp_path_factory):
    real_tree = _real_tree(tmp_path_factory)
    root, _, _, stems = real_tree
    lessons = _load_lessons_module()
    secs = sections(read_text(root, MECH))
    heads = [_HEAD.match(h)["value"] for h, _ in secs]
    has_bare = bool(heads) and heads[-1] == "(без mechanism)"
    named = heads[:-1] if has_bare else heads
    assert named == sorted(named) and len(set(named)) == len(named)
    expected_values, bare = set(), set()
    for s in stems:
        mech = lessons.read_lesson(root / MEM / f"{s}.md")["mechanism"]
        expected_values |= set(mech)
        if not mech:
            bare.add(s)
    assert set(named) == expected_values
    assert has_bare == bool(bare)
    covered = {_ITEM.match(ln)["stem"] for _, lines in secs for ln in lines}
    assert covered == set(stems)


def test_real_data_hub_rows_match_the_layer_files(tmp_path_factory):
    real_tree = _real_tree(tmp_path_factory)
    root, _, _, _ = real_tree
    header, rows = hub_rows(read_text(root, HUB))
    assert header == ["слой", "файл", "модулей", "уроков"]
    present = [lay for lay in LAYERS if (root / MEM / layer_file(lay)).is_file()]
    assert [r[0] for r in rows] == present
    for r in rows:
        secs = sections(read_text(root, r[1]))
        assert r[1] == layer_file(r[0])
        assert int(r[2]) == (0 if r[0] == "other" else len(secs))
        assert int(r[3]) == len({_ITEM.match(ln)["stem"] for _, lines in secs for ln in lines})


def test_real_data_second_write_is_identical_and_check_is_clean(tmp_path_factory):
    real_tree = _real_tree(tmp_path_factory)
    root, tmp, _, _ = real_tree
    first = {n: (root / MEM / n).read_bytes() for n in index_names(root)}
    write_ok(root, tmp)
    assert {n: (root / MEM / n).read_bytes() for n in index_names(root)} == first
    r = bm(root, tmp, "--check")
    assert r.rc == 0, r.explain()
    assert r.lines == []


def test_real_data_generated_files_are_not_in_list_or_tags_check(tmp_path_factory):
    real_tree = _real_tree(tmp_path_factory)
    root, tmp, _, stems = real_tree
    assert not any(s.startswith("BY-MODULE") for s in stems)


# --------------------------------------------------------------------------- MAX_FILE_BYTES


def _tools_tree(root: Path, n: int, tune_desc: str) -> Path:
    """n уроков с тремя module слоя tools (строка слоя — по 20 байт, три строки на урок) и один «подгонщик»."""
    for i in range(n):
        lesson(root, f"f{i:04x}.md", module=["tools/a", "tools/b", "tools/c"], mechanism=["m"])
    lesson(root, "tune.md", desc=tune_desc, module=["tools/a"], mechanism=["m"])
    return root


def _tools_size(tmp: Path, tag: str, n: int, tune_desc: str) -> int:
    root = _tools_tree(tmp / f"cal_{tag}", n, tune_desc)
    r = bm(root, tmp, "--write")
    if r.rc != 0:
        pytest.fail(f"калибровка фикстуры: --write rc={r.rc}\n{r.explain()}")
    return len((root / MEM / layer_file("tools")).read_bytes())


def _limit_case(tmp_path_factory):
    if "limit" in _CACHE:
        return _CACHE["limit"]
    """(n, t): дерево из n уроков и подгонщика с описанием из t символов даёт BY-MODULE-tools.md ровно 80000 байт.

    Размер замеряется самим скриптом ТОЛЬКО для подгонки фикстуры; сами проверки границы
    (80000 проходит, 80001 — `too big`) — от литералов спеки.
    """
    tmp = tmp_path_factory.mktemp("limit")
    s1 = _tools_size(tmp, "a", 1000, "")
    s2 = _tools_size(tmp, "b", 1100, "")
    per_lesson, rest = divmod(s2 - s1, 100)
    if rest or per_lesson <= 0:
        pytest.fail(f"калибровка фикстуры: размер не линеен по числу уроков ({s1}, {s2})")
    n = 1100 + (MAX_FILE_BYTES - 6 - s2) // per_lesson
    s = _tools_size(tmp, "c", n, "")
    gap = MAX_FILE_BYTES - s
    # описание в строке слоя стоит за « — » (1 + 3 байта em dash + 1 = 5 байт), затем t символов
    if not 6 <= gap <= 85:
        pytest.fail(f"калибровка фикстуры: зазор {gap} вне 6..85 (n={n}, size={s})")
    _CACHE["limit"] = (n, gap - 5, tmp)
    return _CACHE["limit"]


def test_file_of_exactly_80000_bytes_is_written(tmp_path_factory, tmp_path):
    limit_case = _limit_case(tmp_path_factory)
    n, t, _ = limit_case
    root = _tools_tree(tmp_path / "repo", n, "x" * t)
    r = bm(root, tmp_path, "--write")
    assert r.rc == 0, r.explain()
    assert len((root / MEM / layer_file("tools")).read_bytes()) == MAX_FILE_BYTES


def test_file_of_80001_bytes_is_refused_in_write_mode_and_nothing_is_written(tmp_path_factory, tmp_path):
    limit_case = _limit_case(tmp_path_factory)
    n, t, _ = limit_case
    root = _tools_tree(tmp_path / "repo", n, "x" * (t + 1))
    write_bytes(root, f"{MEM}/BY-MODULE.md", b"old hub\n")
    write_bytes(root, f"{MEM}/BY-MODULE-old.md", b"old extra\n")
    before = snapshot(root)
    r = bm(root, tmp_path, "--write")
    assert r.rc == 2, r.explain()
    assert re.findall(r"^too big: .*$", r.err, re.M) == [f"too big: {layer_file('tools')} 80001"], r.explain()
    assert snapshot(root) == before, "при too big записаны или удалены файлы"


def test_file_of_80001_bytes_is_refused_in_check_mode(tmp_path_factory, tmp_path):
    limit_case = _limit_case(tmp_path_factory)
    n, t, _ = limit_case
    root = _tools_tree(tmp_path / "repo", n, "x" * (t + 1))
    before = snapshot(root)
    r = bm(root, tmp_path, "--check")
    assert r.rc == 2, r.explain()
    assert re.findall(r"^too big: .*$", r.err, re.M) == [f"too big: {layer_file('tools')} 80001"], r.explain()
    assert snapshot(root) == before


def test_limit_counts_bytes_not_characters(tmp_path_factory, tmp_path):
    limit_case = _limit_case(tmp_path_factory)
    n, t, _ = limit_case
    # те же 80000 СИМВОЛОВ, но кириллица — по 2 байта: 80000 + t байт
    root = _tools_tree(tmp_path / "repo", n, "я" * t)
    r = bm(root, tmp_path, "--write")
    assert r.rc == 2, r.explain()
    assert re.findall(r"^too big: .*$", r.err, re.M) == [f"too big: {layer_file('tools')} {MAX_FILE_BYTES + t}"], (
        r.explain()
    )
    assert index_names(root) == []


# --------------------------------------------------------------------------- validate.py


def _load_validate():
    spec = importlib.util.spec_from_file_location("validate_under_test_24j", VALIDATE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def validate_mod(monkeypatch):
    v = _load_validate()
    errs: list = []
    monkeypatch.setattr(v, "errors", errs)
    monkeypatch.setattr(v, "warnings", [])
    return v, errs


def test_validate_index_check_ok_on_fresh_index(validate_mod, tmp_path, monkeypatch, capsys):
    v, errs = validate_mod
    root = _tag_repo(tmp_path / "repo")
    write_ok(root, tmp_path)
    monkeypatch.setattr(v, "BASE", root)
    v.check_memory_index()
    out = capsys.readouterr().out
    assert "9. Индекс уроков по модулям" in out
    assert "[OK]" in out and "[FAIL]" not in out, out
    assert errs == []


def test_validate_index_check_fails_on_stale_index(validate_mod, tmp_path, monkeypatch, capsys):
    v, errs = validate_mod
    root = _tag_repo(tmp_path / "repo")
    write_ok(root, tmp_path)
    p = root / MEM / HUB
    p.write_bytes(p.read_bytes() + b" ")
    monkeypatch.setattr(v, "BASE", root)
    v.check_memory_index()
    out = capsys.readouterr().out
    assert "[FAIL]" in out and "[OK]" not in out, out
    assert f"stale: {HUB}" in out, out
    assert len(errs) == 1


def test_validate_index_check_fails_when_index_is_missing(validate_mod, tmp_path, monkeypatch, capsys):
    v, errs = validate_mod
    root = _tag_repo(tmp_path / "repo")  # индекса на диске нет
    monkeypatch.setattr(v, "BASE", root)
    v.check_memory_index()
    out = capsys.readouterr().out
    assert "[FAIL]" in out and f"missing: {HUB}" in out, out
    assert len(errs) == 1


def test_validate_index_check_prints_at_most_20_tail_lines(validate_mod, tmp_path, monkeypatch, capsys):
    v, errs = validate_mod
    root = _tag_repo(tmp_path / "repo")
    write_ok(root, tmp_path)
    for i in range(1, 31):
        write_bytes(root, f"{MEM}/BY-MODULE-x{i:02d}.md", b"x\n")
    monkeypatch.setattr(v, "BASE", root)
    v.check_memory_index()
    out = capsys.readouterr().out
    extra_lines = [ln for ln in out.splitlines() if "extra: BY-MODULE-x" in ln]
    assert len(extra_lines) == 20, out
    assert "extra: BY-MODULE-x30.md" in out and "extra: BY-MODULE-x11.md" in out
    assert "extra: BY-MODULE-x10.md" not in out
    assert len(errs) == 1


def _stub_other_checks(v, monkeypatch) -> list[str]:
    stubbed = [
        n
        for n in dir(v)
        if n.startswith("check_")
        and n not in ("check_header", "check_memory_tags", "check_memory_index")
        and callable(getattr(v, n))
    ]
    assert len(stubbed) >= 9, stubbed
    for n in stubbed:
        monkeypatch.setattr(v, n, lambda *a, **k: None)
    return stubbed


def test_validate_main_runs_index_check_after_tags_and_passes_on_fresh_index(
    validate_mod, tmp_path, monkeypatch, capsys
):
    v, errs = validate_mod
    root = _tag_repo(tmp_path / "repo")
    write_ok(root, tmp_path)
    monkeypatch.setattr(v, "BASE", root)
    _stub_other_checks(v, monkeypatch)
    assert v.main() == 0
    out = capsys.readouterr().out
    assert out.index("8. Проверка тегов памяти") < out.index("9. Индекс уроков по модулям"), out


def test_validate_main_fails_on_stale_index(validate_mod, tmp_path, monkeypatch, capsys):
    v, errs = validate_mod
    root = _tag_repo(tmp_path / "repo")
    write_ok(root, tmp_path)
    lesson(root, "l-one.md", desc="новое описание changed", module=["logger_module"], mechanism=["fixture-trap"])
    monkeypatch.setattr(v, "BASE", root)
    _stub_other_checks(v, monkeypatch)
    assert v.main() == 1
    out = capsys.readouterr().out
    assert f"stale: {layer_file('framework')}" in out, out
    assert len(errs) == 1  # теги в порядке: красна только проверка индекса


# --------------------------------------------------------------------------- файлы репозитория


def _repo_text(rel: str) -> str:
    return (REPO_ROOT / rel).read_bytes().decode("utf-8")


def test_gitattributes_has_eol_lf_rule_for_by_module():
    lines = [ln.rstrip("\r") for ln in _repo_text(".gitattributes").split("\n")]
    assert "docs/claude/memory/BY-MODULE*.md text eol=lf" in lines


def test_git_applies_text_eol_lf_to_generated_names():
    paths = [f"{MEM}/{n}" for n in (HUB, MECH, layer_file("framework"), layer_file("other"))]
    cp = subprocess.run(
        ["git", "check-attr", "text", "eol", "--", *paths],
        cwd=str(REPO_ROOT),
        capture_output=True,
        timeout=TIMEOUT,
    )
    assert cp.returncode == 0, cp.stderr.decode("utf-8", "replace")
    got = set(cp.stdout.decode("utf-8").replace("\r", "").split("\n")) - {""}
    want = {f"{p}: {attr}" for p in paths for attr in ("text: set", "eol: lf")}
    assert got == want


REMEMBER_FILES = [".claude/commands/core/memory/remember.md", ".claude/plugins/core/commands/memory/remember.md"]
SKILL_FILES = [".claude/skills/project-rules/SKILL.md", ".claude/plugins/dev/skills/project-rules/SKILL.md"]


@pytest.mark.parametrize("rel", REMEMBER_FILES)
def test_remember_has_regenerate_step_after_the_lesson_is_written(rel):
    text = _repo_text(rel)
    step = "python scripts/memory/search.py --by-module --write"
    assert step in text
    assert text.index(step) > text.index("Karpathy format")  # шаг записи урока стоит раньше


def test_remember_source_and_mirror_are_identical():
    a, b = [(REPO_ROOT / rel).read_bytes() for rel in REMEMBER_FILES]
    assert a == b


@pytest.mark.parametrize("rel", SKILL_FILES)
def test_skill_craft_line_no_longer_lists_by_module(rel):
    craft_lines = [ln for ln in _repo_text(rel).split("\n") if "docs/claude/memory/CRAFT-{" in ln]
    assert len(craft_lines) == 1, craft_lines
    assert "CRAFT-{tests,injection,verdict,config-qt}.md" in craft_lines[0]
    assert "by-module" not in craft_lines[0].lower()


def test_hand_written_craft_by_module_is_gone():
    assert not (REPO_ROOT / MEM / "CRAFT-by-module.md").exists()


def test_no_file_in_memory_dir_links_to_craft_by_module():
    hits = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in sorted((REPO_ROOT / MEM).rglob("*"))
        if p.is_file() and b"CRAFT-by-module" in p.read_bytes()
    ]
    assert hits == []


@pytest.mark.parametrize(
    "name", ["CRAFT.md", "CRAFT-tests.md", "CRAFT-injection.md", "CRAFT-verdict.md", "CRAFT-config-qt.md", "MEMORY.md"]
)
def test_digests_and_memory_index_link_to_by_module_hub(name):
    assert "BY-MODULE.md" in _repo_text(f"{MEM}/{name}")


def test_committed_index_is_fresh_for_this_tree(tmp_path):
    r = bm(REPO_ROOT, tmp_path, "--check")
    assert r.rc == 0, r.explain()
    assert r.lines == []


def test_generated_files_are_tracked_by_git():
    cp = subprocess.run(
        ["git", "ls-files", "--", f"{MEM}/BY-MODULE*.md"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        timeout=TIMEOUT,
    )
    assert cp.returncode == 0, cp.stderr.decode("utf-8", "replace")
    tracked = sorted(Path(ln).name for ln in cp.stdout.decode("utf-8").split("\n") if ln.strip())
    on_disk = sorted(p.name for p in (REPO_ROOT / MEM).glob("BY-MODULE*.md"))
    assert HUB in tracked and MECH in tracked
    assert tracked == on_disk
