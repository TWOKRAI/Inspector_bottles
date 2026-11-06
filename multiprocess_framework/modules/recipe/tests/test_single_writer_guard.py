# -*- coding: utf-8 -*-
"""Страж одного писателя рецепта (Task 1.5, plans/2026-10-26_recipe-save-noise, design.md §8).

Что защищает. Файл рецепта пишет один движок — ``recipe/yaml_io.py`` (дельта
``before -> after`` поверх ruamel-документа, комментарии и EOL целы). Каждый
второй писатель (``yaml.safe_dump`` в обход, ruamel-дамп целиком) возвращает
шум: переписанный файл, потерянные комментарии, CRLF вместо LF. Этот тест
краснеет на новом писателе вне модуля ``recipe`` и вне allowlist'а.

Четыре правила (R1–R4), все по AST, не по грепу: алиасные формы
(``import yaml as y``, ``from yaml import safe_dump as sd``) грепом не видны.

- R1 — импорт писателей движка (``patch_yaml_preserving`` и др.) из
  ``recipe[.yaml_io]`` или шима ``recipes.yaml_io``;
- R2 — любой YAML-дамп (``yaml.dump``/``safe_dump``/``dump_all``, ``.dump(`` в файле с ruamel);
- R3 — путь к рецепту (строка ``recipes/``, ``/ "recipes"``, f-строка ``{slug}.yaml``, ``.recipes_dir``);
- R4 — нормализация целого рецепта (``normalize_recipe_v3_raw`` и др.) вне модуля и адаптера.

Allowlist — «файл → причина» (что именно пишется), как у
``logger_module/tests/test_std_logger_guard.py``. Мёртвая строка allowlist'а —
такой же красный, как новое нарушение. Файлы читаются как текст, не импортируются.

Обход репозитория — ОДИН раз на сессию (``_repo_hits``, кэш): четыре прохода
по дереву стоят около 75 с.
"""

from __future__ import annotations

import ast
import functools
import subprocess
from pathlib import Path
from typing import NamedTuple

import pytest

#: Корень репозитория: .../multiprocess_framework/modules/recipe/tests/файл
REPO_ROOT = Path(__file__).resolve().parents[4]

ENGINE_PATH = "multiprocess_framework/modules/recipe/yaml_io.py"
RECIPE_MODULE_DIR = "multiprocess_framework/modules/recipe"
CANONICAL_ADAPTER = "multiprocess_prototype/adapters/recipe_canonical.py"

#: Модули, из которых писатели движка доступны (сверка «модуль + имя», не по листу имени).
ENGINE_MODULES = frozenset(
    {
        "multiprocess_framework.modules.recipe",
        "multiprocess_framework.modules.recipe.yaml_io",
        "multiprocess_prototype.recipes.yaml_io",
    }
)
WRITERS = frozenset(
    {
        "patch_yaml_preserving",
        "update_yaml_preserving",
        "update_blueprint_metadata_preserving",
        "_dump_atomic",
        "_make_yaml",
    }
)
YAML_DUMPS = frozenset({"dump", "safe_dump", "dump_all", "safe_dump_all"})
R3_SLUG_NAMES = frozenset({"slug", "name"})
R4_CALLS = frozenset({"normalize_recipe_v3_raw", "build_recipe_v3_raw", "canonicalize_gui_positions"})

#: Подстроки-фильтр: файл без них не содержит ни одной формы R1–R4 — AST не строим.
_PREFILTER = ("yaml", "recipe", "canonicalize_gui_positions")

RULES = ("R1", "R2", "R3", "R4")


class Hit(NamedTuple):
    """Одна точка нарушения правила."""

    rule: str
    path: str  # относительный, со слэшами — чтобы совпадал на Windows и POSIX
    lineno: int
    what: str


# ==============================================================================
# Allowlist'ы: «файл → что именно он пишет». Замер c3269e887, сверка со сканом — в отчёте.
# ==============================================================================

