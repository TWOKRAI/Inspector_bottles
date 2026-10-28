"""Каноническая форма рецепта во framework (Task 1.1f): read_canonical, RecipeFormatError, on_insert, контракт хука.

Приёмка по ``plans/2026-10-26_recipe-save-noise/design.md`` §2.3 (правила движка, включая «равный отсутствующий ключ
не создаётся») и §10 (политика канонической формы, п. 1-5).

Правила файла:
- ожидаемые байты, ``rev`` и документы — литералы и ``hashlib``, не результат кода под тестом;
- проверяется наблюдаемый эффект (байты файла, ``rev``, тип исключения, итоговый документ); шпион ``on_insert`` —
  там, где сам контракт — «вызван ровно для вставляемого поддерева»;
- вызов, который может зависнуть (контракт хука запускает подпроцессы), идёт в daemon-потоке с ``join(timeout)``;
- framework не импортирует прототип: синтетические хуки лежат на уровне модуля — только так подпроцесс контракта
  достаёт их строкой ``"pkg.module:Attr"``.
"""

from __future__ import annotations

import copy
import hashlib
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from multiprocess_framework.modules.recipe.hook_contract import assert_format_hook_contract
from multiprocess_framework.modules.recipe.manager import RecipeFormatError, RecipeManager
from multiprocess_framework.modules.recipe.yaml_io import YamlWriteRefused, apply_delta, patch_yaml_preserving

# Подпроцесс контракта импортирует этот модуль по полному имени: пытаться взять ``__name__`` нельзя — pytest
# может назвать модуль иначе (rootdir/conftest), а в подпроцессе того имени нет.
_THIS_MODULE = "multiprocess_framework.modules.recipe.tests.test_canonical_form"

SLUG = "r1"

# Рецепты записаны в стиле движка (ruamel indent 2/4/2): иначе целая запись переотступит файл.
BASE_TEXT = "name: R1\nlabel: x\ndescription: old\nblueprint:\n  processes:\n    - id: a\n"

_CONTRACT_DEADLINE_S = 240.0  # 4 подпроцесса контракта (по 120 с потолок каждого) идут параллельно


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _make(tmp_path: Path, **kwargs: Any) -> tuple[RecipeManager, Path]:
    recipes_dir = tmp_path / "recipes"
    recipes_dir.mkdir(exist_ok=True)
    # Менеджер берёт у движка только ``recipes_dir``: целый RecipeEngine с TreeStore для этих тестов не нужен.
    return RecipeManager(engine=SimpleNamespace(recipes_dir=recipes_dir), **kwargs), recipes_dir


def _put(recipes_dir: Path, text: str, slug: str = SLUG) -> bytes:
    raw = text.encode("utf-8")
    (recipes_dir / f"{slug}.yaml").write_bytes(raw)
    return raw


# ---------------------------------------------------------------------------------------------------------
# Синтетические хуки (уровень модуля: подпроцесс контракта достаёт их строкой "pkg.module:Attr")
# ---------------------------------------------------------------------------------------------------------


class IdentityHook:
    """Тождество: корректный хук. Не-mapping -> ``RecipeFormatError``."""

    def normalize(self, body: Any) -> dict:
        if not isinstance(body, dict):
            raise RecipeFormatError("корень рецепта не mapping")
        return copy.deepcopy(body)

    def validate(self, body: dict) -> list[dict]:
        return []

    def to_topology(self, body: dict) -> dict:
        return body


class CaseHook(IdentityHook):
    """``name`` -> нижний регистр, ``label`` -> верхний (формат-хук приложения в миниатюре)."""

    def normalize(self, body: Any) -> dict:
        out = super().normalize(body)
        if "name" in out:
            out["name"] = out["name"].lower()
        if "label" in out:
            out["label"] = out["label"].upper()
        return out


class NonIdempotentHook(IdentityHook):
    """``N(N(x)) != N(x)``: каждый проход дописывает ``!``. Остальные свойства контракта соблюдены."""

    def normalize(self, body: Any) -> dict:
        out = super().normalize(body)
        out["name"] = out["name"] + "!"
        return out


