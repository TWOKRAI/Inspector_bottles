"""hook_contract.py — общий набор контрактных проверок формат-хука рецепта (Task 1.1f, design.md §10 п. 2).

Purpose:
    Один набор проверок на ВСЕ хуки ``RecipeFormatHook.normalize`` (``N``): синтетические хуки framework и хук
    приложения. Хук, прошедший набор, безопасен для канонической записи (``read_canonical`` -> ``patch_recipe``).

Public API:
    ``assert_format_hook_contract(hook_factory, docs, invalid_docs=())`` — ``AssertionError`` с причиной на первом
    нарушении, ``None`` — хук соответствует. Проверки:
      * вход не мутирует (Post ``RecipeFormatHook.normalize``): хуку отдаётся копия, после вызова она равна оригиналу;
      * идемпотентность: ``N(N(x)) == N(x)`` (равенство движка: ``1 != True != 1.0``);
      * тотальность: валидное тело -> dict; невалидное (``invalid_docs``) -> ``RecipeFormatError``, любой другой
        исход (чужое исключение, возврат значения, в том числе частичного) — нарушение;
      * детерминизм: подпроцессы с ``PYTHONHASHSEED`` 0..3 дают побайтно один результат (порядок ключей и
        списков входит в сравнение);
      * без правок дельта ``N(файл) -> N(файл)`` пуста: файл с телом ``doc`` читается ``read_canonical``, канон
        без изменений уходит в ``patch_recipe`` — запись не происходит (байты, ``rev`` и ``mtime`` те же) и не
        отказывает. Хук, вводящий корневой ключ, которого нет в файле, эту проверку не проходит: ``patch_recipe``
        видит устаревшую форму (design.md §10 п. 1; тела ``docs`` — рецепты текущей формы).
    ``hook_factory`` — строка ``"pkg.module:Attr"``: вызываемое без аргументов, возвращает экземпляр хука. Строка,
    а не объект, потому что хук должен дойти до подпроцессов; модуль доступен от корня репозитория.
    ``docs`` и ``invalid_docs`` — JSON-совместимые значения (идут в подпроцессы JSON-файлом во временном каталоге).

Stability:
    Публичный, ``public-api-change`` Task 1.1f. Набор проверок только растёт; сигнатуру менять нельзя.
    Новая проверка, которую не проходит хук приложения, — правка хука, не ослабление контракта (design.md §10 п. 4).
"""

from __future__ import annotations

import copy
import importlib
import json
import os
import subprocess  # nosec B404 — подпроцессы контракта: sys.executable и фиксированный скрипт
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from .manager import RecipeFormatError, RecipeManager
from .yaml_io import _equal

__all__ = ["assert_format_hook_contract"]

# Корень репозитория (hook_contract.py лежит в multiprocess_framework/modules/recipe): подпроцессам нужен он.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_HASH_SEEDS = (0, 1, 2, 3)
_SUBPROCESS_TIMEOUT_S = 120.0
_RESULT_MARK = "HOOK-CONTRACT-RESULT:"

# Подпроцесс: хук по строке фабрики, все тела (валидные, потом невалидные) -> исходы. Результат — одна строка с меткой:
# хук и его импорты вправе печатать в stdout. Ключи dict и элементы списков остаются в порядке хука.
_CHILD_SCRIPT = f"""
import importlib, json, sys
factory, docs_path = sys.argv[1], sys.argv[2]
module_name, _, attr = factory.partition(":")
hook = getattr(importlib.import_module(module_name), attr)()
with open(docs_path, encoding="utf-8") as fh:
    payload = json.load(fh)
outcomes = []
for doc in payload["docs"] + payload["invalid"]:
    try:
        outcomes.append(["ok", json.dumps(hook.normalize(doc), ensure_ascii=False, default=repr)])
    except Exception as exc:
        outcomes.append(["error", type(exc).__name__])
sys.stdout.write("\\n" + {_RESULT_MARK!r} + json.dumps(outcomes) + "\\n")
"""


def assert_format_hook_contract(
    hook_factory: str,
    docs: Sequence[dict],
    invalid_docs: Sequence[object] = (),
) -> None:
    """Проверить хук на контракте канонической формы (см. docstring модуля).

    Pre: ``hook_factory`` — ``"pkg.module:Attr"``; ``docs`` — валидные тела рецептов, ``invalid_docs`` — тела,
    которые хук обязан отвергнуть; оба JSON-совместимы.
    Post: ``None`` — все проверки прошли; иначе ``AssertionError`` с номером тела и причиной.
    Подпроцессы ограничены по времени (``_SUBPROCESS_TIMEOUT_S``); зависший хук — ``AssertionError``.
    """
    hook = _load_hook(hook_factory)
    for index, doc in enumerate(docs):
        _check_valid_doc(hook, f"docs[{index}]", doc)
    for index, doc in enumerate(invalid_docs):
        _check_invalid_doc(hook, f"invalid_docs[{index}]", doc)
    _check_hash_seed_determinism(hook_factory, list(docs), list(invalid_docs))


def _load_hook(hook_factory: str) -> Any:
    module_name, sep, attr = hook_factory.partition(":")
    if not (sep and module_name and attr):
        raise ValueError(f"hook_factory должен быть строкой 'pkg.module:Attr', получено: {hook_factory!r}")
    return getattr(importlib.import_module(module_name), attr)()