#: R1: импорт писателей движка. Разрешён только движку и этим файлам.
ALLOWLIST_R1: dict[str, str] = {
    "multiprocess_framework/modules/recipe/__init__.py": (
        "Публичный экспорт модуля: update_blueprint_metadata_preserving и update_yaml_preserving "
        "остаются в API (принцип 3, публичный путь — контракт, заморожен); сам ничего не пишет."
    ),
    "multiprocess_framework/modules/recipe/manager.py": (
        "RecipeManager — API писателя рецепта: patch_recipe и duplicate пишут файл рецепта "
        "через patch_yaml_preserving / update_yaml_preserving движка."
    ),
    "multiprocess_framework/modules/recipe/service.py": (
        "recipe.save хаба (ADR-RCP-007): нормализованный рецепт с rev пишется дельтой "
        "patch_yaml_preserving, до 1.4 это был safe_dump с потерей комментариев."
    ),
    "multiprocess_framework/modules/recipe/recipe_engine.py": (
        "RecipeEngine.save и перезапись после миграции: снимок config-store пишется дельтой "
        "patch_yaml_preserving только по путям снимка, а не целиком."
    ),
    "multiprocess_prototype/recipes/yaml_io.py": (
        "Шим-реэкспорт движка для кода прототипа: публичный путь импорта "
        "multiprocess_prototype.recipes.yaml_io (FREEZE), сам ничего не пишет."
    ),
    "multiprocess_prototype/recipes/migrations/drop_display_name.py": (
        "Офлайн-миграция каталога рецептов по пути: пишет через тонкий контракт движка "
        "update_yaml_preserving, slug и RecipeEngine в ней нет."
    ),
    "multiprocess_prototype/recipes/migrations/displays_to_recipe.py": (
        "Офлайн-миграция каталога рецептов по пути: переносит displays в рецепт через "
        "update_yaml_preserving, slug и RecipeEngine в ней нет."
    ),
    "multiprocess_prototype/recipes/migrations/canonicalize_gui_positions.py": (
        "Офлайн-миграция каталога рецептов по пути: удаляет дубль gui_positions дельтой "
        "patch_yaml_preserving, EOL файла сохраняется (design.md §2.3)."
    ),
    "Plugins/sim/scene_source/plugin.py": (
        "Пишет пресет слоёв line_sim через update_yaml_preserving (ADR-RCP-008): YAML-пресет сцены, не рецепт."
    ),
}