class PartialOnInvalidHook(IdentityHook):
    """На невалидном теле отдаёт частичный результат вместо ``RecipeFormatError``."""

    def normalize(self, body: Any) -> dict:
        if not isinstance(body, dict):
            return {}
        return super().normalize(body)


class WrongErrorOnInvalidHook(IdentityHook):
    """На невалидном теле бросает ``KeyError`` — не типизированную ``RecipeFormatError``."""

    def normalize(self, body: Any) -> dict:
        if not isinstance(body, dict):
            raise KeyError("name")
        return super().normalize(body)


class HashSeedHook(IdentityHook):
    """Порядок ``tags`` зависит от ``hash(str)`` — то есть от ``PYTHONHASHSEED``; внутри процесса детерминирован."""

    def normalize(self, body: Any) -> dict:
        out = super().normalize(body)
        if "tags" in out:
            out["tags"] = sorted(set(out["tags"]), key=hash)
        return out


class RenameOldToNewHook(IdentityHook):
    """Смена формы: корневой ключ ``old`` -> ``new`` (как v1 ``topology:`` -> ``blueprint:``)."""

    def normalize(self, body: Any) -> dict:
        out = super().normalize(body)
        if "old" in out:
            out["new"] = out.pop("old")
        return out


class TopologyToBlueprintHook(IdentityHook):
    """v1 ``topology:`` -> ``blueprint:`` (ключ, который ждёт ``save_layout``)."""

    def normalize(self, body: Any) -> dict:
        out = super().normalize(body)
        if "topology" in out:
            out["blueprint"] = out.pop("topology")
        return out


class AddVersionHook(IdentityHook):
    """Хук только ДОБАВЛЯЕТ корневой ключ ``version`` (умолчание)."""

    def normalize(self, body: Any) -> dict:
        out = super().normalize(body)
        out.setdefault("version", 3)
        return out


class MoveGuiPositionsDeeperHook(IdentityHook):
    """Перенос вглубь: корневой ``gui_positions`` -> ``blueprint.metadata.gui_positions``; корневых ключей не вводит."""

    def normalize(self, body: Any) -> dict:
        out = super().normalize(body)
        if "gui_positions" in out:
            positions = out.pop("gui_positions")
            out["blueprint"].setdefault("metadata", {})["gui_positions"] = positions
        return out


class MutatingRenameHook(IdentityHook):
    """``old`` -> ``new`` прямо во входе (нарушает Post протокола: вход не мутирует) и возвращает его же."""

    def normalize(self, body: Any) -> dict:
        if not isinstance(body, dict):
            raise RecipeFormatError("корень рецепта не mapping")
        if "old" in body:
            body["new"] = body.pop("old")
        return body


class BoomOnFileHook(IdentityHook):
    """Бросает на теле с ключом ``boom`` (несёт его только файл)."""

    def normalize(self, body: Any) -> dict:
        if isinstance(body, dict) and "boom" in body:
            raise KeyError("boom")
        return super().normalize(body)


class NonDictResultHook(IdentityHook):
    """Возвращает не dict."""

    def normalize(self, body: Any) -> Any:
        return [1, 2]


# ---------------------------------------------------------------------------------------------------------
# read_canonical
# ---------------------------------------------------------------------------------------------------------


def test_read_canonical_returns_normalized_doc_and_rev(tmp_path: Path) -> None:
    mgr, d = _make(tmp_path, format_hook=CaseHook())
    raw = _put(d, BASE_TEXT)

    doc, rev = mgr.read_canonical(SLUG)

    # Файл несёт ``R1``/``x``; канон — после хука: ``r1``/``X``.
    assert doc == {"name": "r1", "label": "X", "description": "old", "blueprint": {"processes": [{"id": "a"}]}}
    assert rev == _sha(raw)
    assert (d / f"{SLUG}.yaml").read_bytes() == raw


def test_read_canonical_missing_file_returns_none_none(tmp_path: Path) -> None:
    mgr, d = _make(tmp_path, format_hook=CaseHook())

    assert mgr.read_canonical(SLUG) == (None, None)
    assert list(d.iterdir()) == []


