"""Слепые приёмочные тесты CLI `atlas map <юнит|файл>` (Task 4.2b-2, stage 2, RED до кода): RED 5.

Purpose: разбор цели (id юнита -> `unit`, путь `.py` -> `file`, каталог и неизвестное значение -> `not found`, код 2,
    значение входа в stderr не печатается), `--format` по умолчанию `passport`, `--budget` по умолчанию 60, `--all` из
    списка `MAP_SHOW_ALL`, одна цель, `ref` не принимает `map`-имена среза и юниты. Контракт — файлы
    `plans/2026-11-06_atlas-passport/tasks/4.2b-2.md` и `map-form.md`, докстринги `scripts/atlas/passport.py`;
    флаг `map`
    парсер знает (заглушка INTERFACE), красные идут от заглушки.
Public API: тесты test_*; публичных имён нет.
Stability: lite

Фикстура — репозиторий юнита `u` из `test_passport_map.py` (`_seed`, `_full_text`). Вызовы `main` — через фикстуру
`atlas` из conftest (daemon-поток с дедлайном). Ожидаемые значения — литералы.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.atlas.tests.conftest import GitRepo
from scripts.atlas.tests.test_passport_map import _full_text, _lines, _seed

__all__: list[str] = []


def test_map_target_resolution_and_exit_codes(repo: GitRepo, atlas: Any, tmp_path: Path) -> None:
    """Цель: id юнита -> `kind: unit` (текст без `--format` — `== unit u ==`, при бюджете 60
    образец целиком); путь `.py`
    -> `file`; неизвестное значение, каталог (`u/`, `u/tests`), не-`.py` файл -> код 2, stdout пуст, stderr —
    `atlas map: not found` без значения входа; нет цели и две цели -> код 2; `--all` не из `MAP_SHOW_ALL` -> 2, из
    списка (повторяемый) -> 0; `ref ... --all members` -> 2, `ref u` -> `not found` (код 2: `ref` юнитов не знает);
    `--root` из чужого cwd."""
    sha, _ = _seed(repo)

    js = atlas(repo, "map", "u", "--format", "json")
    assert js.code == 0, js.err
    records = json.loads(js.out)
    assert len(records) == 1
    unit = records[0]
    assert (unit["passport"], unit["kind"], unit["id"], unit["path"], unit["line"], unit["sha"]) == (
        1,
        "unit",
        "u",
        "u/",
        None,
        sha,
    )
    assert list(unit)[7:] == ["purpose", "interface", "links", "runtime", "checks", "status"]

    text = atlas(repo, "map", "u")  # --format по умолчанию: passport; --budget по умолчанию 60
    assert text.code == 0, text.err
    assert text.out.splitlines()[0] == "== unit u =="
    assert _lines(text.out) == _lines(_full_text(sha, unit["scanner"]))

    file = atlas(repo, "map", "u/b.py", "--format", "json")
    assert file.code == 0, file.err
    [fp] = json.loads(file.out)
    assert (fp["kind"], fp["id"], fp["path"], fp["line"]) == ("file", "u/b.py", "u/b.py", None)
    assert [m["name"] for m in fp["interface"]["members"]] == ["run_b", "arun", "_hidden"]
    assert atlas(repo, "map", "u/b.py").out.splitlines()[0] == "== file u/b.py =="

    for bad in ("secret_zzz_unit", "u/", "u/tests", "u/README.md", "u/nope.py"):
        miss = atlas(repo, "map", bad)
        assert miss.code == 2, (bad, miss.err)
        assert miss.out == "", (bad, miss.out)
        assert "atlas map: not found" in miss.err.splitlines(), (bad, miss.err)
    assert (
        "secret_zzz_unit" not in atlas(repo, "map", "secret_zzz_unit").err
    )  # значение входа в сообщении не печатается
    missing_json = atlas(repo, "map", "secret_zzz_unit", "--format", "json")
    assert missing_json.code == 2 and "secret_zzz_unit" not in missing_json.err

    none = atlas(repo, "map")
    assert none.code == 2 and none.out == "" and none.err.strip() != ""
    two = atlas(repo, "map", "u", "u/b.py")
    assert two.code == 2 and two.out == "" and two.err.strip() != ""

    bogus = atlas(repo, "map", "u", "--all", "call_sites")
    assert bogus.code == 2 and bogus.out == "" and bogus.err.strip() != ""
    # ревью стадии 5, И2: ошибка ввода, не падение `render_text` (ValueError -> общий except -> 2 с traceback)
    assert "atlas map: --all принимает members, used_by, tests, threads, io" in bogus.err.splitlines()
    assert "Traceback" not in bogus.err
    lifted = atlas(repo, "map", "u", "--all", "members", "--all", "used_by", "--budget", "1")
    assert lifted.code == 0, lifted.err
    lifted_lines = [line.strip() for line in lifted.out.splitlines()]
    assert "u/b.py — Модуль b.  (run_b, arun)" in lifted_lines and "w — w/y.py:5 (import) ×1" in lifted_lines
    assert not [x for x in lifted_lines if x.startswith("показано")]
    full = atlas(repo, "map", "u", "--budget", "1", "--full")
    assert full.code == 0 and _lines(full.out) == _lines(_full_text(sha, unit["scanner"]))

    ref_all = atlas(repo, "ref", "u/a.py::A", "--format", "passport", "--all", "members")
    assert ref_all.code == 2 and ref_all.err.strip() != ""
    # ревью стадии 5 р.2, М3: ошибка ввода `ref`, не падение `render_text` (мутант J08)
    assert "atlas ref: --all принимает used_by, call_sites, subclasses, structural, tests" in ref_all.err.splitlines()
    assert "Traceback" not in ref_all.err
    ref_unit = atlas(repo, "ref", "u", "--format", "json")
    assert ref_unit.code == 2
    assert json.loads(ref_unit.out) == [{"id": "u", "error": "not found"}]
    ref_ok = atlas(repo, "ref", "u/a.py::A", "--format", "json")
    assert ref_ok.code == 0 and json.loads(ref_ok.out)[0]["kind"] == "class"

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    far = atlas(repo, "map", "u", "--format", "json", "--root", str(repo.path), cwd=elsewhere)
    assert far.code == 0, far.err
    assert json.loads(far.out)[0]["sha"] == sha
