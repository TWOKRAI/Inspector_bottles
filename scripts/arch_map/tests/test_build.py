"""Тесты генератора карты архитектуры scripts/arch_map/build.py.

Фикстуры — маленькие деревья в tmp_path с пакетами трёх слоёв. Ожидаемые значения —
литералы (id файлов, номера строк), а не результат расчёта тестируемого кода.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.arch_map import build

FW = "multiprocess_framework.modules"


def make_tree(base: Path, files: dict[str, str]) -> Path:
    """Создаёт файлы дерева; пустое содержимое — пустой файл."""
    for rel, text in files.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return base


def build_for(base: Path) -> dict:
    model, _graph = build.build_model(base, base / "out")
    return model


def edges_from(model: dict, src: str) -> list[tuple[str, str, int, tuple[str, ...]]]:
    """[(dst, kind, line, names)] рёбер файла src, в порядке строк."""
    rows = [(e["dst"], e["kind"], e["line"], tuple(e["names"])) for e in model["edges"] if e["src"] == src]
    return sorted(rows, key=lambda r: (r[2], r[0]))


def findings_of(model: dict, rule: str) -> list[dict]:
    return [f for f in model["findings"] if f["rule"] == rule]


def base_tree() -> dict[str, str]:
    """Три слоя: два модуля framework, сервис, плагин группы, прототип."""
    return {
        "multiprocess_framework/__init__.py": "",
        "multiprocess_framework/modules/__init__.py": "",
        "multiprocess_framework/modules/alpha_module/__init__.py": "",
        "multiprocess_framework/modules/alpha_module/interfaces.py": "class IAlpha:\n    pass\n",
        "multiprocess_framework/modules/alpha_module/core/__init__.py": "",
        "multiprocess_framework/modules/alpha_module/core/thing.py": "class AlphaThing:\n    pass\n",
        "multiprocess_framework/modules/beta_module/__init__.py": "",
        "multiprocess_framework/modules/gamma_module/__init__.py": "",
        "Services/__init__.py": "",
        "Services/svc_a/__init__.py": "",
        "Plugins/__init__.py": "",
        "Plugins/grp/__init__.py": "",
        "Plugins/grp/plug_a/__init__.py": "",
        "multiprocess_prototype/__init__.py": "",
        "multiprocess_prototype/app/__init__.py": "",
    }


def test_edge_kinds_hard_lazy_tc(tmp_path: Path) -> None:
    files = base_tree()
    files["Services/svc_a/impl.py"] = (
        "from __future__ import annotations\n"  # 1
        "import sys\n"  # 2
        "from typing import TYPE_CHECKING\n"  # 3
        "from multiprocess_framework.modules.alpha_module import AlphaThing\n"  # 4 hard
        "if TYPE_CHECKING:\n"  # 5
        "    from multiprocess_framework.modules.beta_module import BetaThing\n"  # 6 tc
        "def f():\n"  # 7
        "    from multiprocess_framework.modules.gamma_module import G\n"  # 8 lazy
        "if sys.platform:\n"  # 9
        "    def g():\n"  # 10
        "        import multiprocess_framework.modules.gamma_module\n"  # 11 lazy (def внутри if)
    )
    model = build_for(make_tree(tmp_path, files))
    got = edges_from(model, "Services.svc_a.impl")
    assert got == [
        (f"{FW}.alpha_module.__init__", "hard", 4, ("AlphaThing",)),
        (f"{FW}.beta_module.__init__", "tc", 6, ("BetaThing",)),
        (f"{FW}.gamma_module.__init__", "lazy", 8, ("G",)),
        (f"{FW}.gamma_module.__init__", "lazy", 11, ()),
    ]


def test_relative_import_from_init_and_from_file(tmp_path: Path) -> None:
    files = base_tree()
    # __init__: одна точка = сам пакет core
    files["multiprocess_framework/modules/alpha_module/core/__init__.py"] = "from .thing import AlphaThing\n"
    # обычный файл: одна точка = каталог файла; две точки = родитель каталога
    files["multiprocess_framework/modules/alpha_module/core/user.py"] = (
        "from .thing import AlphaThing\n"  # 1
        "from ..interfaces import IAlpha\n"  # 2
        "from .. import core\n"  # 3 (core — подпакет alpha_module)
    )
    model = build_for(make_tree(tmp_path, files))
    core_init = f"{FW}.alpha_module.core.__init__"
    assert edges_from(model, core_init) == [(f"{FW}.alpha_module.core.thing", "hard", 1, ("AlphaThing",))]
    assert edges_from(model, f"{FW}.alpha_module.core.user") == [
        (f"{FW}.alpha_module.core.thing", "hard", 1, ("AlphaThing",)),
        (f"{FW}.alpha_module.interfaces", "hard", 2, ("IAlpha",)),
        (core_init, "hard", 3, ("core",)),
    ]


def test_from_pkg_import_submodule_targets_file(tmp_path: Path) -> None:
    files = base_tree()
    files["Services/svc_a/impl.py"] = (
        f"from {FW}.alpha_module import core\n"  # 1 подпакет -> его __init__
        f"from {FW}.alpha_module.core import thing\n"  # 2 подмодуль -> файл
        f"from {FW}.alpha_module import AlphaThing, core as c2\n"  # 3 имя -> __init__ пакета, подпакет -> core
    )
    model = build_for(make_tree(tmp_path, files))
    got = edges_from(model, "Services.svc_a.impl")
    assert got == [
        (f"{FW}.alpha_module.core.__init__", "hard", 1, ("core",)),
        (f"{FW}.alpha_module.core.thing", "hard", 2, ("thing",)),
        (f"{FW}.alpha_module.__init__", "hard", 3, ("AlphaThing",)),
        (f"{FW}.alpha_module.core.__init__", "hard", 3, ("core",)),
    ]


def test_layer_reverse_and_deep_and_private_findings(tmp_path: Path) -> None:
    files = base_tree()
    files["multiprocess_framework/modules/_fallback.py"] = "X = 1\n"
    files["multiprocess_framework/modules/beta_module/bad.py"] = (
        "from Services.svc_a import impl\n"  # 1 framework -> Services: error
        "from typing import TYPE_CHECKING\n"  # 2
        "if TYPE_CHECKING:\n"  # 3
        "    from Plugins.grp.plug_a import thing\n"  # 4 framework -> Plugins под tc: warn
        "import backend_ctl.driver\n"  # 5 framework -> backend_ctl: error
    )
    files["Services/svc_a/impl.py"] = "X = 1\n"
    files["Plugins/grp/plug_a/thing.py"] = "X = 1\n"
    files["backend_ctl/__init__.py"] = ""
    files["backend_ctl/driver.py"] = "X = 1\n"
    files["Plugins/grp/plug_a/use.py"] = (
        f"from {FW}.alpha_module import AlphaThing\n"  # 1 витрина: ок
        f"from {FW}.alpha_module.interfaces import IAlpha\n"  # 2 interfaces: ок
        f"from {FW}.alpha_module.core.thing import AlphaThing as T\n"  # 3 deep-import
        f"from {FW}.beta_module import _secret\n"  # 4 private-import (имя)
        f"from {FW} import _fallback\n"  # 5 private-import (файл), deep-import не применяется к __root__
        "from Services.svc_a import impl\n"  # 6 deep-import (мимо __init__ юнита Services.svc_a)
    )
    files["multiprocess_prototype/app/main.py"] = (
        "import backend_ctl.driver\n"  # 1 prototype -> backend_ctl: не находка
        "from Plugins.grp.plug_a import thing\n"  # 2 deep-import
    )
    files["backend_ctl/uses.py"] = (
        f"from {FW}.alpha_module.core.thing import AlphaThing\n"  # backend_ctl -> всё: не находка
    )
    files["multiprocess_framework/modules/alpha_module/local.py"] = (
        "from .core.thing import AlphaThing\n"  # внутри юнита — ни deep, ни layer
        "from .core import _x\n"
    )
    files["multiprocess_framework/modules/alpha_module/core/_x.py"] = "X = 1\n"
    model = build_for(make_tree(tmp_path, files))

    rev = sorted((f["where"], f["severity"], f["src_unit"], f["dst_unit"]) for f in findings_of(model, "layer-reverse"))
    assert rev == [
        ("multiprocess_framework/modules/beta_module/bad.py:1", "error", f"{FW}.beta_module", "Services.svc_a"),
        ("multiprocess_framework/modules/beta_module/bad.py:4", "warn", f"{FW}.beta_module", "Plugins.grp.plug_a"),
        ("multiprocess_framework/modules/beta_module/bad.py:5", "error", f"{FW}.beta_module", "backend_ctl.__root__"),
    ]
    deep = sorted(f["where"] for f in findings_of(model, "deep-import"))
    assert deep == [
        "Plugins/grp/plug_a/use.py:3",
        "Plugins/grp/plug_a/use.py:6",
        "multiprocess_framework/modules/beta_module/bad.py:1",
        "multiprocess_framework/modules/beta_module/bad.py:4",
        "multiprocess_prototype/app/main.py:2",
    ]
    private = sorted(f["where"] for f in findings_of(model, "private-import"))
    assert private == ["Plugins/grp/plug_a/use.py:4", "Plugins/grp/plug_a/use.py:5"]
    # backend_ctl: prototype -> backend_ctl и backend_ctl -> всё не дают находок ни по одному правилу
    all_where = [f["where"] for f in model["findings"] if f["where"]]
    assert "multiprocess_prototype/app/main.py:1" not in all_where
    assert "backend_ctl/uses.py:1" not in all_where


def test_unit_cycle_hard_is_error_lazy_is_warn(tmp_path: Path) -> None:
    files = base_tree()
    files["Services/svc_a/a.py"] = "from Services.svc_b import x\n"
    files["Services/svc_b/__init__.py"] = ""
    files["Services/svc_b/x.py"] = "from Services.svc_a import a\n"  # hard: A <-> B
    files["Services/svc_c/__init__.py"] = ""
    files["Services/svc_c/c.py"] = "from Services.svc_d import y\n"  # hard C -> D
    files["Services/svc_d/__init__.py"] = ""
    files["Services/svc_d/y.py"] = "def f():\n    from Services.svc_c import c\n"  # lazy D -> C
    model = build_for(make_tree(tmp_path, files))
    cycles = sorted((f["severity"], tuple(f["members"])) for f in findings_of(model, "unit-cycle"))
    assert cycles == [
        ("error", ("Services.svc_a", "Services.svc_b")),
        ("warn", ("Services.svc_c", "Services.svc_d")),
    ]


def test_unresolved_relative_finding(tmp_path: Path) -> None:
    files = base_tree()
    files["Services/svc_a/impl.py"] = (
        "from .missing import X\n"  # 1 нет такого файла
        "from . import also_missing\n"  # 2 пакет есть, имя — не подмодуль: это атрибут __init__, не ошибка
        "from ..... import deep\n"  # 3 выход за корень
    )
    model = build_for(make_tree(tmp_path, files))
    got = sorted((f["where"], f["severity"]) for f in findings_of(model, "unresolved-relative"))
    assert got == [("Services/svc_a/impl.py:1", "error"), ("Services/svc_a/impl.py:3", "error")]
    # атрибутный импорт `from . import also_missing` даёт ребро в __init__ пакета
    assert ("Services.svc_a.__init__", "hard", 2, ("also_missing",)) in edges_from(model, "Services.svc_a.impl")


def test_all_and_interface_reexport_one_hop(tmp_path: Path) -> None:
    files = base_tree()
    files["Services/svc_a/__init__.py"] = '__all__ = ["A"]\n__all__ += ["B"]\nfrom .core import A\n'
    files["Services/svc_a/core.py"] = "class A:\n    pass\n"
    files["Services/svc_b/__init__.py"] = "from .core import *\n__all__ = core.__all__ + ['Z']\n"
    files["Services/svc_b/core.py"] = "__all__ = []\n"
    # interfaces.py только реэкспортирует: следуем на один шаг в core/interfaces.py
    files["Services/svc_c/__init__.py"] = ""
    files["Services/svc_c/interfaces.py"] = "from .core.interfaces import IRunner, IBase\n"
    files["Services/svc_c/core/__init__.py"] = ""
    files["Services/svc_c/core/interfaces.py"] = (
        "from abc import ABC, abstractmethod\n"  # 1
        "from typing import Protocol\n"  # 2
        "class IRunner(Protocol):\n"  # 3
        "    def run(self, x): ...\n"
        "    def _skip(self): ...\n"
        "    def stop(self): ...\n"
        "class IBase(ABC):\n"  # 7
        "    @abstractmethod\n"
        "    def go(self): ...\n"
        "class IChild(IBase):\n"  # 10 (не реэкспортируется)
        "    pass\n"
    )
    model = build_for(make_tree(tmp_path, files))
    units = {n["id"]: n for n in model["nodes"] if n["kind"] == "unit"}
    assert units["Services.svc_a"]["spec"]["all"] == ["A", "B"]
    assert units["Services.svc_b"]["spec"]["all"] is None
    iface = units["Services.svc_c"]["spec"]["interfaces"]
    assert [(i["name"], i["style"], i["file"], i["line"], i["methods"]) for i in iface] == [
        ("IRunner", "Protocol", "Services/svc_c/core/interfaces.py", 3, ["run", "stop"]),
        ("IBase", "ABC", "Services/svc_c/core/interfaces.py", 7, ["go"]),
    ]
    assert units["Services.svc_c"]["spec"]["docs"]["interfaces"] is True
    tops = units["Services.svc_a"]["spec"]["classes_top"]
    assert [(c["name"], c["file"], c["line"]) for c in tops] == [("A", "Services/svc_a/core.py", 1)]


def test_deterministic_output_and_check_exit_codes(tmp_path: Path) -> None:
    files = base_tree()
    files["Services/svc_a/impl.py"] = f"from {FW}.alpha_module import AlphaThing\n"
    files["Services/svc_a/test_impl.py"] = "def test_x():\n    pass\n"  # тест: в граф не входит, считается
    make_tree(tmp_path, files)
    out = tmp_path / "out"
    argv = ["--root", str(tmp_path), "--out", str(out)]
    assert build.main(argv) == 0
    first = {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()}
    assert set(first) == {"model.json", "model.js", "units.md", "findings.md"}
    assert build.main(argv) == 0
    second = {p.name: p.read_bytes() for p in out.iterdir() if p.is_file()}

    def strip_generated(raw: bytes) -> dict:
        data = json.loads(raw.decode("utf-8"))
        data["meta"].pop("generated")
        return data

    assert strip_generated(first["model.json"]) == strip_generated(second["model.json"])
    for name in ("units.md", "findings.md"):
        assert first[name] == second[name]
    assert first["model.js"].decode("utf-8").startswith("window.ARCH_MODEL = {")
    model = json.loads(first["model.json"].decode("utf-8"))
    unit = next(n for n in model["nodes"] if n["id"] == "Services.svc_a")
    assert unit["spec"]["tests"] == 1
    assert unit["spec"]["files"] == 2  # __init__ + impl
    # модель = код -> 0; поменяли код -> 1; пересобрали -> снова 0
    assert build.main(argv + ["--check"]) == 0
    (tmp_path / "Services/svc_a/extra.py").write_text("import sys\n", encoding="utf-8")
    assert build.main(argv + ["--check"]) == 1
    assert build.main(argv) == 0
    assert build.main(argv + ["--check"]) == 0


def test_real_repo_structural_invariants() -> None:
    root = Path(__file__).resolve().parents[3]
    model, _graph = build.build_model(root, root / "docs" / "arch-map")
    nodes = {n["id"]: n for n in model["nodes"]}
    assert len(nodes) == len(model["nodes"])  # id уникальны
    for n in model["nodes"]:
        assert n["parent"] is None or n["parent"] in nodes, n["id"]
    for e in model["edges"]:
        assert nodes[e["src"]]["kind"] == "file", e
        assert nodes[e["dst"]]["kind"] == "file", e
        assert e["kind"] in ("hard", "lazy", "tc")
    fw_units = [n for n in model["nodes"] if n["kind"] == "unit" and n["parent"] == "multiprocess_framework"]
    assert len(fw_units) >= 27
    assert model["meta"]["layers"] == [
        "multiprocess_framework",
        "Services",
        "Plugins",
        "multiprocess_prototype",
        "backend_ctl",
    ]


REGISTRY = (
    "version: 1\n"
    "modules:\n"
    '  - id: "alpha"\n'
    '    paths: ["multiprocess_framework/modules/alpha_module/"]\n'
    "    layer: framework\n"
    "    tier: core\n"
    "    docs: []\n"
    "    parent: null\n"
    '    purpose: "Alpha registry purpose"\n'
    '  - id: "svc"\n'
    '    paths: ["Services/svc_a/"]\n'
    "    layer: services\n"
    "    tier: optional\n"
    "    docs: []\n"
    "    parent: null\n"
    '    purpose: "Svc registry purpose"\n'
)


def units_of(model: dict) -> dict[str, dict]:
    return {n["id"]: n for n in model["nodes"] if n["kind"] == "unit"}


def test_tier_contour_header_lines_and_purpose_from_docstring(tmp_path: Path) -> None:
    files = base_tree()
    files["modules.yaml"] = REGISTRY
    alpha = "multiprocess_framework/modules/alpha_module"
    files[f"{alpha}/__init__.py"] = '"""Alpha — зачем юнит нужен.\n\nTier: core\nContour: ipc, state\n"""\n'
    files["multiprocess_framework/modules/beta_module/__init__.py"] = '"""Beta.\n\nTier: gold\nContour:\n"""\n'
    files["Services/svc_a/__init__.py"] = '"""Svc doc purpose."""\n'
    files["Services/svc_a/module.yaml"] = 'purpose: "Паспорт больше не читается"\ntier: frozen\n'
    model = build_for(make_tree(tmp_path, files))
    units = units_of(model)
    card = units[f"{FW}.alpha_module"]["spec"]["card"]
    assert card["purpose"] == "Alpha — зачем юнит нужен."  # докстринг важнее modules.yaml
    assert card["tier"] == "core"
    assert card["contour"] == ["ipc", "state"]
    assert card["sources"]["purpose"] == f"{alpha}/__init__.py"
    assert card["sources"]["tier"] == f"{alpha}/__init__.py"
    assert card["sources"]["contour"] == f"{alpha}/__init__.py"
    assert "summary" not in card and "runs_in" not in card
    assert units[f"{FW}.alpha_module"]["spec"]["tier"] == "core"
    beta = units[f"{FW}.beta_module"]["spec"]["card"]
    assert (beta["purpose"], beta["tier"], beta["contour"]) == (
        "Beta.",
        None,
        None,
    )  # tier gold не из core|optional|frozen
    svc = units["Services.svc_a"]["spec"]["card"]
    assert svc["purpose"] == "Svc doc purpose."
    assert svc["tier"] == "optional"  # в докстринге нет Tier -> modules.yaml
    assert svc["sources"]["tier"] == "modules.yaml"  # module.yaml игнорируется
    undeclared = {f["src_unit"]: f["detail"] for f in findings_of(model, "unit-undeclared")}
    assert f"{FW}.alpha_module" not in undeclared
    assert undeclared[f"{FW}.beta_module"] == "не объявлено: tier, contour"
    assert undeclared["Services.svc_a"] == "не объявлено: contour"


def test_card_from_registry_and_derived_fields(tmp_path: Path) -> None:
    files = base_tree()
    files["modules.yaml"] = REGISTRY
    files["Services/svc_a/__init__.py"] = '"""\n\nКраткая сводка юнита.\n\nПодробности ниже.\n"""\n'
    files["Services/svc_a/DECISIONS.md"] = (
        "# Решения\n## ADR-001 первое\n### ADR-002 второе\n## Не про номера ADR\nтекст ADR-003 не заголовок\n"
    )
    files["Services/svc_a/work.py"] = (
        "import threading\n"  # 1
        "from threading import Thread\n"  # 2
        "class H:\n"  # 3
        '    commands = {"start": 1, "stop": 2, "start": 3}\n'  # 4
        "    def setup(self, name, fn):\n"  # 5
        '        self.register_command("pause", fn)\n'  # 6
        "        self.register_command(name, fn)\n"  # 7
        "def go(fn, i):\n"  # 8
        '    register_command("resume", fn)\n'  # 9
        '    threading.Thread(target=fn, name="worker-1")\n'  # 10
        '    Thread(target=fn, name=f"w-{i}")\n'  # 11
        "    threading.Thread(target=fn)\n"  # 12
    )
    units = units_of(build_for(make_tree(tmp_path, files)))
    card = units["Services.svc_a"]["spec"]["card"]
    assert card["purpose"] == "Краткая сводка юнита."
    assert card["tier"] == "optional"
    assert card["sources"]["purpose"] == "Services/svc_a/__init__.py"
    assert card["sources"]["tier"] == "modules.yaml"
    assert "summary" not in card and "runs_in" not in card
    assert card["adr_count"] == 2
    assert card["commands"] == ["pause", "resume", "start", "stop"]
    assert card["threads"] == [
        {"name": "worker-1", "where": "Services/svc_a/work.py:10"},
        {"name": "f'w-{i}'", "where": "Services/svc_a/work.py:11"},
    ]
    other = units["multiprocess_framework.modules.beta_module"]["spec"]["card"]
    assert other["purpose"] is None
    assert other["adr_count"] is None
    assert other["commands"] == []


def test_unit_undeclared_and_registry_drift_findings(tmp_path: Path) -> None:
    files = base_tree()
    files["modules.yaml"] = (
        REGISTRY
        + '  - id: "ghost"\n    paths: ["Services/gone_svc/", "docs/x/"]\n    layer: services\n    tier: null\n'
        "    docs: []\n    parent: null\n"
        '    purpose: "Нет на диске"\n'
    )
    model = build_for(make_tree(tmp_path, files))
    undeclared = {f["src_unit"]: f["detail"] for f in findings_of(model, "unit-undeclared")}
    assert undeclared[f"{FW}.alpha_module"] == "не объявлено: contour"
    assert undeclared[f"{FW}.beta_module"] == "не объявлено: purpose, tier, contour"
    assert not any(u.endswith("__root__") for u in undeclared)  # синтетические юниты не проверяются
    drift = findings_of(model, "registry-drift")
    assert all(f["severity"] == "warn" for f in drift)
    stale = [f for f in drift if f["src_unit"] is None]
    assert len(stale) == 1
    assert "Services/gone_svc/" in stale[0]["detail"] and "docs/x/" not in stale[0]["detail"]
    missing = sorted(f["src_unit"] for f in drift if f["src_unit"] is not None)
    assert missing == [
        "Plugins.grp.plug_a",
        f"{FW}.beta_module",
        f"{FW}.gamma_module",
        "multiprocess_prototype.app",
    ]
    # без modules.yaml: поля null, дрейфа нет, unit-undeclared остаётся
    bare = tmp_path / "bare"
    model = build_for(make_tree(bare, base_tree()))
    assert findings_of(model, "registry-drift") == []
    assert units_of(model)[f"{FW}.alpha_module"]["spec"]["card"]["purpose"] is None
    assert len(findings_of(model, "unit-undeclared")) == 6


def test_unresolved_relative_in_try_importerror_is_info(tmp_path: Path) -> None:
    files = base_tree()
    files["Services/svc_a/impl.py"] = (
        "try:\n"  # 1
        "    from .missing import X\n"  # 2 ловится ImportError -> info
        "except ImportError:\n"  # 3
        "    X = None\n"  # 4
        "try:\n"  # 5
        "    from .missing2 import Y\n"  # 6 ловится KeyError -> error
        "except KeyError:\n"  # 7
        "    pass\n"  # 8
        "try:\n"  # 9
        "    from .missing3 import Z\n"  # 10 кортеж с ModuleNotFoundError -> info
        "except (ValueError, ModuleNotFoundError):\n"  # 11
        "    pass\n"  # 12
        "from .missing4 import W\n"  # 13 без try -> error
        "def f():\n"  # 14
        "    try:\n"  # 15
        "        pass\n"  # 16
        "    except ImportError:\n"  # 17
        "        from .missing5 import V\n"  # 18 в обработчике, не в теле try -> error
    )
    model = build_for(make_tree(tmp_path, files))
    got = sorted((f["where"], f["severity"]) for f in findings_of(model, "unresolved-relative"))
    p = "Services/svc_a/impl.py"
    assert got == [
        (f"{p}:10", "info"),
        (f"{p}:13", "error"),
        (f"{p}:18", "error"),
        (f"{p}:2", "info"),
        (f"{p}:6", "error"),
    ]


def test_docs_dirs_inside_units_are_skipped(tmp_path: Path) -> None:
    files = base_tree()
    files["Services/svc_a/impl.py"] = "X = 1\n"
    files["Services/svc_a/docs/__init__.py"] = ""
    files["Services/svc_a/docs/examples/ex.py"] = (
        f"from .missing import X\nfrom {FW}.alpha_module.core.thing import AlphaThing\n"
    )
    model = build_for(make_tree(tmp_path, files))
    assert [n["id"] for n in model["nodes"] if "docs" in n["id"].split(".")] == []
    assert [e for e in model["edges"] if ".docs." in e["src"]] == []
    assert [f for f in model["findings"] if "docs" in (f["where"] or "")] == []
    assert units_of(model)["Services.svc_a"]["spec"]["files"] == 2  # __init__ + impl


def run_cli(base: Path, *extra: str) -> int:
    return build.main(["--root", str(base), "--out", str(base / "out"), *extra])


def test_imports_in_method_class_body_async_and_loop(tmp_path: Path) -> None:
    files = base_tree()
    files["Services/svc_a/impl.py"] = (
        "class K:\n"  # 1
        f"    from {FW}.alpha_module import AlphaThing\n"  # 2 тело класса исполняется при импорте -> hard
        "    def m(self):\n"  # 3
        f"        from {FW}.beta_module import BetaThing\n"  # 4 метод -> lazy
        "async def a():\n"  # 5
        f"    from {FW}.gamma_module import G\n"  # 6 async def -> lazy
        "for i in range(1):\n"  # 7
        f"    from {FW}.gamma_module import H\n"  # 8 тело цикла на верхнем уровне -> hard
    )
    model = build_for(make_tree(tmp_path, files))
    assert edges_from(model, "Services.svc_a.impl") == [
        (f"{FW}.alpha_module.__init__", "hard", 2, ("AlphaThing",)),
        (f"{FW}.beta_module.__init__", "lazy", 4, ("BetaThing",)),
        (f"{FW}.gamma_module.__init__", "lazy", 6, ("G",)),
        (f"{FW}.gamma_module.__init__", "hard", 8, ("H",)),
    ]


def test_type_checking_in_function_is_tc_and_guarded_flag(tmp_path: Path) -> None:
    files = base_tree()
    files["Services/svc_a/impl.py"] = (
        "from typing import TYPE_CHECKING\n"  # 1
        "def f():\n"  # 2
        "    if TYPE_CHECKING:\n"  # 3
        f"        from {FW}.alpha_module import core\n"  # 4 tc, а не lazy
        "try:\n"  # 5
        f"    from {FW}.beta_module import B\n"  # 6 под try/except ImportError -> guarded
        "except ImportError:\n"  # 7
        "    B = None\n"  # 8
        "try:\n"  # 9
        f"    from {FW}.gamma_module import G\n"  # 10 KeyError не защита
        "except KeyError:\n"  # 11
        "    pass\n"  # 12
    )
    model = build_for(make_tree(tmp_path, files))
    got = {e["line"]: e for e in model["edges"] if e["src"] == "Services.svc_a.impl"}
    assert got[4]["kind"] == "tc" and "guarded" not in got[4]
    assert got[6]["kind"] == "hard" and got[6]["guarded"] is True
    assert got[10]["kind"] == "hard" and "guarded" not in got[10]
    assert list(got[6]) == ["src", "dst", "kind", "names", "line", "guarded"]


def test_tc_edges_do_not_count_in_fan_or_cycles(tmp_path: Path) -> None:
    files = base_tree()
    files["Services/svc_a/a.py"] = (
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from Services.svc_b import x\n"
    )
    files["Services/svc_b/__init__.py"] = ""
    files["Services/svc_b/x.py"] = "from Services.svc_a import a\n"
    model = build_for(make_tree(tmp_path, files))
    units = units_of(model)
    sa, sb = units["Services.svc_a"]["spec"], units["Services.svc_b"]["spec"]
    assert (sa["fan_in"], sa["fan_out"], sa["instability"]) == (1, 0, 0.0)
    assert (sb["fan_in"], sb["fan_out"], sb["instability"]) == (0, 1, 1.0)
    assert findings_of(model, "unit-cycle") == []


def test_tests_dirs_and_conftest_excluded_but_counted(tmp_path: Path) -> None:
    files = base_tree()
    files["Services/svc_a/impl.py"] = "X = 1\n"
    files["Services/svc_a/conftest.py"] = "X = 1\n"
    files["Services/svc_a/test_two.py"] = "def test_b():\n    pass\n"
    files["Services/svc_a/tests/__init__.py"] = ""
    files["Services/svc_a/tests/helper.py"] = "X = 1\n"
    files["Services/svc_a/tests/test_one.py"] = "def test_a():\n    pass\n"
    files["Services/svc_a/test/test_three.py"] = "def test_c():\n    pass\n"
    model = build_for(make_tree(tmp_path, files))
    svc_nodes = sorted(n["id"] for n in model["nodes"] if n["id"].startswith("Services.svc_a"))
    assert svc_nodes == ["Services.svc_a", "Services.svc_a.__init__", "Services.svc_a.impl"]
    spec = units_of(model)["Services.svc_a"]["spec"]
    assert (spec["files"], spec["tests"]) == (2, 3)  # test_one, test_two, test_three; conftest и helper не считаются


def test_check_detects_edge_only_and_finding_only_diffs(tmp_path: Path) -> None:
    files = base_tree()
    files["Services/svc_a/impl.py"] = f"from {FW}.alpha_module import AlphaThing\n"
    make_tree(tmp_path, files)
    assert run_cli(tmp_path) == 0
    path = tmp_path / "out" / "model.json"
    original = json.loads(path.read_text(encoding="utf-8"))
    assert original["edges"] and original["findings"]
    for key in ("edges", "findings"):
        tampered = json.loads(json.dumps(original))
        tampered[key].pop(0)  # расходится только одно ребро / одна находка
        path.write_text(build.render_model_json(tampered), encoding="utf-8")
        assert run_cli(tmp_path, "--check") == 1, key
        path.write_text(build.render_model_json(original), encoding="utf-8")
        assert run_cli(tmp_path, "--check") == 0, key


def test_check_covers_all_four_outputs(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    make_tree(tmp_path, base_tree())
    assert run_cli(tmp_path) == 0
    assert run_cli(tmp_path, "--check") == 0
    out = tmp_path / "out"
    for name in ("units.md", "findings.md", "model.js", "model.json"):
        original = (out / name).read_bytes()
        (out / name).write_text("garbage", encoding="utf-8")
        capsys.readouterr()
        assert run_cli(tmp_path, "--check") == 1, name
        assert name in capsys.readouterr().err
        (out / name).write_bytes(original)
        assert run_cli(tmp_path, "--check") == 0, name
    (out / "units.md").unlink()
    assert run_cli(tmp_path, "--check") == 1  # отсутствующий файл — тоже расхождение


def test_parse_error_finding_and_counts(tmp_path: Path) -> None:
    files = base_tree()
    files["Services/svc_a/broken.py"] = "def (:\n"
    model = build_for(make_tree(tmp_path, files))
    got = [(f["severity"], f["where"], f["src_unit"]) for f in findings_of(model, "parse-error")]
    assert got == [("error", "Services/svc_a/broken.py:1", "Services.svc_a")]
    assert model["meta"]["counts"]["parse_errors"] == 1
    assert model["meta"]["counts"]["unresolved_absolute"] == 0
    assert "Services.svc_a.broken" in {n["id"] for n in model["nodes"]}  # узел остаётся


def test_unresolved_absolute_finding_and_test_target_info(tmp_path: Path) -> None:
    files = base_tree()
    files["Services/svc_a/tests/__init__.py"] = ""
    files["Services/svc_a/tests/test_one.py"] = "X = 1\n"
    files["Services/svc_a/impl.py"] = (
        "from Services.svc_zzz import X\n"  # 1 нет юнита
        "import multiprocess_framework.modules.nope\n"  # 2 нет файла
        "from Services.svc_a.tests.test_one import X as T\n"  # 3 цель — тестовый файл
        "import os\n"  # 4 внешняя библиотека: молчим
    )
    model = build_for(make_tree(tmp_path, files))
    got = sorted((f["where"], f["severity"]) for f in findings_of(model, "unresolved-absolute"))
    p = "Services/svc_a/impl.py"
    assert got == [(f"{p}:1", "warn"), (f"{p}:2", "warn"), (f"{p}:3", "info")]
    info = next(f for f in findings_of(model, "unresolved-absolute") if f["severity"] == "info")
    assert "цель — тестовый файл" in info["detail"]
    assert model["meta"]["counts"]["unresolved_absolute"] == 3
    assert edges_from(model, "Services.svc_a.impl") == []


def test_recipes_plugin_class_mapped_to_units(tmp_path: Path) -> None:
    files = base_tree()
    files["multiprocess_prototype/recipes/r1.yaml"] = (
        "name: x\n"  # 1
        "# plugin_class: Services.nowhere.X\n"  # 2 комментарий: не считается
        "processes:\n"  # 3
        "  - plugin_class: Plugins.grp.plug_a.plugin.PlugA\n"  # 4
        '  - plugin_class: "Services.svc_a.thing.Thing"\n'  # 5 в кавычках
    )
    files["multiprocess_prototype/recipes/r2.yaml"] = (
        "processes:\n"  # 1
        "  - plugin_class: Plugins.grp.plug_a.plugin.PlugA\n"  # 2
        "  - plugin_class: Plugins.grp.ghost.plugin.Ghost\n"  # 3 юнита нет
        "  - plugin_class: Plugins.grp.plug_ab.plugin.Other\n"  # 4 plug_a — не префикс plug_ab
    )
    files["Services/svc_a/other.yaml"] = "plugin_class: Plugins.grp.ghost.X\n"  # вне prototype: тоже сканируется
    make_tree(tmp_path, files)
    assert run_cli(tmp_path) == 0
    model = json.loads((tmp_path / "out" / "model.json").read_text(encoding="utf-8"))
    units = units_of(model)
    r1, r2 = "multiprocess_prototype/recipes/r1.yaml", "multiprocess_prototype/recipes/r2.yaml"
    assert units["Plugins.grp.plug_a"]["spec"]["recipes"] == [r1, r2]
    assert units["Services.svc_a"]["spec"]["recipes"] == [r1]
    assert units[f"{FW}.alpha_module"]["spec"]["recipes"] == []
    unknown = sorted((f["where"], f["severity"]) for f in findings_of(model, "recipe-unknown-plugin"))
    assert unknown == [("Services/svc_a/other.yaml:1", "warn"), (f"{r2}:3", "warn"), (f"{r2}:4", "warn")]
    text = (tmp_path / "out" / "units.md").read_text(encoding="utf-8")
    assert "в рецептах" in text and "plugin_class:" in text


def facade_tree(init_text: str) -> dict[str, str]:
    files = base_tree()
    files[f"{FW.replace('.', '/')}/alpha_module/core/__init__.py"] = init_text
    return files


def test_deep_import_skips_init_with_all(tmp_path: Path) -> None:
    files = facade_tree('__all__ = ["AlphaThing"]\nfrom .thing import AlphaThing\n')
    files["Services/svc_a/use.py"] = (
        f"from {FW}.alpha_module.core import AlphaThing\n"  # 1 имя в __all__
        f"import {FW}.alpha_module.core\n"  # 2 без имён: через витрину
        f"from {FW}.alpha_module.core import *\n"  # 3 звёздочка: через витрину
    )
    model = build_for(make_tree(tmp_path, files))
    assert findings_of(model, "deep-import") == []


def test_deep_import_name_outside_all_fires(tmp_path: Path) -> None:
    files = facade_tree('__all__ = ["AlphaThing"]\nfrom .thing import AlphaThing\n')
    files["Services/svc_a/use.py"] = f"from {FW}.alpha_module.core import AlphaThing, Hidden\n"
    model = build_for(make_tree(tmp_path, files))
    deep = findings_of(model, "deep-import")
    assert [f["where"] for f in deep] == ["Services/svc_a/use.py:1"]
    assert "вне __all__: Hidden" in deep[0]["detail"]
    assert "AlphaThing" not in deep[0]["detail"].split("вне __all__:")[1]


def test_deep_import_init_without_all_fires(tmp_path: Path) -> None:
    files = facade_tree("from .thing import AlphaThing\n")  # __all__ нет
    files["multiprocess_framework/modules/beta_module/sub/__init__.py"] = "__all__ = compute()\n"  # не литерал
    files["Services/svc_a/use.py"] = (
        f"from {FW}.alpha_module.core import AlphaThing\n"  # 1
        f"from {FW}.beta_module.sub import X\n"  # 2
    )
    model = build_for(make_tree(tmp_path, files))
    assert sorted(f["where"] for f in findings_of(model, "deep-import")) == [
        "Services/svc_a/use.py:1",
        "Services/svc_a/use.py:2",
    ]


def test_recipes_live_and_inactive_split_repo_wide(tmp_path: Path) -> None:
    files = base_tree()
    files["Plugins/grp/plug_b/__init__.py"] = ""
    ref_a = "plugin_class: Plugins.grp.plug_a.plugin.A\n"
    files["configs/live.yaml"] = (
        ref_a + "plugin_class: Plugins.grp.ghost.plugin.G\n"
    )  # вне prototype; вторая строка — неизвестная
    files["multiprocess_prototype/recipes/tests/old.yaml"] = ref_a
    files["Services/svc_a/fixtures/f.yml"] = ref_a
    files["archive/x.yaml"] = ref_a
    files["fixtures/b.yaml"] = "plugin_class: Plugins.grp.plug_b.plugin.B\n"
    files["tests/unknown.yaml"] = "plugin_class: Plugins.grp.ghost.plugin.T\n"  # неживой неизвестный: без находки
    for skipped in (
        ".hidden/h.yaml",
        ".claude/worktrees/w/x.yaml",
        "node_modules/n.yaml",
        "graphify-out/g.yaml",
        "logs_old/l.yaml",
        "data/atlas/a.yaml",
        "__pycache__/p.yaml",
    ):
        files[skipped] = ref_a
    model = build_for(make_tree(tmp_path, files))
    units = units_of(model)
    a = units["Plugins.grp.plug_a"]["spec"]
    assert a["recipes"] == ["configs/live.yaml"]
    assert a["recipes_inactive"] == [
        "Services/svc_a/fixtures/f.yml",
        "archive/x.yaml",
        "multiprocess_prototype/recipes/tests/old.yaml",
    ]
    b = units["Plugins.grp.plug_b"]["spec"]
    assert (b["recipes"], b["recipes_inactive"]) == ([], ["fixtures/b.yaml"])
    unknown = [(f["where"], f["severity"]) for f in findings_of(model, "recipe-unknown-plugin")]
    assert unknown == [("configs/live.yaml:2", "warn")]
    assert run_cli(tmp_path) == 0
    text = (tmp_path / "out" / "units.md").read_text(encoding="utf-8")
    assert "только живые" in text


def test_cli_exit_1_on_error_finding(tmp_path: Path) -> None:
    files = base_tree()
    files["Services/svc_a/broken.py"] = "def (:\n"  # parse-error: severity error
    make_tree(tmp_path, files)
    assert run_cli(tmp_path) == 1
    assert (tmp_path / "out" / "model.json").is_file()  # файлы записаны и при коде 1
    assert run_cli(tmp_path, "--check") == 0  # --check смотрит на расхождение, не на ошибки
    (tmp_path / "Services/svc_a/broken.py").write_text("X = 1\n", encoding="utf-8")
    assert run_cli(tmp_path) == 0
