# Арх-ревью 04: библиотеки и инструменты, состояние на 2026-11-22

Метод: прямые загрузки страниц PyPI (HTML и JSON API), GitHub, docs OpenTelemetry и Rerun. Результаты поиска использовались только как наводка. Там, где поиск дал версию, которую не подтвердила загрузка страницы, я это отмечаю. Даты релизов — из PyPI (`Released` / `upload_time`), если не указано иное.

Метки: active = релиз за последние ~3 месяца; slow = релиз 3–12 месяцев назад; stale = больше года или явный статус pre-alpha/archived; abandoned = не нашёл признаков поддержки (не подтверждено ни для одной библиотеки ниже, кроме явного указания).

## Сводка

| Библиотека | Последний релиз (дата) | Метка | Ключевой вывод |
|---|---|---|---|
| msgspec | 0.22.0 (2026-09-29) | active | есть wheel cp314t и cp315t, wheel cp313t не виден |
| OpenTelemetry Python SDK | 1.45.2 (2026-10-29) | active | logs в Python — Development, не stable |
| structlog | 26.1.0 (2026-06-06) | active | Production/Stable по classifier |
| pydantic | 2.14.4 (2026-11-19) | active | |
| pydantic-settings | 2.16.3 (2026-11-13) | active | |
| OmegaConf | 2.4.0 стабильный (2026-10-09) | active | 2.4.1rc2 pre-release (2026-10-28) |
| Hydra (hydra-core) | 1.3.8 (2026-10-25) | active | classifier «4 - Beta», Python-classifiers до 3.11; 1.4.0rc3 pre-release |
| rerun-sdk | 0.43.2 (2026-11-13 по GitHub) | active | Python >=3.11 |
| NodeGraphQt (upstream) | 0.6.44 (2026-02-04) | slow | PySide6 в загруженных страницах не подтверждён |
| OdenGraphQt (fork) | 0.7.4 (2024-04-02) | stale | заявлена совместимость с PySide6 |
| nodegraphqt-quiltix-fork | 0.7.0 (2024-05-24) | stale | |
| ryvencore-qt | 0.5.0 (2024-05-20) | stale | PySide2, PySide6 «untested» |
| qtpynodeeditor | 0.3.3 (2024-12-15) | stale | classifier «2 - Pre-Alpha» |
| casty | 0.31.7 (2026-11-08) | active | classifier «3 - Alpha» |
| reaktiv | 0.25.0 (2026-11-15) | active | сигналы, Qt-моста не найдено |

## 1. msgspec

- Последняя версия 0.22.0, `Released: Sep 29, 2026`. Источник: https://pypi.org/project/msgspec/ (загружено 2026-11-22). `requires_python` = `>=3.10`: https://pypi.org/pypi/msgspec/json. Метка: active.
- Free-threaded: в списке файлов страницы PyPI есть `msgspec-0.22.0-cp314-cp314t-win_arm64.whl` и `msgspec-0.22.0-cp315-cp315t-win_amd64.whl`. Wheel `cp313t` на видимой части страницы не найден. Classifier про free-threading нет. Источник: https://pypi.org/project/msgspec/.
- История версий через JSON API обрезана, поэтому даты предыдущих релизов не подтверждены. Поисковый сниппет про 0.20.0 (ноябрь 2025) устарел относительно 0.22.0 и не использовался как факт.
- Windows: win_amd64 wheel для cp315t подтверждён; для cp313/cp314 на Windows полный список не проверял (не проверено).

## 2. OpenTelemetry Python vs structlog vs stdlib

Статус logs:
- Python README, таблица: Traces — Stable, Metrics — Stable, Logs — Development. Цитата: «We are working on stabilizing the Log signal which would require making deprecations and breaking changes.» Источник: https://raw.githubusercontent.com/open-telemetry/opentelemetry-python/main/README.md (загружено 2026-11-22; дата коммита не указана).
- Спецификация OTel: Logs Bridge API, SDK и Protocol — stable. Источник: https://opentelemetry.io/docs/specs/status/ (даты на странице нет). Stable на уровне спецификации не означает stable в Python-реализации.
- Пакет opentelemetry-sdk: 1.45.2, `Released: Oct 29, 2026`, classifier «5 - Production/Stable». Источник: https://pypi.org/project/opentelemetry-sdk/. Этот classifier относится ко всему пакету и противоречит статусу logs в README; я считаю README точнее для logs.

Локальный режим без collector:
- Страница docs Python SDK по exporters называет console-экспортеры (stdout) для spans и metrics: `ConsoleSpanExporter`, `ConsoleMetricExporter`. Console log exporter, file exporter для logs и in-memory exporter для logs на этой странице не упомянуты. Источник: https://opentelemetry.io/docs/languages/python/exporters/ (загружено 2026-11-22). Вывод: наличие file/in-process log exporter не подтверждено; нужно проверить по исходникам пакета `opentelemetry-sdk`, это не сделано.

