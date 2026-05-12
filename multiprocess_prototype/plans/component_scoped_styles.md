# Plan: Component Styles -- единый roadmap

**Дата:** 2026-05-12
**Статус:** DRAFT

## Обзор

Единый путь стилизации от монолитного main.qss к полноценной Component Design System. Два этапа:

- **Этап A (Phase 5 lite)** -- разбить main.qss на файлы, манифест + theme_loader, регрессионный тест. Всё в прототипе, никаких архитектурных новинок (registry, декораторы). Делаем СЕЙЧАС.
- **Этап B (Component Design System)** -- ComponentStyleRegistry + декораторы, QSS примитивов переезжает в фреймворк, ThemeManager.apply_theme_composed(), ThemeEditor из registry. Делаем ПОЗЖЕ, когда появятся кастомные компоненты.

**Предпосылки (уже merged в main):** design tokens (~140 переменных), main.qss полностью параметризован, ThemeEditorSection с TreeNavWidget + QTableWidget + поиск, inline-стили вынесены в QSS (прототип), 2631 тестов / 0 failures.

---

## Совместимость между этапами

Решения Этапа A спроектированы так, чтобы миграция в Этап B была механической (mv файлов + добавление registry):

| Аспект | Этап A (сейчас) | Этап B (потом) | Совместимость |
|--------|-----------------|----------------|---------------|
| **Имена файлов** | `buttons.qss`, `inputs/text_input.qss`, `chrome/header.qss` | Те же имена | Идентичны |
| **Группировка** | `components/primitives/` + `components/domains/` | primitives -> framework, domains -> prototype | Разделение сделано заранее |
| **Манифест** | `STYLE_MANIFEST` в `style_manifest.py` | registry.assemble_qss() для primitives, manifest для domains | manifest НЕ удаляется |
| **theme_loader** | `load_theme()` собирает base + components по manifest | `load_theme()` собирает base + registry + domain manifest | Добавление, не замена |
| **ThemeManager** | `read_theme_by_manifest()` -- новый метод | + `apply_theme_composed()` (registry) | read_theme_by_manifest() остаётся для domain styles |

### Файловая структура -- путь миграции

```
Этап A (сейчас):
themes/innotech_theme/
  base.qss
  components/
    primitives/           <- потом переедут в framework
      buttons.qss
      inputs.qss
      ...
    domains/              <- останутся здесь
      chrome.qss
      inspector.qss
      ...
  main.qss (DEPRECATED)

Этап B (потом):
framework/components/styles/        <- primitives переехали
  buttons/button.qss
  inputs/text_input.qss
  ...

prototype/styles/
  domain_styles/                    <- domains переименовались
    chrome.qss
    inspector.qss
    ...
  themes/innotech_theme/
    base.qss
    main.qss (DEPRECATED)
```

---

## Этап A: Phase 5 lite (текущая ветка)

### Порядок выполнения

#### Фаза A1: Разбиение main.qss на файлы
- Task A.1: base.qss [PENDING]
- Task A.2: QSS primitives (framework-виджеты) [PENDING]
- Task A.3: QSS domains (прикладные виджеты прототипа) [PENDING]

#### Фаза A2: Манифест + theme_loader
- Task A.4: style_manifest.py [PENDING] (зависит от A.2, A.3)
- Task A.5: ThemeManager.read_theme_by_manifest() [PENDING]
- Task A.6: theme_loader.py -- переход на manifest loading [PENDING] (зависит от A.4, A.5)

#### Фаза A3: Регрессия и финализация
- Task A.7: Регрессионный тест идентичности QSS [PENDING] (зависит от A.1-A.6)
- Task A.8: Deprecation main.qss + документация [PENDING] (зависит от A.7)

---

### Task A.1 -- base.qss: глобальные правила темы

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Выделить из main.qss глобальные правила (строки 1-59) в отдельный base.qss.

**Context:** base.qss -- "тема без компонентов": QWidget defaults, QLabel transparent, QMainWindow/QDialog background, QToolTip. Остаётся в папке темы прототипа. В Этапе B -- без изменений.

**Files:**
- `multiprocess_prototype/frontend/styles/themes/innotech_theme/base.qss` -- создать

**Steps:**
1. Скопировать из main.qss строки 1-59:
   - Заголовочный комментарий с палитрой и ограничениями Qt QSS (строки 1-28)
   - Секция БАЗА: QWidget, QLabel, QMainWindow/QDialog, QToolTip (строки 30-58)
