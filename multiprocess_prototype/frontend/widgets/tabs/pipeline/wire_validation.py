# -*- coding: utf-8 -*-
"""Валидация совместимости портов wire для вкладки Pipeline (Трек F, Task F.3).

Чистая (Qt-free) проверка: можно ли соединить выходной порт источника с входным
портом приёмника. Вынесено из ``PipelinePresenter._validate_wire_ports``
дословно — наблюдаемое поведение (graceful degradation, wildcard-дисплеи,
блокировка несовместимых типов) заморожено ``tests/test_wire_validation.py`` и
НЕ меняется этим разрезом.

Разграничение ответственности:
- ЧТО валидируется (резолв портов через :class:`PluginCatalog`, проверка
  ``are_ports_compatible``) — здесь, без Qt;
- КАК показать отказ пользователю (``QMessageBox``) — остаётся в presenter/tab:
  на ``not ok`` presenter поднимает диалог, используя ``src_dtype``/``tgt_dtype``
  из результата.

Не путать с
:func:`multiprocess_prototype.frontend.bridge.wire_protocol.validate_wire`
(валидация wire-config dict на границе IPC) — здесь другой контракт:
endpoint-строки + каталог плагинов → совместимость типов данных.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from multiprocess_framework.modules.process_module.plugins.port import (
    Port,
    are_ports_compatible,
)

if TYPE_CHECKING:
    from multiprocess_prototype.domain.protocols.plugin_catalog import (
        PluginCatalog,
        PortSpec,
    )

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WireValidation:
    """Результат проверки совместимости портов wire.

    - ``ok`` — можно ли создать wire. ``True`` также при graceful degradation
      (каталог/плагин/порт не найден, некорректный endpoint) — legacy compat;
    - ``src_dtype``/``tgt_dtype`` — типы данных выходного/входного портов.
      Заполнены только при реальной несовместимости (``ok=False``); presenter
      показывает их в диалоге отказа.
    """

    ok: bool
    src_dtype: str = ""
    tgt_dtype: str = ""


def validate_wire_ports(source: str, target: str, catalog: "PluginCatalog") -> WireValidation:
    """Проверить совместимость портов source и target перед созданием wire.

    Task F.5: использует PluginCatalog Protocol (resolve -> PluginSpec.ports)
    вместо raw _registry bridge. PortSpec конвертируется в framework Port для
    проверки через are_ports_compatible.

    Graceful degradation (возвращает ``WireValidation(ok=True)``):
    - PluginSpec не найден -> лог warning;
    - Port не найден -> лог warning;
    - некорректный endpoint (нет plugin/port-сегмента) -> лог debug.
    Display-цель принимает любой image-выход через wildcard ``Port(dtype="image/*")``.

    Args:
        source: endpoint источника в формате "process.plugin.port".
        target: endpoint приёмника "process.plugin.port" либо
            "display.<display_id>.frame".
        catalog: каталог плагинов (services.plugins).

    Returns:
        WireValidation: ``ok=True`` — wire можно создать (совместимо ИЛИ graceful
        degradation); ``ok=False`` — типы несовместимы (``src_dtype``/``tgt_dtype``
        заполнены для диалога отказа).
    """

    def _find_port_spec(
        plugin_name: str,
        port_name: str,
        direction: str,
    ) -> "PortSpec | None":
        """Найти PortSpec по имени плагина, порта и направлению."""
        spec = catalog.resolve(plugin_name)
        if spec is None:
            return None
        for ps in spec.ports:
            if ps.name == port_name and ps.direction == direction:
                return ps
        return None

    def _portspec_to_port(ps: "PortSpec") -> Port:
        """Сконструировать framework Port из domain PortSpec."""
        return Port(
            name=ps.name,
            dtype=ps.dtype,
            shape=ps.shape,
            optional=ps.optional,
        )

    # Шаг 1: разобрать source endpoint -> (process, plugin, port)
    src_parts = source.split(".")
    if len(src_parts) < 3:
        logger.debug("validate_wire_ports: некорректный source endpoint '%s', пропуск", source)
        return WireValidation(ok=True)

    src_plugin_name = src_parts[1]
    src_port_name = src_parts[2]

    # Шаг 2: найти выходной порт источника через PluginCatalog Protocol
    src_spec = catalog.resolve(src_plugin_name)
    if src_spec is None:
        logger.warning(
            "validate_wire_ports: плагин '%s' не найден в catalog (source=%s), пропуск",
            src_plugin_name,
            source,
        )
        return WireValidation(ok=True)

    out_ps = _find_port_spec(src_plugin_name, src_port_name, "output")
    if out_ps is None:
        logger.warning(
            "validate_wire_ports: выходной порт '%s' не найден у плагина '%s', пропуск",
            src_port_name,
            src_plugin_name,
        )
        return WireValidation(ok=True)

    out_port = _portspec_to_port(out_ps)

    # Шаг 3: определить входной порт приёмника
    tgt_parts = target.split(".")
    is_display_target = tgt_parts[0] == "display"

    if is_display_target:
        # Display-узел принимает любой image-выход через wildcard
        in_port = Port(name="frame", dtype="image/*", shape="")
    else:
        if len(tgt_parts) < 3:
            logger.debug(
                "validate_wire_ports: некорректный target endpoint '%s', пропуск",
                target,
            )
            return WireValidation(ok=True)

        tgt_plugin_name = tgt_parts[1]
        tgt_port_name = tgt_parts[2]

        tgt_spec = catalog.resolve(tgt_plugin_name)
        if tgt_spec is None:
            logger.warning(
                "validate_wire_ports: плагин '%s' не найден в catalog (target=%s), пропуск",
                tgt_plugin_name,
                target,
            )
            return WireValidation(ok=True)

        in_ps = _find_port_spec(tgt_plugin_name, tgt_port_name, "input")
        if in_ps is None:
            logger.warning(
                "validate_wire_ports: входной порт '%s' не найден у плагина '%s', пропуск",
                tgt_port_name,
                tgt_plugin_name,
            )
            return WireValidation(ok=True)

        in_port = _portspec_to_port(in_ps)

    # Шаг 4: проверить совместимость
    ok = are_ports_compatible(out_port, in_port)
    if not ok:
        logger.warning(
            "Несовместимые порты: %s (%s) -> %s (%s)",
            source,
            out_port.dtype,
            target,
            in_port.dtype,
        )
        return WireValidation(ok=False, src_dtype=out_port.dtype, tgt_dtype=in_port.dtype)

    return WireValidation(ok=True)


__all__ = ["WireValidation", "validate_wire_ports"]