#: R2: любой YAML-дамп вне движка. Храповик: каждый пишущий YAML файл объявлен с причиной.
ALLOWLIST_R2: dict[str, str] = {
    "Plugins/calibration/camera_robot/store.py": (
        "Атомарно пишет калибровку камера-робот (save_calibration) в её собственный YAML, не рецепт."
    ),
    "Services/auth/storage/yaml_users.py": (
        "Атомарно сохраняет файл пользователей сервиса auth (_atomic_yaml_dump), не рецепт."
    ),
    "Services/device_hub/registry/store.py": (
        "Сохраняет реестр устройств device_hub (tmp + os.replace), не рецепт; вне полосы Д."
    ),
    "Services/layer_render/metadata.py": (
        "Пишет meta.yaml папки слоя render (служебные None-поля опускаются), не рецепт."
    ),
    "Services/layer_render/preset.py": ("Пишет пресет слоя render в YAML (to_yaml, без комментариев), не рецепт."),
    "Services/ml_train/config.py": ("Сохраняет конфиг прогона обучения ml_train для воспроизводимости, не рецепт."),
    "Services/ml_train/export.py": (
        "Пишет sidecar экспортированной модели (data/models/README.md), его читает ModelRegistry, не рецепт."
    ),
    "Services/robot_comm/store.py": ("Сериализует тело записи хранилища robot_comm (_dump) с ревизией, не рецепт."),
    "backend_ctl/dump_capabilities.py": (
        "Дамп capabilities живого бэкенда в детерминированный YAML (render_yaml), не рецепт."
    ),
    "backend_ctl/probes/probe_5_13_orchestrator_layer.py": (
        "Стендовый зонд: временный рецепт прогона _probe_*.yaml с секцией наблюдаемости, не рецепт репозитория."
    ),
    "backend_ctl/probes/probe_basket2_1_live.py": (
        "Стендовый зонд: временный рецепт прогона со всеми формами слоя L2, не рецепт репозитория."
    ),
    "backend_ctl/probes/probe_basket2_live.py": (
        "Стендовый зонд: временный слой рецепта _probe_*.yaml только про каналы, не рецепт репозитория."
    ),
    "backend_ctl/probes/probe_stage2_observability_gate.py": (
        "Стендовый зонд: временный рецепт webcam_sketch с расходящейся парой наблюдаемости для прогона."
    ),
    "multiprocess_framework/modules/app_module/store.py": (
        "Атомарно пишет файл состояния приложения (temp + os.replace) в AppStore, не рецепт."
    ),
    "multiprocess_framework/modules/data_schema_module/container/registers_container.py": (
        "Сериализует регистры в YAML-строку (to_yaml), строка в памяти, файл рецепта не пишется."
    ),
    "multiprocess_framework/modules/data_schema_module/serialization/converter.py": (
        "Конвертирует Pydantic-модель в YAML-строку (model_to_yaml), строка в памяти, не рецепт."
    ),
    "multiprocess_framework/modules/data_schema_module/serialization/io.py": (
        "Экспортирует регистры в YAML-строку (registers_to_yaml), строка в памяти, не рецепт."
    ),
    "multiprocess_framework/modules/display_module/registry.py": (
        "Сохраняет состояние реестра дисплеев (persist) в его YAML-файл, не рецепт."
    ),
    "multiprocess_framework/modules/frontend_module/managers/config_snapshot_manager.py": (
        "Пишет снимок конфигурации GUI (_write_yaml) в каталог снимков, не рецепт."
    ),
    "multiprocess_framework/modules/frontend_module/managers/theme_presets_manager.py": (
        "Пишет кэш пресетов темы (_save) обратно в YAML пресетов, не рецепт."
    ),
    "multiprocess_framework/modules/frontend_module/managers/yaml_persistence_store.py": (
        "Пишет payload хранилища GUI-состояния (_write_raw) в его YAML, не рецепт."
    ),
    "multiprocess_framework/modules/message_module/core/message.py": (
        "Message.to_yaml: сериализация сообщения в YAML-строку в памяти, файл не пишется."
    ),
    "multiprocess_framework/modules/process_module/configs/observability_companion.py": (
        "Пишет файл-спутник наблюдаемости (write_companion) атомарно и идемпотентно, не рецепт."
    ),
    "multiprocess_framework/modules/recipe/hook_contract.py": (
        "Временный recipe.yaml проверки контракта хука в tempdir (_check_empty_delta), не рецепт репозитория."
    ),
    "multiprocess_framework/modules/state_store_module/persistence/persistence_manager.py": (
        "Сохраняет одну секцию дерева state store (_save_file) в её YAML-файл, не рецепт."
    ),
    "multiprocess_prototype/frontend/managers/theme_presets_manager.py": (
        "Пишет custom-тему (save_custom) в YAML пресетов темы GUI, не рецепт."
    ),
    "multiprocess_prototype/frontend/prefs/store.py": (
        "Атомарно пишет пользовательские prefs GUI (.tmp + os.replace), не рецепт."
    ),
    "multiprocess_prototype/frontend/widgets/tabs/pipeline/layout_controller.py": (
        "save_topology_to_file: топология в произвольный файл, FREEZE без живого вызывающего; не формат рецепта v3."
    ),
    "multiprocess_prototype/frontend/widgets/tabs/plugins/presenter.py": (
        "Пишет список путей плагинов в user_overrides.yaml, не рецепт."
    ),
    "multiprocess_prototype/frontend/widgets/tabs/services/neural/dataset_gen_section.py": (
        "Пишет поля формы в пресет генерации датасета ruamel round-trip'ом, не рецепт."
    ),
    "multiprocess_prototype/frontend/widgets/tabs/services/presenter.py": (
        "Пишет список путей сервисов в user_overrides.yaml, не рецепт."
    ),
    "multiprocess_prototype/frontend/widgets/tabs/settings/yaml_io.py": (
        "save_settings: атомарно сохраняет SystemConfig вкладки настроек, не рецепт."
    ),
    "multiprocess_prototype/frontend/widgets/topology/presenter.py": (
        "save_to_file: SystemBlueprint в произвольный файл, FREEZE без живого вызывающего; не формат рецепта v3."
    ),
    "scripts/capacity_bench/recipe.py": (
        "Рендерит рецепт стенда ёмкости (render_recipe) во временный файл прогона, не рецепт репозитория."
    ),
    "scripts/stand_gate/run.py": (
        "Рендерит рецепт стенда 1080p@100 (render) во временный файл прогона, не рецепт репозитория."
    ),
}

