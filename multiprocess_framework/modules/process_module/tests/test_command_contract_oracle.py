# -*- coding: utf-8 -*-
"""Оракул «поля контракта ⊇ ключи, которые читает хендлер» (A1, major-16).

Ровно в этом шве жил Б-1б: ``ObservabilityTailSubscribeParams`` не объявлял
``level``, хендлер его читал. При ``extra="forbid"`` это давало
``contract_violations`` на каждую подписку, а с ``FW_CONTRACTS_STRICT=1``
подписка исчезала бы молча. Точечный тест на одну команду закрыл бы одну
команду; здесь шов судится **классом** — по всему реестру сразу, чтобы
следующее расхождение упало на добавлении, а не на живом стенде.

Почему AST, а не вызов хендлера: прочитанные ключи надо снять, не исполняя
код (у хендлеров есть побочные эффекты и зависимость от живого процесса), и
надо видеть ВСЕ ветки, включая те, куда тестовый вход не заходит.

Известное ограничение метода названо вслух: оракул видит только литеральные
``args.get("ключ")``. Динамическое чтение (``args.get(name)``) он пропустит —
это не «доказано, что таких нет», а «эта проверка их не судит».
"""

from __future__ import annotations

import ast
import pathlib
from typing import Dict, Set

import pytest

from multiprocess_framework.modules.process_module.commands.command_contracts import (
    BUILTIN_COMMAND_CONTRACTS,
)

_FRAMEWORK_ROOT = pathlib.Path(__file__).resolve().parents[3]

#: Файлы, в которых живут хендлеры команд реестра. Оркестраторские команды
#: (``*.subscribe_all``) обрабатывает ProcessManager, но судятся они тем же
#: реестром — см. докстринг ObservabilityTailBrokerParams.
_HANDLER_SOURCES = (
    _FRAMEWORK_ROOT / "modules" / "process_module" / "commands" / "builtin_commands.py",
    _FRAMEWORK_ROOT / "modules" / "process_manager_module" / "process" / "process_manager_process.py",
)

#: Имена, под которыми в хендлерах лежит словарь параметров. ``data`` — сырой
#: вход, остальные — результат слияния ``_merge_args``/``_merge_cmd_args``.
_ARG_HOLDERS = frozenset({"args", "data", "params", "payload"})

#: Ключи, приходящие не от вызывающего, а от транспорта/мидлвари: они есть в
#: конверте всегда и контрактом параметров не объявляются. Список **явный** —
#: молчаливое исключение здесь означало бы дыру ровно того класса, что ловит
#: сам оракул.
_TRANSPORT_KEYS = frozenset(
    {
        "correlation_id",  # сквозной ключ ответа, ставит MessageAdapter
        "command",  # имя самой команды в конверте
        "sender",  # адрес отправителя, ставит роутер
        "session",  # идентификатор соединения внешнего подписчика
    }
)


