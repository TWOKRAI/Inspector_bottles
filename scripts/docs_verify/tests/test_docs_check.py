# -*- coding: utf-8 -*-
"""Сверщик документов обязан быть зелёным И уметь краснеть (задача 5.1 roadmap).

Главное здесь — не первый тест, а второй: **на каждую проверку своя инъекция**,
возвращающая документ ровно в то состояние, в котором его застала приёмка F1.
Молчащий детектор не доказывает ничего, поэтому список инъекций поимённый, а не
«одна на всех»: инъекция, задевающая две проверки сразу, красит обе — и тогда
непонятно, какая именно держит свойство.

Инъекция снимает **все** предохранители своего свойства, а не один из двух: у
пометки снимка в `COMMUNICATION_MAP.md` маркеров два, и правка одного оставляла
проверку зелёной, создавая впечатление, что она слом пережила.

Предсказание сделано ДО прогона (правило плана): каждая инъекция красит **ровно
одну** проверку — свою. Первый же прогон предсказание опроверг дважды и нашёл
этим два дефекта в самом сверщике (вакуумный разбор абзаца в F1-5; два маркера
под одним идентификатором в F1-6) — оба исправлены, а F1-6 разделена надвое.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

import pytest

from scripts.docs_verify.docs_check import CHECKS, Sources, Unverifiable, run_all

CONNECTORS = "multiprocess_framework/docs/observability/CONNECTORS.md"
CONTROL_PANEL = "multiprocess_framework/docs/observability/CONTROL_PANEL.md"
SINKS_MAP = "multiprocess_framework/docs/observability/SINKS_MAP.md"
RECIPE = "multiprocess_framework/docs/observability/NEW_MODULE_RECIPE.md"
COMM_MAP = "multiprocess_framework/docs/COMMUNICATION_MAP.md"
DOCS_README = "multiprocess_framework/docs/README.md"
CONTRACTS = "multiprocess_framework/docs/MODULE_CONTRACTS.md"
CMD_MANAGER = "multiprocess_framework/modules/command_module/core/command_manager.py"
SEVERITY_CFG = "multiprocess_framework/modules/error_module/configs/error_manager_config.py"

Edit = Tuple[str, str, str]  # (файл, что заменить, на что — текст ДО правок 5.1)

INJECTIONS: List["pytest.ParameterSet"] = [
    pytest.param(
        "F1-1",
        [(CONNECTORS, "`_track_error(error, context)`", "`_track_error(exc, context)`")],
        id="F1-1-имя-аргумента-разошлось-с-кодом",
    ),
    pytest.param(
        "F1-2",
        [
            (
                CONTROL_PANEL,
                "| `observability.tail.unsubscribe` | `subscriber` — **и только он** |",
                "| `observability.tail.unsubscribe` | `subscriber`, `level` |",
            )
        ],
        id="F1-2-unsubscribe-объявлен-с-level",
    ),
    pytest.param(
        "F1-3",
        [(CONNECTORS, "Прикладной код звать его **не должен**", "Прикладной код его позвать не может")],
        id="F1-3-ErrorFloor-позвать-не-может",
    ),
    pytest.param(
        "F1-4",
        [
            (
                SINKS_MAP,
                "| `CRITICAL` | `critical_file` → `errors_file` |",
                "| `CRITICAL` | `critical_file` → `warnings_file` |",
            )
        ],
        id="F1-4-таблица-лестницы-разошлась-с-кодом",
    ),
    pytest.param(
        "F1-4",
        [(SINKS_MAP, "**нельзя**", "**можно**")],
        id="F1-4-утверждение-всегда-вверх-вернулось",
    ),
    pytest.param(
        "F1-4",
        # Слом со стороны КОДА, а не документа (Н-B приёмки F2). Прежняя редакция
        # проверки шла по строкам документа и такой слом не видела вовсе: документ
        # продолжал обещать ступень, которой в коде уже нет, а сверщик молчал.
        [(SEVERITY_CFG, '"WARNING": ["warnings_file"', '"WARNING_X": ["warnings_file"')],
        id="F1-4-ступень-снята-из-кода",
    ),
    pytest.param(
        "F1-4",
        [(SEVERITY_CFG, '"CRITICAL": ["critical_file", "errors_file"]', '"CRITICAL": ["critical_file"]')],
        id="F1-4-цепочка-в-коде-укорочена",
    ),
    pytest.param(
        "F1-5",
        [
            (
                RECIPE,
                """сломан». Это **соглашение**: AST-страж
  [`test_std_logger_guard.py`](../../modules/logger_module/tests/test_std_logger_guard.py) считает
  другое — писателей `logging.getLogger` и `loguru` вне whitelist'а; вызовы `emergency_log` не
  считает никто (расхождение №5 приёмки F1);""",
                "сломан» и считается по AST страж-тестом;",
            )
        ],
        id="F1-5-emergency_log-якобы-считает-страж",
    ),
    pytest.param(
        "F1-6",
        [
            # Оба маркера сразу: снятие одного оставляло свойство целым.
            (COMM_MAP, "**⚠️ Это СНИМОК на 2026-05-31, а не живая карта.**", "Карта живая."),
            (COMM_MAP, "устарел вместе со снимком", "актуален вместе со снимком"),
        ],
        id="F1-6-снимок-не-помечен-устаревшим",
    ),
    pytest.param(
        "F1-6b",
        [(COMM_MAP, "(`.gitignore:123`, локальный артефакт того же прогона)", "(рядом)")],
        id="F1-6b-указатель-на-raw.json-без-оговорки",
    ),
    pytest.param(
        "H17-a",
        [(DOCS_README, "**Навигатор по 27 модулям**", "**Навигатор по 21 модулю**")],
        id="H17-a-число-модулей-разошлось",
    ),
    pytest.param(
        "H17-b",
        [(DOCS_README, "OBSERVABILITY_MAP.md", "DIAGRAMS.md")],
        id="H17-b-входа-в-наблюдаемость-нет",
    ),
    pytest.param(
        "H17-c",
        [
            (
                CONTRACTS,
                "`ProcessConfig` (typed-поля `collector`/`chain_targets`/`source_target_fps`/`io_peek` —"
                " приоритет над одноимёнными в `extras`; ключ `inspector` — **легаси-алиас на чтении**"
                " (`_accept_legacy_collector_key`), `model_dump` пишет всегда каноничное `collector`;",
                "`ProcessConfig` (typed-поля `inspector`/`chain_targets`/`source_target_fps`/`io_peek` —"
                " приоритет над одноимёнными в `extras`;",
            )
        ],
        id="H17-c-поле-названо-inspector-без-пометки",
    ),
    pytest.param(
        "H17-d",
        [
            (
                COMM_MAP,
                "ItemCollector.on_item [буфер по (camera_id,seq_id)] → _on_ready → DataReceiver.on_items_ready →"
                " chain_queue.put` | process_module/generic (`collector_registry`), Plugins/_shared/fanin | да |"
                " framework | **alive** (`InspectorManager` не существует: протокол `ItemCollector`, дефолт"
                " `PassThroughCollector`, join-реализации приходят DI из `Plugins`) |",
                "InspectorManager.on_item [буфер по (camera_id,seq_id)] → chain_queue.put`"
                " | process_module/generic | да | framework | **alive** |",
            )
        ],
        id="H17-d-цепочка-через-несуществующий-класс",
    ),
    pytest.param(
        "H6",
        [
            (
                CMD_MANAGER,
                "managers={'logger': logger_manager, 'stats': stats_manager}",
                "managers={'logger': logger_manager, 'statistics': stats_manager}",
            )
        ],
        id="H6-докстринг-учит-мёртвому-слоту",
    ),
    pytest.param(
        "H19-a",
        [(RECIPE, "source_name=LOG_SOURCE", "auto_proxy=True")],
        id="H19-a-шов-source_name-не-показан",
    ),
    pytest.param(
        "H19-b",
        [
            (
                RECIPE,
                """
    def initialize(self) -> bool:            # ОБЯЗАТЕЛЕН — abstractmethod
        self.is_initialized = True
        return True

    def shutdown(self) -> bool:              # ОБЯЗАТЕЛЕН — abstractmethod
        self.is_initialized = False
        return True
