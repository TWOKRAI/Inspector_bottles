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


#: Мета-поля записи плагина: они определяют, КАКОЙ плагин грузится, но в
#: ``ctx.config`` не попадают (их отбрасывает сам рантайм). В каноне держим их
#: отдельно от параметров — смена ``plugin_class`` обязана считаться расхождением,
#: хотя параметры при этом не изменились.
_PLUGIN_META_KEYS = ("plugin_class", "plugin_name", "category")

#: Максимальная глубина спуска голоса по дереву конфига. Реальный proc_dict —
#: единицы уровней; ограничитель стоит не от глубины, а от ЦИКЛА: proc_dict
#: приходит из yaml, а якорь ``&r {k: 1, self: *r}`` даёт самоссылку, на которой
#: рекурсия без предохранителя роняет ``commands()`` изнутри, без перехвата.
#: Дословное сравнение dict'ов цикл переживало — значит предохранитель здесь
#: закрывает поверхность, которой до этой правки не было.
_MAX_VOICE_DEPTH = 12


def _diverged_paths(live: Any, new: Any, prefix: str = "", depth: int = 0) -> list[str]:
    """Пути ключей, по которым два канонических конфига разошлись.

    Нужен не для вердикта (его выносит сравнение целиком), а для ГОЛОСА:
    сообщение «конфиг отличается» без указания ЧЕМ отправляет чинить наугад.
    Именно этот голос назвал третью причину расхождения на живом стенде, которой
    не было видно в разборе на столе.

    Спуск идёт и по dict, и по СПИСКУ (по индексу): плагины лежат списком, и без
    этого главный случай — расхождение внутри плагина — сворачивался в
    бесполезное ``config.plugins``. Порядок устойчив (``sorted``), чтобы
    сообщение не плясало между прогонами.
    """
    if depth >= _MAX_VOICE_DEPTH:
        return [] if live == new else [f"{prefix}… (глубже {_MAX_VOICE_DEPTH})"]
    if isinstance(live, dict) and isinstance(new, dict):
        paths: list[str] = []
        for key in sorted(set(live) | set(new), key=str):
            here = f"{prefix}{key}"
            if key not in live:
                paths.append(f"{here} (только в новом)")
            elif key not in new:
                paths.append(f"{here} (только в живом)")
            else:
                paths.extend(_diverged_paths(live[key], new[key], f"{here}.", depth + 1))
        return paths
    if isinstance(live, list) and isinstance(new, list):
        if len(live) != len(new):
            return [f"{prefix[:-1]} (длина {len(live)} против {len(new)})"]
        paths = []
        for i, (a, b) in enumerate(zip(live, new)):
            paths.extend(_diverged_paths(a, b, f"{prefix[:-1]}[{i}].", depth + 1))
        return paths
    return [] if live == new else [prefix[:-1] if prefix else "<корень>"]


def _canonicalize_plugin_entry(entry: Any) -> Any:
    """Канонизировать ОДНУ запись плагина — ровно так, как её читает рантайм.

    Параметры плагина пишутся двумя способами: плоско (стиль ``base.yaml``) или
    вложенно в ``"config"`` (стиль рецептов), и сборка оставляет обе записи
    рядом. Неоднозначности при этом НЕТ:
    :meth:`PluginOrchestrator._extract_plugin_config` — единственная граница, за
    которой рождается ``ctx.config``, — отбрасывает мета-поля и разворачивает
    вложенный ``config`` ПОВЕРХ плоского. Значит «плоско A, вложенно B» означает
    не противоречие, а «дефолт, перекрытый рецептом», и означает ровно ``B``.

    Поэтому канон берётся у рантайма, а не изобретается здесь: своя копия правила
    разошлась бы с ним на первой же правке, и сравнение начало бы отвечать не про
    ту систему, которая работает. Ревью 2026-08-18 (блокер 1) поймало ровно это:
    выдуманный «сторож противоречия» возвращал ложный конфликт на паре
    «дефолт ассемблера плоско + значение рецепта вложенно», побитово одинаковой в
    рантайме.

    Чистая функция: новый dict, вход не мутируется (``_extract_plugin_config``
    строит свой словарь и во входной ``pdef`` не пишет).
    """
    if not isinstance(entry, dict):
        return entry  # не-dict элемент списка — без изменений
    from multiprocess_framework.modules.process_module.generic.plugin_orchestrator import (
        PluginOrchestrator,
    )

    meta = {k: entry[k] for k in _PLUGIN_META_KEYS if k in entry}
    return {**meta, "config": PluginOrchestrator._extract_plugin_config(entry)}


def _canonicalize_proc_dict_for_comparison(proc_dict: dict) -> dict:
    """Привести proc_dict к канонической форме ТОЛЬКО для сравнения.

    Канонизируется единственно ``proc_dict["config"]["plugins"]`` (если есть
    и это список) — остальные ключи proc_dict сравниваются дословно, как
    раньше. Чистая функция: строит новые dict'ы, ничего не мутирует во
    входе (ни ``proc_dict``, ни вложенные записи плагинов).
    """
    config = proc_dict.get("config")
    if not isinstance(config, dict):
        return proc_dict
    plugins = config.get("plugins")
    if not isinstance(plugins, list):
        return proc_dict
    canonical_plugins = [_canonicalize_plugin_entry(p) for p in plugins]
    return {**proc_dict, "config": {**config, "plugins": canonical_plugins}}


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
            # Сравнение смысла, а не написания: плоская и вложенная запись
            # одного параметра плагина — одно и то же значение (см.
            # _canonicalize_plugin_entry). Дословное сравнение целых dict'ов
            # давало ложный конфликт на КАЖДОМ switch — воспроизведено
            # повторным apply той же топологии (applied=0, конфликты те же).
            if _canonicalize_proc_dict_for_comparison(live) != _canonicalize_proc_dict_for_comparison(proc_dicts[name]):
                conflicts.append(name)
                paths = _diverged_paths(
                    _canonicalize_proc_dict_for_comparison(live),
                    _canonicalize_proc_dict_for_comparison(proc_dicts[name]),
                )
                where = ", ".join(paths[:8]) + (f" и ещё {len(paths) - 8}" if len(paths) > 8 else "")
                self._log_error(
                    f"protected '{name}': конфиг нового рецепта отличается от живого по [{where}] — "
                    f"protected не рестартится, изменения НЕ будут применены (switch не тихо успешен)"
                )
        return conflicts