#: R3: путь к рецепту. Только composition root и не-рецептные файлы.
ALLOWLIST_R3: dict[str, str] = {
    "multiprocess_prototype/backend/launch.py": (
        "Читает рецепт при запуске бэкенда: путь к файлу рецепта и манифест run.py <recipe>."
    ),
    "multiprocess_prototype/frontend/app.py": ("Composition root GUI: каталог рецептов и указатель манифеста рецепта."),
    "multiprocess_prototype/frontend/app_services_factory.py": (
        "Сборка RecipeManager: единственное место, где задаётся каталог рецептов фабрики сервисов."
    ),
    "multiprocess_prototype/main.py": ("Каталог рецептов при старте приложения: точка входа передаёт его менеджеру."),
    "multiprocess_framework/modules/frontend_module/core/prefs_store.py": (
        "Ключ prefs 'recipes/view_mode' (вид вкладки), а не путь файла рецепта."
    ),
    "multiprocess_prototype/frontend/managers/theme_presets_manager.py": (
        "'<name>.yaml' пресета темы GUI, а не файл рецепта; совпадение только по форме f-строки."
    ),
}

#: R4: нормализация целого рецепта вне модуля и адаптера.
ALLOWLIST_R4: dict[str, str] = {
    "multiprocess_prototype/backend/recipe_format_hook.py": (
        "Хук приложения: единственный нормализатор целого рецепта (design.md §10 п. 1)."
    ),
    "multiprocess_prototype/recipes/save.py": (
        "build_recipe_v3_raw FREEZE: путь без живого вызова записи (design.md §10.1)."
    ),
}

#: Каталоги вне всех правил: путь → причина.
EXEMPT_DIRS: dict[str, str] = {
    "docs": "Архивные стенды и отчёты прошлых прогонов, не код приложения: пишут рецепты своих стендов.",
    "plans": "Одноразовые пробы и стенды планов: читают и пишут рецепты в песочнице, не код приложения.",
}

#: Каталоги вне правила R3 (остальные правила их видят): путь → причина.
EXEMPT_DIRS_R3: dict[str, str] = {
    "backend_ctl/probes": "Стендовые зонды читают рецепты по пути каталога рецептов; R1 и R2 их по-прежнему видят.",
    "scripts": "Утилиты и стенды читают и пишут рецепты по пути; R1 и R2 их по-прежнему видят.",
}

_ALLOWLISTS: dict[str, dict[str, str]] = {
    "R1": ALLOWLIST_R1,
    "R2": ALLOWLIST_R2,
    "R3": ALLOWLIST_R3,
    "R4": ALLOWLIST_R4,
}


# ==============================================================================
# Сканер: scan_source(source, rel) — без ФС
# ==============================================================================