""",
                "",
            )
        ],
        id="H19-b-образец-не-инстанцируется",
    ),
]


def test_working_tree_has_no_divergences() -> None:
    """Рабочее дерево: 0 расхождений и 0 «не проверено»."""
    report = run_all()
    assert report.unverifiable == [], f"проверить не удалось: {report.unverifiable}"
    assert report.divergences == [], f"расхождения: {report.divergences}"
    assert report.checked == len(CHECKS)


@pytest.mark.parametrize(("ident", "edits"), INJECTIONS)
def test_each_check_goes_red_on_its_own_break(ident: str, edits: Sequence[Edit]) -> None:
    """Каждая проверка краснеет на своей инъекции — и ТОЛЬКО она."""
    src = Sources()
    for rel, old, new in edits:  # негодная инъекция → Unverifiable, а не тишина
        src = src.with_replacement(rel, old, new)
    report = run_all(src)

    assert report.unverifiable == [], f"инъекция сломала предпосылку, а не свойство: {report.unverifiable}"
    red = {line.split("]")[0].lstrip("[") for line in report.divergences}
    assert ident in red, f"проверка {ident} НЕ покраснела на своём сломе; красные: {red or 'нет'}"
    assert red == {ident}, f"инъекция задела соседей: покраснели {red}, ожидалась только {ident}"


def test_a_broken_injection_is_an_error_not_a_pass() -> None:
    """Инъекция, которой некуда лечь, обязана дать ошибку, а не молча ничего не сделать."""
    with pytest.raises(Unverifiable, match="инъекция негодна"):
        Sources().with_replacement(DOCS_README, "текста-которого-там-нет", "неважно")


def test_unreadable_source_is_unverifiable_not_green() -> None:
    """«Не смог проверить» ≠ «проверил, всё хорошо»: код возврата 2, а не 0."""
    report = run_all(Sources(root="Z:/каталога-нет"))
    assert report.unverifiable, "исчезнувшее дерево дало зелёный отчёт"
    assert report.exit_code == 2


def test_readme_states_the_true_number_of_checks() -> None:
    """README называет РЕАЛЬНОЕ число проверок.

    Сверщик документов, чей собственный README врёт про свой объём, — ровно тот
    класс дефекта, который он и ловит. Первая редакция обещала 15 при 14; поймал
    внешний приёмщик F2 пересчётом, не автор.
    """
    import re
    from pathlib import Path

    readme = Path(__file__).resolve().parents[1] / "README.md"
    stated = re.search(r"\*\*(\d+) проверок\*\*", readme.read_text(encoding="utf-8"))
    assert stated, "в README нет строки «**N проверок**»"
    assert int(stated.group(1)) == len(CHECKS), f"README обещает {stated.group(1)} проверок, в CHECKS их {len(CHECKS)}"


def test_every_check_is_covered_by_an_injection() -> None:
    """Ни одна проверка не остаётся без доказательства красноты."""
    covered = {p.values[0] for p in INJECTIONS}
    missing = {c.ident for c in CHECKS} - covered
    assert not missing, f"проверки без инъекции (не доказано, что краснеют): {sorted(missing)}"
