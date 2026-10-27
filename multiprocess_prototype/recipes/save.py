# -*- coding: utf-8 -*-
"""save.py — единая сборка v3-raw рецепта из живой топологии на запись (RS-1).

Purpose:
    Оба GUI-пути сохранения рецепта — Pipeline-таб (``LayoutController.save_to_active_recipe``,
    источник = live-модель редактора) и Recipes-таб (``RecipesPresenter.on_save``, источник =
    ``TopologyRepository`` SSOT) — раньше собирали blueprint по-разному:
      - Pipeline-путь звал ``graph_to_blueprint`` с дефолтами ``name="default"``/``description=""``
        и ЗАТИРАЛ авторские ``blueprint.name``/``blueprint.description`` при каждом Save (LP-1);
      - Recipes-путь собирал только ``processes``/``wires``/``displays`` БЕЗ ``metadata`` — т.е.
        стирал позиции узлов (``gui_positions``) и фиксацию (``locked_nodes``).

    Путь записи теперь один — :func:`save_editor_topology_to_recipe`: читает канон файла
    (``read_canonical``), правит в нём только ``blueprint.processes/wires/displays`` адаптером
    ``topology_to_canonical`` и пишет одной ``save_raw`` (ADR-RCP-010, design.md §10); рецепт целиком из
    модели не собирается, ``name``/``description``/раскладка остаются как в файле.

    :func:`build_recipe_v3_raw` (прежний сборщик v3-raw; делегирует нормализацию в
    :func:`normalize_recipe_v3_raw`, C1, ADR-RCP-001) — FREEZE: на пути записи не используется,
    оставлен как публичный контракт и для своих contract-тестов.

    ``validate_recipe_blueprint`` (RS-5, C-4) — gate на запись: домен-валидация ПЕРЕД
    ``store.save_raw``. Домен-валидатор не новый — переиспользует
    ``SystemBlueprint.check_structure()`` (blueprint.py), НЕ пишет второй валидатор.
    Gate стоит внутри :func:`save_editor_topology_to_recipe` (общий для всех Save-путей) и у
    ``TopologyPresenter.load_from_file`` (тот же валидатор на чтении из файла).
    ``build_recipe_v3_raw`` сам НЕ валидирует (его contract-тесты используют синтетические
    wire-фикстуры, не проходящие полную доменную проверку).

Public API (module-contract: lite):
    - build_recipe_v3_raw — собрать v3-raw рецепта на запись из raw + topology-dict.
    - validate_recipe_blueprint — структурная gate-валидация blueprint перед записью.
    - save_editor_topology_to_recipe — единая последовательность read_canonical→adapt→validate→save_raw (RS-4 #5).
    - RecipeValidationError — ошибка невалидного blueprint (дубли имён процессов / циклы).
    - RecipeNotFoundError — рецепт не читается через RecipeStore.

Stability: lite
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from multiprocess_framework.modules.recipe.format import normalize_recipe_v3_raw

__all__ = [
    "build_recipe_v3_raw",
    "validate_recipe_blueprint",
    "save_editor_topology_to_recipe",
    "RecipeValidationError",
    "RecipeNotFoundError",
]


class RecipeNotFoundError(LookupError):
    """Рецепт с данным slug не читается через RecipeStore (нет файла / битый)."""


class RecipeValidationError(ValueError):
    """Blueprint не прошёл структурную валидацию (RS-5, C-4).

    ``errors`` — список сообщений из ``SystemBlueprint.check_structure()``
    (дубли имён процессов, циклы графа wires). Это НЕ полный ``check()``: тот
    дополнительно проверяет совместимость портов и обязательные входы, что
    зависит от состояния PluginRegistry — в разреженном окружении (headless/
    тесты) даёт ложные срабатывания и непригоден как gate на запись (см.
    docs/audits/2026-07-12_recipe-lifecycle-audit.md, класс C-4).
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(errors) or "рецепт не прошёл валидацию")