2. Добавить заголовок `/* === base.qss -- глобальные правила темы === */` перед секцией БАЗА
3. Все `@переменные` оставить как есть
4. НЕ удалять эти строки из main.qss (он остаётся как deprecated fallback)

**Acceptance criteria:**
- [ ] `base.qss` существует и содержит QWidget, QLabel, QMainWindow/QDialog, QToolTip
- [ ] Заголовочный комментарий с палитрой перенесён
- [ ] Все `@переменные` сохранены, ни одна не изменена
- [ ] main.qss не изменён

**Out of scope:** Рефакторинг CSS-правил. Удаление main.qss.
**Edge cases:** нет
**Dependencies:** нет

---

### Task A.2 -- QSS primitives: универсальные Qt-виджеты

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Создать ~25 QSS-файлов для primitives (универсальных Qt-виджетов), выделив секции из main.qss.

**Context:** Primitives -- стили стандартных Qt-виджетов, которые любое приложение на фреймворке захочет использовать. Размещаются в `themes/innotech_theme/components/primitives/`. В Этапе B именно эти файлы переедут в `framework/components/styles/`.

**ВАЖНО:** группировка primitives/ vs domains/ делается СЕЙЧАС, чтобы миграция в Этап B была mv файлов.

**Files (создать все в `multiprocess_prototype/frontend/styles/themes/innotech_theme/components/primitives/`):**
- `buttons.qss` -- секция КНОПКИ (строки 122-210)
- `groupbox.qss` -- секция GROUPBOX (строки 212-238)
- `tabs.qss` -- секция TABS (строки 240-298)
- `combobox.qss` -- секция COMBOBOX (строки 300-336)
- `text_input.qss` -- секция LINE EDIT (строки 338-356)
- `spinbox.qss` -- секция SPIN BOX (строки 358-403)
- `checkbox.qss` -- секция CHECKBOX (строки 405-433)
- `radio.qss` -- секция RADIO (строки 435-453)
- `slider.qss` -- секция SLIDER (строки 455-512)
- `progress.qss` -- секция PROGRESS BAR (строки 514-532)
- `scrollbars.qss` -- секция SCROLLBARS (строки 534-588)
- `menu.qss` -- секция MENU / MENUBAR (строки 590-624)
- `statusbar.qss` -- секция STATUS BAR (строки 626-635)
- `tables.qss` -- секция TABLE / LIST / TREE (строки 637-671)
- `splitter.qss` -- секция SPLITTER (строки 673-679)
- `image_slot.qss` -- секция FRAME / IMAGE SLOT (строки 681-695)
- `cards.qss` -- секция ds-card + EntityCard (строки 697-704, 863-876)
- `note.qss` -- секция Note-блок (строки 706-714)
- `typography.qss` -- секция ОБЩИЕ КЛАССЫ (строки 716-748) + утилитарные label-стили из INLINE секции (строки 767-775: MutedLabel, HintLabel, HintLabelLg, PlaceholderLabel, SectionTitle, PanelTitle, PanelTitleLg, WarningBar) + tab/panel headers (строки 800-810) + readonly-hint, placeholder-italic, PermissionsHint (строки 838-854)
- `toggle.qss` -- ViewModeSwitch (строки 886-904)
- `error_banner.qss` -- Error banner rows (строки 906-916)
- `validation.qss` -- ValidationOutput (строки 918-924)
- `error_border.qss` -- hasError border (строки 937-941)
- `slot_button.qss` -- SlotButton states (строки 943-958)
- `displays.qss` -- DisplaySlotLabel, CameraViewLabel (строки 877-883) + DisplayImageLabel, CameraStatus (строки 789-790)
- `auth_readonly.qss` -- Auth RBAC (строки 985-1006)

Также создать файлы из INLINE-секции, которые являются framework-уровнем:
- `chrome_misc.qss` -- InfoTickerLabel, StatusIndicator, WatchdogOverlay, RecDot (строки 760-765) + DirtyLabel (строки 816-819) + StatusHint (строки 822-825)

**Steps:**
1. Создать директорию `themes/innotech_theme/components/primitives/`
2. Для каждого файла: точная вырезка секции из main.qss по номерам строк из маппинга выше
3. Каждый файл начинать с `/* === {name}.qss -- {описание} === */`
4. Все `@переменные` оставить как есть
5. Проверить: каждая строка main.qss (кроме base 1-59, кроме доменных секций) попала ровно в один файл primitives

