# -*- coding: utf-8 -*-
"""
Слоистое владение конфигом наблюдаемости (Task 5.12).

Четыре источника одной секции ``observability``, от общего к частному:

===== ==================================== =========================================
Слой  Где живёт                            На какой вопрос отвечает
===== ==================================== =========================================
L0    код — :class:`ObservabilityConfig`   «как правильно вообще»
L1    ``system.yaml observability:``       «что верно на ЭТОЙ машине при любом рецепте»
L2    рецепт (+ спутник) ``observability:`` «что верно для ЭТОГО конвейера»
L3    память процесса                      «что кручу руками прямо сейчас»
===== ==================================== =========================================

Отсутствие ключа на слое = наследование снизу. Резолв — ``L1 → L2 → L3``;
L0 подставляется НЕ здесь, а :func:`~.observability_config.expand_observability`
(валидация Pydantic-дефолтами). Это намеренно: единственная точка раскладки —
якорь ADR-CRM-006, и резолвер стоит **над** expand, а не внутри и не рядом.

**Provenance считается по СЫРЫМ секциям слоёв — до expand.** После раскладки
ключ из L0 неотличим от заданного явно: ``_toggled_logger_channels`` и профиль
уровня материализуют дефолты в полноценные словари. Спросить «почему у меня
INFO» у раскрытого конфига уже нельзя — поэтому ответ вычисляется один раз,
здесь, пока слои ещё различимы.

Форма L2 в рецепте (``defaults`` + per-process, per-process побеждает)::

    observability:
      defaults:
        log_level: INFO
        scopes: {DEBUG: {enabled: false}}
      processes:
        camera_0:
          channels: {module_trace: {enabled: false}}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from ...data_schema_module import deep_merge

# Имена слоёв — они же значения поля ``source`` в ответе introspect.observability.
LAYER_FRAMEWORK = "framework"
LAYER_APP = "app"
LAYER_RECIPE = "recipe"
LAYER_SESSION = "session"

#: Порядок применения: каждый следующий побеждает предыдущий.
LAYER_ORDER: Tuple[str, ...] = (LAYER_FRAMEWORK, LAYER_APP, LAYER_RECIPE, LAYER_SESSION)

#: Ключ, под которым сырая L2-дельта процесса едет в ``proc_dict["config"]``
#: (точный аналог ``telemetry_override``, см. assembler прототипа).
OVERRIDE_CONFIG_KEY = "observability_override"

#: Ключ сырой L1-секции в ``proc_dict["config"]``. Нужен ДО первого reload:
#: без него процесс не знает, какие ключи пришли из ``system.yaml``, и
#: provenance приписал бы их фреймворку — то есть соврал бы.
APP_CONFIG_KEY = "observability_app"

#: Ключ с путём к активному рецепту — адрес слоя L2 (рецепт + спутник рядом).
RECIPE_PATH_CONFIG_KEY = "observability_recipe_path"

#: Атрибут, под которым стек живёт на объекте процесса.
LAYERS_ATTR = "_observability_layers"


def resolve_recipe_section(section: Any, process_name: str) -> Dict[str, Any]:
    """Сырая L2-дельта КОНКРЕТНОГО процесса из секции рецепта.

    ``defaults`` применяется всем процессам рецепта, ``processes[<имя>]``
    мержится поверх. Процесс, не названный в ``processes``, получает только
    ``defaults`` — и правка соседа его не задевает.

    Секция без ``defaults``/``processes`` трактуется как ``defaults`` целиком:
    короткая форма для рецепта, у которого все процессы настроены одинаково.

    Returns:
        Сырой dict (возможно пустой) — форма секции ``observability`` процесса.
    """
    if not isinstance(section, dict) or not section:
        return {}
    if "defaults" not in section and "processes" not in section:
        return dict(section)
    defaults = section.get("defaults") or {}
    per_process = (section.get("processes") or {}).get(process_name) or {}
    if not isinstance(defaults, dict):
        defaults = {}
    if not isinstance(per_process, dict):
        per_process = {}
    return deep_merge(defaults, per_process)


@dataclass
class ObservabilityLayers:
    """Стек сырых секций наблюдаемости одного процесса.

    Хранит ИСТОЧНИКИ, а не результат: резолв (:meth:`resolve`) и объяснение
    (:meth:`provenance`) вычисляются от них каждый раз. Именно это делает
    возможной пересборку конфига вместо дельты поверх живого — удаление ключа
    из слоя в дельте невыразимо, а в пересборке выражается само собой.

    Attributes:
        app: L1 — секция ``observability`` из ``system.yaml`` (сырая).
        recipe: L2 — уже разрешённая для ЭТОГО процесса дельта рецепта
            (см. :func:`resolve_recipe_section`).
        session: L3 — рантайм-правки оператора (``logger.sink.disable``,
            ``config.reload`` с ``persist=False``).
        app_source / recipe_source: файлы, давшие L1/L2 — наружу отдаётся
            КОНКРЕТНЫЙ файл, а не абстрактное имя слоя (иначе при паре
            «рецепт + спутник» оператор не знает, какой из двух править).
    """

    app: Dict[str, Any] = field(default_factory=dict)
    recipe: Dict[str, Any] = field(default_factory=dict)
    session: Dict[str, Any] = field(default_factory=dict)
    app_source: str = ""
    recipe_source: str = ""

    def resolve(self) -> Dict[str, Any]:
        """Сырая секция ``observability`` после наложения L1 → L2 → L3."""
        merged = deep_merge(self.app or {}, self.recipe or {})
        return deep_merge(merged, self.session or {})

    def raw_layers(self) -> Tuple[Tuple[str, Dict[str, Any], str], ...]:
        """``(имя слоя, сырая секция, источник)`` в порядке применения."""
        return (
            (LAYER_APP, self.app or {}, self.app_source),
            (LAYER_RECIPE, self.recipe or {}, self.recipe_source),
            (LAYER_SESSION, self.session or {}, LAYER_SESSION),
        )

    # ---------------------------------------------------------------- L3

    def session_set(self, path: str, value: Any) -> None:
        """Записать ключ в L3 (``"channels.messages_file.enabled"``)."""
        node = self.session
        parts = path.split(".")
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[parts[-1]] = value

    def session_reset(self, path: str) -> bool:
        """Удалить ключ из L3 — записать ОТСУТСТВИЕ, а не текущее значение.

        Присвоение значения дефолта порвало бы связь с ним навсегда: поменяется
        L0/L1 — сессия продолжит держать старое число. Поэтому сброс именно
        удаляет, и действующее значение после него едет за нижним слоем.

        Returns:
            True, если ключ был и удалён; False — если его не было.
        """
        parts = path.split(".")
        stack = [self.session]
        node: Any = self.session
        for part in parts[:-1]:
            node = node.get(part) if isinstance(node, dict) else None
            if not isinstance(node, dict):
                return False
            stack.append(node)
        if not isinstance(node, dict) or parts[-1] not in node:
            return False
        del node[parts[-1]]
        # Подчистить опустевшие ветки: иначе `session` перестаёт быть честным
        # ответом на «что держится сессией» — {"channels": {"a": {}}} читается
        # как «канал a чем-то управляется», хотя не управляется ничем.
        for parent, part in zip(reversed(stack[:-1]), reversed(parts[:-1])):
            child = parent.get(part)
            if isinstance(child, dict) and not child:
                del parent[part]
            else:
                break
        return True

    def session_keys(self) -> Tuple[str, ...]:
        """Плоский список ключей, которые сейчас держит L3 (для ответа команды)."""
        return tuple(sorted(flatten_section(self.session or {}).keys()))

    def session_clear(self) -> Tuple[str, ...]:
        """Сбросить L3 целиком, вернув перечень сброшенных ключей."""
        keys = self.session_keys()
        self.session = {}
        return keys

    # -------------------------------------------------------- provenance

    def provenance(self, expanded_logger: Optional[Mapping[str, Any]] = None) -> Dict[str, Dict[str, str]]:
        """Слой-победитель для каждого действующего ключа секции.

        Args:
            expanded_logger: секция ``logger`` из :func:`expand_observability`
                (нужна, чтобы назвать слой у МАТЕРИАЛИЗОВАННЫХ ``channels``/
                ``scopes``: их имена появляются только после раскладки).

        Returns:
            ``{ключ: {"layer": ..., "source": ...}}``. Ключи — в сыром
            namespace секции (``log_level``, ``errors.level``,
            ``channels.<имя>.enabled``), потому что править оператор будет
            именно их, а не имена полей manager-конфига.
        """
        explicit: Dict[str, Tuple[str, str]] = {}
        for layer, section, source in self.raw_layers():
            for key in flatten_section(section):
                explicit[key] = (layer, source or layer)

        out: Dict[str, Dict[str, str]] = {}

        # 1. Все поля схемы: явно заданное — со своего слоя, остальное — L0.
        for key in _schema_keys():
            layer, source = explicit.get(key, (LAYER_FRAMEWORK, LAYER_FRAMEWORK))
            out[key] = {"layer": layer, "source": source}

        # 2. Явные ключи вне плоского набора схемы (channels.*/scopes.* задают
        #    произвольные имена) — их слой известен точно.
        for key, (layer, source) in explicit.items():
            out[key] = {"layer": layer, "source": source}

        # 3. Материализованные ключи: имя канала/скоупа появилось из дефолта L0,
        #    но управляет им тот слой, который тронул породившую ручку.
        if expanded_logger:
            out.update(self._materialized_provenance(expanded_logger, explicit, out))
        return out

    def _materialized_provenance(
        self,
        expanded_logger: Mapping[str, Any],
        explicit: Mapping[str, Tuple[str, str]],
        already: Mapping[str, Dict[str, str]],
    ) -> Dict[str, Dict[str, str]]:
        """Слой у ключей, которых в сырых секциях нет — их материализовал expand."""
        out: Dict[str, Dict[str, str]] = {}

        channels = expanded_logger.get("channels")
        if isinstance(channels, dict):
            for name, body in channels.items():
                if not isinstance(body, dict):
                    continue
                for field_name in body:
                    key = f"channels.{name}.{field_name}"
                    if key in explicit:
                        continue
                    # `enabled` каналов рождается оптовым тогглом console/file;
                    # остальные поля канала — чистый дефолт L0.
                    toggle = _channel_toggle(str(body.get("type", "")))
                    if field_name == "enabled" and toggle and toggle in explicit:
                        layer, source = explicit[toggle]
                    else:
                        layer, source = LAYER_FRAMEWORK, LAYER_FRAMEWORK
                    out[key] = {"layer": layer, "source": source}

        scopes = expanded_logger.get("scopes")
        if isinstance(scopes, dict):
            level_owner = explicit.get("log_level")
            for name, body in scopes.items():
                if not isinstance(body, dict):
                    continue
                for field_name in body:
                    key = f"scopes.{name}.{field_name}"
                    if key in explicit or key in out:
                        continue
                    if level_owner is not None:
                        layer, source = level_owner
                    else:
                        layer, source = LAYER_FRAMEWORK, LAYER_FRAMEWORK
                    out[key] = {"layer": layer, "source": source}

        # Уже объяснённое явными ключами не переписываем.
        return {k: v for k, v in out.items() if k not in explicit and k not in already}


def process_observability_layers(svc: Any) -> ObservabilityLayers:
    """Стек слоёв ЭТОГО процесса — один на процесс, создаётся лениво.

    L1/L2 приезжают в ``proc_dict["config"]`` (ассемблер), L3 рождается пустым и
    живёт до конца процесса. Кэш на объекте процесса, а не пересборка на каждый
    вызов: L3 — это состояние, и пересоздавать его значило бы терять ручку
    оператора при каждой команде.

    Процесс без обоих ключей (тесты, одиночный запуск) получает пустой стек —
    работоспособный, просто без объяснимого происхождения ключей.
    """
    existing = getattr(svc, LAYERS_ATTR, None)
    if isinstance(existing, ObservabilityLayers):
        return existing

    get_config = getattr(svc, "get_config", None)
    app: Dict[str, Any] = {}
    recipe: Dict[str, Any] = {}
    app_source = ""
    recipe_source = ""
    if callable(get_config):
        app = get_config(APP_CONFIG_KEY) or {}
        recipe = get_config(OVERRIDE_CONFIG_KEY) or {}
        app_source = str(get_config("observability_config_path") or "")
        recipe_source = str(get_config(RECIPE_PATH_CONFIG_KEY) or "")
    layers = ObservabilityLayers(
        app=dict(app) if isinstance(app, dict) else {},
        recipe=dict(recipe) if isinstance(recipe, dict) else {},
        app_source=app_source,
        recipe_source=recipe_source,
    )
    try:
        setattr(svc, LAYERS_ATTR, layers)
    except Exception:  # noqa: BLE001 — объект без сеттеров: работаем без кэша, но работаем
        pass
    return layers


def _channel_toggle(channel_type: str) -> str:
    """Какая оптовая ручка секции управляет ``enabled`` канала этого типа."""
    if channel_type == "console":
        return "console"
    if channel_type == "file":
        return "file"
    return ""


def flatten_section(section: Any, prefix: str = "") -> Dict[str, Any]:
    """Вложенный dict → ``{"a.b.c": значение}`` по листьям.

    Пустой dict — тоже лист: ``{"scopes": {}}`` даёт ключ ``scopes``. Иначе
    «слой задал пустую карту» и «слой не сказал ничего» стали бы неотличимы.
    """
    out: Dict[str, Any] = {}
    if not isinstance(section, dict):
        return out
    for key, value in section.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict) and value:
            out.update(flatten_section(value, prefix=f"{path}."))
        else:
            out[path] = value
    return out


def _schema_keys() -> Iterable[str]:
    """Плоские ключи всех полей :class:`ObservabilityConfig` с дефолтами.

    Ленивый импорт: модуль слоёв не должен тянуть схему на импорт-тайме
    (её тянет expand, а слои стоят НАД ним).
    """
    from .observability_config import ObservabilityConfig

    dumped = ObservabilityConfig().model_dump()
    # channels/scopes у дефолта пусты: имён у них ещё нет, они появятся после
    # expand — и объясняются отдельной веткой (_materialized_provenance).
    dumped.pop("channels", None)
    dumped.pop("scopes", None)
    return flatten_section(dumped).keys()