@pytest.mark.parametrize(
    "text",
    ["secret_marker: [\n", "- 1\n- 2\n"],
    ids=["broken_yaml", "list_root"],
)
def test_read_canonical_unparseable_raises_format_error(tmp_path: Path, text: str) -> None:
    mgr, d = _make(tmp_path, format_hook=CaseHook())
    raw = _put(d, text)

    with pytest.raises(RecipeFormatError) as info:
        mgr.read_canonical(SLUG)

    assert isinstance(info.value, ValueError)
    assert "secret_marker" not in str(info.value)  # содержимое файла в сообщение не попадает
    assert (d / f"{SLUG}.yaml").read_bytes() == raw


@pytest.mark.parametrize("hook", [BoomOnFileHook(), NonDictResultHook()], ids=["hook_raises", "hook_returns_list"])
def test_read_canonical_hook_failure_raises_format_error(tmp_path: Path, hook: Any) -> None:
    mgr, d = _make(tmp_path, format_hook=hook)
    raw = _put(d, "name: r1\nboom: 1\n")

    with pytest.raises(RecipeFormatError):
        mgr.read_canonical(SLUG)

    assert (d / f"{SLUG}.yaml").read_bytes() == raw


@pytest.mark.parametrize("slug", ["", "..", "a/b"], ids=["empty", "dotdot", "sep"])
def test_read_canonical_rejects_path_like_slug(tmp_path: Path, slug: str) -> None:
    mgr, d = _make(tmp_path)

    with pytest.raises(ValueError):
        mgr.read_canonical(slug)

    assert list(d.iterdir()) == []


def test_patch_recipe_yaml11_scalar_unchanged_not_rewritten(tmp_path: Path) -> None:
    """Р4 (из 1.1c): ``flag: yes`` в файле, правка соседнего листа через канонический документ — ``yes`` на месте."""
    mgr, d = _make(tmp_path)
    text = "flag: yes\nname: r1\ndescription: old\nblueprint:\n  processes:\n    - id: a\n"
    _put(d, text)

    doc, rev = mgr.read_canonical(SLUG)
    assert doc is not None
    assert doc["flag"] is True  # PyYAML (YAML 1.1) читает ``yes`` как bool: канон несёт True, файл — слово
    doc["description"] = "new"
    new_rev = mgr.patch_recipe(SLUG, doc, expected_rev=rev)

    expected = text.replace("description: old", "description: new").encode("utf-8")
    assert (d / f"{SLUG}.yaml").read_bytes() == expected
    assert new_rev == _sha(expected)


# ---------------------------------------------------------------------------------------------------------
# Запись: неразбираемый файл, хук файла, отказ на смене формы корня
# ---------------------------------------------------------------------------------------------------------


def test_patch_recipe_unchanged_yaml11_word_with_changed_bool_like_string_refused(tmp_path: Path) -> None:
    """Неизменённое ``flag: yes`` запись не отказывает; изменённый лист строкой ``On`` (PyYAML читает bool) — отказ."""
    mgr, d = _make(tmp_path)
    raw = _put(d, "flag: yes\nmode: x\n")

    with pytest.raises(YamlWriteRefused, match="PyYAML читает дамп иначе"):
        mgr.patch_recipe(SLUG, {"flag": True, "mode": "On"}, expected_rev=_sha(raw))

    assert (d / f"{SLUG}.yaml").read_bytes() == raw


def test_patch_yaml_source_unreadable_by_pyyaml_checks_dump_against_ruamel_doc(tmp_path: Path) -> None:
    """Табуляция в flow-списке: PyYAML исходник не читает, ruamel читает и пишет без неё — запись проходит."""
    path = tmp_path / "r.yaml"
    path.write_bytes("k: [a,\t b]\nname: r1\n".encode("utf-8"))

    written = patch_yaml_preserving(path, {"name": "r1"}, {"name": "r2"})

    assert written is True
    assert path.read_bytes() == b"k: [a, b]\nname: r2\n"

    # Сторона отказа: откат на ruamel-документ не отключает сверку — ``mode: "On"`` PyYAML читает как bool.
    refused = tmp_path / "refused.yaml"
    raw = "k: [a,\t b]\nname: r1\nmode: x\n".encode("utf-8")
    refused.write_bytes(raw)

    with pytest.raises(YamlWriteRefused, match="PyYAML читает дамп иначе"):
        patch_yaml_preserving(refused, {"mode": "x"}, {"mode": "On"})

    assert refused.read_bytes() == raw