def _normalize(hook: Any, label: str, body: Any, what: str) -> Any:
    """``N(копия тела)``; любое исключение хука на валидном теле — нарушение тотальности."""
    arg = copy.deepcopy(body)
    try:
        result = hook.normalize(arg)
    except Exception as exc:
        raise AssertionError(f"{label}: normalize бросил {type(exc).__name__} на валидном теле ({what})") from exc
    if not _equal(arg, body):  # Post RecipeFormatHook.normalize: вход не мутирует
        raise AssertionError(f"{label}: normalize мутирует вход ({what})")
    return result


def _check_valid_doc(hook: Any, label: str, doc: dict) -> None:
    first = _normalize(hook, label, doc, "тотальность")
    if not isinstance(first, dict):
        raise AssertionError(f"{label}: normalize вернул {type(first).__name__}, ждали dict (тотальность)")
    second = _normalize(hook, label, first, "идемпотентность")
    if not _equal(first, second):
        raise AssertionError(f"{label}: normalize не идемпотентен: N(N(x)) != N(x)")
    _check_empty_delta(hook, label, doc)


def _check_empty_delta(hook: Any, label: str, doc: dict) -> None:
    """Файл с телом ``doc``: ``read_canonical`` -> ``patch_recipe`` без правок — записи нет (``rev``, ``mtime``)."""
    with tempfile.TemporaryDirectory() as tmp:
        recipes_dir = Path(tmp)
        path = recipes_dir / "recipe.yaml"
        path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
        raw = path.read_bytes()
        mtime = path.stat().st_mtime_ns
        # Менеджер берёт у движка только ``recipes_dir``.
        manager = RecipeManager(engine=SimpleNamespace(recipes_dir=recipes_dir), format_hook=hook)
        try:
            canonical, rev = manager.read_canonical("recipe")
            new_rev = manager.patch_recipe("recipe", canonical, expected_rev=rev)
        except Exception as exc:
            raise AssertionError(
                f"{label}: без правок дельта N(файл) -> N(файл) не пуста — запись по канону не прошла: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if new_rev != rev or path.read_bytes() != raw or path.stat().st_mtime_ns != mtime:
            raise AssertionError(f"{label}: без правок дельта N(файл) -> N(файл) не пуста — файл перезаписан")


def _check_invalid_doc(hook: Any, label: str, doc: object) -> None:
    try:
        result = hook.normalize(copy.deepcopy(doc))
    except RecipeFormatError:
        return
    except Exception as exc:
        raise AssertionError(
            f"{label}: normalize бросил {type(exc).__name__} вместо RecipeFormatError (тотальность)"
        ) from exc
    raise AssertionError(
        f"{label}: normalize вернул {type(result).__name__} вместо RecipeFormatError — частичный результат недопустим"
    )


def _check_hash_seed_determinism(hook_factory: str, docs: list[dict], invalid_docs: list[object]) -> None:
    payload = {"docs": docs, "invalid": invalid_docs}
    labels = [f"docs[{i}]" for i in range(len(docs))] + [f"invalid_docs[{i}]" for i in range(len(invalid_docs))]
    results: dict[int, list] = {}
    with tempfile.TemporaryDirectory() as tmp:
        docs_path = Path(tmp) / "docs.json"
        docs_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        procs = {seed: _spawn_child(hook_factory, docs_path, seed) for seed in _HASH_SEEDS}
        deadline = time.monotonic() + _SUBPROCESS_TIMEOUT_S
        try:
            for seed, proc in procs.items():
                try:
                    out, err = proc.communicate(timeout=max(0.1, deadline - time.monotonic()))
                except subprocess.TimeoutExpired as exc:
                    raise AssertionError(
                        f"подпроцесс PYTHONHASHSEED={seed} не уложился в {_SUBPROCESS_TIMEOUT_S:.0f} с — хук завис"
                    ) from exc
                if proc.returncode != 0:
                    raise AssertionError(
                        f"подпроцесс PYTHONHASHSEED={seed} завершился с кодом {proc.returncode}: {err.strip()[-1500:]}"
                    )
                results[seed] = _parse_child_result(seed, out)
        finally:
            for proc in procs.values():
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()
    reference = results[_HASH_SEEDS[0]]
    for seed in _HASH_SEEDS[1:]:
        for label, expected, got in zip(labels, reference, results[seed]):
            if expected != got:
                raise AssertionError(
                    f"{label}: результат normalize зависит от PYTHONHASHSEED "
                    f"(seed {_HASH_SEEDS[0]}: {expected!r}, seed {seed}: {got!r})"
                )


def _spawn_child(hook_factory: str, docs_path: Path, seed: int) -> subprocess.Popen:
    env = {**os.environ, "PYTHONHASHSEED": str(seed), "PYTHONPATH": str(_REPO_ROOT), "PYTHONUTF8": "1"}
    return subprocess.Popen(  # nosec B603 — sys.executable, фиксированный скрипт, shell=False; hook_factory — аргумент, не код
        [sys.executable, "-c", _CHILD_SCRIPT, hook_factory, str(docs_path)],
        cwd=_REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _parse_child_result(seed: int, stdout: str) -> list:
    for line in reversed(stdout.splitlines()):
        if line.startswith(_RESULT_MARK):
            return json.loads(line[len(_RESULT_MARK) :])
    raise AssertionError(f"подпроцесс PYTHONHASHSEED={seed} не вернул результата; stdout: {stdout.strip()[-500:]}")
