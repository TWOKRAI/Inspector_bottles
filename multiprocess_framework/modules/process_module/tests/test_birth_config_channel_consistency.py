# -*- coding: utf-8 -*-
"""Task 1.2 — конфиг, с которым менеджеры РОЖДАЮТСЯ, обязан быть непротиворечивым.

**Что было (замер живого стенда 2026-08-31).** У ``ProcessManager`` на чистом
старте ``unresolved_channel_records == 12`` — ``{'system_file': 6,
'messages_file': 6}``. Трассы всех двенадцати легли между ``logger.initialize()``
и пересборкой на boot: ``LoggerManager initialized``, ``RouterManager``,
``StatsManager``, порт наблюдений, ``StatsAdapter.setup``.

**Причина — не в логгере.** К одному и тому же конфигу вели ДВЕ дороги, и они
расходились молча:

* **рождение** собирало голым ``expand_observability(layers.resolve())``;
* **пересборка на boot** — ``merge_managers(база L0, expanded)``.

``expand_observability`` эмитит ЧАСТИЧНЫЙ словарь каналов (только названные
слоем: в конфиге прототипа ``gui_file`` / ``trace_file`` / ``busy_file``), а
Pydantic на ``LoggerManagerConfig`` заменяет словарь каналов целиком. Значит
рождавшийся менеджер имел три канала, а ``scopes`` у него оставались дефолтные и
вели в ``system_file`` / ``messages_file``, которых в его реестре не было вовсе.
Пересборка секундой позже собирала конфиг верно — и потери прекращались.

**Что здесь судится.** Свойство, нарушение которого стоило двенадцати записей, и
которое не зависит от того, КАК собран конфиг: *каждый приёмник, названный
маршрутом, объявлен среди каналов*. Тест намеренно не сверяет две дороги между
собой (это доказывало бы согласие двух копий одной модели) — он проверяет
конфиг, с которым процесс РОЖДАЕТСЯ, на самосогласованность.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from multiprocess_framework.modules.logger_module import LoggerManagerConfig
from multiprocess_framework.modules.process_module.configs.observability_layers import APP_CONFIG_KEY
from multiprocess_framework.modules.process_module.managers.process_managers import ProcessManagers

#: Секция приложения в той же ФОРМЕ, что у прототипа: приёмники ДОБАВЛЯЮТСЯ, а не
#: заменяют набор. Именно эта форма и вскрыла дефект — она частичная.
PARTIAL_CHANNELS_SECTION: Dict[str, Any] = {
    "channels": {
        "gui_file": {"type": "file", "file_path": "gui.log"},
        "trace_file": {"type": "file", "file_path": "trace.log"},
    }
}


class _Handler:
    """Секция менеджеров в том виде, в каком её отдаёт настоящий handler."""

    def __init__(self, managers: Optional[Dict[str, Any]] = None) -> None:
        self._managers = managers

    def get_managers_config(self) -> Dict[str, Any]:
        return self._managers or {}


class _Orchestrator:
    """Процесс в форме ОРКЕСТРАТОРА: секции ``managers`` в его bundle нет вовсе.

    Это единственная форма, на которой дефект воспроизводится: у ребёнка секция
    приезжает готовой от ассемблера, и ветка сборки при создании не работает.
    """

    def __init__(self, section: Dict[str, Any]) -> None:
        self.name = "ProcessManager"
        self.config_handler = _Handler()
        self.config_manager = None
        self._flat = {APP_CONFIG_KEY: section}

    def get_config(self, key: str, default: Any = None) -> Any:
        node: Any = self._flat
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


def _effective(logger_cfg: Dict[str, Any]) -> LoggerManagerConfig:
    """Конфиг в том виде, в каком его увидит РОЖДАЮЩИЙСЯ менеджер.

    **Смотреть на сырой словарь нельзя, и это измерено** (инъекция I5, предсказание
    разошлось с прогоном). Прежняя редакция читала ``scopes`` прямо из словаря — а
    при старой сборке словарь ``scopes`` не содержит ВОВСЕ: маршрут приезжает
    Pydantic-дефолтом схемы. Тест видел «маршрут ничего не называет» и оставался
    ЗЕЛЁНЫМ на конфиге, который живьём терял 12 записей. Лечится единственно верным
    объективом: спросить ту же схему, через которую пройдёт менеджер.
    """
    return LoggerManagerConfig.model_validate(logger_cfg)


def _routed_channel_names(cfg: LoggerManagerConfig) -> Set[str]:
    """Все имена приёмников, которые МАРШРУТ может назвать: скоупы + правила имён."""
    names: Set[str] = set()
    for scope in (cfg.scopes or {}).values():
        names.update(_as_names(scope))
    for rule in (cfg.loggers or {}).values():
        names.update(_as_names(rule))
    return names


def _as_names(node: Any) -> List[str]:
    out: List[str] = []
    for key in ("channels", "channels_extra"):
        value = node.get(key) if isinstance(node, dict) else getattr(node, key, None)
        if isinstance(value, (list, tuple)):
            out.extend(str(v) for v in value)
    return out


class TestBirthConfigNamesOnlyDeclaredChannels:
    def test_every_routed_channel_is_declared(self) -> None:
        """Ни один приёмник маршрута не остаётся необъявленным.

        Красный вид этого теста и есть живая поломка: недостающее имя — это
        ``unresolved_channel_records`` на каждой записи, попавшей в тот маршрут.
        """
        managers = ProcessManagers(_Orchestrator(PARTIAL_CHANNELS_SECTION))._managers_config_for_creation()
        cfg = _effective(managers["logger"])

        declared = set((cfg.channels or {}).keys())
        routed = _routed_channel_names(cfg)
        missing = sorted(routed - declared)

        assert not missing, (
            f"маршрут ведёт в необъявленные приёмники {missing}: записи туда уйдут в "
            f"unresolved_channel_records. Объявлено: {sorted(declared)}"
        )

    def test_partial_section_adds_channels_and_does_not_replace_them(self) -> None:
        """Частичная секция ДОБАВЛЯЕТ приёмники, а не подменяет набор.

        Литералы, а не «то, что вернёт код»: ``system_file`` и ``messages_file``
        — ровно те два имени, по которым живой стенд терял записи (6 + 6 = 12);
        ``gui_file`` — то, что назвало приложение. Обязаны быть все три.
        """
        managers = ProcessManagers(_Orchestrator(PARTIAL_CHANNELS_SECTION))._managers_config_for_creation()
        declared = set((_effective(managers["logger"]).channels or {}).keys())

        assert {"system_file", "messages_file", "gui_file", "trace_file", "console"} <= declared, (
            f"частичная секция подменила набор приёмников вместо добавления: {sorted(declared)}"
        )

    def test_silent_layers_leave_the_section_untouched(self) -> None:
        """Молчащие слои не дают повода собрать что-либо (инвариант ADR-PM-020).

        Пара к тестам выше: они требуют, чтобы сборка ПРОИСХОДИЛА и была полной;
        этот — чтобы она не происходила там, где слои ничего не сказали. Без него
        «собери на всякий случай» затёрло бы конфиг, заданный встройщиком
        программно, и тесты выше остались бы зелёными.
        """
        assert ProcessManagers(_Orchestrator({}))._managers_config_for_creation() == {}