def test_patch_recipe_mutating_hook_does_not_corrupt_callers_after(tmp_path: Path) -> None:
    """Хук-мутант получает копию ``after``: словарь вызывающего после ``patch_recipe`` прежний."""
    mgr, d = _make(tmp_path, format_hook=MutatingRenameHook())
    raw = _put(d, "new:\n  a: 1\nname: r1\n")
    after = {"old": {"a": 2}, "name": "r1"}

    new_rev = mgr.patch_recipe(SLUG, after, expected_rev=_sha(raw))

    assert after == {"old": {"a": 2}, "name": "r1"}
    expected = b"new:\n  a: 2\nname: r1\n"
    assert (d / f"{SLUG}.yaml").read_bytes() == expected
    assert new_rev == _sha(expected)


def test_empty_file_read_canonical_refuses_patch_recipe_writes(tmp_path: Path) -> None:
    """Пустой файл: для чтения не mapping (``RecipeFormatError``), для записи — пустой mapping (как в 1.1e)."""
    mgr, d = _make(tmp_path)
    raw = _put(d, "")

    with pytest.raises(RecipeFormatError):
        mgr.read_canonical(SLUG)

    new_rev = mgr.patch_recipe(SLUG, {"name": "y"}, expected_rev=_sha(raw))

    assert (d / f"{SLUG}.yaml").read_bytes() == b"name: y\n"
    assert new_rev == _sha(b"name: y\n")


@pytest.mark.parametrize("entry", ["patch_recipe", "save_layout"])
def test_write_unparseable_file_raises_format_error_bytes_intact(tmp_path: Path, entry: str) -> None:
    mgr, d = _make(tmp_path)
    raw = _put(d, "secret_marker: [\n")

    with pytest.raises(RecipeFormatError) as info:
        if entry == "patch_recipe":
            mgr.patch_recipe(SLUG, {"name": "x"}, expected_rev=_sha(raw))
        else:
            mgr.save_layout(SLUG, {"a": [1, 2]}, [], expected_rev=_sha(raw))

    assert "secret_marker" not in str(info.value)
    assert (d / f"{SLUG}.yaml").read_bytes() == raw


def test_patch_recipe_hook_error_on_file_raises_format_error_bytes_intact(tmp_path: Path) -> None:
    mgr, d = _make(tmp_path, format_hook=BoomOnFileHook())
    raw = _put(d, "name: r1\nboom: 1\n")

    with pytest.raises(RecipeFormatError):
        mgr.patch_recipe(SLUG, {"name": "x"}, expected_rev=_sha(raw))

    assert (d / f"{SLUG}.yaml").read_bytes() == raw


@pytest.mark.parametrize(
    ("hook", "text", "after"),
    [
        (RenameOldToNewHook(), "old:\n  a: 1\nname: r1\n", {"new": {"a": 2}, "name": "r1"}),
        (AddVersionHook(), "name: r1\ndescription: old\n", {"name": "r1", "description": "new", "version": 3}),
    ],
    ids=["renamed", "added_only"],
)
def test_patch_recipe_refuses_new_root_key_file_intact(tmp_path: Path, hook: Any, text: str, after: dict) -> None:
    """``N(файл)`` вводит корневой ключ, которого нет в файле -> файл в устаревшей форме: отказ, байты целы."""
    mgr, d = _make(tmp_path, format_hook=hook)
    raw = _put(d, text)

    with pytest.raises(RecipeFormatError, match="устаревшей форме"):
        mgr.patch_recipe(SLUG, after, expected_rev=_sha(raw))

    assert (d / f"{SLUG}.yaml").read_bytes() == raw