def _iter_handler_defs(tree: ast.AST) -> Dict[str, ast.FunctionDef]:
    """Все методы ``_cmd_*`` файла: имя метода → его AST-узел."""
    found: Dict[str, ast.FunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_cmd_"):
            found[node.name] = node
    return found


def _iter_registrations(tree: ast.AST) -> Dict[str, str]:
    """Карта «имя команды → имя метода-хендлера», снятая с мест регистрации.

    Три формы регистрации в коде, все учитываются:
      * кортеж таблицы ``("worker.create", self._cmd_worker_create, "…")``;
      * прямой вызов ``cm.register_command("имя", self._cmd_x, …)``;
      * словарь ``{"имя": (self._cmd_x, "описание")}`` — форма оркестратора.

    Третью форму первая редакция оракула не знала, и ВСЯ командная поверхность
    ProcessManager оставалась несудимой при зелёном тесте. Поэтому ниже стоит
    :meth:`TestHandlerKeysDeclaredInContract.test_oracle_sees_both_command_surfaces`
    — молчащий детектор обязан сперва показать, что он видит.
    """
    mapping: Dict[str, str] = {}

    def _handler_name(node: ast.AST) -> str | None:
        # self._cmd_x  →  "_cmd_x"
        if isinstance(node, ast.Attribute) and node.attr.startswith("_cmd_"):
            return node.attr
        return None

    for node in ast.walk(tree):
        # форма 1: кортеж в таблице specs
        if isinstance(node, ast.Tuple) and len(node.elts) >= 2:
            head = node.elts[0]
            if isinstance(head, ast.Constant) and isinstance(head.value, str) and "." in head.value:
                name = _handler_name(node.elts[1])
                if name:
                    mapping[head.value] = name
        # форма 2: прямой register_command(...)
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "register_command" and node.args:
                head = node.args[0]
                if isinstance(head, ast.Constant) and isinstance(head.value, str):
                    name = _handler_name(node.args[1]) if len(node.args) > 1 else None
                    if name:
                        mapping[head.value] = name
        # форма 3: словарь {"имя": (хендлер, "описание")} либо {"имя": хендлер}
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                    continue
                if "." not in key.value:
                    continue
                candidate = value.elts[0] if isinstance(value, ast.Tuple) and value.elts else value
                name = _handler_name(candidate)
                if name:
                    mapping[key.value] = name
    return mapping


def _keys_read_by(handler: ast.FunctionDef) -> Set[str]:
    """Литеральные ключи, которые тело хендлера читает из словаря параметров.

    Ищется ``<держатель>.get("ключ")`` — та единственная форма, которой в этих
    хендлерах читают вход. ``in``-проверки (``"k" in args``) тоже считаются
    чтением: отсутствие ключа в схеме означает, что при ``forbid`` он не доедет.
    """
    keys: Set[str] = set()
    for node in ast.walk(handler):
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "get"
                and isinstance(func.value, ast.Name)
                and func.value.id in _ARG_HOLDERS
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                keys.add(node.args[0].value)
        elif isinstance(node, ast.Compare) and isinstance(node.ops[0], ast.In):
            left, right = node.left, node.comparators[0]
            if (
                isinstance(left, ast.Constant)
                and isinstance(left.value, str)
                and isinstance(right, ast.Name)
                and right.id in _ARG_HOLDERS
            ):
                keys.add(left.value)
        elif isinstance(node, ast.Subscript):
            # args["ключ"] — редкая, но столь же обязывающая форма
            if (
                isinstance(node.value, ast.Name)
                and node.value.id in _ARG_HOLDERS
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
            ):
                keys.add(node.slice.value)
    return keys


def _build_oracle() -> Dict[str, Set[str]]:
    """Реестр «команда → ключи, читаемые её хендлером» по обоим файлам."""
    handlers: Dict[str, ast.FunctionDef] = {}
    registrations: Dict[str, str] = {}
    for source in _HANDLER_SOURCES:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        handlers.update(_iter_handler_defs(tree))
        registrations.update(_iter_registrations(tree))

    oracle: Dict[str, Set[str]] = {}
    for command, handler_name in registrations.items():
        handler = handlers.get(handler_name)
        if handler is not None:
            oracle[command] = _keys_read_by(handler)
    return oracle


_ORACLE = _build_oracle()


class TestHandlerKeysDeclaredInContract:
    """Каждая команда реестра: схема обязана объявлять всё, что читает хендлер."""

    def test_oracle_itself_is_not_empty(self):
        """Молчащий детектор ничего не доказывает — сперва покажи, что он видит.

        Без этой проверки поломка AST-разбора (переименование ``_cmd_``,
        смена формы регистрации) превратила бы оракул в вечнозелёный: пустая
        карта проходит любую проверку ниже.
        """
        judged = set(_ORACLE) & set(BUILTIN_COMMAND_CONTRACTS)
        assert len(judged) >= 30, (
            f"оракул нашёл хендлеры лишь для {len(judged)} команд реестра "
            f"из {len(BUILTIN_COMMAND_CONTRACTS)} — разбор сломан, "
            f"а не 'нарушений нет'. Найдено: {sorted(judged)}"
        )
        # и он обязан видеть непустые ключи хотя бы у части команд
        with_keys = {c for c in judged if _ORACLE[c]}
        assert len(with_keys) >= 10, (
            f"оракул не извлёк ни одного ключа у {len(judged) - len(with_keys)} команд — извлечение ключей сломано"
        )

    def test_oracle_sees_both_command_surfaces(self):
        """Поимённо: процессная поверхность И оркестраторская.

        Счётчик «≥30» этого не ловит: команд процесса заведомо больше тридцати,
        поэтому полная слепота к ProcessManager проходила бы незамеченной — так
        первая редакция оракула и не судила НИ ОДНОЙ команды оркестратора,
        оставаясь зелёной. Порог, взятый там, где кандидаты не расходятся,
        не проверяет ничего.
        """
        expected = {
            # процесс (таблицы specs в builtin_commands.py)
            "observability.tail.subscribe": "level",
            "config.reload": "persist",
            # оркестратор (словарь команд в process_manager_process.py)
            "observability.tail.subscribe_all": "level",
        }
        for command, key in expected.items():
            assert command in _ORACLE, (
                f"оракул не видит команду '{command}' — форма её регистрации "
                "не разобрана, и вся её поверхность не судится"
            )
            assert key in _ORACLE[command], (
                f"оракул видит '{command}', но не извлёк ключ '{key}': извлечено {sorted(_ORACLE[command])}"
            )

    @pytest.mark.parametrize("command", sorted(set(_ORACLE) & set(BUILTIN_COMMAND_CONTRACTS)))
    def test_contract_declares_every_key_the_handler_reads(self, command: str):
        schema = BUILTIN_COMMAND_CONTRACTS[command]
        declared = set(schema.model_fields)
        read = _ORACLE[command] - _TRANSPORT_KEYS
        missing = read - declared
        assert not missing, (
            f"команда '{command}': хендлер читает {sorted(missing)}, "
            f"а контракт {schema.__name__} их не объявляет "
            f"(объявлено: {sorted(declared) or '—'}). При extra='forbid' такой ключ "
            f"даёт contract_violation, а с FW_CONTRACTS_STRICT=1 команда исчезает молча."
        )


def _commands_registered_by(method_name: str) -> Set[str]:
    """Имена команд, регистрируемых конкретным методом ``_register_*`` (AST).

    Считается по таблице ``specs`` внутри метода — той же форме 1, что разбирает
    :func:`_iter_registrations`; ограничивать разбор телом ОДНОГО метода нужно
    затем, что вопрос здесь другой: не «какие команды есть», а «какие из них
    принадлежат поверхности наблюдаемости».
    """
    source = _HANDLER_SOURCES[0]
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == method_name:
            return {
                n.elts[0].value
                for n in ast.walk(node)
                if isinstance(n, ast.Tuple)
                and n.elts
                and isinstance(n.elts[0], ast.Constant)
                and isinstance(n.elts[0].value, str)
                and "." in n.elts[0].value
            }
    return set()


class TestTypedScopeCoversTheObservabilitySurface:
    """Вторая ось шва (Task 2.2): охват проверки типов ⊇ поверхность наблюдаемости.

    Первая ось судит ИМЕНА (контракт объявляет всё, что читает хендлер). Она
    ничего не говорит о том, что с объявленным типом кто-то СВЕРЯЕТСЯ, — и
    ровно в этом зазоре жила Н-5: контракт объявлял
    ``resolve: Optional[Union[str, List[str]]]``, оракул был зелёным, а
    ``resolve=true`` доезжал до ``list(True)``.

    Здесь судится третье: команда поверхности, не попавшая в
    ``OBSERVABILITY_TYPED_COMMANDS``, остаётся со СТАРЫМ поведением молча.
    Проверка нужна именно как страж дрейфа: добавить команду в таблицу
    регистрации проще, чем вспомнить про список охвата, и забытая команда
    выглядела бы ровно как защищённая.
    """

    def test_the_ast_side_is_not_empty(self):
        """Молчащий детектор: пустое множество слева проходит любое ⊆ справа."""
        registered = _commands_registered_by("_register_observability_commands")
        assert len(registered) >= 10, (
            f"разбор таблицы регистрации нашёл лишь {len(registered)} команд — "
            f"форма таблицы изменилась, и страж ослеп: {sorted(registered)}"
        )

    def test_every_registered_observability_command_is_typed(self):
        from multiprocess_framework.modules.process_module.commands.builtin_commands import (
            OBSERVABILITY_TYPED_COMMANDS,
        )

        registered = _commands_registered_by("_register_observability_commands")
        escaped = sorted(registered - OBSERVABILITY_TYPED_COMMANDS)
        assert not escaped, (
            f"команды наблюдаемости вне охвата проверки типов: {escaped}. "
            f"Добавьте имя в OBSERVABILITY_TYPED_COMMANDS — иначе мусорный тип "
            f"параметра дойдёт до хендлера, как это было с 'resolve' (Н-5)."
        )

    def test_the_scope_does_not_name_commands_that_do_not_exist(self):
        """Обратная сторона: имя в охвате, которого нет нигде, сторожит пустоту."""
        from multiprocess_framework.modules.process_module.commands.builtin_commands import (
            OBSERVABILITY_TYPED_COMMANDS,
        )

        known = set(_ORACLE) | _commands_registered_by("_register_introspect_commands")
        phantom = sorted(OBSERVABILITY_TYPED_COMMANDS - known)
        assert not phantom, f"в охвате имена, которых нет среди зарегистрированных команд: {phantom}"