def build_recipe_v3_raw(
    raw: dict[str, Any],
    topology: dict[str, Any],
    *,
    gui_positions: dict[str, Any] | None = None,
    locked_nodes: list[str] | None = None,
) -> dict[str, Any]:
    """Собрать полный v3-raw рецепта из существующего raw + живой топологии. FREEZE: на пути записи не используется.

    Единый механизм для обоих GUI-путей Save (Pipeline-таб / Recipes-таб). Из плоского
    topology-dict берёт ``processes``/``wires``/``displays``; авторские ``name``/``description``
    и layout-метаданные СОХРАНЯЕТ из существующего рецепта (не затирает). Результат прогоняется
    через :func:`normalize_recipe_v3_raw` (снятие legacy-мусора, top-level ``gui_positions``).

    Args:
        raw: текущий raw-dict рецепта (из ``RecipeStore.read_raw``). Не мутируется.
        topology: плоский dict топологии-источника с ключами ``processes``/``wires``/``displays``
            (напр. ``PipelineModel``-сериализация или ``Topology.to_dict()``). Позиции/фиксация
            могут лежать в ``topology['metadata']``, но приоритет у явных override-параметров.
        gui_positions: override позиций узлов ``{node_id: [x, y]}`` из живой сцены (Pipeline-путь).
            None → позиции берутся из существующего рецепта (Recipes-путь не стирает layout).
        locked_nodes: override списка зафиксированных узлов из живого редактора (Pipeline-путь).
            None → фиксация берётся из существующего рецепта.

    Pre:
      - ``raw`` — dict (копируется, не мутируется).
      - ``topology`` — dict; отсутствующие ключи трактуются как пустые списки.
    Post:
      - результат — новый dict (копия raw) с ``blueprint`` = собранному:
        ``{name?, description?, processes, wires, displays, metadata?}``.
      - ``blueprint.name``/``blueprint.description`` присутствуют ТОЛЬКО если были в исходном
        ``raw['blueprint']`` (не фабрикуется ``"default"``/``""``).
      - ``blueprint.metadata`` присутствует ТОЛЬКО если непустой (сохранённый layout или override).
      - top-level ``gui_positions``/``data``/``meta`` в результат не попадают (см. normalize).

    Returns:
        Новый v3-raw dict, готовый к записи через ``RecipeStore.save_raw``.
    """
    existing_bp = raw.get("blueprint")
    if not isinstance(existing_bp, dict):
        existing_bp = {}
    existing_meta = existing_bp.get("metadata")
    if not isinstance(existing_meta, dict):
        existing_meta = {}

    blueprint: dict[str, Any] = {}

    # Авторские name/description — только из существующего рецепта. Не фабрикуем "default":
    # SystemBlueprint.name/description имеют дефолты в схеме, отсутствие ключа безопасно (LP-1).
    if "name" in existing_bp:
        blueprint["name"] = existing_bp["name"]
    if "description" in existing_bp:
        blueprint["description"] = existing_bp["description"]

    # Структура графа — из topology-источника (SSOT). displays ВНУТРИ blueprint (v3).
    blueprint["processes"] = list(topology.get("processes", []) or [])
    blueprint["wires"] = list(topology.get("wires", []) or [])
    blueprint["displays"] = list(topology.get("displays", []) or [])

    # Layout-метаданные: база — существующие (Recipes-путь не стирает позиции/фиксацию),
    # поверх — явные override из живого редактора (Pipeline-путь).
    metadata: dict[str, Any] = dict(existing_meta)
    if gui_positions is not None:
        metadata["gui_positions"] = gui_positions
    if locked_nodes is not None:
        metadata["locked_nodes"] = locked_nodes
    if metadata:
        blueprint["metadata"] = metadata

    return normalize_recipe_v3_raw(raw, blueprint)


def validate_recipe_blueprint(blueprint_raw: dict[str, Any]) -> None:
    """Gate-валидация blueprint перед записью на диск (RS-5, C-4).

    Прогоняет ``blueprint_raw`` через ``SystemBlueprint.check_structure()`` —
    единственный переиспользуемый домен-валидатор (blueprint.py), НЕ второй
    валидатор: та же логика, что используется и при полной pre-launch проверке
    (``SystemBlueprint.check()``), но без части, зависящей от PluginRegistry.

    Вызывается из :func:`save_editor_topology_to_recipe` (общий для обоих путей Save) на каноне
    ПОСЛЕ ``topology_to_canonical`` и ДО ``store.save_raw`` — при непустых ошибках
    исключение всплывает в уже существующий ``except Exception`` вызывающего
    (``show_error``/``QMessageBox.critical``), запись на диск не происходит.
    Также используется ``TopologyPresenter.load_from_file`` (тот же валидатор
    на чтении "Загрузить из файла" — C-4 требует не обходить его).

    Args:
        blueprint_raw: dict секции ``blueprint`` рецепта (``processes``/``wires``/...).

    Raises:
        RecipeValidationError: если граф содержит дубли имён процессов или циклы.
    """
    from multiprocess_framework.modules.process_manager_module.topology.blueprint import (
        SystemBlueprint,
    )

    blueprint = SystemBlueprint.model_validate(blueprint_raw or {})
    errors = blueprint.check_structure()
    if errors:
        raise RecipeValidationError(errors)


