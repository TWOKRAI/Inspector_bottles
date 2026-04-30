# -*- coding: utf-8 -*-
"""
Единая реализация outbound GUI-команды: resolve targets → MessageAdapter.command → send_message.

Домен (command_id → targets, каталог args) инжектируется приложением; фреймворк не импортирует прототип.

Расположение в ``core/`` (а не ``application/``), чтобы импорт sender не подтягивал Qt через ``FrontendManager``.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from ..interfaces import IRouterLike, SupportsCommandMessage


class RoutedCommandSender:
    """
    Сборка COMMAND и отправка первому получателю из resolve_targets(command_id).

    См. ADR-058 (DECISIONS.md).
    """

    def __init__(
        self,
        router: IRouterLike,
        message_factory: SupportsCommandMessage,
        resolve_targets: Callable[[str], List[str]],
        get_args_builder: Optional[
            Callable[[str], Optional[Callable[..., Dict[str, Any]]]]
        ] = None,
    ) -> None:
        self._router = router
        self._message_factory = message_factory
        self._resolve_targets = resolve_targets
        self._get_args_builder = get_args_builder

    def send(
        self,
        command_id: str,
        *,
        args: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> bool:
        """
        Отправить команду.

        Если задан get_args_builder и для command_id есть builder, и переданы kwargs —
        args собираются как builder(**kwargs). Иначе используются переданные args (или {}).
        data, если не None, передаётся в message_factory.command (как у MessageAdapter);
        иначе в качестве data используется итоговый args (как в прототипе).
        """
        builder: Optional[Callable[..., Dict[str, Any]]] = None
        if self._get_args_builder is not None:
            builder = self._get_args_builder(command_id)

        if builder is not None and kwargs:
            final_args = builder(**kwargs)
        else:
            final_args = dict(args or {})

        targets = self._resolve_targets(command_id)
        payload = data if data is not None else final_args
        msg = self._message_factory.command(
            targets=targets,
            command=command_id,
            args=final_args,
            data=payload,
        )
        return self._router.send_message(targets[0], msg.to_dict())
