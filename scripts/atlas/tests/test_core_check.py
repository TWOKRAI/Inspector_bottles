"""Приёмочные тесты гейта check и legacy_before ядра scripts/atlas (Task 1.2, RED).

Purpose: слепые тесты (REDS 4, 5, 7) по ADR-ATL-002: блокирует только новая
    blocking-находка против merge-base, перенос файла не делает находку новой,
    legacy_before — SHA коммита базы, ошибки exit 2 при shallow и пропавшем ref.
Public API: нет (только test_*).
Stability: lite
"""

from __future__ import annotations

import json

__all__: list[str] = []

SHALLOW_MSG = "atlas: shallow clone — legacy_before is unreliable; run: git fetch --unshallow"
NOT_FOUND_MSG = "atlas: legacy_before not found — main ref missing or baseline not on it"
BASELINE = "scripts/atlas/baseline.txt"
BASELINE_TEXT = "# header\nBROKEN_LINK\tdoc:a.md\tx.md\n"


def _lines(out: str) -> list[str]:
    return out.splitlines()


def test_check_blocks_only_on_a_new_blocking_finding(repo_factory, atlas, set_adapters):
    from scripts.atlas.tests.conftest import MarkerAdapter

    set_adapters(MarkerAdapter())

    # 1. новые находки всех уровней только на HEAD: exit 1, строки отсортированы по (code, node, detail)
    first = repo_factory.create("new_all")
    first.write("z.md", "# z\n")
    first.commit("base")
    first.git("checkout", "-q", "-b", "feat")
    first.write(
        "b.md",
        "# b\n"
        "@@finding warning SURFACE_CHANGED_WITHOUT_TEST commit:c22\n"
        "@@finding info REF_MOVED commit:c11 plans/old.md\n"
        "@@finding blocking BROKEN_LINK doc:{path} x.md\n"
        "@@finding info REF_MOVED commit:c11 plans/a.md\n",
    )
    first.commit("feat: findings")
    result = atlas(first, "check")
    assert result.code == 1, result.out + result.err
    assert _lines(result.out) == [
        "blocking BROKEN_LINK doc:b.md x.md",
        "info REF_MOVED commit:c11 plans/a.md",
        "info REF_MOVED commit:c11 plans/old.md",
        "warning SURFACE_CHANGED_WITHOUT_TEST commit:c22 -",
        "atlas check: 1 new blocking, 1 new warning, 2 new info",
    ]

    # 2. та же находка уже есть на ref: не новая, exit 0, остаётся одна итоговая строка
    second = repo_factory.create("same_on_both")
    second.write("b.md", "# b\n@@finding blocking BROKEN_LINK doc:{path} x.md\n")
    second.commit("base with the finding")
    second.git("checkout", "-q", "-b", "feat")
    second.write("other.txt", "unrelated\n")
    second.commit("feat: unrelated")
    result = atlas(second, "check")
    assert result.code == 0, result.out + result.err
    assert _lines(result.out) == ["atlas check: 0 new blocking, 0 new warning, 0 new info"]

    # 3. новое только предупреждение: exit 0, строка видна, пустой detail печатается как "-"
    third = repo_factory.create("new_warning")
    third.write("z.md", "# z\n")
    base_sha = third.commit("base")
    third.git("checkout", "-q", "-b", "feat")
    third.write("w.md", f"# w\n@@finding warning SURFACE_CHANGED_WITHOUT_TEST commit:{base_sha}\n")
    third.commit("feat: warning")
    result = atlas(third, "check")
    assert result.code == 0, result.out + result.err
    assert _lines(result.out) == [
        f"warning SURFACE_CHANGED_WITHOUT_TEST commit:{base_sha} -",
        "atlas check: 0 new blocking, 1 new warning, 0 new info",
    ]