**Acceptance criteria:**
- [ ] ~27 QSS-файлов в `components/primitives/`
- [ ] Каждая строка main.qss (исключая base + domains) -- ровно в одном файле
- [ ] `@переменные` не изменены
- [ ] Нет дублирования между файлами
- [ ] Конкатенация base.qss + все primitives + все domains = полный main.qss (с точностью до whitespace и комментариев-заголовков)

**Out of scope:** Рефакторинг CSS-правил. Создание tokens.yaml (Этап B). Удаление main.qss.
**Edge cases:** EntityCard (строки 863-876) расположен в INLINE-секции, но по типу -- primitive (cards). Поместить в `cards.qss`. Секция QAbstractScrollArea (строки в пределах TABS) -- в `tabs.qss`.
**Dependencies:** нет (параллельно с A.1)

---

### Task A.3 -- QSS domains: доменные стили прототипа

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Создать 8 QSS-файлов для доменных стилей, специфичных для inspector_bottles.

**Context:** Доменные стили -- объектные имена и property-селекторы виджетов, которые существуют только в прототипе. Другое приложение на фреймворке их не подключает. В Этапе B -- остаются в прототипе как `domain_styles/`.

**Files (создать все в `multiprocess_prototype/frontend/styles/themes/innotech_theme/components/domains/`):**
- `recipes.qss` -- NavList, RecipeSlotList (строки 752-758)
- `sources.qss` -- (пусто на данный момент -- все source-стили уже в primitives/displays.qss; файл-заглушка для будущих доменных стилей)
- `pipeline.qss` -- PipelineGraphView (строки 828-830)
- `inspector.qss` -- InspectorPlaceholder, InspectorTitle, InspectorCategoryBadge, InspectorDivider, plugin-name (строки 960-983)
- `settings.qss` -- ThemeDivider (строки 832-835)
- `dialogs.qss` -- ConfirmActionLabel (строка 813), Login/Confirm/PasswordErrorLabel (строки 927-934)
- `diff_scroll.qss` -- DiffScrollNavGroup, DiffScrollLeft/Right (строки 777-787, 857-861)
- `pagination.qss` -- PaginationArrow (строки 793-798)

**Steps:**
1. Создать директорию `themes/innotech_theme/components/domains/`
2. Для каждого файла: вырезать доменные строки из main.qss INLINE-секции
3. Каждый файл начинать с `/* === {name}.qss -- {описание} === */`
4. `sources.qss` -- файл-заглушка с комментарием `/* Зарезервировано для доменных стилей источников */`
5. Все `@переменные` оставить как есть

**Acceptance criteria:**
- [ ] 8 QSS-файлов в `components/domains/`
- [ ] Все доменные строки INLINE-секции попали в domain-файлы
- [ ] Нет пересечений с файлами из Task A.2
- [ ] `@переменные` не изменены

**Out of scope:** style_manifest.py (Task A.4). Рефакторинг селекторов.
**Edge cases:** `sources.qss` -- пустой (DisplayImageLabel, CameraStatus -- в primitives/displays.qss, т.к. это универсальные display-виджеты). Создаём заглушку для будущего.
**Dependencies:** нет (параллельно с A.1, A.2)

---

### Task A.4 -- style_manifest.py: манифест компонентных файлов

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Создать манифест со списком QSS-файлов и функцией сборки, заменяющей чтение монолитного main.qss.

**Context:** Манифест -- единственное место, определяющее порядок конкатенации QSS-файлов. В Этапе B registry заменит primitives-часть манифеста, но domains-часть останется.

**Files:**
- `multiprocess_prototype/frontend/styles/style_manifest.py` -- создать

