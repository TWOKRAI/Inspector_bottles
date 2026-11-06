# map-E2 signboard — отчёт разработчика (2026-11-06)

Полный отчёт. Короткая версия — в финальном сообщении. Файлы: `scripts/arch_map/signboard.py`, `scripts/arch_map/tests/test_signboard.py`,
`scripts/arch_map/SIGNBOARD.md`, `docs/arch-map/_bench/k0_targets.json`, `k0_reference.json`, `docs/arch-map/cards.html`.

## Проверки

- `pytest scripts/arch_map/tests/test_signboard.py`: 16 passed (10 заданных REDS + 6 своих: dump/schedule, откат файла-теста, метод без импорта, красная карточка слоя, район, exit 2).
- Инъекция 1 (дандеры считаются приватными): предсказано test_protocol_dunder_member_kept; получено 1 failed — он же.
- Инъекция 2 (`is_abstract` всегда False): предсказано test_abstractmethod_flag, test_structural_match_not_subclass, test_cli_show_on_fixture; получено те же три.
- После отката файла: 15 passed (тогда было 15 тестов).

## Покрытие 7 недостающих полей K0

Полностью: сигнатуры (включая `__init__`, у dataclass — по полям), abstractmethod-флаг, первый абзац, дандеры Protocol.
Частично: кто наследует и структурные двойники (прямые, по имени; двойники Protocol из одного `__call__` шумны),
тесты как nodeid (файл целиком, если test-функция не упоминает имя), вызовы по имени (интерфейсы дают 0).

## show --format text

### IConfigObserver
```
[house] IConfigObserver
Protocol — Протокол подписчика на изменения конфигурации
использует меня 0 (вызовы по имени) / использую 0

Сигнатура:
  IConfigObserver   (__init__: none)

Докстринг:
  Протокол подписчика на изменения конфигурации.

Базы:
  Protocol

Члены (1):
  __call__(self, key: str, old_value: Any, new_value: Any) -> None

Наследники по имени базы (0):
  нет

Структурно подходят, не наследуют (8):
  _TransportProbe  Services/otel_export/exporter.py:129
  Check  scripts/docs_verify/docs_check.py:107
  _Release  multiprocess_framework/modules/event_module/subscribers.py:54
  Arrivals  backend_ctl/probes/probe_observability_consumer_acceptance.py:331
  RateSampler  multiprocess_framework/modules/logger_module/core/sampling.py:121

Вызовы по имени: 0 (+0 в файле); 0 — не «не используется»:
  не найдено по имени

Тесты (1):
  multiprocess_framework/modules/config_module/tests/test_iconfig_contract.py::test_iconfig_observer_protocol_and_subscribe_passes_key_old_new
```

### IConfigManager
```
[house] IConfigManager
ABC — Контракт менеджера конфигураций
использует меня 0 (вызовы по имени) / использую 1

Сигнатура:
  IConfigManager   (__init__: none)

Докстринг:
  Контракт менеджера конфигураций.

Базы:
  IBaseManager, ABC

Члены (7):
  [abstract] create_config(self, name: str, initial_data: Optional[Dict[str, Any]]=None, validation_schema: Optional[Any]=None, env_prefix: Optional[str]=None) -> IConfig
  [abstract] get_config(self, name: str) -> Optional[IConfig]
  [abstract] remove_config(self, name: str) -> bool
  [abstract] list_configs(self) -> List[str]
  [abstract] has_config(self, name: str) -> bool
  [abstract] sync_config(self, name: str) -> bool
  [abstract] load_config_from_storage(self, name: str) -> bool

Унаследовано (10):
  IBaseManager: [abstract] initialize(self) -> bool
  IBaseManager: [abstract] shutdown(self) -> bool
  IBaseManager: [abstract] scope(self) -> IScope | None
  IBaseManager: [abstract] attach_adapter(self, adapter: Any, name: Optional[str]=None) -> bool
  IBaseManager: [abstract] get_adapter(self, name: Optional[str]=None) -> Optional[Any]
  IBaseManager: [abstract] has_adapter(self, name: str) -> bool
  IBaseManager: [abstract] list_adapters(self) -> List[str]
  IBaseManager: [abstract] detach_adapter(self, name: str) -> bool
  IBaseManager: [abstract] get_stats(self) -> Dict[str, Any]
  IBaseManager: [abstract] get_debug_info(self) -> Dict[str, Any]

Наследники по имени базы (1):
  ConfigManager  multiprocess_framework/modules/config_module/core/config_manager.py:29

Структурно подходят, не наследуют (0):
  нет

Вызовы по имени: 0 (+0 в файле); 0 — не «не используется»:
  не найдено по имени

Тесты (1):
  multiprocess_framework/modules/config_module/tests/test_iconfig_manager_contract.py::test_iconfig_manager_abstract_set_has_7_own_and_10_inherited_names
```

## Что понял по-своему

- «observability companion writer» — функция `write_companion` в `observability_companion.py`; `observability_reload.py` — цель-файл (карточка района, 31 дом).
- `collect_imports` из build.py теряет `as`-имена, поэтому импорты разбираю своим обходом `ast`; из build.py взяты `class_style`, `leaf_name`, `resolve_relative`, `is_test_path`, `layer_of` и константы слоёв.
- Подпись `можно → …; нельзя ← …` читаю так: что узел может импортировать / откуда не может.
- Каталоги `data` и `plans` исключены из индекса: в `data` 12 267 `.py`, первый запуск шёл больше двух минут.

## Что оставил открытым / ненадёжно

- Структурные двойники и наследники — по имени, без транзитивных баз и без разрешения повторного экспорта.
- Вызовы по имени не видят динамику; метод ищется по имени атрибута в файлах, импортирующих класс (чужие одноимённые методы дают ложные срабатывания).
- Файл `robot/universal3/neuroun_2805_big.py` не разбирается (ошибка в stderr), в индекс не вошёл.
- Адаптивность страницы проверена только скриншотом Edge шириной 500 px (меньше окно не ставится); реального телефона и hover мышью нет — hover/focus проверены чтением кода, закреплённая карточка — через `#card=`.
- В `cards.html` только `config_module` раскрыт до домов; остальные юниты — карточки без спуска.
- ruff format переписал `signboard.py` (много строк); `fmt: skip` местами.