structlog и stdlib:
- structlog 26.1.0, `Released: Jun 6, 2026`, `Python >=3.10`, classifier «5 - Production/Stable». Источник: https://pypi.org/project/structlog/.
- stdlib logging: источник не загружался, поэтому сравнение по нему не делаю (не исследовано).
- Оверхед OTel-logs против structlog и stdlib: цифр не нашёл (не проверено).

Оценка для локального desktop/industrial приложения, сделанная мной (не из источников): logs в OTel Python — Development, значит ломающие изменения возможны. Для локального журнала без collector сначала нужна проверка экспортера, а не предположение о его наличии.

## 3. pydantic, pydantic-settings, OmegaConf, Hydra

- pydantic: 2.14.4, `Released 2026-11-19`; предыдущие 2.14.3 (2026-11-04), 2.14.2 (2026-10-29), 2.14.1 (2026-10-11). Источник: https://pypi.org/project/pydantic/. Метка: active. Python-требование для 2.14 не загружено (не проверено).
- pydantic-settings: 2.16.3, `Released: Nov 13, 2026`; предыдущие 2.16.2 (2026-10-28), 2.16.1 (2026-10-20), 2.16.0 (2026-10-14). Источник: https://pypi.org/project/pydantic-settings/. Метка: active. Поисковый сниппет про 2.14.2 устарел.
- OmegaConf: стабильный 2.4.0, `Released Oct 9, 2026`; pre-release 2.4.1rc2, `Oct 28, 2026`. Classifier статуса разработки не указан. Источник: https://pypi.org/project/omegaconf/. Метка: active.
- Hydra: стабильный 1.3.8, `Oct 25, 2026`; предыдущие 1.3.7 (2026-09-14), 1.3.6 (2026-08-29), 1.3.5 (2026-08-05). Pre-release 1.4.0rc3 тоже `Oct 25, 2026`. Classifier «4 - Beta»; перечисленные Python-classifiers: 3.7–3.11, без 3.12+. Источник: https://pypi.org/project/hydra-core/. Метка: active, но beta-статус и отставание classifiers.
- Для YAML recipe/config валидации: данные показывают, что все перечисленные пакеты поддерживаются. Какой вариант лучше, по этим источникам не решить. Моё предположение: pydantic дает валидацию типов, OmegaConf — интерполяции и merge; Hydra тяжелее (beta, classifiers не обновлены). YAML-парсер (ruamel или PyYAML) не исследовал (не проверено).

## 4. Rerun SDK