**Steps:**
1. Определить два списка:
   ```python
   PRIMITIVE_STYLE_FILES: list[str] = [
       "components/primitives/buttons.qss",
       "components/primitives/groupbox.qss",
       "components/primitives/tabs.qss",
       "components/primitives/combobox.qss",
       "components/primitives/text_input.qss",
       "components/primitives/spinbox.qss",
       "components/primitives/checkbox.qss",
       "components/primitives/radio.qss",
       "components/primitives/slider.qss",
       "components/primitives/progress.qss",
       "components/primitives/scrollbars.qss",
       "components/primitives/menu.qss",
       "components/primitives/statusbar.qss",
       "components/primitives/tables.qss",
       "components/primitives/splitter.qss",
       "components/primitives/image_slot.qss",
       "components/primitives/cards.qss",
       "components/primitives/note.qss",
       "components/primitives/typography.qss",
       "components/primitives/toggle.qss",
       "components/primitives/error_banner.qss",
       "components/primitives/validation.qss",
       "components/primitives/error_border.qss",
       "components/primitives/slot_button.qss",
       "components/primitives/displays.qss",
       "components/primitives/chrome_misc.qss",
       "components/primitives/auth_readonly.qss",
   ]

   DOMAIN_STYLE_FILES: list[str] = [
       "components/domains/recipes.qss",
       "components/domains/diff_scroll.qss",
       "components/domains/pipeline.qss",
       "components/domains/inspector.qss",
       "components/domains/settings.qss",
       "components/domains/dialogs.qss",
       "components/domains/pagination.qss",
       # sources.qss -- заглушка, добавить когда появятся доменные стили
   ]

   STYLE_MANIFEST: list[str] = PRIMITIVE_STYLE_FILES + DOMAIN_STYLE_FILES
   ```
2. Порядок в `PRIMITIVE_STYLE_FILES` ДОЛЖЕН соответствовать порядку секций в main.qss (каскад)
3. Порядок в `DOMAIN_STYLE_FILES` -- доменные всегда после primitives (каскад)
4. Функция `assemble_qss_by_manifest(theme_dir: Path, manifest: list[str] | None = None) -> str`:
   - Если manifest=None -- использовать STYLE_MANIFEST
   - Конкатенировать файлы из theme_dir / file_path через `"\n\n"`
   - Если файл не существует -- warning в лог, пропустить
   - Возвращать собранный QSS
5. Функция `assemble_domain_qss(theme_dir: Path) -> str`:
   - То же, но только по DOMAIN_STYLE_FILES (для Этапа B -- registry заменит primitives)

**Acceptance criteria:**
- [ ] `style_manifest.py` экспортирует: `PRIMITIVE_STYLE_FILES`, `DOMAIN_STYLE_FILES`, `STYLE_MANIFEST`, `assemble_qss_by_manifest()`, `assemble_domain_qss()`
- [ ] Порядок PRIMITIVE_STYLE_FILES = порядок секций в main.qss
- [ ] `assemble_qss_by_manifest(theme_dir)` возвращает непустой QSS
- [ ] Отсутствующий файл -- warning, не ошибка
- [ ] Пустой манифест -> пустая строка

**Out of scope:** GUI управления манифестом. tokens.yaml.
**Edge cases:** `sources.qss` -- заглушка, не включён в DOMAIN_STYLE_FILES (пустой файл не добавляет значения). Файл не найден -- warning + пропуск.
**Dependencies:** Task A.2, Task A.3

---

### Task A.5 -- ThemeManager.read_theme_by_manifest()

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Добавить в ThemeManager метод чтения темы по манифесту (base.qss + component files) вместо склейки всех .qss по алфавиту.

**Context:** Текущий `read_theme()` читает все .qss из папки темы в алфавитном порядке. Для composed-подхода нужен контроль порядка: сначала base.qss, потом файлы по манифесту. Метод принимает manifest как аргумент (без зависимости от style_manifest.py -- инверсия зависимостей). В Этапе B метод не удаляется -- используется для domain styles.

**Files:**
- `multiprocess_framework/modules/frontend_module/managers/theme_manager.py` -- добавить метод

**Steps:**
1. Добавить метод `read_theme_by_manifest(self, name: str, manifest: list[str]) -> str | None`:
   - Прочитать `base.qss` из `themes/{name}/base.qss`
   - Если base.qss нет -- fallback на пустую строку с warning
   - Для каждого пути из manifest: прочитать `themes/{name}/{path}`
   - Пропускать несуществующие с warning
   - Конкатенировать: base_qss + "\n\n" + "\n\n".join(component_parts)
   - Вернуть результат или None если вообще ничего нет
2. НЕ менять существующие методы `read_theme()`, `apply_theme()`, `apply_theme_with_variables()`
3. Добавить метод `apply_theme_by_manifest(self, name: str, manifest: list[str], variables: dict[str, str]) -> bool`:
   - `template = self.read_theme_by_manifest(name, manifest)`
   - `qss = self.resolve_qss(template, variables)`
   - `app.setStyleSheet(qss)`
   - Возвращает bool как apply_theme_with_variables