def test_patch_recipe_mutating_hook_cannot_bypass_root_refusal(tmp_path: Path) -> None:
    """Хук, меняющий вход на месте, не прячет смену корня: ключи файла сняты до хука, хуку уходит копия."""
    mgr, d = _make(tmp_path, format_hook=MutatingRenameHook())
    raw = _put(d, "old:\n  a: 1\nname: r1\n")

    with pytest.raises(RecipeFormatError, match="устаревшей форме"):
        mgr.patch_recipe(SLUG, {"new": {"a": 2}, "name": "r1"}, expected_rev=_sha(raw))

    assert (d / f"{SLUG}.yaml").read_bytes() == raw


def test_save_layout_refuses_new_root_key_file_intact(tmp_path: Path) -> None:
    """v1-файл с ``topology:``: хук отдаёт ``blueprint:``; раскладка не должна дописать второй корневой ключ."""
    mgr, d = _make(tmp_path, format_hook=TopologyToBlueprintHook())
    raw = _put(d, "name: r1\ntopology:\n  processes:\n    - id: a\n")

    with pytest.raises(RecipeFormatError, match="устаревшей форме"):
        mgr.save_layout(SLUG, {"a": [1, 2]}, [], expected_rev=_sha(raw))

    assert (d / f"{SLUG}.yaml").read_bytes() == raw


def test_patch_recipe_root_key_moved_deeper_not_refused(tmp_path: Path) -> None:
    """Перенос вглубь (legacy ``gui_positions`` -> ``blueprint.metadata``) корневых ключей не вводит: отказа нет."""
    mgr, d = _make(tmp_path, format_hook=MoveGuiPositionsDeeperHook())
    text = "name: r1\ngui_positions:\n  a: [1, 2]\nblueprint:\n  processes:\n    - id: a\n"
    _put(d, text)

    doc, rev = mgr.read_canonical(SLUG)
    assert doc is not None
    assert doc["blueprint"]["metadata"] == {"gui_positions": {"a": [1, 2]}}
    doc["name"] = "new"
    new_rev = mgr.patch_recipe(SLUG, doc, expected_rev=rev)

    # Канон шире файла (``metadata`` только в нём), но равен ``after`` — в файл не пишется (design §2.3).
    expected = text.replace("name: r1", "name: new").encode("utf-8")
    assert (d / f"{SLUG}.yaml").read_bytes() == expected
    assert new_rev == _sha(expected)


# ---------------------------------------------------------------------------------------------------------
# on_insert движка
# ---------------------------------------------------------------------------------------------------------


def test_on_insert_applied_to_inserted_subtree_only() -> None:
    target = {"keep": 1, "outer": {"a": 1}, "procs": [{"id": "p1"}]}
    # ``derived`` шире цели, но равен в before и after: ключ не создаётся (design §2.3), on_insert для него не зовётся.
    before = {"keep": 1, "outer": {"a": 1}, "procs": [{"id": "p1"}], "derived": {"k": 1}}
    after = {
        "keep": 1,
        "outer": {"a": 1, "new": {"y": 7}},
        "procs": [{"id": "p1"}, {"id": "p2", "extra": 0}],
        "derived": {"k": 1},
        "fresh": {"x": 5},
    }
    calls: list[tuple[tuple, Any]] = []

    def on_insert(path: tuple, value: Any) -> Any:
        calls.append((path, copy.deepcopy(value)))
        return {**value, "min": True}

    result = apply_delta(target, before, after, on_insert=on_insert)

    assert len(calls) == 3  # ровно по одному вызову на вставляемое поддерево, детей вставленного он не обходит
    assert dict(calls) == {
        ("outer", "new"): {"y": 7},
        ("procs", 1): {"id": "p2", "extra": 0},
        ("fresh",): {"x": 5},
    }
    assert result == {
        "keep": 1,
        "outer": {"a": 1, "new": {"y": 7, "min": True}},
        "procs": [{"id": "p1"}, {"id": "p2", "extra": 0, "min": True}],
        "fresh": {"x": 5, "min": True},
    }