def _dotted(node: ast.AST) -> str | None:
    """``a.b.c`` для цепочки Name/Attribute, иначе None."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    return ".".join(reversed(parts))


def _leaf(func: ast.AST) -> str | None:
    """Лист вызываемого: ``Name.id`` или ``Attribute.attr``."""
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _resolve_from(node: ast.ImportFrom, rel: str) -> str:
    """Полное имя модуля ``from <module> import``; относительный импорт — через ``node.level``."""
    module = node.module or ""
    if not node.level:
        return module
    package = rel.split("/")[:-1]  # каталог файла (для __init__.py он же — пакет)
    base = package[: len(package) - (node.level - 1)]
    return ".".join([*base, *([module] if module else [])])


def _docstring_ids(tree: ast.Module) -> set[int]:
    """id Constant-узлов, которые являются docstring модуля, класса или функции."""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr):
                value = body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    ids.add(id(value))
    return ids


def _import_tables(tree: ast.Module, rel: str) -> tuple[dict[str, str], set[str], set[str], bool]:
    """Таблицы импортов файла.

    Returns:
        ``(modules, yaml_aliases, dump_names, ruamel_file)``:
        ``modules`` — локальное имя -> полное имя модуля/объекта (для R1);
        ``yaml_aliases`` — локальные имена модуля ``yaml``;
        ``dump_names`` — локальные имена дампов, импортированных из ``yaml``;
        ``ruamel_file`` — файл импортирует ``ruamel`` или ``_make_yaml``.
    """
    modules: dict[str, str] = {}
    yaml_aliases: set[str] = set()
    dump_names: set[str] = set()
    ruamel_file = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    modules[alias.asname] = alias.name
                else:
                    first = alias.name.split(".")[0]
                    modules[first] = first
                if alias.name == "yaml":
                    yaml_aliases.add(alias.asname or "yaml")
                if alias.name.split(".")[0] == "ruamel":
                    ruamel_file = True
        elif isinstance(node, ast.ImportFrom):
            module = _resolve_from(node, rel)
            for alias in node.names:
                if alias.name != "*":
                    modules[alias.asname or alias.name] = f"{module}.{alias.name}" if module else alias.name
                if module == "yaml":
                    if alias.name == "*":
                        dump_names.update(YAML_DUMPS)
                    elif alias.name in YAML_DUMPS:
                        dump_names.add(alias.asname or alias.name)
                if module.split(".")[0] == "ruamel" or alias.name == "_make_yaml":
                    ruamel_file = True
    return modules, yaml_aliases, dump_names, ruamel_file


def scan_source(source: str, rel: str) -> list[Hit]:
    """Все нарушения R1–R4 в тексте одного файла. Без обращения к ФС.

    ``rel`` — путь от корня репозитория со слэшами: нужен для разрешения
    относительных импортов (``node.level``) и для структурных исключений
    (движок — не R1/R2; модуль ``recipe`` — не R3/R4; адаптер — не R4).
    Allowlist'ы и ``EXEMPT_*`` здесь НЕ применяются — их применяет обход.
    """
    lowered = source.lower()
    if not any(key in lowered for key in _PREFILTER):
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover — битый файл не наше дело
        return []

    is_engine = rel == ENGINE_PATH
    in_recipe_module = rel.startswith(RECIPE_MODULE_DIR + "/")
    check_r12 = not is_engine
    check_r3 = not in_recipe_module
    check_r4 = not in_recipe_module and rel != CANONICAL_ADAPTER

    modules, yaml_aliases, dump_names, ruamel_file = _import_tables(tree, rel)
    docstrings = _docstring_ids(tree)
    hits: dict[tuple[str, int], Hit] = {}

    def add(rule: str, node: ast.AST, what: str) -> None:
        lineno = getattr(node, "lineno", 0)
        hits.setdefault((rule, lineno), Hit(rule, rel, lineno, what))

    for node in ast.walk(tree):
        # --- R1: импорт писателей движка ---------------------------------------
        if check_r12 and isinstance(node, ast.ImportFrom):
            module = _resolve_from(node, rel)
            if module in ENGINE_MODULES:
                for alias in node.names:
                    if alias.name in WRITERS or alias.name == "*":
                        add("R1", node, f"from {module} import {alias.name}")
        elif check_r12 and isinstance(node, ast.Attribute) and node.attr in WRITERS:
            base = _dotted(node.value)
            if base is not None:
                head, _, tail = base.partition(".")
                resolved = modules.get(head, head) + (f".{tail}" if tail else "")
                if resolved in ENGINE_MODULES:
                    add("R1", node, f"{base}.{node.attr}")

        # --- R2: любой YAML-дамп -----------------------------------------------
        if check_r12 and isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute):
                if func.attr in YAML_DUMPS and isinstance(func.value, ast.Name) and func.value.id in yaml_aliases:
                    add("R2", node, f"{func.value.id}.{func.attr}(...)")
                elif func.attr == "dump" and ruamel_file:
                    add("R2", node, ".dump(...) в файле с ruamel")
            elif isinstance(func, ast.Name) and func.id in dump_names:
                add("R2", node, f"{func.id}(...)")

        # --- R3: путь к рецепту ------------------------------------------------
        if check_r3:
            if isinstance(node, ast.Constant):
                if isinstance(node.value, str) and "recipes/" in node.value and id(node) not in docstrings:
                    add("R3", node, f"строка {node.value!r}")
            elif isinstance(node, ast.BinOp):
                right = node.right
                if isinstance(node.op, ast.Div) and isinstance(right, ast.Constant) and right.value == "recipes":
                    add("R3", node, '... / "recipes"')
            elif isinstance(node, ast.JoinedStr):
                values = node.values
                for current, following in zip(values, values[1:]):
                    if (
                        isinstance(current, ast.FormattedValue)
                        and isinstance(current.value, ast.Name)
                        and current.value.id in R3_SLUG_NAMES
                        and isinstance(following, ast.Constant)
                        and isinstance(following.value, str)
                        and following.value.startswith(".yaml")
                    ):
                        add("R3", node, f'f"{{{current.value.id}}}.yaml"')
            elif isinstance(node, ast.Attribute) and node.attr == "recipes_dir":
                add("R3", node, ".recipes_dir")

        # --- R4: нормализация целого рецепта ----------------------------------
        if check_r4 and isinstance(node, ast.Call):
            leaf = _leaf(node.func)
            if leaf in R4_CALLS:
                add("R4", node, f"{leaf}(...)")
            elif leaf == "from_dict" and isinstance(node.func, ast.Attribute) and _leaf(node.func.value) == "Recipe":
                add("R4", node, "Recipe.from_dict(...)")

    return sorted(hits.values(), key=lambda h: (h.lineno, h.rule))


# ==============================================================================
# Обход репозитория — один раз на сессию
# ==============================================================================


def _is_test_file(rel: str) -> bool:
    parts = rel.split("/")
    name = parts[-1]
    return "tests" in parts[:-1] or name.startswith("test_") or name == "conftest.py"


def _tracked_py_files() -> list[str]:
    """``git ls-files --cached --others --exclude-standard`` — без .venv и кэшей, но с новыми файлами."""
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "*.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(set(result.stdout.splitlines()))


@functools.cache
def _repo_hits() -> tuple[Hit, ...]:
    """Все точки R1–R4 по репозиторию без allowlist'ов; тесты не сканируются. Кэш на сессию."""
    hits: list[Hit] = []
    for rel in _tracked_py_files():
        if _is_test_file(rel) or rel.startswith(".claude/worktrees/"):
            continue
        path = REPO_ROOT / rel
        if not path.is_file():  # удалён, но ещё в индексе
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:  # pragma: no cover — не наш файл
            continue
        hits.extend(scan_source(source, rel))
    return tuple(hits)


