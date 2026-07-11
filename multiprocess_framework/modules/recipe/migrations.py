"""migrations.py — реестр step-миграций рецептов (ADR-RCP-003).

Purpose:
    Миграции рецептов подключались к RecipeEngine через прямую инъекцию
    callbacks (migration_fn/migration_check_fn, ADR-SS-003) — рабочий, но
    незарегистрированный механизм: шаги миграции существовали как отдельные
    функции (напр. migrate_recipe_data, migrate_v1_to_v2) без общего каталога
    «какая версия doc_type → какая версия».

    Здесь — декоратор ``@migration(doc_type, from_, to)`` регистрирует шаг в
    реестре и цепочечный раннер ``run_chain(doc_type, data, from_version,
    to_version)`` прогоняет data через цепочку шагов v → v+1 → ... → target,
    in-memory (READ-путь): раннер не читает и не пишет файлы — запись
    результата остаётся заботой вызывающего (как и раньше в
    ``RecipeEngine.load()``).

    Инъекция callbacks (ADR-SS-003) остаётся рабочим механизмом — реестр её
    НЕ заменяет, а становится дефолтным источником шагов: домен регистрирует
    свою миграцию декоратором (см. ``backend/state/recipes/migrations/v1_to_v2.py``,
    ``recipes/migrations/format_v1_to_v2.py``), и эта же функция по-прежнему
    инжектируется как migration_fn — декоратор прозрачен для прямого вызова.

    Namespace (doc_type) в ключе реестра различает одноимённые шаги разных
    доменов: в проекте есть два ``v1_to_v2`` (config-snapshot regions
    processing_blocks→nodes и file-format topology→blueprint) — под разными
    doc_type они не конфликтуют (C2, дубль D6).

Public API:
    - migration — декоратор регистрации шага (doc_type, from_, to).
    - registered_steps — шаги, зарегистрированные под doc_type.
    - run_chain — прогнать data через цепочку шагов from_version → to_version.

Stability: lite
"""

from __future__ import annotations

from typing import Callable

MigrationStep = Callable[[dict], dict]

_REGISTRY: dict[tuple[str, int, int], MigrationStep] = {}


def migration(doc_type: str, from_: int, to: int) -> Callable[[MigrationStep], MigrationStep]:
    """Декоратор: зарегистрировать шаг миграции doc_type версии from_ → to.

    Ключ реестра — (doc_type, from_, to). Два одноимённых шага (напр. оба
    называются v1_to_v2) под РАЗНЫМИ doc_type не конфликтуют — namespace
    различает их.

    Pre:
      - doc_type — непустая строка.
      - from_ < to (шаг только вперёд по версии).
    Post:
      - функция зарегистрирована под (doc_type, from_, to); исходная функция
        возвращается БЕЗ изменений (декоратор прозрачен для прямых вызовов —
        существующая инъекция migration_fn=<декорированная функция> продолжает
        работать бит-в-бит).
      - повторная регистрация того же ключа перезаписывает предыдущий шаг.

    Raises:
        ValueError: doc_type пуст или from_ >= to.
    """
    if not doc_type:
        raise ValueError("migration: doc_type не может быть пустым")
    if from_ >= to:
        raise ValueError(f"migration({doc_type!r}): from_={from_} должен быть < to={to}")

    def _decorator(fn: MigrationStep) -> MigrationStep:
        _REGISTRY[(doc_type, from_, to)] = fn
        return fn

    return _decorator


def registered_steps(doc_type: str) -> dict[tuple[int, int], MigrationStep]:
    """Шаги, зарегистрированные под doc_type: {(from_, to): fn}.

    Pre:
      - doc_type — строка (пустая допустима, просто не найдёт совпадений).
    Post:
      - возвращает новый dict (снимок реестра на момент вызова); пустой,
        если под doc_type ничего не зарегистрировано.
    """
    return {(f, t): fn for (dt, f, t), fn in _REGISTRY.items() if dt == doc_type}


def run_chain(doc_type: str, data: dict, from_version: int, to_version: int) -> dict:
    """Прогнать data через цепочку зарегистрированных шагов from_version → to_version.

    In-memory: не читает и не пишет файлы — только применяет зарегистрированные
    dict-трансформации по возрастанию версии (v → v+1 → ... → to_version).

    Pre:
      - from_version <= to_version.
      - для каждого шага v → v+1 (from_version <= v < to_version) под doc_type
        зарегистрирована функция.
    Post:
      - from_version == to_version → data возвращён БЕЗ изменений, тем же
        объектом (идемпотентность: повторный прогон уже мигрированных данных —
        no-op, детект версии выше по стеку не находит расхождения — вызывать
        не нужно).
      - иначе — результат последнего шага цепочки. Сохранение неизвестных
        (не тронутых ни одним шагом) ключей — ответственность самих шагов;
        раннер их не удаляет и не подменяет.

    Raises:
        ValueError: from_version > to_version.
        RuntimeError: отсутствует зарегистрированный шаг в цепочке.
    """
    if from_version > to_version:
        raise ValueError(f"run_chain({doc_type!r}): from_version={from_version} > to_version={to_version}")

    result = data
    version = from_version
    while version < to_version:
        step = _REGISTRY.get((doc_type, version, version + 1))
        if step is None:
            raise RuntimeError(f"run_chain({doc_type!r}): нет зарегистрированного шага {version} → {version + 1}")
        result = step(result)
        version += 1
    return result


__all__ = ["migration", "registered_steps", "run_chain"]