- rerun-sdk: последняя 0.43.2; `requires_python` = `>=3.11` (https://pypi.org/pypi/rerun-sdk/json, загружено 2026-11-22). Дата 13 Nov (год 2026 по меткам ассетов GitHub) — https://github.com/rerun-io/rerun/releases. Предыдущая 0.43.1 — по той же странице. Метка: active.
- Поисковые сниппеты про 0.41.0 (2026-10-28) устарели относительно 0.43.2 и не используются как факт.
- Windows: на странице релизов GitHub есть CLI-бинарь для Windows x86_64 (MSVC). Wheel `win_amd64` для Python-SDK не подтверждён: JSON API обрезан (не проверено). Страница установки viewer: https://rerun.io/docs/getting-started/installing-viewer — явного заявления о Windows нет; установка через `pip3 install rerun-sdk`.
- Multi-camera debugging: в этом обзоре не исследовано (не проверено). Нужна отдельная проверка API (например, timeline и временные ряды), пока без источников.

## 5. Node-graph и Qt-редакторы

- NodeGraphQt (upstream, jchanvfx): последний релиз 0.6.44, upload 2026-02-04; предыдущие 0.6.43 (2025-09-30), 0.6.42 (2025-09-02), 0.6.41 (2025-08-19). Источник: https://pypi.org/pypi/NodeGraphQt/json. Метка: slow. Classifiers без Qt-binding. README описывает библиотеку как «node graph UI framework written in python using Qt» и не называет binding: https://raw.githubusercontent.com/jchanvfx/NodeGraphQt/master/README.md. Репозиторий: 1 467 коммитов, 73 открытых issue, 4 открытых PR, раздел Releases пуст: https://github.com/jchanvfx/NodeGraphQt. Поддержку PySide6 в upstream в загруженных страницах подтвердить не удалось (не нашёл). Поисковый сниппет про PySide2/PyQt5 не подтверждён загрузкой.
- OdenGraphQt: форк upstream, 0.7.4, 2024-04-02; заявлена совместимость с PySide6 («I have not tested PyQt6»). Метка: stale. Источник: https://pypi.org/project/OdenGraphQt/ и https://pypi.org/pypi/OdenGraphQt/json.
- nodegraphqt-quiltix-fork: 0.7.0, 2024-05-24; предыдущий 0.6.0 (2023-08-01); extra `pyside6`, но описание говорит «for PySide2». Метка: stale. Источник: https://pypi.org/project/nodegraphqt-quiltix-fork/.
- ryvencore-qt: 0.5.0, 2024-05-20; «uses the PySide2 Python bindings»; переход на PySide6 «untested». Метка: stale. Источник: https://pypi.org/project/ryvencore-qt/.
- qtpynodeeditor: 0.3.3, 2024-12-15; classifier «2 - Pre-Alpha»; PyQt5/PySide через qtpy. Метка: stale. Источник: https://pypi.org/project/qtpynodeeditor/.
- Вывод: из загруженных страниц ни один Python-редактор узлов для Qt не выпускал релиз в 2026 году, кроме upstream NodeGraphQt (февраль 2026, slow). Активно поддерживаемый PySide6-редактор узлов в 2026 не найден (не нашёл).
- Не исследовано: QtNodes (C++), NodeGraphQtPy (поисковый сниппет говорит «archived», но страница не загружена; не проверено).

## 6. Новые или недавно созревшие библиотеки

- casty: 0.31.7, `Released: Nov 8, 2026`; Python >=3.12; classifier «3 - Alpha»; описание: «minimalist, type-safe actor framework for Python 3.12+ with built-in distributed clustering». Источник: https://pypi.org/project/casty/. Метка: active, alpha. Для нас релевантна только идея typed-акторов; кластеризация не нужна. Supervision и совместимость с multiprocessing не проверены.
- reaktiv: 0.25.0, `Release date: Nov 15, 2026`; Python >=3.9; описание: «Signals for Python - inspired by Angular Signals / SolidJS». Источник: https://pypi.org/project/reaktiv/. Метка: active. Кандидат на реактивное состояние. Мост к Qt-сигналам не найден (не нашёл); это нужно писать самим.
- pykka, pymiro, tapio-py, uactor: загрузка страниц PyPI не удалась. Из поисковых сниппетов: pykka 4.5.0 (зрелая библиотека акторов, подпись релиза проверена 2026-10-10); pymiro — PyQt6/PySide6 signals, 0.1.1 (2026-06-10); tapio — pre-alpha; uactor — акторы на multiprocessing. Все четыре — не проверено по первичному источнику, в вывод не входят.
- Дата первого релиза casty и reaktiv не проверена, поэтому «новизну» я не подтверждаю; подтверждена только свежесть последней версии.

## Что я оставил открытым или ненадёжным

1. OTel logs: file и in-process exporter для logs не подтверждены. Страница exporters их не упоминает. Нужна проверка исходников `opentelemetry-sdk` или пример в docs.
2. Оверхед OTel-logs, structlog и stdlib: цифр нет (не нашёл). Сравнение stdlib не проводил: источник не загружался.
3. NodeGraphQt upstream и PySide6: поддержка не подтверждена по загруженным страницам. Отсутствие PySide6 в README — не доказательство; нужно проверить `pyproject`/исходники на GitHub.
4. Нет данных по 2025–2026 релизам кроме перечисленных страниц PyPI; загрузки pydantic 2.14, OmegaConf и Hydra Python-требований не дали полной картины.
5. msgspec: Windows wheel для cp313/cp314 и даты предыдущих версий не подтверждены (JSON обрезан).
6. Rerun: win_amd64 wheel для Python SDK и применимость для multi-camera debugging не проверены.
7. Пункты 6: pykka, pymiro, tapio, uactor не загружены — только сниппеты. casty и reaktiv подтверждены по версии, но не по функциям, нужным для framework.
8. Конфликт статуса OTel: classifier «Production/Stable» у opentelemetry-sdk против README «Logs — Development». Выбрал README; проверку не проводил.
9. Поисковые сниппеты дали версии, которые более новые страницы опровергли (msgspec 0.20.0, rerun 0.41.0, pydantic-settings 2.14.2, OdenGraphQt как «новейший»). Использованы только загруженные значения.
10. Я не проверял, как библиотеки сочетаются с проектом (Python 3.12 и PySide6 в кодовой базе). Это вне задачи и не проверено.

## Sources

- https://pypi.org/project/msgspec/
- https://pypi.org/pypi/msgspec/json
- https://raw.githubusercontent.com/open-telemetry/opentelemetry-python/main/README.md
- https://opentelemetry.io/docs/specs/status/
- https://pypi.org/project/opentelemetry-sdk/
- https://opentelemetry.io/docs/languages/python/exporters/
- https://pypi.org/project/structlog/
- https://pypi.org/project/pydantic/
- https://pypi.org/project/pydantic-settings/
- https://pypi.org/project/omegaconf/
- https://pypi.org/project/hydra-core/
- https://pypi.org/project/rerun-sdk/ (загрузка не удалась; использован JSON)
- https://pypi.org/pypi/rerun-sdk/json
- https://github.com/rerun-io/rerun/releases
- https://rerun.io/docs/getting-started/installing-viewer
- https://pypi.org/pypi/NodeGraphQt/json
- https://raw.githubusercontent.com/jchanvfx/NodeGraphQt/master/README.md
- https://github.com/jchanvfx/NodeGraphQt
- https://pypi.org/project/OdenGraphQt/
- https://pypi.org/pypi/OdenGraphQt/json
- https://pypi.org/project/nodegraphqt-quiltix-fork/
- https://pypi.org/project/ryvencore-qt/
- https://pypi.org/project/qtpynodeeditor/
- https://pypi.org/project/casty/
- https://pypi.org/project/reaktiv/