def _under(rel: str, directory: str) -> bool:
    return rel == directory or rel.startswith(directory + "/")


def _violations(rule: str) -> list[Hit]:
    """Точки правила вне allowlist'а и вне исключённых каталогов."""
    allow = _ALLOWLISTS[rule]
    result = []
    for hit in _repo_hits():
        if hit.rule != rule or hit.path in allow:
            continue
        if any(_under(hit.path, d) for d in EXEMPT_DIRS):
            continue
        if rule == "R3" and any(_under(hit.path, d) for d in EXEMPT_DIRS_R3):
            continue
        result.append(hit)
    return result


def _report(rule: str, advice: str) -> str:
    return "\n".join(f"  {h.path}:{h.lineno}  {h.what} — {advice}" for h in _violations(rule))


# ==============================================================================
# Охрана на репозитории
# ==============================================================================


def test_no_yaml_dump_outside_allowlist() -> None:
    """R2: YAML пишет движок. Новый дамп — строка ALLOWLIST_R2 с причиной «что пишется»."""
    assert _violations("R2") == [], "YAML-дамп вне движка и allowlist'а:\n" + _report(
        "R2", "писать через движок recipe.yaml_io или внести в ALLOWLIST_R2 с причиной"
    )


def test_no_recipe_writer_import_outside_allowlist() -> None:
    """R1: писатели движка импортируют только allowlist и сам движок."""
    assert _violations("R1") == [], "импорт писателя движка вне allowlist'а:\n" + _report(
        "R1", "писать через RecipeManager.patch_recipe или внести в ALLOWLIST_R1 с причиной"
    )


