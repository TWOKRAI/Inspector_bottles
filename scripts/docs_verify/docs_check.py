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
BACKEND_CTL = "backend_ctl"


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


def _tuple_constant(src: Sources, rel: str, name: str) -> List[str]:
    """Значения кортежа-константы ``name`` из файла ``rel`` — по AST, без импорта.

    Тем же приёмом, что разбор ``DEFAULT_SEVERITY_ROUTES``: сверщик не имеет
    права импортировать фреймворк — оракул, падающий вместе с проверяемым,
    ничего не доказывает.
    """
    tree = ast.parse(src.read(rel))
    for node in ast.walk(tree):
        named = (
            isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)
        ) or (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name)
        if named and node.value is not None:
            try:
                value = ast.literal_eval(node.value)
            except ValueError as exc:  # значение не литерал — предпосылка не вычислилась
                raise Unverifiable(f"{rel}: {name} не разбирается литералом: {exc}") from exc
            return [str(item) for item in value]
    raise Unverifiable(f"{rel}: константа {name} не найдена")


def _section(text: str, title_fragment: str) -> str:
    """Текст раздела от заголовка, содержащего ``title_fragment``, до следующего заголовка.

    «Следующий» — того же или более высокого уровня: подразделы остаются внутри.

    Строки внутри ```-блоков кода заголовками не считаются, даже если начинаются
    с ``#`` (шапка bash-комментария в примере команды) — без этого секция
    обрывалась на первом же таком комментарии. Найдено добором Н-4 (ревью Ф2,
    2026-09-01): секция «Flight recorder» в CONTROL_PANEL.md резалась до 87
    символов строкой ``# что происходило в процессе...`` внутри ```bash``` —
    первого же примера команды под заголовком.
    """
    lines = text.splitlines()

    def _is_fence(line: str) -> bool:
        return line.lstrip().startswith("```")

    start = None
    level = 0
    in_fence = False
    for index, line in enumerate(lines):
        if _is_fence(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("#") and title_fragment in line:
            start = index
            level = len(line) - len(line.lstrip("#"))
            break
    if start is None:
        raise Unverifiable(f"в документе нет заголовка со словами {title_fragment!r}")
    in_fence = False
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if _is_fence(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("#") and (len(line) - len(line.lstrip("#"))) <= level:
            return "\n".join(lines[start:index])
    return "\n".join(lines[start:])


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
        # Ф1.1 (C3): команды впрыска в процессные хуки. Судятся тем же
        # правилом, что соседи, — иначе новая поверхность приехала бы без
        # сверщика ровно в тот документ, ради которого он заведён.
        "diag.thread_raise": "DiagThreadRaiseParams",
        "diag.warn": "DiagWarnParams",
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


#: Секции ``observability.*``, для которых CONTROL_PANEL.md обязан назвать
#: КАЖДОЕ поле Pydantic-схемы (замыкатель класса Н-4, добор ревью Ф2,
#: 2026-09-01). Ключ — фрагмент заголовка секции в документе, значение — имя
#: схемы в ``observability_config.py``.
#:
#: Список полей ВЫЧИСЛЯЕТСЯ из схемы через ``_model_fields`` (AST, без
#: импорта фреймворка) — новое поле схемы (как ``max_tracked_keys``/
#: ``stale_windows`` у Task 2.7) попадёт под проверку САМО, без правки этого
#: файла. Честная граница (~80%, не 100%, названо явно): СПИСОК СЕКЦИЙ (какая
#: секция в каком заголовке документа рассказана) остаётся объявленным
#: руками — вывести его из кода значило бы знать заранее, в каком месте
#: прозы документа человек решит рассказать о новой секции, а это решение не
#: в коде. Числительные словом («шесть копий», «две ручки» — Н-3, Н-4) эта
#: проверка тоже не видит: для них своя дисциплина «число не пишется
#: словом», другой класс сторожей (см. ``test_f2_task27_manual_window_
#: registry_matches_claims.py`` в дереве тестов).
_OBSERVABILITY_SECTION_SCHEMAS: Dict[str, str] = {
    "Окна голоса": "ObservabilityVoicesConfig",
    "Flight recorder": "ObservabilityFlightConfig",
}


def _check_observability_section_fields(src: Sources) -> Optional[str]:
    """CONTROL_PANEL.md называет КАЖДОЕ поле схемы для секций ``observability.*``.

    Находка Н-4 (добор ревью Ф2, 2026-09-01): секции ``observability.voices``
    не было в документе вовсе — четыре ручки существовали в схеме
    (``ObservabilityVoicesConfig``, Task 2.7) и ни одна не была названа
    оператору. Эта проверка — не заплатка под одно расхождение, а вычисляемая
    проверка КЛАССА: добавь новое поле в схему секции из
    ``_OBSERVABILITY_SECTION_SCHEMAS`` — проверка покраснеет сама, без правки
    этого файла (см. ``_model_fields``).
    """
    config_file = f"{MODULES}/process_module/configs/observability_config.py"
    doc = src.read(f"{OBS}/CONTROL_PANEL.md")

    bad: List[str] = []
    for heading_fragment, schema in _OBSERVABILITY_SECTION_SCHEMAS.items():
        fields = _model_fields(src, config_file, schema)
        try:
            section_text = _section(doc, heading_fragment)
        except Unverifiable:
            bad.append(
                f"{schema}: в CONTROL_PANEL.md нет заголовка со словами {heading_fragment!r} — "
                "секция не документирована вовсе"
            )
            continue
        named: Set[str] = set()
        for cells in _md_table_rows(section_text):
            if cells:
                named.update(_backticked(cells[0]))
        missing = fields - named
        if missing:
            bad.append(f"{schema}: секция {heading_fragment!r} не называет поля схемы в таблице: {sorted(missing)}")
    return "; ".join(bad) or None


#: Реестр имён счётчиков процессных хуков — там, где он определён.
_PROCESS_HOOKS = f"{MODULES}/logger_module/core/process_hooks.py"


def _check_hook_counter_names(src: Sources) -> Optional[str]:
    """Имена счётчиков в разделе «Что ловится автоматически» ↔ ``HOOK_COUNTER_KEYS``.

    Ф1.1 (C3). Три имени живут в четырёх местах (константа, объявление в
    ``ErrorManager``, реестр публикации, документ), и три из четырёх связаны
    импортом — а документ связать импортом нельзя. Отсюда эта проверка: без неё
    именно документ и разошёлся бы, причём молча, потому что счётчик,
    переименованный в коде, продолжает существовать под старым именем на бумаге.

    Сверяется МНОЖЕСТВО имён в первых ячейках таблиц раздела: и лишнее (счётчика
    нет, а документ обещает), и недостающее (счётчик есть, документ молчит).
    """
    keys = set(_tuple_constant(src, _PROCESS_HOOKS, "HOOK_COUNTER_KEYS"))
    if not keys:
        raise Unverifiable("HOOK_COUNTER_KEYS пуст — предпосылка не вычислилась")
    section = _section(src.read(f"{OBS}/CONNECTORS.md"), "Что ловится автоматически")
    named = {
        name
        for cells in _md_table_rows(section)
        if cells
        for name in _backticked(cells[0])
        if re.fullmatch(r"[a-z_]+", name)
    }
    if named == keys:
        return None
    return (
        f"документ называет счётчики {sorted(named)}, HOOK_COUNTER_KEYS — {sorted(keys)}"
        + (f"; лишние: {sorted(named - keys)}" if named - keys else "")
        + (f"; не названы: {sorted(keys - named)}" if keys - named else "")
    )


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
    # Таблица лестницы: строка, у которой во второй ячейке цепочка приёмников.
    # Собираем её ЦЕЛИКОМ, а не сверяем построчно: прежняя редакция шла по строкам
    # документа и пропускала уровень со `if level not in routes: continue` — то есть
    # была слепа к правке КОДА. Снятая из DEFAULT_SEVERITY_ROUTES ступень не давала
    # ни одного расхождения, документ продолжал обещать её, а гейт молчал
    # (находка Н-B приёмки F2, воспроизведена переименованием ключа "WARNING").
    doc_routes: Dict[str, List[str]] = {}
    for cells in _md_table_rows(doc):
        if len(cells) != 2:
            continue
        level = "".join(_backticked(cells[0]))
        chain = _backticked(cells[1])
        if not level.isupper() or not chain or not all(name.endswith("_file") for name in chain):
            continue
        doc_routes[level] = chain
    if not doc_routes:
        raise Unverifiable("SINKS_MAP.md: таблица лестницы отказа не разобралась")

    bad: List[str] = []
    only_in_code = sorted(set(routes) - set(doc_routes))
    only_in_doc = sorted(set(doc_routes) - set(routes))
    if only_in_code:
        bad.append(f"уровни есть в коде, но не в документе: {only_in_code}")
    if only_in_doc:
        bad.append(f"документ обещает уровни, которых нет в DEFAULT_SEVERITY_ROUTES: {only_in_doc}")
    for level in sorted(set(routes) & set(doc_routes)):
        if doc_routes[level] != routes[level]:
            bad.append(f"{level}: документ {doc_routes[level]}, код {routes[level]}")

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


def _check_overview_telemetry_readmodel_empty_kind(src: Sources) -> Optional[str]:
    """Task 2.8: kind ``telemetry_readmodel_empty`` в шпаргалке AGENTS.md ↔ реальный литерал overview.py.

    Ф2 Task 2.8 завела новую аномалию ``system_overview``: холодная сессия (read-model
    пуст И подписки нет) перестаёт молчать про предусловие. Имя kind'а — inline-строка
    в ``anomalies.append``, константы под ней нет (единственное место, где он назван
    в коде, — сам вызов), поэтому проверка сверяет строку документа с текстом файла
    через ``ast``-парсер было бы избыточно — здесь регулярка по литералу, тем же
    приёмом, что у остальных «проверка фразы» в этом модуле.
    """
    agents = src.read(f"{BACKEND_CTL}/AGENTS.md")
    row = next((line for line in agents.splitlines() if "system_overview(timeout=)" in line), None)
    if row is None:
        raise Unverifiable(f"{BACKEND_CTL}/AGENTS.md: строки со `system_overview(timeout=)` нет — предпосылка ушла")
    if "telemetry_readmodel_empty" not in row:
        return "AGENTS.md: строка system_overview не называет kind telemetry_readmodel_empty"
    overview = src.read(f"{BACKEND_CTL}/overview.py")
    if not re.search(r'"kind":\s*"telemetry_readmodel_empty"', overview):
        return "AGENTS.md называет kind telemetry_readmodel_empty, в overview.py такого литерала нет"
    return None


def _module_constant(src: Sources, rel: str, name: str) -> object:
    """Значение модульной константы ``name`` по AST файла ``rel`` (без импорта)."""
    tree = ast.parse(src.read(rel))
    for node in ast.walk(tree):
        targets = (
            node.targets if isinstance(node, ast.Assign) else ([node.target] if isinstance(node, ast.AnnAssign) else [])
        )
        if any(isinstance(t, ast.Name) and t.id == name for t in targets) and node.value is not None:
            try:
                return ast.literal_eval(node.value)
            except ValueError as exc:  # pragma: no cover — константа перестала быть литералом
                raise Unverifiable(f"{rel}: {name} не литерал ({exc})") from exc
    raise Unverifiable(f"{rel}: константа {name} не найдена")


def _schema_field_default(src: Sources, rel: str, cls: str, field: str) -> object:
    """Дефолт поля Pydantic-схемы ``cls.field`` по AST — без импорта фреймворка."""
    tree = ast.parse(src.read(rel))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.ClassDef) and node.name == cls):
            continue
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.target.id == field:
                if stmt.value is None:
                    raise Unverifiable(f"{rel}: {cls}.{field} без дефолта")
                try:
                    return ast.literal_eval(stmt.value)
                except ValueError as exc:
                    raise Unverifiable(f"{rel}: дефолт {cls}.{field} не литерал ({exc})") from exc
        raise Unverifiable(f"{rel}: поле {field} не найдено у {cls}")
    raise Unverifiable(f"{rel}: класс {cls} не найден")


