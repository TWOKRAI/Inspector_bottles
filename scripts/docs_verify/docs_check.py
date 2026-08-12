# -*- coding: utf-8 -*-
"""Сверщик документов наблюдаемости с кодом (задача 5.1 плана ``observability-roadmap``).

Что это
-------
Приёмка F1 (2026-08-10) проверила 129 утверждений справочников **исполнением** и
нашла 6 расхождений с кодом. Проверяющий жил в scratchpad'е координатора и умер
вместе с сессией — то есть свойство «документы не врут» держалось ровно один
день. Этот файл возвращает его в репозиторий: каждое из шести расхождений
становится проверкой, которая **гоняется в дефолтном гейте** и умеет краснеть.

Чего этот сверщик НЕ делает — названо, а не умолчано
-----------------------------------------------------
1. **Это не восстановление всех 129 проверок S1.** Восстановлены шесть
   расхождений и их ближайший класс (перечень — в ``CHECKS`` ниже, каждая
   проверка называет свой источник). Остальные 123 утверждения совпали при
   приёмке и здесь не сторожатся: перенос их всех превратил бы справочник в
   копию кода, а расходятся не они.
2. **Проверяется соответствие названному факту кода, а не полнота документа.**
   Абзац, которого нет вовсе, ни одна проверка не заметит.
3. **Проверка фразы — это проверка фразы.** Там, где утверждение документа
   нельзя выразить структурно (ErrorFloor «звать не должен»), сверщик сторожит
   формулировку, привязанную к факту кода: факт исчезнет — проверка обязана это
   увидеть, поэтому у каждой такой проверки предпосылка вычисляется из кода, а
   не зашита константой.

Правила для самого проверяющего (те же, что у ``observability_seal``)
--------------------------------------------------------------------
* радикально проще проверяемого: чтение файлов, регулярка, разбор сигнатуры
  через ``ast`` — **без импорта фреймворка** (иначе сверщик падал бы вместе с
  тем, что сверяет);
* «не смог проверить» ≠ «проверил, всё хорошо» — это разные коды возврата;
* всё читается через :class:`Sources`, поэтому тест умеет подсунуть подменённый
  текст и показать проверку красной, не трогая рабочее дерево.

Коды возврата
-------------
``0`` — расхождений нет; ``1`` — есть расхождения; ``2`` — проверить не удалось
(файл не читается, сигнатура не разобралась, предпосылка не вычислилась).
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set

REPO_ROOT = Path(__file__).resolve().parents[2]

DOCS = "multiprocess_framework/docs"
OBS = f"{DOCS}/observability"
MODULES = "multiprocess_framework/modules"


class Unverifiable(Exception):
    """Проверить не удалось — это НЕ «проверил, всё хорошо» (код возврата 2)."""


class Sources:
    """Доступ к файлам репозитория с возможностью подмены (для break-injection).

    ``overlay`` — словарь ``{относительный путь: текст}``: путь из него читается
    вместо файла на диске. Так тест показывает проверку красной, не трогая
    рабочее дерево и не копируя репозиторий.
    """

    def __init__(self, root: Path = REPO_ROOT, overlay: Optional[Dict[str, str]] = None) -> None:
        self.root = Path(root)
        self.overlay = dict(overlay or {})

    def read(self, rel: str) -> str:
        if rel in self.overlay:
            return self.overlay[rel]
        path = self.root / rel
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:  # noqa: PERF203 — причина важнее скорости
            raise Unverifiable(f"не читается {rel}: {exc}") from exc

    def exists(self, rel: str) -> bool:
        if rel in self.overlay:
            return True
        return (self.root / rel).exists()

    def with_replacement(self, rel: str, old: str, new: str, count: int = -1) -> "Sources":
        """Копия источников, где в ``rel`` подменён кусок текста (инъекция).

        ``count=-1`` — все вхождения. Отсутствие искомого текста — **ошибка**, а
        не тихий no-op: негодная инъекция обязана дать ERROR, иначе зелёный
        прогон читается как «проверка выдержала слом», которого не было.
        """
        text = self.read(rel)
        if old not in text:
            raise Unverifiable(f"инъекция негодна: в {rel} нет искомого текста {old!r}")
        overlay = dict(self.overlay)
        overlay[rel] = text.replace(old, new, count)
        return Sources(self.root, overlay)


@dataclass(frozen=True)
class Check:
    """Одна проверка: утверждение документа против факта кода."""

    ident: str
    doc: str
    claim: str
    source: str
    run: Callable[[Sources], Optional[str]]

    def __call__(self, src: Sources) -> Optional[str]:
        return self.run(src)


# =============================================================================
# Разбор кода — без импорта фреймворка
# =============================================================================


def _param_names(src: Sources, rel: str, func: str, cls: Optional[str] = None) -> List[str]:
    """Имена аргументов функции ``func`` (без ``self``) по AST файла ``rel``."""
    tree = ast.parse(src.read(rel))
    scopes: List[ast.AST] = [tree]
    if cls is not None:
        scopes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == cls]
        if not scopes:
            raise Unverifiable(f"{rel}: класс {cls} не найден")
    for scope in scopes:
        for node in ast.walk(scope):
            if isinstance(node, ast.FunctionDef) and node.name == func:
                args = [a.arg for a in node.args.args if a.arg != "self"]
                args += [a.arg for a in node.args.kwonlyargs]
                return args
    raise Unverifiable(f"{rel}: функция {func} не найдена")


def _model_fields(src: Sources, rel: str, cls: str) -> Set[str]:
    """Поля Pydantic-схемы ``cls`` — по аннотированным присваиваниям в теле класса."""
    tree = ast.parse(src.read(rel))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            fields = {
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            }
            fields.discard("model_config")
            if not fields:
                raise Unverifiable(f"{rel}: у {cls} не разобрано ни одного поля")
            return fields
    raise Unverifiable(f"{rel}: схема {cls} не найдена")


def _md_table_rows(text: str) -> List[List[str]]:
    """Строки markdown-таблиц файла: список ячеек без ведущих/хвостовых пустых."""
    rows: List[List[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):  # разделитель шапки
            continue
        rows.append(cells)
    return rows


def _backticked(cell: str) -> List[str]:
    return re.findall(r"`([^`]+)`", cell)


def _paragraphs_with(text: str, needle: str) -> List[str]:
    """ВСЕ абзацы, содержащие ``needle``.

    Именно все: первая редакция проверки F1-5 брала первый попавшийся и была
    вакуумной — слово ``emergency_log`` встречается в рецепте трижды, и абзац с
    утверждением про стража был не первым. Инъекция показала это молчанием.
    """
    blocks = [b for b in re.split(r"\n\s*\n", text) if needle in b]
    if not blocks:
        raise Unverifiable(f"в документе нет абзаца со словом {needle!r}")
    return blocks


def _paragraph_with(text: str, needle: str) -> str:
    """Первый абзац, содержащий ``needle`` (когда он в документе заведомо один)."""
    return _paragraphs_with(text, needle)[0]


def _leading_quote_block(text: str) -> str:
    """Шапка-цитата документа: подряд идущие строки ``>`` от начала файла."""
    lines: List[str] = []
    for line in text.splitlines():
        if line.startswith(">"):
            lines.append(line)
        elif lines and line.strip() == "":
            continue
        elif lines:
            break
    if not lines:
        raise Unverifiable("у документа нет шапки-цитаты")
    return "\n".join(lines)


def _fenced_block_with(text: str, needle: str) -> str:
    """Блок ```…``` , содержащий ``needle`` (внутри него пустые строки законны)."""
    for block in re.findall(r"```.*?\n(.*?)```", text, re.S):
        if needle in block:
            return block
    raise Unverifiable(f"в документе нет блока кода со словом {needle!r}")


# =============================================================================
# Проверки. Каждая называет расхождение приёмки F1, из которого родилась.
# =============================================================================


def _check_connector_signatures(src: Sources) -> Optional[str]:
    doc = src.read(f"{OBS}/CONNECTORS.md")
    bad: List[str] = []
    for func in ("_track_error", "_record_metric", "_record_timing"):
        real = _param_names(src, f"{MODULES}/base_manager/mixins/observable_mixin.py", func, cls="ObservableMixin")
        # Ячейка таблицы §1 со ссылкой на метод: берём написание из документа.
        written = re.search(rf"`{func}\(([^`)]*)\)`", doc)
        if written is None:
            bad.append(f"{func}: в CONNECTORS.md нет ни одного написания сигнатуры")
            continue
        spelled = [p.strip().split("=")[0] for p in written.group(1).split(",") if p.strip()]
        # Документ вправе показать хвост короче (…), но НЕ вправе переименовать.
        if spelled != real[: len(spelled)]:
            bad.append(f"{func}: документ пишет {spelled}, код — {real}")
    return "; ".join(bad) or None


def _check_command_params(src: Sources) -> Optional[str]:
    """Параметры команд наблюдаемости в CONTROL_PANEL.md ↔ поля их Pydantic-схем."""
    contracts = f"{MODULES}/process_module/commands/command_contracts.py"
    judged = {
        "observability.tail.subscribe": "ObservabilityTailSubscribeParams",
        "observability.tail.unsubscribe": "ObservabilityTailUnsubscribeParams",
        "health.report": "HealthReportParams",
    }
    doc = src.read(f"{OBS}/CONTROL_PANEL.md")
    rows = {}
    for cells in _md_table_rows(doc):
        if len(cells) < 2:
            continue
        names = _backticked(cells[0])
        if len(names) == 1 and names[0] in judged:
            rows[names[0]] = cells[1]
    bad: List[str] = []
    for command, schema in judged.items():
        if command not in rows:
            bad.append(f"{command}: строки в таблице команд нет (или в её первой ячейке не одно имя)")
            continue
        declared = {n for n in _backticked(rows[command]) if re.fullmatch(r"[a-z_]+", n)}
        fields = _model_fields(src, contracts, schema)
        extra = declared - fields
        missing = fields - declared
        if extra or missing:
            bad.append(
                f"{command}: документ объявляет {sorted(declared)}, схема {schema} — {sorted(fields)}"
                + (f"; лишние: {sorted(extra)}" if extra else "")
                + (f"; не названы: {sorted(missing)}" if missing else "")
            )
    return "; ".join(bad) or None


def _check_error_floor_wording(src: Sources) -> Optional[str]:
    """«Позвать не может» — неверно: класс публичен, стража нет (Н-18)."""
    floor = src.read(f"{MODULES}/logger_module/core/error_floor.py")
    if not re.search(r"^class ErrorFloor\b", floor, re.M):
        raise Unverifiable("error_floor.py: класс ErrorFloor не найден — предпосылка не вычислилась")
    # Предпосылка: имя публичное (без подчёркивания) → импорт прикладным кодом возможен.
    bad: List[str] = []
    for rel in (f"{OBS}/CONNECTORS.md", f"{DOCS}/OBSERVABILITY_MAP.md"):
        text = src.read(rel)
        for line in text.splitlines():
            if "ErrorFloor" not in line:
                continue
            if re.search(r"позвать не может|нельзя позвать|невозможно позвать", line):
                bad.append(f"{rel}: «{line.strip()[:80]}…» — вызов воспроизведён приёмкой F1")
    return "; ".join(bad) or None


_IMPORTANCE = ("warnings_file", "errors_file", "critical_file")


def _check_severity_ladder(src: Sources) -> Optional[str]:
    """Таблица лестницы отказа в SINKS_MAP.md ↔ DEFAULT_SEVERITY_ROUTES (Н-18)."""
    cfg = src.read(f"{MODULES}/error_module/configs/error_manager_config.py")
    tree = ast.parse(cfg)
    routes: Dict[str, List[str]] = {}
    for node in ast.walk(tree):
        named = (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "DEFAULT_SEVERITY_ROUTES" for t in node.targets)
        ) or (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "DEFAULT_SEVERITY_ROUTES"
        )
        if named and node.value is not None:
            value = ast.literal_eval(node.value)
            routes = {str(k): [str(x) for x in v] for k, v in value.items()}
    if not routes:
        raise Unverifiable("DEFAULT_SEVERITY_ROUTES не разобрался")

    doc = src.read(f"{OBS}/SINKS_MAP.md")
    bad: List[str] = []
    for cells in _md_table_rows(doc):
        if len(cells) != 2:
            continue
        level = "".join(_backticked(cells[0]))
        if level not in routes:
            continue
        written = _backticked(cells[1])
        if written != routes[level]:
            bad.append(f"{level}: документ {written}, код {routes[level]}")

    # Утверждение «запасной всегда вверх» ложно, если хоть одна лестница идёт вниз.
    goes_down = any(
        _IMPORTANCE.index(chain[i + 1]) < _IMPORTANCE.index(chain[i])
        for chain in routes.values()
        for i in range(len(chain) - 1)
        if chain[i] in _IMPORTANCE and chain[i + 1] in _IMPORTANCE
    )
    if (
        goes_down
        and re.search(r"никогда к менее важному", doc)
        and "нельзя" not in _paragraph_with(doc, "никогда к менее важному")
    ):
        bad.append("SINKS_MAP.md утверждает «никогда к менее важному», а CRITICAL → errors_file идёт вниз")
    return "; ".join(bad) or None


def _check_emergency_log_guard(src: Sources) -> Optional[str]:
    """Рецепт учил, что вызовы emergency_log считает AST-страж. Не считает (F1 №5)."""
    guard = src.read(f"{MODULES}/logger_module/tests/test_std_logger_guard.py")
    if "getLogger" not in guard:
        raise Unverifiable("страж не похож на себя: в test_std_logger_guard.py нет getLogger")
    if "emergency_log" in guard:
        return None  # страж научился считать — тогда утверждение рецепта верно
    for block in _paragraphs_with(src.read(f"{OBS}/NEW_MODULE_RECIPE.md"), "emergency_log"):
        if "страж" in block and "соглашение" not in block and "не считает" not in block:
            return (
                "NEW_MODULE_RECIPE.md связывает emergency_log со стражем, не называя это соглашением; "
                "страж считает stdlib-писателей и loguru, вызовы emergency_log — никто"
            )
    return None


def _check_communication_map_is_marked_stale(src: Sources) -> Optional[str]:
    """BatchBuffer снят (ADR-LOG-008) — снимок, где он живой, обязан быть помечен (Н-17)."""
    if src.exists(f"{MODULES}/channel_routing_module/buffers/batch_buffer.py"):
        return None  # механизм вернулся — снимок снова актуален
    doc = src.read(f"{DOCS}/COMMUNICATION_MAP.md")
    if "BatchBuffer" not in doc:
        return None
    if not re.search(r"СНИМОК|устарел", _leading_quote_block(doc), re.I):
        return "COMMUNICATION_MAP.md описывает снятый BatchBuffer и не помечен устаревшим в шапке"
    return None


def _check_raw_json_pointer(src: Sources) -> Optional[str]:
    """Ссылка на `COMMUNICATION_MAP_raw.json` обязана называть, что файла нет в репозитории.

    Отдельная проверка, а не второй ассерт предыдущей: два утверждения под одним
    идентификатором прячут, какое из них держит свойство (шрам «два
    предохранителя»). Здесь их два — пометка снимка и судьба указателя.
    """
    rel_json = f"{DOCS}/COMMUNICATION_MAP_raw.json"
    doc = src.read(f"{DOCS}/COMMUNICATION_MAP.md")
    if "COMMUNICATION_MAP_raw.json" not in doc:
        return None
    ignored = ".gitignore" in _leading_quote_block(doc)
    if src.exists(rel_json) and ignored:
        return None
    if not ignored:
        return "COMMUNICATION_MAP.md ссылается на raw.json, не называя, что файла нет в репозитории"
    return None


def _check_module_count(src: Sources) -> Optional[str]:
    """«Навигатор по N модулям» в docs/README.md ↔ число каталогов modules/ (Н-17)."""
    root = src.root / MODULES
    if not root.is_dir():
        raise Unverifiable(f"нет каталога {MODULES}")
    real = sum(
        1
        for p in root.iterdir()
        if p.is_dir() and not p.name.startswith(("_", ".")) and p.name not in {"tests", "logs"}
    )
    doc = src.read(f"{DOCS}/README.md")
    written = re.search(r"Навигатор по (\d+) модул", doc)
    if written is None:
        return "docs/README.md: строки «Навигатор по N модулям» нет"
    if int(written.group(1)) != real:
        return f"docs/README.md называет {written.group(1)} модулей, в modules/ их {real}"
    return None


def _check_readme_has_observability_entry(src: Sources) -> Optional[str]:
    """Вход в наблюдаемость из «порядка чтения для нового агента» (Н-17)."""
    doc = src.read(f"{DOCS}/README.md")
    if "observability/" not in doc or "OBSERVABILITY_MAP.md" not in doc:
        return "docs/README.md не называет наблюдаемость — новый агент до неё не доходит"
    return None


def _check_collector_field_name(src: Sources) -> Optional[str]:
    """Поле ProcessConfig зовётся collector; inspector — легаси-алиас на чтении (Н-17)."""
    bp = src.read(f"{MODULES}/process_manager_module/topology/blueprint.py")
    tree = ast.parse(bp)
    fields: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "ProcessConfig":
            fields = {s.target.id for s in node.body if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)}
    if not fields:
        raise Unverifiable("ProcessConfig: поля не разобрались")
    if "inspector" in fields:
        return None  # поле вернулось — документы вправе его называть
    bad: List[str] = []
    for rel in (f"{DOCS}/MODULE_CONTRACTS.md", f"{DOCS}/MODULES_OVERVIEW.md"):
        for num, line in enumerate(src.read(rel).splitlines(), 1):
            if "`inspector`" not in line:
                continue
            if not re.search(r"легаси|алиас|снят", line):
                bad.append(f"{rel}:{num} называет поле `inspector`, в схеме его нет (канон — `collector`)")
    return "; ".join(bad) or None


@lru_cache(maxsize=8)
def _defines_class(root: str, name: str) -> bool:
    """Есть ли в ``modules/`` объявление класса ``name`` (кэш: обход дерева не бесплатен)."""
    needle = f"class {name}"
    return any(needle in p.read_text(encoding="utf-8", errors="ignore") for p in (Path(root) / MODULES).rglob("*.py"))


def _check_inspector_manager_is_gone(src: Sources) -> Optional[str]:
    """`InspectorManager` не существует в коде — документы не вправе вести через него цепочку."""
    if _defines_class(str(src.root), "InspectorManager"):
        return None
    bad: List[str] = []
    for num, line in enumerate(src.read(f"{DOCS}/COMMUNICATION_MAP.md").splitlines(), 1):
        if "InspectorManager" in line and "не существует" not in line:
            bad.append(f"COMMUNICATION_MAP.md:{num} ведёт цепочку через несуществующий InspectorManager")
    return "; ".join(bad) or None


def _check_stats_slot_docstrings(src: Sources) -> Optional[str]:
    """Докстринги-примеры не вправе учить слоту, которого не адресует _record_metric (Н-6-сосед)."""
    mixin = src.read(f"{MODULES}/base_manager/mixins/observable_mixin.py")
    slot = re.search(r'_call_manager\(\s*"(\w+)"\s*,\s*"record_metric"', mixin)
    if slot is None:
        raise Unverifiable("не найден слот, который адресует _record_metric")
    canonical = slot.group(1)
    bad: List[str] = []
    for rel in (
        f"{MODULES}/command_module/core/command_manager.py",
        f"{MODULES}/dispatch_module/core/dispatcher.py",
    ):
        for num, line in enumerate(src.read(rel).splitlines(), 1):
            if not line.strip().startswith("managers={"):
                continue
            names = re.findall(r"'(\w+)'\s*:", line)
            if "statistics" in names or canonical not in names:
                bad.append(f"{rel}:{num} учит {names}, метрики адресуют слот '{canonical}'")
    return "; ".join(bad) or None


def _check_source_name_seam(src: Sources) -> Optional[str]:
    """Рецепт обязан соединить объявленное имя со штампом записи (Н-19, линза S2)."""
    params = _param_names(src, f"{MODULES}/base_manager/mixins/observable_mixin.py", "__init__", cls="ObservableMixin")
    if "source_name" not in params:
        raise Unverifiable("у ObservableMixin.__init__ больше нет аргумента source_name — предпосылка ушла")
    recipe = src.read(f"{OBS}/NEW_MODULE_RECIPE.md")
    if "source_name" not in recipe:
        return "NEW_MODULE_RECIPE.md не упоминает source_name — записи поедут под именем менеджера"
    if not re.search(r"source_name\s*=\s*LOG_SOURCE", recipe):
        return "NEW_MODULE_RECIPE.md называет source_name, но не показывает связку source_name=LOG_SOURCE"
    return None


def _check_recipe_lifecycle_is_named(src: Sources) -> Optional[str]:
    """initialize/shutdown — abstractmethod: без них наследник не инстанцируется (линза S2)."""
    base = src.read(f"{MODULES}/base_manager/core/base_manager.py")
    tree = ast.parse(base)
    abstract: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "BaseManager":
            for stmt in node.body:
                if isinstance(stmt, ast.FunctionDef) and any(
                    isinstance(d, ast.Name) and d.id == "abstractmethod" for d in stmt.decorator_list
                ):
                    abstract.add(stmt.name)
    if not {"initialize", "shutdown"} <= abstract:
        return None  # перестали быть обязательными — рецепт вправе о них молчать
    recipe = src.read(f"{OBS}/NEW_MODULE_RECIPE.md")
    block = _fenced_block_with(recipe, "class MyManager")
    missing = [name for name in ("initialize", "shutdown") if name not in block]
    if missing:
        return (
            f"NEW_MODULE_RECIPE.md: в образце шага 1 нет {missing}, а они abstractmethod (TypeError на инстанцировании)"
        )
    return None


CHECKS: Sequence[Check] = (
    Check(
        "F1-1",
        "observability/CONNECTORS.md",
        "имена аргументов _track_error/_record_metric/_record_timing — как в коде",
        "расхождение №1 приёмки F1",
        _check_connector_signatures,
    ),
    Check(
        "F1-2",
        "observability/CONTROL_PANEL.md",
        "параметры команд наблюдаемости = поля их Pydantic-схем",
        "расхождение №2 приёмки F1 (unsubscribe без level)",
        _check_command_params,
    ),
    Check(
        "F1-3",
        "observability/CONNECTORS.md + OBSERVABILITY_MAP.md",
        "ErrorFloor: «звать не должен», а не «позвать не может»",
        "Н-18",
        _check_error_floor_wording,
    ),
    Check(
        "F1-4",
        "observability/SINKS_MAP.md",
        "лестница отказа = DEFAULT_SEVERITY_ROUTES; «всегда вверх» не утверждается",
        "Н-18",
        _check_severity_ladder,
    ),
    Check(
        "F1-5",
        "observability/NEW_MODULE_RECIPE.md",
        "AST-страж считает stdlib-писателей, а не вызовы emergency_log",
        "расхождение №5 приёмки F1",
        _check_emergency_log_guard,
    ),
    Check(
        "F1-6",
        "COMMUNICATION_MAP.md",
        "снимок 2026-05-31 помечен устаревшим в шапке",
        "Н-17 (BatchBuffer живым 9 раз)",
        _check_communication_map_is_marked_stale,
    ),
    Check(
        "F1-6b",
        "COMMUNICATION_MAP.md",
        "указатель на raw.json назван внерепозиторным",
        "Н-17",
        _check_raw_json_pointer,
    ),
    Check(
        "H17-a",
        "docs/README.md",
        "число модулей = число каталогов modules/",
        "Н-17",
        _check_module_count,
    ),
    Check(
        "H17-b",
        "docs/README.md",
        "вход в наблюдаемость есть в порядке чтения",
        "Н-17",
        _check_readme_has_observability_entry,
    ),
    Check(
        "H17-c",
        "MODULE_CONTRACTS.md + MODULES_OVERVIEW.md",
        "typed-поле зовётся collector; inspector — только с пометкой «легаси»",
        "Н-17",
        _check_collector_field_name,
    ),
    Check(
        "H17-d",
        "COMMUNICATION_MAP.md",
        "цепочка не ведёт через несуществующий InspectorManager",
        "Н-17",
        _check_inspector_manager_is_gone,
    ),
    Check(
        "H6",
        "command_manager.py + dispatcher.py",
        "докстринг-пример называет слот, который адресует _record_metric",
        "Н-6-сосед",
        _check_stats_slot_docstrings,
    ),
    Check(
        "H19-a",
        "observability/NEW_MODULE_RECIPE.md",
        "шов source_name=LOG_SOURCE назван",
        "Н-19 (линза S2)",
        _check_source_name_seam,
    ),
    Check(
        "H19-b",
        "observability/NEW_MODULE_RECIPE.md",
        "образец шага 1 несёт initialize/shutdown",
        "линза S2",
        _check_recipe_lifecycle_is_named,
    ),
)


@dataclass
class Report:
    divergences: List[str]
    unverifiable: List[str]
    checked: int

    @property
    def exit_code(self) -> int:
        if self.unverifiable:
            return 2
        return 1 if self.divergences else 0


def run_all(src: Optional[Sources] = None, checks: Sequence[Check] = CHECKS) -> Report:
    src = src or Sources()
    divergences: List[str] = []
    unverifiable: List[str] = []
    for check in checks:
        try:
            result = check(src)
        except Unverifiable as exc:
            unverifiable.append(f"[{check.ident}] {exc}")
            continue
        if result:
            divergences.append(f"[{check.ident}] {check.doc}: {result}")
    return Report(divergences, unverifiable, len(checks))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Сверщик документов наблюдаемости с кодом")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="корень репозитория")
    parser.add_argument("--list", action="store_true", help="перечислить проверки и выйти")
    args = parser.parse_args(argv)

    if args.list:
        for check in CHECKS:
            print(f"{check.ident:7} {check.doc:45} {check.claim}  ({check.source})")
        return 0

    report = run_all(Sources(args.root))
    for line in report.unverifiable:
        print(f"НЕ ПРОВЕРЕНО: {line}", file=sys.stderr)
    for line in report.divergences:
        print(f"РАСХОЖДЕНИЕ: {line}", file=sys.stderr)
    print(
        f"проверок: {report.checked}; расхождений: {len(report.divergences)}; не проверено: {len(report.unverifiable)}"
    )
    return report.exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
