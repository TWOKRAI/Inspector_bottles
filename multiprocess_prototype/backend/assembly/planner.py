"""FullReplacePlanner — стратегия полной замены топологии (diff + commands).

Класс-стратегия: обе половины политики (diff и commands) когерентны в одном
классе, что гарантирует согласованность protected-списка и набора процессов.

**Архитектурный паттерн:** ``BaseManager + ObservableMixin`` (решение владельца
2026-06-07 — единообразие: все компоненты одинаковые, исключений нет).

**Framework-готов:** вся app-специфика (``SystemConfig``-defaults, нормализация)
инъектируется как ``proc_dicts_fn``; planner про неё не знает. Позже рядом
появится ``IncrementalPlanner`` с тем же интерфейсом.

**Контракт сидов (инъекция, не импорт):**
- ``proc_dicts_fn(desired_dict) -> dict[str, dict]`` — «нормализуй + собери»
  (= ``assembler.assemble ∘ normalize``; поставляет прототип в Task 2.2).
  Может бросить ``BlueprintInvalid``.
- ``protected_provider() -> set[str]`` — живые protected-процессы
  (= ``PM._get_protected_names``).
- ``current_provider() -> set[str]`` — живые non-protected имена процессов
  (из ``PM._process_configs`` минус protected).

**Зачем ``current_provider``:** ``_current_topology`` менеджера на первом switch
= ``None`` (boot шёл дорогой A, не через TopologyManager), поэтому «что сносить»
нельзя брать из аргумента ``current`` — иначе первый switch не снесёт
boot-процессы. Источник истины «что живо» = PM (как в дороге B:
``to_replace`` из ``_process_configs``). Это fix-forward.
"""

from __future__ import annotations

from typing import Any, Callable

from multiprocess_framework.modules.base_manager import BaseManager, ObservableMixin