def test_no_recipe_path_outside_allowlist() -> None:
    """R3: путь к файлу рецепта строит модуль recipe; прочие — allowlist."""
    assert _violations("R3") == [], "путь к рецепту вне модуля recipe и allowlist'а:\n" + _report(
        "R3", "брать путь у RecipeManager или внести в ALLOWLIST_R3 с причиной"
    )


def test_no_whole_recipe_normalization_outside_adapter() -> None:
    """R4: нормализует целый рецепт один хук приложения; прочие — allowlist."""
    assert _violations("R4") == [], "нормализация целого рецепта вне адаптера:\n" + _report(
        "R4", "звать через adapters/recipe_canonical или внести в ALLOWLIST_R4 с причиной"
    )


# ==============================================================================
# Протухание allowlist'ов и причины
# ==============================================================================


def _stale_params() -> list[str]:
    ids = [f"{rule}:{path}" for rule, allow in _ALLOWLISTS.items() for path in allow]
    ids += [f"EXEMPT:{d}" for d in EXEMPT_DIRS]
    ids += [f"EXEMPT_R3:{d}" for d in EXEMPT_DIRS_R3]
    return ids


@pytest.mark.parametrize("entry", _stale_params())
def test_allowlist_entries_not_stale(entry: str) -> None:
    """Строка обязана указывать на живое нарушение своего правила — иначе удалить её."""
    kind, _, target = entry.partition(":")
    hits = _repo_hits()
    if kind in _ALLOWLISTS:
        assert (REPO_ROOT / target).is_file(), f"{entry}: файла нет — удалить строку"
        assert any(h.rule == kind and h.path == target for h in hits), (
            f"{entry}: в {target} больше нет точки {kind} — удалить строку allowlist'а"
        )
        return
    assert (REPO_ROOT / target).is_dir(), f"{entry}: каталога нет — удалить строку"
    rule_filter = {"EXEMPT": RULES, "EXEMPT_R3": ("R3",)}[kind]
    assert any(h.rule in rule_filter and _under(h.path, target) for h in hits), (
        f"{entry}: в {target} нет живой точки {'/'.join(rule_filter)} — снять исключение"
    )


def test_allowlist_reason_states_what_is_written() -> None:
    """Причина — по существу (>= 40 символов) и своя у каждой строки словаря."""
    problems: list[str] = []
    dicts = {**_ALLOWLISTS, "EXEMPT": EXEMPT_DIRS, "EXEMPT_R3": EXEMPT_DIRS_R3}
    for name, allow in dicts.items():
        seen: dict[str, str] = {}
        for path, reason in allow.items():
            if len(reason) < 40:
                problems.append(f"{name}:{path} — причина короче 40 символов: {reason!r}")
            if reason in seen:
                problems.append(f"{name}:{path} — причина дословно совпадает с {seen[reason]}")
            seen[reason] = path
    assert problems == [], "\n".join(problems)


# ==============================================================================
# Самопроверка сканера: каждая форма — пара (rel, source) литералов
# ==============================================================================

