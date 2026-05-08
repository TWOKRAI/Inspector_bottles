"""ServicesPresenter — бизнес-логика таба сервисов."""
from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from multiprocess_prototype_2.frontend.app_context import AppContext


class ServicesPresenter:
    """Presenter для ServicesTab.

    Определяет какие плагины показывать как "сервисы" и генерирует
    данные для секций SectionedForm.
    """

    # Плагины, которые считаются "сервисами" — отображаются в этом табе
    SERVICE_PLUGINS: dict[str, str] = {
        "camera_service": "Камеры",
        "database": "База данных",
        "robot_control": "Управление роботом",
        "frame_saver": "Сохранение кадров",
    }

    def __init__(self, ctx: "AppContext") -> None:
        self._ctx = ctx

    def get_service_sections(self) -> list[tuple[str, str, list]]:
        """Получить список сервисных секций.

        Returns:
            list[(русский_заголовок, plugin_name, list[FieldInfo])]
            Пустые секции (без registers/fields) НЕ включаются.
        """
        rm = self._ctx.registers_manager()
        registry = self._ctx.plugin_registry()

        sections = []
        for plugin_name, title in self.SERVICE_PLUGINS.items():
            fields = []

            # Проверить что плагин существует в реестре
            if registry:
                entry = registry.get(plugin_name)
                if entry is None:
                    continue

            # Получить поля из RegistersManager
            if rm:
                try:
                    fields = rm.get_fields(plugin_name)
                except Exception:
                    fields = []

            if fields:
                sections.append((title, plugin_name, fields))

        return sections