**Acceptance criteria:**
- [ ] `read_theme_by_manifest()` читает base.qss + файлы из manifest в правильном порядке
- [ ] `apply_theme_by_manifest()` применяет тему к QApplication
- [ ] Отсутствующий файл -- warning, пропуск (не крэш)
- [ ] Отсутствующий base.qss -- warning, собирается только из manifest
- [ ] Существующие тесты ThemeManager проходят без изменений
- [ ] Новые unit-тесты (4+): happy path, missing base.qss, missing manifest file, empty manifest

**Out of scope:** ComponentStyleRegistry (Этап B). Duck-typing protocol. Не трогать `apply_theme()`.
**Edge cases:** Пустой manifest + нет base.qss -> None. Manifest с одним файлом -> base + 1 файл.
**Dependencies:** нет (параллельно с A.1-A.4, изменяет только ThemeManager)

---

### Task A.6 -- theme_loader.py: переход на manifest loading

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Обновить theme_loader.py для использования manifest-подхода вместо чтения монолитного main.qss.

**Context:** theme_loader.py -- composition root загрузки стилей в прототипе. Переход: `read_theme()` (все .qss по алфавиту) -> `read_theme_by_manifest()` (base + manifest в правильном порядке). Fallback на старый путь если manifest-файлы отсутствуют.

**Files:**
- `multiprocess_prototype/frontend/styles/theme_loader.py` -- модифицировать

**Steps:**
1. Добавить импорт:
   ```python
   from multiprocess_prototype.frontend.styles.style_manifest import STYLE_MANIFEST
   ```
2. Обновить `load_theme(theme_name)`:
   - Создать ThemeManager
   - Проверить наличие `themes/{theme_name}/components/` директории
   - Если есть: `template = tm.read_theme_by_manifest(theme_name, STYLE_MANIFEST)`
   - Если нет: fallback на `tm.read_theme(theme_name)` (обратная совместимость со старыми темами без components/)
   - Подстановка переменных -- без изменений
3. Обновить `apply_default_theme(app)`:
   - Проверить наличие components/ для innotech_theme
   - Если есть: `tm.apply_theme_by_manifest("innotech_theme", STYLE_MANIFEST, variables)`
   - Если нет: текущий путь через `app.setStyleSheet(qss)`
4. Сохранить полную обратную совместимость: старые темы (без components/) работают как раньше

**Acceptance criteria:**
- [ ] `load_theme()` использует manifest если `components/` существует
- [ ] `load_theme()` fallback на старый путь если `components/` отсутствует
- [ ] `apply_default_theme()` применяет тему через manifest
- [ ] Существующие тесты theme_loader проходят без изменений
- [ ] Новые тесты (3+): manifest path, fallback path, переменные подставляются

**Out of scope:** Не менять `_register_theme_fonts()`. Не менять `available_themes()`. Не менять `create_theme_manager()`.
**Edge cases:** Тема без components/ директории (пользовательская тема через ThemePresetsManager) -- fallback на read_theme(). ImportError style_manifest -- fallback с warning.
**Dependencies:** Task A.4, Task A.5

---

### Task A.7 -- Регрессионный тест: идентичность QSS

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Тест, гарантирующий что manifest-сборка функционально идентична оригинальному main.qss.

**Context:** Критический тест. Если assembled QSS отличается -- визуал сломается. Сравнение с нормализацией whitespace. Тест не зависит от PySide6.

**Files:**
- `multiprocess_prototype/frontend/tests/test_style_manifest.py` -- создать

**Steps:**
1. Helper `normalize_qss(text: str) -> str`:
   - Удалить строки, начинающиеся с `/* ===` (заголовки файлов)
   - Убрать trailing whitespace на каждой строке
   - Заменить множественные пустые строки на одну
   - Strip начала и конца
2. Тест `test_manifest_assembly_matches_main`:
   - Прочитать main.qss, подставить переменные
   - Собрать через `assemble_qss_by_manifest()`, подставить переменные
   - `assert normalize_qss(assembled) == normalize_qss(original)`
3. Тест `test_all_selectors_present`:
   - Извлечь QSS-селекторы из main.qss (regex: строки перед `{`)
   - Извлечь из assembled QSS
   - `assert original_selectors.issubset(assembled_selectors)`
4. Тест `test_no_duplicate_selectors_across_files`:
   - Для каждого QSS-файла компонента: извлечь селекторы
   - Ни один селектор не встречается в двух файлах
5. Тест `test_all_component_files_in_manifest`:
   - Все .qss в `components/primitives/` + `components/domains/` присутствуют в STYLE_MANIFEST (кроме заглушек)