_PROTO = "multiprocess_prototype/some/x.py"
_SETTINGS = "multiprocess_prototype/frontend/widgets/tabs/settings/x.py"

#: id -> (rel, source, правило, которое одно и должно сработать).
_DETECT: dict[str, tuple[str, str, str]] = {
    "yaml_dump": (_PROTO, "import yaml\nyaml.dump({}, f)\n", "R2"),
    "safe_dump_alias": (_PROTO, "from yaml import safe_dump as sd\nsd({}, f)\n", "R2"),
    "from_yaml_import": (_PROTO, "from yaml import dump\ndump({}, f)\n", "R2"),
    "module_alias": (_PROTO, "import yaml as y\ny.safe_dump({}, f)\n", "R2"),
    "star_import": (_PROTO, "from yaml import *\nsafe_dump({}, f)", "R2"),
    "dump_all": (_PROTO, "import yaml\nyaml.safe_dump_all([], f)\n", "R2"),
    "relative_import": (
        "multiprocess_framework/modules/recipe/x.py",
        "from .yaml_io import update_yaml_preserving",
        "R1",
    ),
    "ruamel_dump": (_PROTO, "from ruamel.yaml import YAML\ny = YAML()\ny.dump(d, f)\n", "R2"),
    "ruamel_alias": (_PROTO, "from ruamel.yaml import YAML as Y\nY().dump(d, f)\n", "R2"),
    "shim_import": (
        _PROTO,
        "from multiprocess_prototype.recipes.yaml_io import update_yaml_preserving as u\n",
        "R1",
    ),
    "engine_import_alias": (
        _PROTO,
        "import multiprocess_framework.modules.recipe.yaml_io as yio\nyio.patch_yaml_preserving(p, a, b)\n",
        "R1",
    ),
    "r3_literal": (_PROTO, 'PATH = "multiprocess_prototype/recipes/demo.yaml"\n', "R3"),
    "r3_div": (_PROTO, 'PATH = ROOT / "recipes"\n', "R3"),
    "r3_fstring_slug": (_PROTO, 'PATH = base / f"{slug}.yaml"\n', "R3"),
    "r3_recipes_dir_attr": (_PROTO, "PATH = manager.recipes_dir\n", "R3"),
    "r4_build": (_PROTO, "raw = build_recipe_v3_raw(data)\n", "R4"),
    "r4_normalize": (_PROTO, "raw = normalize_recipe_v3_raw(data)\n", "R4"),
    "r4_canonicalize": (_PROTO, "raw = canonicalize_gui_positions(data)\n", "R4"),
    "r4_recipe_from_dict": (_PROTO, "recipe = Recipe.from_dict(data)\n", "R4"),
}

#: id -> (rel, source): форма, которую страж видеть НЕ должен (ложное срабатывание).
_IGNORE: dict[str, tuple[str, str]] = {
    "other_yaml_io_writer_name": (_SETTINGS, "from .yaml_io import update_yaml_preserving"),
    "other_yaml_io_load_settings": (_SETTINGS, "from ..yaml_io import load_settings"),
    "json_dump": (_PROTO, "import json\njson.dump({}, f)\n"),
    "r3_in_docstring": (_PROTO, '"""путь recipes/x.yaml"""\n'),
    "r4_other_from_dict": (_PROTO, "topology = Topology.from_dict(x)\n"),
}


@pytest.mark.parametrize("form", list(_DETECT))
def test_guard_detects_forms(form: str) -> None:
    """Каждая форма даёт ровно своё правило — и никакое другое."""
    rel, source, rule = _DETECT[form]
    assert {h.rule for h in scan_source(source, rel)} == {rule}, f"форма {form} не поймана как {rule}"


@pytest.mark.parametrize("form", list(_IGNORE))
def test_guard_ignores_forms(form: str) -> None:
    """Похожие формы, которые писателем рецепта не являются, не флагуются."""
    rel, source = _IGNORE[form]
    assert scan_source(source, rel) == [], f"форма {form} ложно сработала"
