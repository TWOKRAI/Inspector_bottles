---
paths:
  - "multiprocess_framework/**/*.py"
  - "Services/**/*.py"
  - "Plugins/**/*.py"
  - "multiprocess_prototype/**/*.py"
---

# Модульное состояние — `global` и модульные словари

## Факт, из которого следует всё остальное

`multiprocessing.set_start_method("spawn")` — [`process_manager_module/platforms/base.py`](../multiprocess_framework/modules/process_manager_module/platforms/base.py).

При **spawn** ребёнок не наследует память родителя: он импортирует модули заново и
получает **свои** модульные переменные, с нуля. Отсюда два следствия, и оба важны:

1. Модульная переменная в этом фреймворке — всегда «одно **на процесс**», никогда «одно на
   систему». Само по себе это не дефект: для владения ресурсом уровня процесса это
   единственная честная форма.
2. То, что зарегистрировали в родителе, **у ребёнка не появится само**. Регистрация из
   composition root родителя в ребёнке отсутствует, и это тихо.

## Белый список: когда модульное состояние законно

- **Ленивый кэш чистой величины на процесс.** Значение одно и то же при любом порядке
   вызова. Пример: [`version.code_version`](../multiprocess_framework/version.py).
- **Владение OS-ресурсом уровня процесса.** Дескриптор, слот `sys.excepthook`, хендл файла.
   Объект-владелец тут не при чём — ресурс принадлежит процессу. Примеры:
   [`log_channel._shared_handlers`](../multiprocess_framework/modules/logger_module/channels/log_channel.py),
   [`error_floor._floors`](../multiprocess_framework/modules/logger_module/core/error_floor.py)
   (два хендла на один путь дают на Windows `WinError 32`).
- **Install-once процессный хук.** `logger_module/core/process_hooks.py::_installed` (приезжает
   веткой `feat/observability-closure`) — откат обязан сверять `is`, иначе снесёт чужой хук молча.
- **Реестр объявлений, наполняемый импортом.**
   [`observability_declarations._DECLARED`](../multiprocess_framework/modules/observability_declarations.py).

## Обязательные условия для каждого такого сайта

- **Явный reset для тестов** (`reset_*`, `forget_*`, `snapshot`/`restore`). Без него тесты
  начинают влиять друг на друга через порядок запуска, и красный приезжает к соседу.
- **Потребитель обязан пережить spawn-разрыв громко.** Если регистрация в ребёнке не
  случилась — падать (образец: `build_collector` в
  [`collector_registry`](../multiprocess_framework/modules/process_module/generic/collector_registry.py)
  отказывает вместо тихого PassThrough) либо иметь безопасный дефолт. Тихий fallback,
  который выглядит как работа, — запрещён.

## Запрещено

- **Ключ кэша по `id()` живого объекта.** `id` переиспользуется после сборки мусора: новый
  объект получает адрес умершего и вместе с ним чужую запись. Прецедент —
  `_PATHS_SECTION_CACHE` в plugins-вкладке (снят 2026-09-03, коммит `a45a1e34`).
- **Модульный кэш, чья запись живёт по времени жизни ОБЪЕКТА, а не процесса.** Владельцем
  должен быть сам объект (вкладка, менеджер), держатель передаётся параметром. Модуль такую
  запись не удалит никогда — это течь по построению.
- **`WeakKeyDictionary` по `AppServices`** как «починка» предыдущего пункта не работает:
  контейнер объявлен `@dataclass(frozen=True, slots=True)`, weakref на него создать нельзя
  (`cannot create weak reference`), а атрибут не навесить из-за `slots`.

## Как проверять

Свойство «модуль состояния не копит» проверяется детерминированно: `weakref.ref` на объект,
явный `del` всех своих ссылок, `gc.collect()`, ассерт `ref() is None`. Образец —
[`test_paths_section_ownership.py`](../multiprocess_prototype/frontend/widgets/tabs/plugins/tests/test_paths_section_ownership.py).
Тест на утечку без инъекции не доказан: заплата, возвращающая модульный держатель, обязана
его покраснить.