6. Тест `test_manifest_order_matches_main`:
   - Для каждого файла в STYLE_MANIFEST: найти первый селектор
   - Проверить что порядок первых селекторов соответствует порядку в main.qss

**Acceptance criteria:**
- [ ] `test_manifest_assembly_matches_main` проходит
- [ ] `test_all_selectors_present` проходит
- [ ] `test_no_duplicate_selectors_across_files` проходит
- [ ] Тесты не зависят от PySide6 (чистый файловый I/O + regex)
- [ ] 6+ тестов

**Out of scope:** Визуальное регрессионное тестирование. Тесты ThemeManager (они уже есть).
**Edge cases:** Комментарии-заголовки файлов (`/* === ... === */`) -- нормализатор их удаляет. Пустые QSS-файлы (sources.qss) -- допустимы.
**Dependencies:** Task A.1, Task A.2, Task A.3, Task A.4

---

### Task A.8 -- Deprecation main.qss + документация

**Level:** Junior (Haiku, normal thinking)
**Assignee:** docs-writer
**Goal:** Пометить main.qss как deprecated и документировать новый composed loading.

**Files:**
- `multiprocess_prototype/frontend/styles/themes/innotech_theme/main.qss` -- добавить DEPRECATED комментарий
- `multiprocess_prototype/frontend/styles/themes/innotech_theme/components/README.md` -- создать

**Steps:**
1. В начало main.qss (после заголовочного комментария) добавить:
   ```
   /* !!!! DEPRECATED !!!!
      Этот файл -- fallback для обратной совместимости.
      Актуальные стили: base.qss + components/primitives/ + components/domains/
      Сборка: style_manifest.py -> STYLE_MANIFEST -> assemble_qss_by_manifest()
      Не редактировать — изменения вносить в компонентные файлы.
   */
   ```
2. `components/README.md`:
   - Структура: primitives/ vs domains/
   - Как добавить новый компонентный файл (создать .qss + добавить в STYLE_MANIFEST)
   - Порядок файлов = каскад (важен!)
   - Путь миграции в Этап B

**Acceptance criteria:**
- [ ] main.qss содержит DEPRECATED комментарий
- [ ] README объясняет структуру и как добавить новый файл
- [ ] Документация на русском

**Out of scope:** ARCHITECTURE.md (Этап B).
**Edge cases:** нет
**Dependencies:** Task A.7

---

## Этап B: Component Design System (будущее)

> Этот этап выполняется когда в проекте появятся кастомные компоненты, заменяющие голые Qt-виджеты. Ниже -- краткие описания задач. Полная архитектура registry, декораторов, API -- в секции "Архитектура Этапа B" в конце документа.

### Порядок выполнения

#### Фаза B1: Registry и декораторы (ядро)
- Task B.1: ComponentStyleRegistry -- singleton-реестр [PENDING]
- Task B.2: Декораторы @component_style, @style_group [PENDING]
- Task B.3: Тесты registry + декораторов (23+ тестов) [PENDING]

#### Фаза B2: Миграция primitives в фреймворк
- Task B.4: Перенести primitives/ из прототипа в `frontend_module/components/styles/` [PENDING]
- Task B.5: tokens.yaml для каждой группы компонентов (12 файлов) [PENDING]
- Task B.6: register_all_component_styles() -- модуль регистрации [PENDING]

#### Фаза B3: ThemeManager + theme_loader интеграция
- Task B.7: ThemeManager.apply_theme_composed() с duck-typed registry [PENDING]
- Task B.8: theme_loader.py -- переход на composed loading (registry + domain manifest) [PENDING]

#### Фаза B4: Миграция inline-стилей
- Task B.9: Миграция 11 мест setStyleSheet в фреймворке [PENDING]

#### Фаза B5: ThemeEditor + style_group
- Task B.10: ThemeEditor -- component_tree() интеграция [PENDING]
- Task B.11: @style_group для доменных виджетов прототипа [PENDING]

#### Фаза B6: Финализация
- Task B.12: Полное тестовое покрытие (30+ тестов) [PENDING]
- Task B.13: Документация (ARCHITECTURE.md, README) [PENDING]

### Краткие описания задач Этапа B

**B.1 ComponentStyleRegistry** (Senior, teamlead): Singleton в `frontend_module/components/registry.py`. Методы: register/unregister, assemble_qss(include/exclude), all_tokens(), component_tree(), reset(). Кэширование QSS с инвалидацией. Не зависит от PySide6.