def _validation_messages(exc: ValidationError) -> list[str]:
    """Сообщения pydantic-ошибки без входных значений: ``"<loc через точку>: <msg>"`` (design.md §4.3).

    ``str(exc)`` не годится: он несёт входные значения конфига (пароли, пути). Остаточный путь:
    ``msg`` кастомного валидатора модели может сам вставить значение (``ttl={raw!r}``) — секретов
    в таких валидаторах нет, но гарантия держится на их тексте, не на этой функции.
    """
    return [
        f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}"
        for err in exc.errors(include_input=False, include_url=False)
    ]


def save_editor_topology_to_recipe(
    recipes: Any,
    slug: str,
    topology: dict[str, Any],
    *,
    gui_positions: dict[str, Any] | None = None,
    locked_nodes: list[str] | None = None,
    expected_rev: str | None = None,
) -> str:
    """Единая последовательность записи графа редактора в рецепт: read_canonical → adapt → validate → save_raw.

    Один вызываемый для ВСЕХ Save-путей (RS-4 #5, класс A-3): ``RecipesPresenter.on_save``,
    ``LayoutController.save_to_active_recipe`` (с раскладкой) и closeEvent-сохранение в ``app.py``.

    Политика ADR-RCP-010 (design.md §10): рецепт целиком из модели НЕ собирается. Читается канон файла
    (``read_canonical`` — канон и ``rev`` одного чтения), адаптер :func:`topology_to_canonical` правит
    в нём только ``blueprint.processes/wires/displays``, остальное (в т.ч. ``name``/``description``
    и неизменённые поля) остаётся как в файле. Запись — ОДНА (``save_raw``), минимальной дельтой:
    раскладка (``gui_positions``/``locked_nodes``, если переданы) идёт в ту же запись через ``layout=``
    (design.md §9.5), второго вызова ``save_layout`` нет. :func:`build_recipe_v3_raw` здесь не
    используется (FREEZE).

    Исключения (RecipeNotFoundError/RecipeValidationError/RecipeConflict) НЕ глотает — вызывающий сам
    решает, как показать пользователю и не помечает ли сессию сохранённой.

    Args:
        recipes: RecipeStore (``read_canonical``/``save_raw``).
        slug: целевой рецепт.
        topology: плоский topology-dict (processes/wires/displays).
        gui_positions: позиции узлов (Pipeline-путь); None → раскладка файла не меняется.
        locked_nodes: фиксация узлов (Pipeline-путь); None → раскладка файла не меняется.
        expected_rev: ревизия, на которой строилась правка редактора; None → ревизия этого чтения.

    Returns:
        ``rev`` единственной записи.

    Pre:
      - ``recipes`` — RecipeStore с ``read_canonical`` / ``save_raw(slug, data, *, expected_rev, layout)``.
      - ``topology`` — dict, который разбирает ``Topology`` (``extra="forbid"``).
    Post:
      - записан ровно один раз (одна ``save_raw``), возвращён ``rev`` этой записи; при любом
        исключении запись не выполнена.

    Raises:
        RecipeNotFoundError: рецепт ``slug`` не читается.
        RecipeFormatError: файл рецепта не разбирается (битый YAML / корень не mapping).
        RecipeValidationError: топология или blueprint (в т.ч. не-mapping ``blueprint`` в файле) не
            разбираются / не прошли структурную валидацию.
        RecipeConflict: ``expected_rev`` устарел (файл изменён после чтения).
    """
    # Ленивый импорт: цикла recipes.save <-> adapters.recipe_canonical сегодня нет; импорт в теле
    # функции — в стиле файла и страхует от будущего цикла.
    from multiprocess_prototype.adapters.recipe_canonical import topology_to_canonical

    doc, rev = recipes.read_canonical(slug)
    if doc is None:
        raise RecipeNotFoundError(slug)
    if "blueprint" in doc and not isinstance(doc["blueprint"], dict):
        raise RecipeValidationError(["blueprint: ожидался mapping"])
    try:
        after = topology_to_canonical(topology, doc)
        validate_recipe_blueprint(after.get("blueprint", {}))
    except ValidationError as exc:
        raise RecipeValidationError(_validation_messages(exc)) from None
    layout = None
    if gui_positions is not None or locked_nodes is not None:
        metadata = (after.get("blueprint") or {}).get("metadata") or {}
        layout = (
            gui_positions if gui_positions is not None else dict(metadata.get("gui_positions") or {}),
            locked_nodes if locked_nodes is not None else list(metadata.get("locked_nodes") or []),
        )
    return recipes.save_raw(slug, after, expected_rev=expected_rev if expected_rev is not None else rev, layout=layout)