def test_check_uses_merge_base_and_translates_renames(repo_factory, atlas, set_adapters):
    from scripts.atlas.tests.conftest import MarkerAdapter

    set_adapters(MarkerAdapter())

    # merge-base, а не кончик main: main починил находку, ветка ответвилась до починки
    fork = repo_factory.create("fork")
    fork.write("a.md", "# a\n@@finding blocking BROKEN_LINK doc:{path} x.md\n")
    fork.commit("base with the finding")
    fork.git("checkout", "-q", "-b", "feat")
    fork.write("x.txt", "branch work\n")
    fork.commit("feat: unrelated")
    fork.git("checkout", "-q", "main")
    fork.write("a.md", "# a fixed\n")
    fork.commit("main: fix the finding")
    fork.git("checkout", "-q", "feat")
    by_merge_base = atlas(fork, "check")
    assert by_merge_base.code == 0, by_merge_base.out + by_merge_base.err
    by_tip = atlas(fork, "check", "--base", "main")
    assert by_tip.code == 1, by_tip.out + by_tip.err
    assert "blocking BROKEN_LINK doc:a.md x.md" in _lines(by_tip.out)

    # git mv doc: a.md -> b.md, находка переехала вместе с файлом
    doc = repo_factory.create("rename_doc")
    prose = "".join(f"line {i} of the document\n" for i in range(20))
    doc.write("a.md", "# a\n" + prose + "@@finding blocking BROKEN_LINK doc:{path} x.md\n")
    doc.commit("base")
    doc.git("checkout", "-q", "-b", "feat")
    doc.git("mv", "a.md", "b.md")
    doc.commit("feat: rename a.md to b.md")
    renamed_doc = atlas(doc, "check")
    assert renamed_doc.code == 0, renamed_doc.out + renamed_doc.err
    assert _lines(renamed_doc.out) == ["atlas check: 0 new blocking, 0 new warning, 0 new info"]

    # git mv test: tests/test_a.py -> tests/test_b.py, nodeid test:<path>::test_x переведён
    test = repo_factory.create("rename_test")
    body = "".join(f"# filler {i}\n" for i in range(20))
    test.write(
        "tests/test_a.py",
        body + "def test_x():\n    pass\n# @@finding blocking BROKEN_LINK test:{path}::test_x G-X-001\n",
    )
    test.commit("base")
    test.git("checkout", "-q", "-b", "feat")
    test.git("mv", "tests/test_a.py", "tests/test_b.py")
    test.commit("feat: rename test_a.py to test_b.py")
    renamed_test = atlas(test, "check")
    assert renamed_test.code == 0, renamed_test.out + renamed_test.err
    assert _lines(renamed_test.out) == ["atlas check: 0 new blocking, 0 new warning, 0 new info"]


def test_legacy_before_shallow_no_ff_and_absent(repo_factory, atlas, set_adapters):
    set_adapters()

    # неглубокий клон (file:// --depth 1), база старше границы: exit 2 и точная фраза
    origin = repo_factory.create("origin")
    origin.write(BASELINE, BASELINE_TEXT)
    origin.commit("add baseline")
    origin.write("b.txt", "b\n")
    origin.commit("second")
    origin.write("c.txt", "c\n")
    origin.commit("third")
    clone = repo_factory.clone_shallow(origin, "clone")
    assert clone.git("rev-parse", "--is-shallow-repository") == "true"
    shallow = atlas(clone, "--json")
    assert shallow.code == 2, shallow.out + shallow.err
    assert SHALLOW_MSG in shallow.err
    # legacy_before считает только --json: build и check в неглубоком клоне работают
    assert atlas(clone, "build").code == 0
    assert atlas(clone, "check").code == 0

    # база в дереве HEAD, а main-ref нет: exit 2, не null
    missing = repo_factory.create("missing_ref")
    missing.write(BASELINE, BASELINE_TEXT)
    missing.commit("add baseline")
    absent_ref = atlas(missing, "--json", "--main-ref", "nosuch")
    assert absent_ref.code == 2, absent_ref.out + absent_ref.err
    assert NOT_FOUND_MSG in absent_ref.err

    # база добавлена веткой, влитой --no-ff: legacy_before == SHA коммита слияния
    merged = repo_factory.create("no_ff")
    merged.write("a.txt", "a\n")
    merged.commit("base")
    merged.git("checkout", "-q", "-b", "feat")
    merged.write(BASELINE, BASELINE_TEXT)
    merged.commit("feat: add baseline")
    merged.write("f.txt", "f\n")
    merged.commit("feat: more")
    merged.git("checkout", "-q", "main")
    merged.write("m.txt", "m\n")
    merged.commit("main: diverge")
    merged.git("merge", "-q", "--no-ff", "-m", "merge feat", "feat")
    merge_sha = merged.head
    merged.write("after.txt", "after\n")
    after_sha = merged.commit("main: after the merge")
    data = json.loads(atlas(merged, "--json").out)
    assert data["head"] == after_sha
    assert data["legacy_before"] == merge_sha

    # файла базы нет в дереве HEAD: null
    plain = repo_factory.create("no_baseline")
    plain.write("a.txt", "a\n")
    plain.commit("base")
    result = atlas(plain, "--json")
    assert result.code == 0, result.err
    assert json.loads(result.out)["legacy_before"] is None
