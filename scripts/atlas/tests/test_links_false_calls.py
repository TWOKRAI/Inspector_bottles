"""REDS Task 4.5a (автор — исполнитель): `ref` не приписывает символу чужие голые вызовы (`scripts/atlas/links.py`).

Purpose: затенение параметром и вложенным `def`, параметр с именем модуля (`import lib` + `def run(lib)`),
    двусмысленный from-импорт, нечитаемая сигнатура. Проверяется наблюдаемый ответ `Links.of(...)`:
    `call_sites` и `call_sites_unresolved`.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Факты — `scan_text(исходник)`, кроме теста нечитаемой сигнатуры (там `FileFacts` собран вручную: `ast.unparse`
сигнатуру `"("` не даёт). Ожидаемые адреса — литералы `путь:строка`. Построение и опрос — в daemon-потоке с
дедлайном (`run_with_deadline`).
"""

from __future__ import annotations

from scripts.atlas.tests.conftest import run_with_deadline

__all__: list[str] = []

DEADLINE_S = 30.0


def _links(files: dict[str, str]):
    from scripts.atlas.links import build_links
    from scripts.atlas.scan import scan_text

    return run_with_deadline(lambda: build_links({p: scan_text(s) for p, s in files.items()}), DEADLINE_S)


def _of(links, ident: str) -> dict:
    res = run_with_deadline(lambda: links.of(ident), DEADLINE_S)
    assert res is not None, f"нет записи для {ident}"
    return res


def _site(where: str, enclosing: str, same_file: bool) -> dict:
    return {"where": where, "how": "name-call", "scope": "prod", "enclosing": enclosing, "same_file": same_file}


def test_param_named_like_function_not_attributed():
    """`def run(callback): callback()` — вызов параметра, а не функции `callback` файла: `call_sites` пусто."""
    files = {
        "mod.py": (
            "def callback():\n"  # 1
            "    pass\n"
            "\n"
            "\n"
            "def run(callback):\n"  # 5
            "    callback()\n"  # 6
        )
    }
    res = _of(_links(files), "mod.py::callback")
    assert res["call_sites"] == []
    assert res["call_sites_unresolved"] == 1


def test_nested_def_shadows_top_level():
    """Вложенный `def helper` в `run` затеняет верхний `helper` (своего файла и from-импорта) для вызова в `run`."""
    files = {
        "lib.py": "def helper():\n    pass\n",
        "mod.py": (
            "def helper():\n"  # 1
            "    pass\n"
            "\n"
            "\n"
            "def run():\n"  # 5
            "    def helper():\n"
            "        pass\n"
            "\n"
            "    helper()\n"  # 9: затенён
            "\n"
            "\n"
            "def other():\n"  # 12
            "    helper()\n"  # 13: верхний helper
        ),
        "use.py": (
            "from lib import helper\n"  # 1
            "\n"
            "\n"
            "def run():\n"  # 4
            "    def helper():\n"
            "        pass\n"
            "\n"
            "    helper()\n"  # 8: затенён
        ),
    }
    links = _links(files)
    own = _of(links, "mod.py::helper")
    assert own["call_sites"] == [_site("mod.py:13", "other", True)]
    imported = _of(links, "lib.py::helper")
    assert imported["call_sites"] == []
    assert own["call_sites_unresolved"] == 2  # счётчик — по имени: два затенённых вызова `helper()`


def test_enclosing_class_method_does_not_shadow():
    """Граница затенения: метод `Svc.helper` охватывающего класса голый `helper()` не затеняет (до правки зелёный)."""
    files = {
        "mod.py": (
            "def helper():\n"  # 1
            "    pass\n"
            "\n"
            "\n"
            "class Svc:\n"  # 5
            "    def helper(self):\n"
            "        pass\n"
            "\n"
            "    def run(self):\n"  # 9
            "        helper()\n"  # 10
        )
    }
    res = _of(_links(files), "mod.py::helper")
    assert res["call_sites"] == [_site("mod.py:10", "Svc.run", True)]
    assert res["call_sites_unresolved"] == 0


def test_module_alias_shadowed_by_param():
    """`import lib` + `def run(lib): lib.func()` — получатель `lib` здесь параметр: вызов не отнесён, unresolved +1.

    Алиас `import lib as x` в фактах не хранится (решение лида в), поэтому проверяется имя модуля как есть."""
    files = {
        "lib.py": "def func():\n    pass\n",
        "use.py": (
            "import lib\n"  # 1
            "\n"
            "\n"
            "def run(lib):\n"  # 4
            "    lib.func()\n"  # 5: затенён
            "\n"
            "\n"
            "def other():\n"  # 8
            "    lib.func()\n"  # 9
        ),
    }
    res = _of(_links(files), "lib.py::func")
    assert res["call_sites"] == [_site("use.py:9", "other", False)]
    assert res["call_sites_unresolved"] == 1


def test_ambiguous_from_import_not_attributed():
    """`from a import f` + `from b import f`, оба файла определяют `f`: вызов `f()` не отнесён ни к `a`, ни к `b`."""
    files = {
        "a.py": "def f():\n    pass\n",
        "b.py": "def f():\n    pass\n",
        "use.py": (
            "from a import f\nfrom b import f\n\n\ndef run():\n    f()\n"  # 6
        ),
    }
    links = _links(files)
    assert _of(links, "a.py::f")["call_sites"] == []
    assert _of(links, "b.py::f")["call_sites"] == []
    assert _of(links, "a.py::f")["call_sites_unresolved"] == 1


def test_unparsed_signature_counts_as_shadowed():
    """`DefFact(signature="(")` не разбирается -> любое имя в функции затенено, и во вложенной (решение лида б)."""
    from scripts.atlas.links import build_links
    from scripts.atlas.scan import CallFact, DefFact, FileFacts, ImportRec

    lib = FileFacts(defs=(DefFact("f", "function", 1),))
    imp = ImportRec(kind="hard", line=1, level=0, module="lib", names=("f",), is_from=True, guarded=False)
    use = FileFacts(
        imports=(imp,),
        defs=(
            DefFact("run", "function", 3, signature="("),
            DefFact("run.inner", "function", 4),
            DefFact("ok", "function", 7, signature="x"),
        ),
        calls=(CallFact("f", 5, "run.inner"), CallFact("f", 6, "run"), CallFact("f", 8, "ok")),
    )
    links = run_with_deadline(lambda: build_links({"lib.py": lib, "use.py": use}), DEADLINE_S)
    res = _of(links, "lib.py::f")
    assert res["call_sites"] == [_site("use.py:8", "ok", False)]
    assert res["call_sites_unresolved"] == 2
