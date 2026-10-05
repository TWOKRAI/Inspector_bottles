# ruff: noqa: E501  -- литералы-фикстуры планов в одну строку
"""Авторские тесты опасностей механизма Task 4.1: `summarize_plan` — адаптер над `analyze_plan`.

Что может сломаться в ЭТОМ механизме (так, как он построен):

1. Кэш по пути модуля. Ledger грузит `<корень>/scripts/plans_progress/plans_progress.py` один
   раз на процесс и запоминает результат по пути. Ключ не по пути (одна глобальная ячейка) —
   и второй корень в том же процессе считается модулем первого: тихо, без ошибки.
2. Имя в `sys.modules`. Модуль регистрируется ДО `exec_module` (иначе `@dataclass` падает).
   Фиксированное имя (`plans_progress`) затирает чужой уже импортированный модуль с тем же
   именем или берёт его вместо своего; общее имя на два корня — тот же дефект, что в п. 1.
3. Неудача загрузки. Она кэшируется и печатает ОДНУ строку stderr на процесс и корень.
   Без кэша неудачи модуль исполняется на каждом плане (и строка повторяется на каждом);
   полуинициализированный модуль не должен остаться в `sys.modules`.
4. Отсутствие модуля — не неудача: молча, без строки, и не навсегда (файл, появившийся
   позже в том же процессе, подхватывается — промах не кэшируется).
5. Исключение `analyze_plan` на одном плане: только этот план уходит в «прежний», строка
   stderr одна на план, сколько бы команд ни спросили этот план.
6. Форма плана, которую страница не знает (файл не в `plans/`, `_archive/`, `_archive/<квартал>/`
   и не `plan.md`/`phase-N`/`tasks/`), — «прежний» без шума, не исключение.
7. Сид: копия ledger в `.claude/plugins/core/scripts/` побайтно равна источнику, а хеш
   манифеста — sha256 байтов после CRLF->LF (рабочая копия на Windows хранит CRLF: хеш
   «как на диске» разъедется с хешем, который считает доставка).

Ledger грузится в процессе свежим экземпляром на тест: у каждого свой кэш.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
LEDGER_PATH = REPO_ROOT / "scripts" / "plans_ledger.py"
SEED_PATH = REPO_ROOT / ".claude" / "plugins" / "core" / "scripts" / "plans_ledger.py"
MANIFEST = REPO_ROOT / ".claude" / ".delivery-manifest.json"
PARSER = REPO_ROOT / "scripts" / "plans_progress" / "plans_progress.py"

TAIL = "# B\n\n#### Task 1.1 — альфа ✅ DONE\n\nт\n\n#### Task 1.2 — бета\n\nт\n\n#### Task 1.3 — гамма ✅ DONE\n\nт\n"
TABLE = "# T\n\n| ✓ T1.1 | a |\n| T1.2 | b |\n"


@pytest.fixture
def ledger_mod():
    """Свежий экземпляр ledger (свой кэш парсеров) под уникальным именем."""
    name = f"plans_ledger_author_{id(object())}"
    spec = importlib.util.spec_from_file_location(name, LEDGER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop(name, None)
    for key in list(getattr(mod, "_PARSER_CACHE", {})):
        for mname, m in list(sys.modules.items()):
            if getattr(m, "__file__", None) == key:
                sys.modules.pop(mname, None)


def _root(tmp: Path, name: str, plans: dict[str, str], parser: str | None) -> Path:
    root = tmp / name
    for rel, text in plans.items():
        p = root / "plans" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode("utf-8"))
    (root / "plans").mkdir(parents=True, exist_ok=True)
    if parser is not None:
        dst = root / "scripts" / "plans_progress" / "plans_progress.py"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(parser.encode("utf-8"))
    return root


def _parser_text(extra: str = "") -> str:
    return PARSER.read_text(encoding="utf-8").replace("\r\n", "\n") + extra


def _truncating(k: int) -> str:
    """Копия парсера, у которой analyze_plan оставляет первые k задач: метка «чей модуль считал»."""
    return _parser_text(
        f"\n_orig = analyze_plan\ndef analyze_plan(*a, **kw):\n    p = _orig(*a, **kw)\n    p.tasks = p.tasks[:{k}]\n    return p\n"
    )


def _summ(mod, path: Path):
    return mod.summarize_plan(mod.discover_plan_files(path))


# --------------------------------------------------------------------------- 1. кэш на много корней


def test_many_roots_in_one_process_each_counted_by_its_own_module(ledger_mod, tmp_path, capsys):
    roots = [_root(tmp_path, f"r{k}", {"2026-07-02_tail.md": TAIL}, _truncating(k)) for k in range(4)]
    plans = [r / "plans" / "2026-07-02_tail.md" for r in roots]
    # чередование корней дважды: второй круг обязан взять модуль из кэша СВОЕГО корня
    got = [_summ(ledger_mod, p).total for p in plans + plans[::-1]]
    assert got == [0, 1, 2, 3, 3, 2, 1, 0]
    assert len(ledger_mod._PARSER_CACHE) == 4
    assert capsys.readouterr().err == ""


def test_each_module_is_registered_under_a_path_unique_name(ledger_mod, tmp_path):
    roots = [_root(tmp_path, f"r{k}", {"2026-07-02_tail.md": TAIL}, _parser_text()) for k in range(3)]
    for r in roots:
        _summ(ledger_mod, r / "plans" / "2026-07-02_tail.md")
    loaded = ledger_mod._PARSER_CACHE
    names = {m.__name__ for m in loaded.values()}
    assert len(names) == 3, names
    for key, m in loaded.items():
        assert sys.modules[m.__name__] is m, "модуль зарегистрирован в sys.modules (нужно @dataclass)"
        assert Path(m.__file__) == Path(key)


# --------------------------------------------------------------------------- 2. коллизии имён sys.modules


def test_foreign_plans_progress_in_sys_modules_is_neither_used_nor_replaced(ledger_mod, tmp_path, monkeypatch):
    decoy = types.ModuleType("plans_progress")
    decoy.analyze_plan = lambda *a, **kw: (_ for _ in ()).throw(AssertionError("взят чужой модуль"))
    monkeypatch.setitem(sys.modules, "plans_progress", decoy)
    root = _root(tmp_path, "r", {"2026-07-11_tab.md": TABLE}, _parser_text())
    s = _summ(ledger_mod, root / "plans" / "2026-07-11_tab.md")
    assert (s.done, s.counted) == (1, 2), "таблица `✓` — счёт адаптера"
    assert sys.modules["plans_progress"] is decoy, "чужой модуль с тем же коротким именем не затёрт"


# --------------------------------------------------------------------------- 3. неудача загрузки


def test_load_failure_prints_once_and_leaves_no_half_module(ledger_mod, tmp_path, capsys):
    root = _root(
        tmp_path,
        "r",
        {"2026-07-02_tail.md": TAIL, "2026-07-11_tab.md": TABLE},
        _parser_text("\nraise ValueError('X')\n"),
    )
    before = set(sys.modules)
    for _ in range(3):
        a = _summ(ledger_mod, root / "plans" / "2026-07-02_tail.md")
        b = _summ(ledger_mod, root / "plans" / "2026-07-11_tab.md")
    assert (a.done, a.total, b.done, b.total) == (0, 3, 0, 0), "прежний код"
    err = [ln for ln in capsys.readouterr().err.splitlines() if ln.strip()]
    assert len(err) == 1 and "ValueError" in err[0], err
    leaked = [n for n in set(sys.modules) - before if n.startswith("_plans_ledger_parser_")]
    assert leaked == [], f"полуинициализированный модуль остался: {leaked}"


def test_module_without_analyze_plan_is_a_load_failure(ledger_mod, tmp_path, capsys):
    root = _root(tmp_path, "r", {"2026-07-02_tail.md": TAIL}, "X = 1\n")
    s = _summ(ledger_mod, root / "plans" / "2026-07-02_tail.md")
    assert (s.done, s.total) == (0, 3)
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "AttributeError" in err, err


# --------------------------------------------------------------------------- 4. отсутствие модуля


def test_missing_module_is_silent_and_not_cached_as_failure(ledger_mod, tmp_path, capsys):
    root = _root(tmp_path, "r", {"2026-07-11_tab.md": TABLE}, None)
    plan = root / "plans" / "2026-07-11_tab.md"
    s = _summ(ledger_mod, plan)
    assert (s.done, s.counted) == (0, 0), "прежний: таблицу не знает"
    dst = root / "scripts" / "plans_progress" / "plans_progress.py"
    dst.parent.mkdir(parents=True)
    dst.write_bytes(_parser_text().encode("utf-8"))
    s = _summ(ledger_mod, plan)
    assert (s.done, s.counted) == (1, 2), "модуль, появившийся позже, подхвачен"
    assert capsys.readouterr().err == ""


# --------------------------------------------------------------------------- 5. исключение analyze_plan


def test_analyze_plan_exception_reported_once_per_plan_across_repeated_calls(ledger_mod, tmp_path, capsys):
    patch = "\n_o = analyze_plan\ndef analyze_plan(name, *a):\n    if name == '2026-07-11_tab':\n        raise KeyError(name)\n    return _o(name, *a)\n"
    root = _root(tmp_path, "r", {"2026-07-02_tail.md": TAIL, "2026-07-11_tab.md": TABLE}, _parser_text(patch))
    for _ in range(3):
        bad = _summ(ledger_mod, root / "plans" / "2026-07-11_tab.md")
        good = _summ(ledger_mod, root / "plans" / "2026-07-02_tail.md")
    assert (bad.done, bad.counted) == (0, 0), "упавший план — прежним кодом"
    assert (good.done, good.counted) == (2, 3), "соседний — адаптером"
    err = [ln for ln in capsys.readouterr().err.splitlines() if ln.strip()]
    assert len(err) == 1 and "KeyError" in err[0] and "2026-07-11_tab" in err[0], err


# --------------------------------------------------------------------------- 6. незнакомая форма


def test_unknown_plan_shape_falls_back_without_noise(ledger_mod, tmp_path, capsys):
    root = _root(tmp_path, "r", {"sub/notes.md": TABLE}, _parser_text())
    s = ledger_mod.summarize_plan([root / "plans" / "sub" / "notes.md"])
    assert (s.done, s.counted) == (0, 0), "файл не в plans/ и не plan.md/phase/tasks -> прежний"
    assert capsys.readouterr().err == ""


def test_phase_file_path_first_resolves_to_its_directory(ledger_mod, tmp_path):
    # paths без plan.md (каталог только с phase-N): plan_dir — каталог phase-файла
    root = _root(
        tmp_path,
        "r",
        {"2026-07-06_p/phase-2-ui.md": "# Ф2\n\n#### Task 2.1 — окно ✅ DONE\n\n#### Task 2.2 — б\n"},
        _parser_text(),
    )
    s = _summ(ledger_mod, root / "plans" / "2026-07-06_p")
    assert (s.done, s.counted, s.open_tasks, s.phase) == (1, 2, ["2.2"], "phase 2")


# --------------------------------------------------------------------------- 7. сид и манифест


def test_seed_copy_is_byte_identical():
    assert LEDGER_PATH.read_bytes() == SEED_PATH.read_bytes()


def test_manifest_hash_is_lf_normalised_not_raw_bytes():
    raw = LEDGER_PATH.read_bytes()
    recorded = json.loads(MANIFEST.read_text(encoding="utf-8"))["scripts/plans_ledger.py"]
    assert recorded == hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
    if b"\r\n" in raw:
        assert recorded != hashlib.sha256(raw).hexdigest(), "хеш CRLF-копии не годится"


# --------------------------------------------------------------------------- поля PlanSummary: дубль id


def test_duplicate_open_id_is_counted_twice_but_listed_once(ledger_mod, tmp_path):
    # оба пункта ОТКРЫТЫ: счёт как у страницы (2), в open_tasks id без повторов
    text = "# D\n\n## Порядок выполнения\n\n- Task 1.1: a [PENDING]\n- Task 1.1: a [IN PROGRESS]\n"
    root = _root(tmp_path, "r", {"2026-07-10_dup.md": text}, _parser_text())
    s = _summ(ledger_mod, root / "plans" / "2026-07-10_dup.md")
    assert (s.done, s.total, s.counted, s.open_tasks) == (0, 2, 2, ["1.1"])


# --------------------------------------------------------------------------- фаза: пункты раздела порядка главнее заголовков


@pytest.mark.parametrize("with_parser", [False, True], ids=["legacy", "adapter"])
def test_phase_heading_outside_order_section_is_ignored_when_items_exist(ledger_mod, tmp_path, with_parser):
    # у плана есть пункты раздела порядка -> фаза только из пункта (здесь её нет): None в обоих режимах.
    # `## Phase 1` над заголовком задачи прежний ledger не читает (живой план line-sim-layer-editor).
    text = "# P\n\n## Порядок выполнения\n\n- Task 1.1: a [PENDING]\n\n## Phase 1\n\n### Task 1.1: a\n"
    root = _root(tmp_path, "r", {"2026-07-14_ph/plan.md": text}, _parser_text() if with_parser else None)
    s = _summ(ledger_mod, root / "plans" / "2026-07-14_ph")
    assert (s.done, s.counted, s.open_tasks, s.phase) == (0, 1, ["1.1"], None)


def test_ledger_side_error_after_analyze_plan_is_not_swallowed(ledger_mod, tmp_path, monkeypatch, capsys):
    # try охватывает только вызовы парсера: ошибка в разборе результата — дефект ledger, она идёт наружу
    def boom(*a, **kw):
        raise RuntimeError("ledger-side")

    monkeypatch.setattr(ledger_mod, "_summary_from_plan", boom)
    root = _root(tmp_path, "r", {"2026-07-02_tail.md": TAIL}, _parser_text())
    with pytest.raises(RuntimeError, match="ledger-side"):
        _summ(ledger_mod, root / "plans" / "2026-07-02_tail.md")
    assert "analyze_plan failed" not in capsys.readouterr().err