def test_on_insert_path_is_position_in_after() -> None:
    """Вложенная вставка под сдвинутым элементом: путь — индекс в ``after`` (2), не в ``before`` (1)."""
    target = before = {"items": [{"id": "a"}, {"id": "b"}]}
    after = {"items": [{"id": "new"}, {"id": "a"}, {"id": "b", "extra": {"k": 1}}]}
    calls: list[tuple[tuple, Any]] = []

    def on_insert(path: tuple, value: Any) -> Any:
        calls.append((path, copy.deepcopy(value)))
        return value

    result = apply_delta(target, before, after, on_insert=on_insert)

    assert len(calls) == 2
    assert dict(calls) == {("items", 0): {"id": "new"}, ("items", 2, "extra"): {"k": 1}}
    assert result == after


def test_on_insert_not_applied_to_changed_leaf() -> None:
    target = {"a": {"b": 1, "c": [1, 2], "d": 1}}
    before = copy.deepcopy(target)
    after = {"a": {"b": 2, "c": [1, 3], "d": {"x": 1}}}  # лист, лист в списке, смена типа (замена, не вставка)
    calls: list[tuple[tuple, Any]] = []

    def on_insert(path: tuple, value: Any) -> Any:
        calls.append((path, value))
        return value

    result = apply_delta(target, before, after, on_insert=on_insert)

    assert calls == []
    assert result == {"a": {"b": 2, "c": [1, 3], "d": {"x": 1}}}


# ---------------------------------------------------------------------------------------------------------
# Контракт формат-хука
# ---------------------------------------------------------------------------------------------------------

_VALID_DOCS: list[dict] = [
    {"name": "r1", "tags": ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]},
    {"name": "r2", "blueprint": {"processes": [{"id": "a"}, {"id": "b"}]}},
]
_INVALID_DOCS: list[object] = [[1, 2], "text"]


def _factory(hook_cls: type) -> str:
    return f"{_THIS_MODULE}:{hook_cls.__name__}"


def _run_contract(hook_cls: type, docs: list[dict] = _VALID_DOCS) -> None:
    """Контракт в daemon-потоке с дедлайном: исключение потока пробрасывается в тест."""
    outcome: list[BaseException] = []

    def target() -> None:
        try:
            assert_format_hook_contract(_factory(hook_cls), docs, _INVALID_DOCS)
        except BaseException as exc:  # noqa: BLE001 - передаём любое исключение в основной поток
            outcome.append(exc)

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(_CONTRACT_DEADLINE_S)
    assert not worker.is_alive(), "контракт хука завис"
    if outcome:
        raise outcome[0]


def test_hook_contract_accepts_identity_hook() -> None:
    _run_contract(IdentityHook)


def test_hook_contract_rejects_non_idempotent_hook() -> None:
    with pytest.raises(AssertionError, match="идемпотент"):
        _run_contract(NonIdempotentHook)


@pytest.mark.parametrize(
    "hook_cls", [PartialOnInvalidHook, WrongErrorOnInvalidHook], ids=["returns_partial", "wrong_error"]
)
def test_hook_contract_rejects_partial_result_on_invalid(hook_cls: type) -> None:
    with pytest.raises(AssertionError, match="RecipeFormatError"):
        _run_contract(hook_cls)


def test_hook_contract_rejects_hook_without_empty_delta() -> None:
    """``AddVersionHook`` идемпотентен, тотален и детерминирован, но вводит корневой ключ: запись отказывает."""
    with pytest.raises(AssertionError, match="не пуста"):
        _run_contract(AddVersionHook)


def test_hook_contract_rejects_input_mutating_hook() -> None:
    with pytest.raises(AssertionError, match="мутирует"):
        _run_contract(MutatingRenameHook, [{"old": {"a": 1}, "name": "r1"}])


def test_hook_contract_rejects_hash_seed_dependent_hook() -> None:
    with pytest.raises(AssertionError, match="PYTHONHASHSEED"):
        _run_contract(HashSeedHook)
