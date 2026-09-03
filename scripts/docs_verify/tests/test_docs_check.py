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
PROCESS_HOOKS = "multiprocess_framework/modules/logger_module/core/process_hooks.py"
BACKEND_CTL_AGENTS = "backend_ctl/AGENTS.md"
BACKEND_CTL_OVERVIEW = "backend_ctl/overview.py"
OBSERVATION_POLICY = "multiprocess_framework/modules/process_module/configs/observation_policy.py"
OBSERVABILITY_CONFIG = "multiprocess_framework/modules/process_module/configs/observability_config.py"

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
                "| `observability.tail.unsubscribe` | `subscriber`, `scope` |",
                "| `observability.tail.unsubscribe` | `subscriber`, `scope`, `level` |",
            )
        ],
        id="F1-2-unsubscribe-объявлен-с-level",
    ),
    # Т-1 (2026-08-12): вторая инъекция того же F1-2 — на ПРОТИВОПОЛОЖНОЕ направление
    # дрифта. Единственная инъекция «документ объявляет лишнее» не сторожила случай
    # «схема завела поле, документ промолчал» — а именно он и произошёл: коммит 5.6
    # добавил `scope` в обе схемы, CONTROL_PANEL.md не обновили, и 17 красных прожили
    # сутки. Проверка это поймала честно; не поймала её собственная батарея сломов.
    pytest.param(
        "F1-2",
        [
            (
                CONTROL_PANEL,
                "| `observability.tail.subscribe` | `subscriber`, `level`, `scope` |",
                "| `observability.tail.subscribe` | `subscriber`, `level` |",
            )
        ],
        id="F1-2-subscribe-умолчал-о-scope",
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
    pytest.param(
        "C3",
        [(CONNECTORS, "| `hook_delivery_failures` |", "| `hook_delivery_failure` |")],
        id="C3-имя-счётчика-в-документе-разошлось-с-кодом",
    ),
    # Вторая инъекция того же C3 — со стороны КОДА, а не документа. Единственный
    # слом «документ переврал имя» не сторожил бы противоположный дрейф: счётчик
    # переименовали в константе, документ остался с прежним написанием (ровно то,
    # что произошло с F1-2 при добавлении `scope`).
    pytest.param(
        "C3",
        [(PROCESS_HOOKS, '"warnings_captured"', '"warnings_counted"')],
        id="C3-счётчик-переименован-в-коде",
    ),
    pytest.param(
        "T2.8",
        # Обе живые упоминания в строке лежат в одной физической строке таблицы
        # (перечень + пояснение рядом) — заменяем все вхождения разом, иначе одно
        # оставшееся упоминание тихо спасло бы проверку от красноты.
        [(BACKEND_CTL_AGENTS, "telemetry_readmodel_empty", "REMOVED_KIND")],
        id="T2.8-документ-забыл-kind",
    ),
    pytest.param(
        "T2.8",
        # Противоположное направление дрифта — код переименовал литерал, документ
        # остался со старым написанием (тот же класс слома, что у F1-2/C3 выше).
        [(BACKEND_CTL_OVERVIEW, '"kind": "telemetry_readmodel_empty"', '"kind": "telemetry_readmodel_missing"')],
        id="T2.8-код-переименовал-kind",
    ),
    # F2-1 (Ф2, задача 2.1). Две инъекции на ПРОТИВОПОЛОЖНЫЕ направления дрифта —
    # то же правило, что у F1-2 и T2.8: одна проверка «документ обещает лишнее»
    # не сторожит случай «код изменился, документ промолчал».
    pytest.param(
        "F2-1",
        [
            (
                CONTROL_PANEL,
                "**Теги в путь НЕ входят и правилом не адресуются**",
                "Теги в путь входят и адресуются правилом",
            )
        ],
        id="F2-1-документ-обещает-адресацию-по-тегам",
    ),
    pytest.param(
        "F2-1",
        [(OBSERVATION_POLICY, "STATS_SUBTREE_INTERVAL_SEC = 0.0", "STATS_SUBTREE_INTERVAL_SEC = 1.0")],
        id="F2-1-код-сменил-дефолтный-интервал-чисел",
    ),
    # Task 2.9 (M2, добор ревью Ф2): CONTROL_PANEL.md перестал называть readback-ключ
    # `enabled` рядом с `plane_disabled` — код факт держит (регэксп по stats_manager.py
    # не тронут), молчит именно документ.
    pytest.param(
        "F2-1",
        [
            (
                CONTROL_PANEL,
                "| `enabled` | `introspect.observability` → `effective.stats` |",
                "| `enabled_renamed_for_test` | `introspect.observability` → `effective.stats` |",
            )
        ],
        id="F2-1-документ-перестал-называть-readback-enabled",
    ),
    # F2-3 (Ф2, задача 2.3, M9). Тот же парный приём, что у F2-1 выше: документ
    # обещает лишнее (дефолт разошёлся) И код сменился молча (документ не узнал).
    pytest.param(
        "F2-3",
        [(CONTROL_PANEL, "(L0 **`5.0`**)", "(L0 **`1.0`**)")],
        id="F2-3-документ-называет-неверный-дефолт-такта",
    ),
    # F2-3, третье утверждение (Ф2, задача 2.11, Р-11): документ обязан называть
    # ЧИСЛОМ дефолт поддерева порта. Заведено находкой матрицы K: до этой записи
    # проверка F2-3 несла три утверждения, а инъекции были только у ОДНОГО из них
    # (дефолт такта, две записи выше). `test_every_check_is_covered_by_an_injection`
    # это не ловит — он требует покрытия на ПРОВЕРКУ, а не на утверждение, поэтому
    # ослабь кто-нибудь именно половину про поддерево — и ни один тест не заметил бы:
    # `test_working_tree_has_no_divergences` остался бы зелёным (дерево-то согласно),
    # а инъекция про такт краснела бы по-прежнему.
    #
    # Числом: заплата измерена руками до этой записи (набор K, K6) —
    # `python -m scripts.docs_verify.docs_check` дал exit 1, «проверок: 19;
    # расхождений: 1; [F2-3] … не называет дефолт поддерева числом (0.0)».
    #
    # Парной записи «код сменил дефолт поддерева» здесь быть НЕ МОЖЕТ, и это не
    # забывчивость: страж кода после Р-11 отвечает на другое число `Unverifiable`
    # («останови сверку и пересмотри формулировку вместе с кодом»), а
    # `test_each_check_goes_red_on_its_own_break` требует `unverifiable == []` —
    # такая инъекция сломала бы предпосылку, а не свойство. Код-половина стережётся
    # отдельным тестом ниже (`test_a_changed_subtree_default_stops_the_check`).
    pytest.param(
        "F2-3",
        [(CONTROL_PANEL, "дефолт поддерева\n`0.0` с (", "дефолт поддерева\n`1.0` с (")],
        id="F2-3-документ-называет-неверный-дефолт-поддерева",
    ),
    pytest.param(
        "F2-3",
        [
            (
                OBSERVABILITY_CONFIG,
                '"Такт heartbeat/телеметрии процесса, сек — эффективный тик = min(это, tick_sec)",\n'
                "            min=0.0,\n"
                "            max=86400.0,\n"
                "        ),\n"
                "    ] = 5.0",
                '"Такт heartbeat/телеметрии процесса, сек — эффективный тик = min(это, tick_sec)",\n'
                "            min=0.0,\n"
                "            max=86400.0,\n"
                "        ),\n"
                "    ] = 3.0",
            )
        ],
        id="F2-3-код-сменил-дефолт-такта",
    ),
    # H3H4-schema (замыкатель класса Н-4, добор ревью Ф2, 2026-09-01). Тот же
    # парный приём, что у F1-2/C3/T2.8/F2-1 выше: одна инъекция «документ забыл
    # поле» не сторожит противоположный дрейф «схема завела поле, документ
    # молчит» — а именно ЭТОТ дрейф и был точкой находки Н-4 (max_tracked_keys/
    # stale_windows добавлены в схему Task 2.7, документ не узнал ни об одном).
    pytest.param(
        "H3H4-schema",
        [
            (
                CONTROL_PANEL,
                "| `stale_windows` | `10` | окон молчания до того, как бездолжный ключ считается протухшим |\n",
                "",
            )
        ],
        id="H3H4-schema-документ-забыл-поле-таблицы",
    ),
    pytest.param(
        "H3H4-schema",
        # Схема завела поле, документ не узнал: доказывает, что список полей
        # ДЕЙСТВИТЕЛЬНО читается из схемы (_model_fields), а не переписан
        # константой в самой проверке — иначе эта инъекция не покраснела бы.
        [
            (
                OBSERVABILITY_CONFIG,
                "    stale_windows: Annotated[\n"
                "        int,\n"
                '        FieldMeta("Сколько окон молчания до того, как бездолжный ключ '
                'считается протухшим", min=1, max=10_000),\n'
                "    ] = 10\n",
                "    stale_windows: Annotated[\n"
                "        int,\n"
                '        FieldMeta("Сколько окон молчания до того, как бездолжный ключ '
                'считается протухшим", min=1, max=10_000),\n'
                "    ] = 10\n"
                "    new_field_for_h3h4_injection: Annotated[\n"
                "        int,\n"
                '        FieldMeta("поле для инъекции сторожа H3H4-schema", min=1, max=10),\n'
                "    ] = 1\n",
            )
        ],
        id="H3H4-schema-код-завёл-поле-документ-молчит",
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


def test_a_changed_subtree_default_stops_the_check() -> None:
    """Смена ``DEFAULT_SUBTREE_INTERVAL_SEC`` ОСТАНАВЛИВАЕТ F2-3, а не проползает мимо.

    Код-половина третьего утверждения F2-3 (Ф2, задача 2.11, Р-11). Она не может
    жить в :data:`INJECTIONS`: страж отвечает ``Unverifiable``, а
    :func:`test_each_check_goes_red_on_its_own_break` требует ``unverifiable == []``.

    **Зачем именно так, а не «краснеет».** До Р-11 страж сравнивал
    ``subtree_default < heartbeat_default`` — и на новом числе (``0.0 < 5.0``)
    условие ОСТАЛОСЬ истинным, то есть проверка молча продолжала бы охранять
    снятое утверждение о сужении голоса. Это была не мелочь формулировки: страж
    сторожил СЛЕДСТВИЕ столкновения чисел, а не его причину, и отмены причины не
    заметил бы вовсе. Поэтому теперь требуется ровно ``0.0``, а любое другое
    значение — повод остановиться и пересмотреть документ вместе с кодом, а не
    повод для расхождения: расхождение означало бы «документ врёт», а здесь врать
    начинает ПОСЫЛКА проверки.

    Что сломается, если это перестанет быть правдой: кто-нибудь вернёт мягкое
    сравнение, дефолт поддерева уедет на любое ненулевое значение, и F2-3 отдаст
    зелёный, хотя половина её утверждений к коду больше не относится.
    """
    src = Sources().with_replacement(
        OBSERVATION_POLICY,
        "DEFAULT_SUBTREE_INTERVAL_SEC = 0.0",
        "DEFAULT_SUBTREE_INTERVAL_SEC = 2.0",
    )
    report = run_all(src)

    assert any("F2-3" in line for line in report.unverifiable), (
        f"F2-3 не остановилась на смене дефолта поддерева; unverifiable={report.unverifiable}, "
        f"divergences={report.divergences}"
    )
    assert any("2.0" in line for line in report.unverifiable), (
        f"сообщение не называет новое значение — оператор не поймёт, что пересматривать: {report.unverifiable}"
    )


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