class FullReplacePlanner(BaseManager, ObservableMixin):
    """Стратегия полной замены: diff + commands в одном классе.

    Args:
        proc_dicts_fn: ``(desired_dict) -> {name: proc_dict}`` — валидация +
            сборка (может бросить ``BlueprintInvalid``).
        protected_provider: ``() -> set[str]`` — живые protected-имена.
        current_provider: ``() -> set[str]`` — живые non-protected имена
            (источник истины «что снести», а не ``current`` из аргумента diff).
        manager_name: имя менеджера (дефолт ``"full_replace_planner"``).
        logger: менеджер логирования (ObservableMixin).
        error: менеджер ошибок (ObservableMixin).
        stats: менеджер статистики (ObservableMixin).
    """

    def __init__(
        self,
        proc_dicts_fn: Callable[[dict], dict[str, dict]],
        protected_provider: Callable[[], set[str]],
        current_provider: Callable[[], set[str]],
        *,
        protected_config_provider: Callable[[str], dict | None] | None = None,
        manager_name: str = "full_replace_planner",
        logger: Any = None,
        error: Any = None,
        stats: Any = None,
    ) -> None:
        BaseManager.__init__(self, manager_name)
        ObservableMixin.__init__(
            self,
            managers={"logger": logger, "error": error, "stats": stats},
        )
        self._proc_dicts_fn = proc_dicts_fn
        self._protected_provider = protected_provider
        self._current_provider = current_provider
        # B-2 (RS-3): живой конфиг protected-процесса (для детекции расхождения
        # с новым blueprint). None → детекция выключена (обратная совместимость).
        self._protected_config_provider = protected_config_provider
        # Имена protected-процессов, чей конфиг в новом рецепте отличается от
        # живого. Заполняется в commands(); PM читает через
        # ``_collect_protected_conflicts`` и поднимает в ответ apply + hub.
        self.last_protected_conflicts: list[str] = []

    # -------------------------------------------------------------------------
    # Lifecycle (BaseManager контракт)
    # -------------------------------------------------------------------------

    def initialize(self) -> bool:
        """Инициализация — тривиальная (stateless стратегия)."""
        self.is_initialized = True
        return True

    def shutdown(self) -> bool:
        """Завершение — тривиальное."""
        self.is_initialized = False
        return True

    # -------------------------------------------------------------------------
    # Публичный API — политика
    # -------------------------------------------------------------------------

    def diff(self, current: dict | None, desired: dict) -> dict:
        """Вычислить diff: full-replace ВСЕГДА меняет.

        Debounce / guard от спама — ответственность backend (Task 2.2),
        не plannerа. Planner всегда отвечает ``has_changes: True``.

        Args:
            current: текущая topology dict (может быть None при первом switch).
            desired: желаемая topology dict.

        Returns:
            ``{"has_changes": True}``
        """
        self._log_info(
            f"full-replace diff: current={'есть' if current else 'нет'}, "
            f"desired={len(desired.get('processes', []))} процессов"
        )
        return {"has_changes": True}

    def commands(self, diff_result: dict, desired: dict) -> list[dict]:
        """Сгенерировать 5-фазный список команд для полной замены.

        **Порядок = исполнение** (плоский цикл TopologyManager воспроизводит
        двухфазность boot): stop_all → cleanup → provision → create → start.

        **Фаза stop — bulk:** одна команда ``process.stop_all`` вместо N×``process.stop``
        (паритет stop_many дороги B). Без этого N×timeout (4 проц × 5с = 20с).

        **Валидация ДО эмиссии:** ``proc_dicts_fn`` вызывается первым; если
        blueprint невалиден (``BlueprintInvalid``) — ни одной stop-команды
        не генерируется, exception пробрасывается наверх.

        Args:
            diff_result: результат ``self.diff(...)`` (не используется в
                full-replace, но контракт TopologyManager требует).
            desired: желаемая topology dict.

        Returns:
            Плоский список команд по 5 фазам.

        Raises:
            BlueprintInvalid: если ``proc_dicts_fn`` бросил (невалидный blueprint).
        """
        # 1. Валидация + сборка ДО любой stop-команды
        proc_dicts = self._proc_dicts_fn(desired)

        # 2. Из replace исключаем ТОЛЬКО реальных выживших = live_protected
        #    (процессы, которых switch физически НЕ трогает). B-2/RS-3:
        #    - имя, живущее НЕ-protected, но protected:True в новом рецепте: оно ∈ old
        #      (сносится) и ∈ new (пересоздаётся) → честно пересоздаётся и дальше
        #      живёт protected по новому конфигу (не «снесён и не создан», регресс a);
        #    - имя, protected ТОЛЬКО в новом рецепте (не живое): ∉ live_protected →
        #      ∈ new → создаётся как обычный новый процесс (не «никогда не стартует»,
        #      регресс b).
        live_protected = self._protected_provider()
        old = self._current_provider()  # живые non-protected, не из аргумента

        # B-2: расхождение конфига РЕАЛЬНОГО выжившего (live_protected) с новым
        # рецептом. Такой процесс НЕ рестартится (живёт со старым конфигом) → если
        # новый рецепт задаёт иной конфиг, это «тихий успех» switch'а. Фиксируем громко.
        self.last_protected_conflicts = self._detect_protected_conflicts(proc_dicts, live_protected)

        # Новые = из собранных proc_dicts минус реальные выжившие (live_protected).
        new = [n for n in proc_dicts if n not in live_protected]

        # 3. Собрать команды по 5 фазам
        cmds: list[dict] = []

        # Фаза A: bulk-остановка старых (одна команда, параллельный stop_many)
        if old:
            cmds.append({"cmd": "process.stop_all", "process_names": sorted(old)})

        # Фаза B: cleanup старых
        for name in sorted(old):
            cmds.append({"cmd": "process.cleanup", "process_name": name})

        # Фаза C: provision новых (очереди + SHM)
        for name in new:
            cmds.append(
                {
                    "cmd": "process.provision",
                    "process_name": name,
                    "proc_dict": proc_dicts[name],
                }
            )

        # Фаза D: create новых (экземпляр без старта)
        for name in new:
            cmds.append(
                {
                    "cmd": "process.create",
                    "process_name": name,
                    "proc_dict": proc_dicts[name],
                }
            )

        # Фаза E: start новых
        for name in new:
            cmds.append({"cmd": "process.start", "process_name": name})

        self._log_info(
            f"full-replace commands: {len(cmds)} (stop_all={'1' if old else '0'}, "
            f"old={len(old)}, new={len(new)}, live_protected={len(live_protected)})"
        )
        self._record_metric("planner.commands", len(cmds))

        return cmds

    def _detect_protected_conflicts(self, proc_dicts: dict[str, dict], live_protected: set[str]) -> list[str]:
        """Имена РЕАЛЬНЫХ выживших (live_protected), чей конфиг в новом рецепте разошёлся.

        live_protected НЕ перезапускается при switch (switch их физически не трогает —
        живут со старым конфигом). Если новый blueprint задаёт для такого имени ИНОЙ
        конфиг, изменения молча не применятся — switch выглядел бы «успешным».
        Возвращаем такие имена, чтобы PM поднял их в ответ apply и в ObservabilityHub.

        Считаем ТОЛЬКО по live_protected (не по union с new-blueprint protected): имя,
        впервые ставшее protected в новом рецепте, честно пересоздаётся — расхождения
        у него нет по определению.

        Сравнение apples-to-apples: и живой конфиг (``_process_configs[name]``), и
        ``proc_dicts[name]`` — результат одного ассемблера. Провайдер не задан →
        детекция выключена (пустой список).
        """
        if self._protected_config_provider is None:
            return []
        conflicts: list[str] = []
        for name in sorted(set(proc_dicts) & live_protected):
            live = self._protected_config_provider(name)
            if live is None:
                continue  # нет живого (первый boot протектеда) — нечего сравнивать
            if live != proc_dicts[name]:
                conflicts.append(name)
                self._log_error(
                    f"protected '{name}': конфиг нового рецепта отличается от живого — "
                    f"protected не рестартится, изменения НЕ будут применены (switch не тихо успешен)"
                )
        return conflicts