def _string_members(src: Sources, rel: str, name: str) -> Set[str]:
    """Строковые элементы кортежа ``name`` — ЧЛЕНСТВО, а не точное значение.

    ``literal_eval`` здесь не годится: перечень собран конкатенацией
    (``PLANE_COUNTER_KEYS = (...) + DELIVERY_COUNTER_KEYS``), и узел выражения
    не литерал. Обходим поддерево и берём все строковые константы — для вопроса
    «опубликован ли ЭТОТ ключ» этого достаточно, а точный порядок ни один
    документ не обещает.
    """
    tree = ast.parse(src.read(rel))
    for node in ast.walk(tree):
        targets = (
            node.targets if isinstance(node, ast.Assign) else ([node.target] if isinstance(node, ast.AnnAssign) else [])
        )
        if any(isinstance(t, ast.Name) and t.id == name for t in targets) and node.value is not None:
            return {n.value for n in ast.walk(node.value) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    raise Unverifiable(f"{rel}: перечень {name} не найден")


def _check_numbers_policy_claims(src: Sources) -> Optional[str]:
    """CONTROL_PANEL.md о плоскости ЧИСЕЛ ↔ константы и схема (Ф2, задача 2.1).

    Сторожатся ровно те утверждения документа, которые несут ИМЯ, ЧИСЛО или
    ДЕФОЛТ, — то есть те, что расходятся с кодом молча:

    * форма пути правила (``processes.<процесс>.stats.<имя метрики>``) ↔
      ``STATS_SUBTREE_PATTERN``;
    * дефолтный интервал чисел ``0.0`` ↔ ``STATS_SUBTREE_INTERVAL_SEC``;
    * дефолт ``stats.log_snapshots`` ↔ поле схемы ``ObservabilityStatsConfig``.

    Формулировка «теги правилом не адресуются» структурно не выразима, и
    сторожится ФРАЗОЙ — но с предпосылкой, вычисленной из кода: пока в паттерне
    поддерева нет сегмента про теги, документ обязан говорить об этом вслух.
    """
    policy_rel = f"{MODULES}/process_module/configs/observation_policy.py"
    pattern = _module_constant(src, policy_rel, "STATS_SUBTREE_PATTERN")
    interval = _module_constant(src, policy_rel, "STATS_SUBTREE_INTERVAL_SEC")
    log_default = _schema_field_default(
        src, f"{MODULES}/process_module/configs/observability_config.py", "ObservabilityStatsConfig", "log_snapshots"
    )
    # Пробелы и жирный markdown схлопываются ДО сверки: перенос строки в
    # документе — вопрос вёрстки, и проверка, краснеющая от него, научила бы
    # обходить себя переносом, а не сверять факт.
    doc = re.sub(r"\s+", " ", src.read(f"{OBS}/CONTROL_PANEL.md").replace("*", ""))
    bad: List[str] = []

    # Путь в документе записан человеческой формой с угловыми скобками, а в коде
    # — glob'ом. Сверяется ЯДРО (`processes` … `stats` …), общее у обеих форм:
    # сменись корень плоскости в коде — документ обязан покраснеть.
    if not str(pattern).startswith("processes.") or ".stats." not in str(pattern):
        raise Unverifiable(f"STATS_SUBTREE_PATTERN сменил форму ({pattern!r}) — проверку нужно переписать")
    if "`processes.<процесс>.stats.<имя метрики>`" not in doc:
        bad.append(f"CONTROL_PANEL.md не называет форму пути чисел, а код её держит: {pattern!r}")
    if f"`{pattern}`" not in doc and "`processes.<процесс>.stats.<имя метрики>`" not in doc:
        bad.append(f"CONTROL_PANEL.md не сходится с STATS_SUBTREE_PATTERN={pattern!r}")
    if f"интервал `{interval}`" not in doc:
        bad.append(f"CONTROL_PANEL.md: дефолтный интервал чисел в коде {interval!r}, в документе его нет")
    if bool(log_default) is not True:
        bad.append(f"дефолт log_snapshots в схеме стал {log_default!r} — документ обещает true")
    elif "log_snapshots` с дефолтом `true`" not in doc:
        bad.append("CONTROL_PANEL.md не называет дефолт log_snapshots (`true`), а от него зависит миграция")
    if "Теги в путь НЕ входят и правилом не адресуются" not in doc:
        bad.append("CONTROL_PANEL.md молчит про Р-2(а): теги правилом не адресуются")

    counters = _string_members(src, f"{MODULES}/process_module/managers/observability_reload.py", "PLANE_COUNTER_KEYS")
    for key in ("numbers_policy_dropped", "numbers_policy_throttled"):
        if key not in counters:
            bad.append(f"{key} обещан документами, но не публикуется через PLANE_COUNTER_KEYS")
        if f"`{key}`" not in doc:
            bad.append(f"CONTROL_PANEL.md не называет счётчик {key}")
    return "; ".join(bad) if bad else None


CHECKS: Sequence[Check] = (
    Check(
        "F2-1",
        "observability/CONTROL_PANEL.md",
        "плоскость ЧИСЕЛ: форма пути, дефолтный интервал, дефолт log_snapshots, имена счётчиков",
        "Ф2 задача 2.1 (Р-2а/Р-3а)",
        _check_numbers_policy_claims,
    ),
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
    Check(
        "C3",
        "observability/CONNECTORS.md",
        "имена счётчиков раздела «Что ловится автоматически» = HOOK_COUNTER_KEYS",
        "C3 ревью 2026-08-28 (Task 1.1)",
        _check_hook_counter_names,
    ),
    Check(
        "T2.8",
        "backend_ctl/AGENTS.md",
        "kind telemetry_readmodel_empty (шпаргалка system_overview) — реальный литерал overview.py",
        "Task 2.8 плана observability-closure (Ф2)",
        _check_overview_telemetry_readmodel_empty_kind,
    ),
    Check(
        "H3H4-schema",
        "observability/CONTROL_PANEL.md",
        "секции observability.* называют КАЖДОЕ поле своей Pydantic-схемы (схемо-управляемо)",
        "Н-4, добор ревью Ф2 (замыкатель класса, 2026-09-01)",
        _check_observability_section_fields,
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
