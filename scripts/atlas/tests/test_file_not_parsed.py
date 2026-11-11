"""Приёмочные тесты находки FILE_NOT_PARSED в `atlas check` и `--json` (Task B7, слепой RED до кода).

Purpose: сломанный нетестовый `.py` слоёв framework/services/plugins не должен молча выпадать из карты.
    REDS 1-8 плана atlas-passport: строка `warning FILE_NOT_PARSED file:<путь> <Исключение>`, только новые
    находки против merge-base, определение «не разобран» (SyntaxError, нулевой байт, UnicodeDecodeError,
    BOM, BlobTooLarge на границе 1_048_576), охват (services, plugins; не тесты и не prototype), контракт `--json`,
    перенос файла (R) переводит находку, symlink и путь с переводом строки пропускаются.
Public API: нет (только test_*).
Stability: lite

Спецификация — только tasks/B7.md (REDS, «Определение», «Охват»). Ожидаемые строки и счётчики — литералы.
Symlink и путь с `\\n` создаются git-plumbing (`update-index --cacheinfo`), не `os.symlink`: проект ходит
и на Windows. Все вызовы git и main() идут через дедлайн conftest. Импорты проверяемого кода — внутри
фабрик/тестов (здесь их нет: проверяется только публичный CLI).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.atlas.tests.conftest import GitRepo, RepoFactory
from scripts.atlas.tests.test_ref_code import modules_yaml

__all__: list[str] = []

BROKEN = "def broken(:\n    pass\n"
VALID = "x = 1\n"
MAX_BLOB = 1_048_576
CODE = "FILE_NOT_PARSED"


# ---------------------------------------------------------------- хелперы


def _put(repo: GitRepo, rel: str, data: bytes | str) -> None:
    """Файл с точными байтами (без перевода строк ОС)."""
    target = repo.path / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)


def _new(factory: RepoFactory, name: str, rows: list[tuple[str, str]], files: dict[str, bytes | str]) -> GitRepo:
    """Репозиторий: modules.yaml и файлы базы закоммичены в main, ветка feat создана."""
    repo = factory.create(name)
    _put(repo, "modules.yaml", modules_yaml(rows))
    for rel, data in files.items():
        _put(repo, rel, data)
    repo.commit("base")
    repo.git("checkout", "-q", "-b", "feat")
    return repo


def _check(atlas: Any, repo: GitRepo) -> tuple[int, list[str]]:
    res = atlas(repo, "check")
    return res.code, res.out.splitlines()


def _long_valid(tail: bytes) -> bytes:
    """Длинный валидный файл и одна последняя строка `tail`: сходство при правке строки остаётся >= 50 %."""
    return "".join(f"value_{i} = {i}\n" for i in range(40)).encode("utf-8") + tail


def _blob_oid(repo: GitRepo, tmp: Path, name: str, data: bytes) -> str:
    """oid блоба, записанного в базу объектов (файл лежит вне репозитория)."""
    src = tmp / name
    src.write_bytes(data)
    return repo.git("hash-object", "-w", str(src))


# ---------------------------------------------------------------- RED 1


def test_broken_file_in_framework_gives_one_warning_and_exit_0(repo_factory, atlas):
    repo = _new(repo_factory, "r1", [("m", "framework")], {"m/x.py": VALID})
    _put(repo, "m/x.py", BROKEN)
    repo.commit("feat: break x.py")

    code, lines = _check(atlas, repo)

    assert code == 0, lines
    assert lines == [
        "warning FILE_NOT_PARSED file:m/x.py SyntaxError",
        "atlas check: 0 new blocking, 1 new warning, 0 new info",
    ]


# ---------------------------------------------------------------- RED 2


def test_only_the_file_broken_on_the_branch_is_new(repo_factory, atlas):
    repo = _new(repo_factory, "r2", [("m", "framework")], {"m/a.py": BROKEN, "m/ok.py": VALID})
    _put(repo, "m/b.py", BROKEN)
    repo.commit("feat: add broken b.py")

    code, lines = _check(atlas, repo)

    assert code == 0, lines
    assert lines == [
        "warning FILE_NOT_PARSED file:m/b.py SyntaxError",
        "atlas check: 0 new blocking, 1 new warning, 0 new info",
    ]


# ---------------------------------------------------------------- RED 3


def test_definition_of_not_parsed_valid_neighbour_nul_bad_utf8_and_bom(repo_factory, atlas):
    repo = _new(repo_factory, "r3", [("m", "framework")], {"m/keep.py": VALID})
    _put(repo, "m/bad.py", BROKEN)  # сломанный сосед
    _put(repo, "m/good.py", VALID)  # (а) валидный рядом со сломанным: находки нет
    _put(repo, "m/nul.py", b"x = 1\0")  # (б) нулевой байт: SyntaxError (Python 3.12), не ValueError
    _put(repo, "m/latin.py", b"\xff\xfe")  # (в) невалидный utf-8
    _put(repo, "m/bom.py", b"\xef\xbb\xbfx = 1\n")  # (г) валидный файл с BOM: находки нет
    repo.commit("feat: files")

    code, lines = _check(atlas, repo)

    assert code == 0, lines
    assert lines == [
        "warning FILE_NOT_PARSED file:m/bad.py SyntaxError",
        "warning FILE_NOT_PARSED file:m/latin.py UnicodeDecodeError",
        "warning FILE_NOT_PARSED file:m/nul.py SyntaxError",
        "atlas check: 0 new blocking, 3 new warning, 0 new info",
    ]


# ---------------------------------------------------------------- RED 4


def test_services_and_plugins_layers_are_covered_one_finding_per_file(repo_factory, atlas):
    services = _new(repo_factory, "r4s", [("s", "services")], {"s/a.py": VALID, "s/b.py": VALID})
    _put(services, "s/a.py", BROKEN)
    _put(services, "s/b.py", BROKEN)
    services.commit("feat: break both")
    code, lines = _check(atlas, services)
    assert code == 0, lines
    assert lines == [
        "warning FILE_NOT_PARSED file:s/a.py SyntaxError",
        "warning FILE_NOT_PARSED file:s/b.py SyntaxError",
        "atlas check: 0 new blocking, 2 new warning, 0 new info",
    ]

    plugins = _new(repo_factory, "r4p", [("pl", "plugins")], {"pl/a.py": VALID, "pl/b.py": VALID})
    _put(plugins, "pl/a.py", BROKEN)
    _put(plugins, "pl/b.py", BROKEN)
    plugins.commit("feat: break both")
    code, lines = _check(atlas, plugins)
    assert code == 0, lines
    assert lines == [
        "warning FILE_NOT_PARSED file:pl/a.py SyntaxError",
        "warning FILE_NOT_PARSED file:pl/b.py SyntaxError",
        "atlas check: 0 new blocking, 2 new warning, 0 new info",
    ]


# ---------------------------------------------------------------- RED 5


def test_test_files_and_prototype_layer_are_out_of_scope_but_source_is_in(repo_factory, atlas):
    repo = _new(
        repo_factory,
        "r5",
        [("m", "framework"), ("p", "prototype")],
        {"m/x.py": VALID, "m/tests/test_x.py": VALID, "p/y.py": VALID},
    )
    _put(repo, "m/x.py", BROKEN)
    _put(repo, "m/tests/test_x.py", BROKEN)
    _put(repo, "p/y.py", BROKEN)
    repo.commit("feat: break all three")

    code, lines = _check(atlas, repo)

    assert code == 0, lines
    assert lines == [
        "warning FILE_NOT_PARSED file:m/x.py SyntaxError",
        "atlas check: 0 new blocking, 1 new warning, 0 new info",
    ]


# ---------------------------------------------------------------- RED 6


def _without_commits(doc: dict[str, Any]) -> tuple[list[Any], list[Any]]:
    nodes = [n for n in doc["nodes"] if n["kind"] != "commit"]
    edges = [e for e in doc["edges"] if not str(e["src"]).startswith("commit:")]
    return nodes, edges


def test_json_findings_carry_the_new_finding_and_the_rest_equals_the_revision_without_the_file(repo_factory, atlas):
    repo = repo_factory.create("r6")
    _put(repo, "modules.yaml", modules_yaml([("m", "framework")]))
    _put(repo, "m/ok.py", VALID)
    _put(repo, "m/x.py", BROKEN)
    with_file = repo.commit("with the broken file")
    repo.git("rm", "-q", "m/x.py")  # удалён, не заменён
    repo.git("commit", "-q", "-m", "without the file")
    without_file = repo.head

    res_with = atlas(repo, "--json", "--ref", with_file)
    res_without = atlas(repo, "--json", "--ref", without_file)
    assert res_with.code == 0, res_with.err
    assert res_without.code == 0, res_without.err
    doc_with = json.loads(res_with.out)
    doc_without = json.loads(res_without.out)

    ours = [f for f in doc_with["findings"] if f["code"] == CODE]
    assert ours == [
        {
            "code": "FILE_NOT_PARSED",
            "severity": "warning",
            "node": "file:m/x.py",
            "detail": "SyntaxError",
            "message": "Файл не разобран (SyntaxError): в карту не попадёт",
            "source": "m/x.py",
        }
    ]
    assert [f for f in doc_without["findings"] if f["code"] == CODE] == []
    assert [f for f in doc_with["findings"] if f["code"] != CODE] == doc_without["findings"]
    assert _without_commits(doc_with) == _without_commits(doc_without)


# ---------------------------------------------------------------- RED 7


def _rename_status(repo: GitRepo) -> list[str]:
    return repo.git("diff", "-M", "--name-status", "main", "HEAD").splitlines()


def test_rename_of_a_broken_file_is_not_new_but_rename_with_a_new_breakage_is(repo_factory, atlas):
    # R100: тот же сломанный файл под новым именем — находки нет
    pure = _new(repo_factory, "r7a", [("m", "framework")], {"m/x.py": _long_valid(BROKEN.encode("utf-8"))})
    pure.git("mv", "m/x.py", "m/y.py")
    pure.commit("feat: rename x.py to y.py")
    status = _rename_status(pure)
    assert len(status) == 1 and status[0].startswith("R100\tm/x.py\tm/y.py"), status
    code, lines = _check(atlas, pure)
    assert code == 0, lines
    assert lines == ["atlas check: 0 new blocking, 0 new warning, 0 new info"]

    # перенос с правкой в другую поломку (SyntaxError -> UnicodeDecodeError): находка новая, detail сменился
    edited = _new(repo_factory, "r7b", [("m", "framework")], {"m/x.py": _long_valid(BROKEN.encode("utf-8"))})
    edited.git("mv", "m/x.py", "m/z.py")
    _put(edited, "m/z.py", _long_valid(b"\xff\xfe\n"))
    edited.commit("feat: rename x.py to z.py and break it differently")
    status = _rename_status(edited)
    assert len(status) == 1 and status[0].startswith("R") and status[0].endswith("\tm/x.py\tm/z.py"), status
    code, lines = _check(atlas, edited)
    assert code == 0, lines
    assert lines == [
        "warning FILE_NOT_PARSED file:m/z.py UnicodeDecodeError",
        "atlas check: 0 new blocking, 1 new warning, 0 new info",
    ]


# ---------------------------------------------------------------- RED 8


def _padded(size: int) -> bytes:
    """Валидный Python ровно `size` байт: присваивание и комментарий-заполнитель."""
    head = b"x = 1\n#"
    return head + b"a" * (size - len(head) - 1) + b"\n"


def test_size_boundary_utf8_change_and_symlink(repo_factory, atlas, tmp_path):
    repo = _new(
        repo_factory,
        "r8",
        [("m", "framework")],
        {"m/x.py": BROKEN, "m/ok.py": VALID},  # на базе x.py — SyntaxError
    )
    _put(repo, "m/x.py", b"\xff\xfe\n")  # на ветке в том же файле невалидный utf-8: находка новая
    big = _padded(MAX_BLOB + 1)
    edge = _padded(MAX_BLOB)
    assert (len(big), len(edge)) == (1_048_577, 1_048_576)
    _put(repo, "m/big.py", big)  # строго больше предела: BlobTooLarge
    _put(repo, "m/edge.py", edge)  # ровно предел: проходит
    repo.git("add", ".")
    # symlink на валидный файл — через git plumbing; текст блоба `../m/ok.py` как исходник — SyntaxError, так что
    # чтение symlink-а как файла дало бы находку. `git add .` после update-index стёр бы запись индекса
    link_oid = _blob_oid(repo, tmp_path, "link_target", b"../m/ok.py")
    repo.git("update-index", "--add", "--cacheinfo", f"120000,{link_oid},m/x_link.py")
    repo.git("commit", "-q", "-m", "feat: boundaries")
    assert repo.git("ls-tree", "HEAD", "m/x_link.py").startswith("120000 blob")  # symlink действительно в дереве

    code, lines = _check(atlas, repo)

    assert code == 0, lines
    assert lines == [
        "warning FILE_NOT_PARSED file:m/big.py BlobTooLarge",
        "warning FILE_NOT_PARSED file:m/x.py UnicodeDecodeError",
        "atlas check: 0 new blocking, 2 new warning, 0 new info",
    ]


def test_newline_in_path_does_not_break_the_new_finding(repo_factory, atlas, set_adapters, tmp_path):
    # Адаптер `rules` уже сегодня роняет любую сборку с `\n` в пути юнита (AtlasError, exit 2) — вне B7. Чтобы
    # проверить именно новый адаптер, rules на время теста выключен; остальные адаптеры настоящие.
    from scripts.atlas.build import ADAPTERS

    set_adapters(*[a for a in ADAPTERS if a.name != "rules"])
    repo = _new(repo_factory, "r8nl", [("m", "framework")], {"m/x.py": VALID})
    _put(repo, "m/x.py", BROKEN)  # настоящая находка рядом: тест красный, пока адаптера нет
    repo.git("add", ".")
    nl_oid = _blob_oid(repo, tmp_path, "nl_body", BROKEN.encode("utf-8"))  # сломан: прочти его адаптер, была бы находка
    repo.git("update-index", "--add", "--cacheinfo", f"100644,{nl_oid},m/a\nb.py")
    repo.git("commit", "-q", "-m", "feat: newline path")
    assert "m/a\nb.py" in repo.git("ls-tree", "-r", "--name-only", "-z", "HEAD").split("\0")

    code, lines = _check(atlas, repo)

    assert code == 0, lines
    assert lines == [
        "warning FILE_NOT_PARSED file:m/x.py SyntaxError",
        "atlas check: 0 new blocking, 1 new warning, 0 new info",
    ]