**B.2 Декораторы** (Senior, teamlead): `@component_style(name, qss, tokens)` -- регистрирует компонент при импорте. `@style_group(*groups)` -- setProperty("styleGroup") при создании. `register_component_styles()` -- императивная альтернатива.

**B.3 Тесты** (Middle+, developer): 15+ тестов registry (singleton, register, assemble, tokens, cache) + 8+ тестов декораторов.

**B.4 Миграция primitives** (Middle, developer): mv файлов из `themes/innotech_theme/components/primitives/` в `frontend_module/components/styles/{group}/`. Переименование: `buttons.qss` -> `buttons/button.qss` и т.д.

**B.5 tokens.yaml** (Middle, developer): Для каждой группы -- дефолтные значения ТОЛЬКО компонент-специфичных токенов (btn_*, input_*, tab_*). Общие (bg_deep, text_0) -- из темы.

**B.6 Регистрация** (Middle+, developer): `register_all_component_styles()` в `styles/__init__.py` -- lazy, порядок = порядок main.qss.

**B.7 apply_theme_composed** (Senior, teamlead): base_qss + registry.assemble_qss() + extra_qss. Токены: component defaults < theme variables. Duck-typing registry. Не ломает apply_theme().

**B.8 theme_loader composed** (Middle+, developer): registry не пустой -> composed path; пустой -> fallback на manifest (Этап A).

**B.9 Миграция inline** (Middle+, developer): 11 мест setStyleSheet в фреймворке. Перенос в QSS с objectName/property selectors. Исключения: status_strip.py, inspector_panel.py -- предопределённые состояния + минимальный fallback.

**B.10 ThemeEditor** (Middle+, developer): component_tree() из registry -> 3-й уровень навигации "Компоненты > Кнопки > btn_grad_top".

**B.11 style_group** (Middle, developer): @style_group("inspector") для InspectorPanel и т.д.

**B.12 Тесты** (Middle+, developer): Интеграционные: apply_theme_composed, token override order, composed end-to-end, grep setStyleSheet=0.

**B.13 Документация** (Junior, docs-writer): ARCHITECTURE.md + README компонентных стилей + deprecation.

---

## Миграционный путь A -> B

Чёткие шаги перехода от Этапа A к Этапу B:

1. **Создать registry + декораторы** (B.1, B.2) -- чистые Python-модули в фреймворке, ничего не ломают
2. **mv primitives/**: `themes/innotech_theme/components/primitives/*.qss` -> `frontend_module/components/styles/{group}/` с переименованием по группам
3. **Создать tokens.yaml** рядом с перенесёнными QSS
4. **Зарегистрировать** все primitives через `register_all_component_styles()`
5. **Обновить STYLE_MANIFEST**: убрать PRIMITIVE_STYLE_FILES, оставить DOMAIN_STYLE_FILES
6. **Обновить theme_loader.py**:
   - `load_theme()`: base.qss + registry.assemble_qss() + assemble_domain_qss()
   - `read_theme_by_manifest()` НЕ удаляется -- используется для domain styles
7. **Добавить apply_theme_composed()** в ThemeManager
8. **Мигрировать inline-стили** (B.9)
9. **Интегрировать ThemeEditor** с component_tree()
10. **Обновить регрессионный тест** -- сравнивать assembled из registry + domains с main.qss

**Ключ:** шаги 2-6 -- механические операции (mv + правка manifest). Архитектурные изменения (registry, composed) ортогональны.

---

## Архитектура Этапа B (справочник)

> Эта секция содержит полную техническую спецификацию Component Design System для использования при реализации Этапа B.

### Файловая структура фреймворка (после Этапа B)

```
multiprocess_framework/modules/frontend_module/
  components/
    registry.py                      # ComponentStyleRegistry (singleton)
    decorators.py                    # @component_style, @style_group
    styles/
      __init__.py                    # register_all_component_styles()
      buttons/
        button.qss
        tokens.yaml
      inputs/
        text_input.qss, combobox.qss, spinbox.qss, checkbox.qss,
        radio.qss, slider.qss, toggle.qss
        tokens.yaml
      tabs/           tab.qss, tokens.yaml
      tables/         table.qss, tokens.yaml
      scrollbars/     scrollbar.qss, tokens.yaml
      containers/     groupbox.qss, splitter.qss, tokens.yaml
      cards/          card.qss, tokens.yaml
      feedback/       progress.qss, note.qss, error_banner.qss,
                      validation.qss, error_border.qss, tokens.yaml
      typography/     typography.qss, labels.qss, headers.qss, hints.qss, tokens.yaml
      chrome/         header.qss, status_pill.qss, info_ticker.qss, menu.qss,
                      statusbar.qss, indicators.qss, misc.qss, tokens.yaml
      displays/       image_slot.qss, slot_label.qss, slot_button.qss, tokens.yaml
      auth/           readonly.qss, tokens.yaml
```

### ComponentStyleRegistry API

```python
class ComponentStyleInfo:
    name: str                          # "buttons", "inputs/checkbox"
    qss_path: Path | None
    tokens: dict[str, str]
    groups: list[str]
    description: str
    order: int                         # auto-increment

class ComponentStyleRegistry:
    _instance: ComponentStyleRegistry | None
    _components: dict[str, ComponentStyleInfo]

    @classmethod
    def instance(cls) -> ComponentStyleRegistry: ...
    def register(info) -> None: ...
    def unregister(name) -> None: ...
    def assemble_qss(*, include=None, exclude=None) -> str: ...
    def all_tokens() -> dict[str, str]: ...
    def component_tree() -> dict[str, list[str]]: ...
    def registered_names() -> list[str]: ...
    def get(name) -> ComponentStyleInfo | None: ...
    def reset() -> None: ...
```

### ThemeManager.apply_theme_composed()

```python
def apply_theme_composed(self, name, variables, registry, *, extra_qss="") -> bool:
    base_qss = self.read_base_qss(name)       # base.qss из темы
    component_qss = registry.assemble_qss()    # все primitives из registry
    final_template = base_qss + "\n\n" + component_qss + "\n\n" + extra_qss
    tokens = registry.all_tokens()             # дефолты компонентов
    tokens.update(variables)                   # тема перезаписывает
    resolved = self.resolve_qss(final_template, tokens)
    app.setStyleSheet(resolved)
```

### Inline-стили -- маппинг миграции

| Файл | Стиль | Целевой QSS | Способ |
|------|-------|-------------|--------|
| `common/styles.py` | SLIDER_HANDLE_STYLESHEET | inputs/slider.qss | параметризация @переменными |
| `common/slider_styles.py` | дубликат | удалить | |
| `header/button_style.py` | HEADER_BUTTON_STYLESHEET | chrome/header.qss | objectName |
| `tabs/tab_widget.py` | 3x setStyleSheet | tabs/tab.qss | objectName |
| `tabs/placeholder_utils.py` | "color: gray..." | typography/labels.qss | #PlaceholderLabel |
| `chrome/status_strip.py` | dynamic f"color: {color}" | property selectors | [status="online/offline/error"] + fallback |
| `keyboard/keyboard_mini.py` | inline QSS | inputs/keyboard.qss (новый) | objectName |
| `image_panel.py` | "#1e1e1e" | displays/image_slot.qss | @переменные |
| `entity_editor/base_editor_toolbar.py` | _DIRTY_STYLE | feedback/validation.qss | property selector |
| `windows/loading_window.py` | font-size, color | chrome/loading.qss (новый) | objectName |
| `inspector_panel.py` | dynamic color | property selectors | [category="detection/preprocessing"] + fallback |

---

## Риски и ограничения

### R1: Qt QSS != CSS scoping
Qt QSS не поддерживает scoping. Порядок в manifest = каскад. **Митигация:** qualified selectors (#objectName, [role], [property]), фиксированный порядок в STYLE_MANIFEST.

### R2: Обратная совместимость
Склеенный QSS должен быть идентичен main.qss. **Митигация:** регрессионный тест (Task A.7).

### R3: Custom-темы пользователей
ThemePresetsManager копирует variables.yaml. Пользовательские темы без components/ -> fallback на read_theme(). **Митигация:** проверка наличия components/ в theme_loader (Task A.6).

### R4: Dynamic colors
`status_strip.py` и `inspector_panel.py` используют dynamic f-string setStyleSheet. **Митигация (Этап B):** предопределённые состояния через property selectors + минимальный fallback.

### R5: Производительность
~27+ QSS-файлов вместо 1. **Митигация:** один раз при старте, суммарно < 5мс.

---

## Суммарная оценка

| Этап | Задачи | Файлов | Тестов |
|------|--------|--------|--------|
| **A: Phase 5 lite** | 8 задач (A.1-A.8) | ~40 создано, 2 изменено | 6+ |
| **B: Component Design System** | 13 задач (B.1-B.13) | ~70 создано/изменено | 30+ |
| **Итого** | **21 задача** | **~110 файлов** | **36+** |
