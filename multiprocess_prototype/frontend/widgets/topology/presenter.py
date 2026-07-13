"""TopologyPresenter — бизнес-логика Topology Editor.

Центральный MVP-presenter: работает только с данными, никакого GUI.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from multiprocess_framework.modules.process_manager_module.topology.blueprint import (
    ProcessConfig,
    SystemBlueprint,
    Wire,
)
from multiprocess_framework.modules.process_module.plugins.registry import PluginRegistry


class TopologyPresenter:
    """MVP presenter: вся логика работы с SystemBlueprint.

    Не импортирует и не использует PySide6.
    GUI-слой вызывает методы этого класса и получает чистые данные.
    """

    def __init__(self) -> None:
        self._blueprint = SystemBlueprint(name="new_topology", description="")
        self._file_path: Path | None = None

    # ------------------------------------------------------------------ #
    #  Свойства                                                            #
    # ------------------------------------------------------------------ #

    @property
    def blueprint(self) -> SystemBlueprint:
        """Текущий blueprint."""
        return self._blueprint

    @property
    def file_path(self) -> Path | None:
        """Путь к файлу, из которого был загружен blueprint (или None)."""
        return self._file_path

    # ------------------------------------------------------------------ #
    #  CRUD blueprint                                                      #
    # ------------------------------------------------------------------ #

    def new_topology(self, name: str = "new_topology") -> None:
        """Создать пустой blueprint."""
        self._blueprint = SystemBlueprint(name=name, description="")
        self._file_path = None

    def load_from_file(self, path: Path) -> None:
        """Загрузить topology из YAML файла.

        RS-5 (C-4): "Загрузить из файла" раньше обходил домен-валидацию целиком —
        ``model_validate`` проверяет только схему (типы/поля), не граф (цикл/дубли
        имён процессов можно было загрузить и сохранить дальше). Теперь тот же
        валидатор, что и на Save (``check_structure()`` — дубли имён + циклы),
        прогоняется и здесь; на невалидном графе бросает ``RecipeValidationError``
        ДО присвоения ``self._blueprint`` (предыдущий blueprint не подменяется).

        Raises:
            RecipeValidationError: если загруженный граф содержит дубли имён
                процессов или циклы.
        """
        from multiprocess_prototype.recipes.save import validate_recipe_blueprint

        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        blueprint = SystemBlueprint.model_validate(data)
        validate_recipe_blueprint(blueprint.model_dump())
        self._blueprint = blueprint
        self._file_path = path

    def save_to_file(self, path: Path) -> None:
        """Сохранить topology в YAML файл."""
        data = self._blueprint.model_dump(exclude_defaults=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(
                data,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
        self._file_path = path

    # ------------------------------------------------------------------ #
    #  CRUD процессов                                                      #
    # ------------------------------------------------------------------ #

    def add_process(
        self,
        name: str,
        plugins: list[dict] | None = None,
        process_class: str = "",
        priority: str = "normal",
    ) -> None:
        """Добавить процесс в blueprint."""
        proc = ProcessConfig(
            process_name=name,
            plugins=plugins or [],
            process_class=process_class,
            priority=priority,
        )
        self._blueprint.processes.append(proc)

    def remove_process(self, name: str) -> None:
        """Удалить процесс и все связанные wires."""
        self._blueprint.processes = [p for p in self._blueprint.processes if p.process_name != name]
        # Каскадно удалить wires с участием удалённого процесса
        self._blueprint.wires = [
            w
            for w in self._blueprint.wires
            if not w.source.startswith(f"{name}.") and not w.target.startswith(f"{name}.")
        ]

    def get_process_names(self) -> list[str]:
        """Имена всех процессов."""
        return [p.process_name for p in self._blueprint.processes]

    # ------------------------------------------------------------------ #
    #  CRUD wires                                                          #
    # ------------------------------------------------------------------ #

    def add_wire(self, source: str, target: str, description: str = "") -> None:
        """Добавить wire между портами."""
        wire = Wire(source=source, target=target, description=description)
        self._blueprint.wires.append(wire)

    def remove_wire(self, index: int) -> None:
        """Удалить wire по индексу."""
        if 0 <= index < len(self._blueprint.wires):
            self._blueprint.wires.pop(index)

    # ------------------------------------------------------------------ #
    #  Валидация и вспомогательные методы                                  #
    # ------------------------------------------------------------------ #

    def validate(self) -> list[str]:
        """Валидация blueprint через blueprint.check().

        Returns:
            Список ошибок. Пустой список = всё ОК.
        """
        return self._blueprint.check()

    def available_plugins(self) -> list:
        """Список плагинов из PluginRegistry (может быть пустым до discover)."""
        return PluginRegistry.list()

    def get_yaml_preview(self) -> str:
        """YAML-превью текущего blueprint."""
        data = self._blueprint.model_dump(exclude_defaults=True)
        return yaml.dump(
            data,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
