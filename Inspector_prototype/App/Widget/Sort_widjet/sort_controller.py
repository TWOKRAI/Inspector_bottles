# -*- coding: utf-8 -*-
"""
SortController — контроллер виджета сортов/рецептов.

Ответственность:
  - Владение ParamsManager (сбор параметров из виджетов, YAML-хранилище)
  - Обработка сигналов SortWidget (applied / saved / default)
  - Применение рецепта: ParamsManager → RegistersManager → observer → RouterManager (IPC)
  - Автоматическое резервное сохранение по таймеру

Иерархия:
  SortController
    ├── SortWidget      — только отображение и ввод пользователя
    ├── ParamsManager   — сбор параметров из виджетов и YAML-хранилище
    └── RegistersManager — единый источник состояния регистров

  После apply_recipe():
    ParamsManager.apply_recipe()
      → widget.apply_params()            (виджеты обновляют UI)
      → RegistersManager.set_field_value() (обновляет Pydantic-регистры)
        → observer → WindowManager.send_register_update()  (IPC в бэкенд)
"""
from typing import Any, Optional

from PyQt5.QtCore import QObject, QTimer

from App.Core.Managers.params_manager import ParamsManager
from App.Widget.Sort_widjet.sort_data import SortData


class SortController(QObject):
    """
    Контроллер для SortWidget: связывает UI-виджет с бизнес-логикой рецептов.

    Не содержит Qt-виджетов — только логику и данные.
    Создаётся в MainWindow._startup() после того как все виджеты собраны.

    Args:
        sort_widget:      экземпляр SortWidget (UI)
        sort_data:        экземпляр SortData (YAML-хранилище)
        registers_manager: RegistersManager (единый источник состояния)
        window_manager:   WindowManager (для доступа к reset_count и автосохранению)
        extra_widgets:    словарь {name: widget} дополнительных виджетов с get_params/apply_params
    """

    def __init__(
        self,
        sort_widget,
        sort_data: SortData,
        registers_manager,
        window_manager=None,
        extra_widgets: Optional[dict] = None,
    ) -> None:
        super().__init__()

        self._sort_widget = sort_widget
        self._sort_data = sort_data
        self._registers_manager = registers_manager
        self._wm = window_manager

        # ParamsManager собирает параметры из всех переданных виджетов
        widgets_dict = {"sort_widget": sort_widget}
        if extra_widgets:
            widgets_dict.update(extra_widgets)
        self._params_manager = ParamsManager(widgets_dict, sort_data)

        # Загружаем текущий рецепт при старте
        self._load_initial_recipe()

        # Подключаем сигналы виджета к методам контроллера
        self._connect_signals()

        # Таймер автоматического резервного сохранения (каждые 5 секунд)
        self._backup_timer = QTimer(self)
        self._backup_timer.timeout.connect(self._auto_save_backup)
        self._backup_timer.start(5_000)

    # ------------------------------------------------------------------
    # Инициализация
    # ------------------------------------------------------------------

    def _load_initial_recipe(self) -> None:
        """Применить текущий рецепт при запуске приложения."""
        try:
            current = self._sort_data.get_current_recipe_number()
            self._params_manager.apply_recipe(
                current if current is not None else "default_value"
            )
        except Exception as e:
            print(f"[SortController] Ошибка загрузки рецепта при старте: {e}")

    def _connect_signals(self) -> None:
        """Подключить сигналы SortWidget к методам этого контроллера."""
        self._sort_widget.applied.connect(self.apply_recipe)
        self._sort_widget.saved.connect(self.save_recipe)
        self._sort_widget.default.connect(self.set_default_recipe)

    # ------------------------------------------------------------------
    # Публичный API — вызывается из MainWindow и SortWidget
    # ------------------------------------------------------------------

    def apply_recipe(self, number: Any) -> None:
        """Применить рецепт №number ко всем виджетам.

        Поток данных:
          ParamsManager.apply_recipe()
            → widget.apply_params()           (обновляет UI-виджеты)
            → (observer RegistersManager)     (если виджеты пишут в регистры)
              → WindowManager.send_register_update()  (IPC в бэкенд)
        """
        self._params_manager.apply_recipe(number)
        # Принудительно обновляем таблицу параметров
        if hasattr(self._sort_widget, "refresh_table"):
            self._sort_widget.refresh_table()

    def save_recipe(self, number: Any) -> None:
        """Сохранить текущие значения виджетов в рецепт №number."""
        self._params_manager.save_recipe(number)
        if hasattr(self._sort_widget, "refresh_table"):
            self._sort_widget.refresh_table()

    def set_default_recipe(self, number: Any) -> None:
        """Загрузить дефолтный рецепт в виджеты (игнорирует номер, берёт default_value)."""
        self._params_manager.set_default_recipe(number)

    def get_all_params(self) -> dict:
        """Вернуть текущие параметры всех виджетов (используется SortWidget для live-обновления таблицы)."""
        return self._params_manager.get_all_params()

    def reset_count(self) -> None:
        """Сбросить счётчик — отправить событие в бэкенд через queue_manager."""
        qm = getattr(self._wm, "queue_manager", None)
        if qm and hasattr(qm, "reset_count"):
            qm.reset_count.set()

    # ------------------------------------------------------------------
    # Автосохранение
    # ------------------------------------------------------------------

    def _auto_save_backup(self) -> None:
        """Периодическое резервное сохранение состояния (каждые 5 секунд)."""
        try:
            # Сохраняем DataManager если доступен через window_manager
            data_manager = getattr(self._wm, "_data_manager_ref", None)
            if data_manager and hasattr(data_manager, "save_to_recipe"):
                data_manager.save_to_recipe("backup")
            self._params_manager.save_to_excel("backup")
        except Exception:
            pass
