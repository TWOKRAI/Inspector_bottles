# multiprocess_prototype/frontend/commands/gui_command_handler.py
"""
GuiCommandHandler — единый слой отправки GUI-команд.

Каталог payload: ``registers.gui_command_catalog``; targets — ``registers.command_routing``.

Цепочка: process.send_message(target, msg) → ProcessCommunication.send_to_process
→ RouterManager.queue_registry.send_to_queue. MessageAdapter формирует формат command.
"""

from typing import Any, Dict, Optional

from multiprocess_prototype.registers.command_routing import resolve_command_targets
from multiprocess_prototype.registers.gui_command_catalog import GUI_COMMAND_CATALOG


class GuiCommandHandler:
    """
    Обработчик GUI-команд. Отправляет команды через process.

    Callbacks для виджетов получают методы execute(command_id, **kwargs).
    """

    def __init__(self, process: Any):
        """
        Args:
            process: GuiProcess / ProcessModule с send_message, _msg.
        """
        self._process = process

    def _send(
        self,
        command: str,
        args: Dict[str, Any],
        data: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Отправить команду через process (targets из command_routing)."""
        targets = resolve_command_targets(command)
        payload = data if data is not None else args
        msg = self._process._msg.command(
            targets=targets,
            command=command,
            args=args,
            data=payload,
        )
        return self._process.send_message(targets[0], msg.to_dict())

    def execute(self, command_id: str, **kwargs: Any) -> bool:
        """
        Выполнить команду по каталогу.

        Args:
            command_id: Ключ из GUI_COMMAND_CATALOG.
            **kwargs: Аргументы для args_builder.

        Returns:
            True если отправка успешна.
        """
        args_builder = GUI_COMMAND_CATALOG.get(command_id)
        if not args_builder:
            return False
        args = args_builder(**kwargs)
        return self._send(command_id, args)

    # --- Удобные методы для callbacks ---

    def send_start_capture(self) -> bool:
        return self.execute("start_capture")

    def send_stop_capture(self) -> bool:
        return self.execute("stop_capture")

    def send_set_fps(self, fps: int) -> bool:
        return self.execute("set_fps", fps=fps)

    def send_set_color_range(
        self, b_l: int, g_l: int, r_l: int, b_u: int, g_u: int, r_u: int
    ) -> bool:
        return self.execute(
            "set_color_range",
            b_l=b_l, g_l=g_l, r_l=r_l,
            b_u=b_u, g_u=g_u, r_u=r_u,
        )

    def send_set_min_area(self, min_area: int) -> bool:
        return self.execute("set_min_area", min_area=min_area)

    def send_set_max_area(self, max_area: int) -> bool:
        return self.execute("set_max_area", max_area=max_area)

    def send_set_show_original(self, show: bool) -> bool:
        return self.execute("set_show_original", show=show)

    def send_set_show_mask(self, show: bool) -> bool:
        return self.execute("set_show_mask", show=show)

    def send_set_draw_contours(self, draw: bool) -> bool:
        return self.execute("set_draw_contours", draw=draw)

    def send_enum_devices(self) -> bool:
        return self.execute("enum_devices")

    def send_open_camera(self, camera_index: int = 0) -> bool:
        return self.execute("open", camera_index=camera_index)

    def send_close_camera(self) -> bool:
        return self.execute("close")

    def send_start_grabbing(self) -> bool:
        return self.execute("start_grabbing")

    def send_stop_grabbing(self) -> bool:
        return self.execute("stop_grabbing")

    def send_get_parameters(self) -> bool:
        return self.execute("get_parameters")

    def send_set_parameters(self, frame_rate: float, exposure_time: float, gain: float) -> bool:
        return self.execute(
            "set_parameters",
            frame_rate=frame_rate,
            exposure_time=exposure_time,
            gain=gain,
        )

    def send_camera_type_changed(self, camera_type: str) -> bool:
        return self.execute("set_camera_type", camera_type=camera_type)
