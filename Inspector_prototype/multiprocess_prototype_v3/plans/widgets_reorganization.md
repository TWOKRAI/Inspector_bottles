# План: Реорганизация frontend/widgets/

**Дата:** 2026-04-27
**Статус:** DRAFT
**Область:** `multiprocess_prototype_v3/frontend/widgets/`

---

## Обзор

Плоский каталог из 28 пакетов + 2 base-файла группируется по доменам: `chrome/`, `sources/`, `recipes/`, `processing/`, `pipeline/`, `settings/`. Мёртвый код уходит в `_archive/`. Базовые классы переезжают в `_base/`. `pipeline_tab/` (4829 LoC) разбивается на 5 подпакетов. `tabs_setting/` остаётся плоским. Задача — только перемещение + правка импортов, без переименования классов.

---

## Часть 1. Полный mapping путей (таблица)

### 1.1. Аббревиатуры

| Аббревиатура | Полный префикс |
|---|---|
| `v3` | `multiprocess_prototype_v3.frontend.widgets` |
| `tab` | `multiprocess_prototype_v3.frontend.widgets.tabs_setting` |

### 1.2. Dead-code → `_archive/` (Task 1.1)

| # | Пакет (старый путь) | Новый путь | Импортёры | Статус |
|---|---|---|---|---|
| 1 | `widgets/recipes_cards/` | `widgets/_archive/recipes_cards/` | **нет** — пустой пакет, нет `__init__.py` с кодом | dead/empty |
| 2 | `widgets/_hikvision_widget_legacy/` | `widgets/_archive/_hikvision_widget_legacy/` | **нет** — подтверждено grep | legacy |
| 3 | `widgets/catalog_editor/` | `widgets/_archive/catalog_editor/` | **нет** | dead |
| 4 | `widgets/chain_editor/` | `widgets/_archive/chain_editor/` | **нет** | dead |

> Перемещение в `_archive/` — без изменений `__init__.py` пакетов: если пакеты не импортируются, ничего не сломается.

### 1.3. Base-файлы → `_base/` (Task 1.2)

| Старый путь | Новый путь | Импортёры (точная строка) |
|---|---|---|
| `widgets/_navigation_panel_base.py` | `widgets/_base/navigation_panel_base.py` | `recipes_slot_buttons/panel.py:21` `from .._navigation_panel_base import NavigationPanelBase` → `from .._base.navigation_panel_base import NavigationPanelBase` |
| `widgets/_navigation_panel_base.py` | — | `settings_tab/settings_nav_panel.py:8` `from .._navigation_panel_base import NavigationPanelBase` → `from .._base.navigation_panel_base import NavigationPanelBase` |
| `widgets/_recipe_panel_base.py` | `widgets/_base/recipe_panel_base.py` | `recipes_widget/panel_widget.py:16` `from .._recipe_panel_base import RecipePanelBase` → `from .._base.recipe_panel_base import RecipePanelBase` |
| `widgets/_recipe_panel_base.py` | — | `settings_recipe_widget/panel_widget.py:13` `from .._recipe_panel_base import RecipePanelBase` → `from .._base.recipe_panel_base import RecipePanelBase` |
| `widgets/cards_field_factory/` | `widgets/_base/cards_field_factory/` | `settings_tab/settings_cards.py:24` `from ..cards_field_factory import create_field_widget` → `from .._base.cards_field_factory import create_field_widget` |

`_base/__init__.py` создать с реэкспортами:
```python
from .navigation_panel_base import NavigationPanelBase
from .recipe_panel_base import RecipePanelBase
from .cards_field_factory import create_field_widget
__all__ = ["NavigationPanelBase", "RecipePanelBase", "create_field_widget"]
```

### 1.4. Chrome → `chrome/` (Task 1.3)

Перемещаются 6 пакетов. Импортёры используют `from multiprocess_prototype_v3.frontend.widgets.<pkg>` или относительные пути.

| Пакет | Старый путь | Новый путь | Файлы-импортёры |
|---|---|---|---|
| `app_header` | `widgets/app_header/` | `widgets/chrome/app_header/` | `windows/main_window/window.py:21` `from multiprocess_prototype_v3.frontend.widgets.app_header import AppHeaderWidget` |
| `side_panels` | `widgets/side_panels/` | `widgets/chrome/side_panels/` | `windows/main_window/window.py:22` `from multiprocess_prototype_v3.frontend.widgets.side_panels import CollapsibleSidePanel` |
| `watchdog_overlay` | `widgets/watchdog_overlay/` | `widgets/chrome/watchdog_overlay/` | `windows/main_window/window.py:27` `from multiprocess_prototype_v3.frontend.widgets.watchdog_overlay import WatchdogOverlay` |
| `recording_indicator` | `widgets/recording_indicator/` | `widgets/chrome/recording_indicator/` | `display_window/widget.py` (через `.source_selector` или внутренний импорт — см. ниже) |
| `view_mode_toggle` | `widgets/view_mode_toggle/` | `widgets/chrome/view_mode_toggle/` | `tabs_setting/recipes_tab/widget.py:72` `from ...view_mode_toggle import ViewModeToggle`; `settings_tab/widget.py:39` `from ..view_mode_toggle import ViewModeToggle` |
| `search_filter_bar` | `widgets/search_filter_bar/` | `widgets/chrome/search_filter_bar/` | `tabs_setting/recipes_tab/widget.py` — через `recipe_content_section.py`; `settings_tab/ui_section.py:13` `from ..search_filter_bar import SearchFilterBar, apply_filter`; `settings_tab/system_section.py:23` `from ..search_filter_bar import SearchFilterBar, apply_filter` |

Детали `recording_indicator`:
- `display_window/__init__.py` не импортирует `recording_indicator` напрямую (нет строки в `__init__.py`).
- `display_window/widget.py` ссылается на него через `.source_selector` — **требуется grep** в `display_window/widget.py` для точной строки. Паттерн: `from ..recording_indicator import RecordingIndicator` или `from multiprocess_prototype_v3.frontend.widgets.recording_indicator import ...`.

**Обновить при Task 1.3:**
- `window.py` строки 21, 22, 27: изменить на `chrome.app_header`, `chrome.side_panels`, `chrome.watchdog_overlay`
- `tabs_setting/recipes_tab/widget.py`: `from ...view_mode_toggle` → `from ...chrome.view_mode_toggle`
- `settings_tab/widget.py`: `from ..view_mode_toggle` → `from ..chrome.view_mode_toggle`
- `settings_tab/ui_section.py`, `system_section.py`: `from ..search_filter_bar` → `from ..chrome.search_filter_bar`
- `display_window/widget.py`: уточнить grep + обновить импорт recording_indicator (переезжает в Task 1.4/chrome вместе с sources)

> **Примечание:** `recording_indicator` является зависимостью `display_window`. Поскольку `display_window` переезжает в `sources/`, а `recording_indicator` — в `chrome/`, это кросс-доменная зависимость. При Task 1.3 (chrome) обновляем путь `recording_indicator` в `display_window/widget.py` (если там относительный импорт). При Task 1.4 (sources) обновляем относительный путь в display_window, т.к. он переедет в `sources/display_window/`.

### 1.5. Sources → `sources/` (Task 1.4)

| Пакет | Старый путь | Новый путь | Файлы-импортёры |
|---|---|---|---|
| `camera_common` | `widgets/camera_common/` | `widgets/sources/camera_common/` | `tabs_setting/camera_tab/widget.py:30` `from ...camera_common import SimWebcamWidget`; `tabs_setting/camera_tab/__init__.py:27` `from ...camera_common import build_sim_webcam_callbacks` |
| `hikvision_camera_mvp` | `widgets/hikvision_camera_mvp/` | `widgets/sources/hikvision_camera_mvp/` | `tabs_setting/camera_tab/widget.py` (проверить grep) — вероятно `from ...hikvision_camera_mvp import HikvisionCameraMvpWidget` |
| `display_window` | `widgets/display_window/` | `widgets/sources/display_window/` | `frontend/launcher.py` — нет прямого импорта display_window (используется через `window_manager.py`); `managers/window_manager.py:85` `from frontend.widgets.display_window.widget import DisplayWindow`; `tabs_setting/display_tab/widget.py:30` (TYPE_CHECKING — `from frontend.managers.window_manager import DisplayWindowManager`); `pipeline_tab/preview_bridge.py` — нет прямого импорта display_window; `frontend/widgets/__init__.py` — display_window не в `_LAZY_NAMES` |

**Обновить при Task 1.4:**
- `tabs_setting/camera_tab/widget.py`, `__init__.py`: `...camera_common` → `...sources.camera_common`
- `tabs_setting/camera_tab/widget.py` (Hikvision): `...hikvision_camera_mvp` → `...sources.hikvision_camera_mvp`
- `managers/window_manager.py:85`: `from frontend.widgets.display_window.widget` → `from frontend.widgets.sources.display_window.widget`
- Если в `display_window/widget.py` есть `from ..recording_indicator import ...` — нужно заменить на `from ..chrome.recording_indicator import ...` (chrome уже переехал в Task 1.3)

> **Примечание по `window_manager.py` импорту:** Он использует `from frontend.widgets.display_window.widget` (без `multiprocess_prototype_v3`-префикса). Это работает, если `Inspector_prototype/multiprocess_prototype_v3/` находится в `sys.path`. При переезде путь станет `from frontend.widgets.sources.display_window.widget`.

### 1.6. Recipes → `recipes/` (Task 1.5)

| Пакет | Старый путь | Новый путь | Файлы-импортёры |
|---|---|---|---|
| `recipes_widget` | `widgets/recipes_widget/` | `widgets/recipes/recipes_widget/` | `tabs_setting/recipes_tab/__init__.py:10` `from ...recipes_widget import RegisterRecipePanelWidget`; `tabs_setting/recipes_tab/widget.py:65` `from ...recipes_widget import RegisterRecipePanelWidget as RegisterRecipePanel` |
| `settings_recipe_widget` | `widgets/settings_recipe_widget/` | `widgets/recipes/settings_recipe_widget/` | `tabs_setting/recipes_tab/__init__.py:8` `from ...settings_recipe_widget.schemas import RecipesTabConfig`; `tabs_setting/recipes_settings_tab/widget.py:31` `from ...settings_recipe_widget import AppRecipePanelWidget as AppRecipePanel`; `tabs_setting/recipes_settings_tab/widget.py:32` `from ...settings_recipe_widget.schemas import RecipesTabConfig`; `settings_tab/widget.py:36` `from ..settings_recipe_widget import AppRecipePanelWidget as AppRecipePanel`; `settings_tab/widget.py:37` `from ..settings_recipe_widget.schemas import RecipesTabConfig`; `managers/app_recipe_aggregate.py:22` `from multiprocess_prototype_v3.frontend.widgets.settings_recipe_widget.schemas import RecipesTabConfig`; `configs/frontend_config.py:36` `from multiprocess_prototype_v3.frontend.widgets.settings_recipe_widget.schemas import RecipesTabConfig` |
| `settings_profile_widget` | `widgets/settings_profile_widget/` | `widgets/recipes/settings_profile_widget/` | `tabs_setting/recipes_settings_tab/widget.py` — проверить grep (`SettingsProfilePanelWidget`) |
| `recipes_slot_buttons` | `widgets/recipes_slot_buttons/` | `widgets/recipes/recipes_slot_buttons/` | `tabs_setting/recipes_tab/widget.py:64` `from ...recipes_slot_buttons import RecipesSlotButtonsPanel` |

**Обновить при Task 1.5:**
- `tabs_setting/recipes_tab/__init__.py`, `widget.py`: `...recipes_widget` → `...recipes.recipes_widget`; `...settings_recipe_widget` → `...recipes.settings_recipe_widget`; `...recipes_slot_buttons` → `...recipes.recipes_slot_buttons`
- `tabs_setting/recipes_settings_tab/widget.py`: `...settings_recipe_widget` → `...recipes.settings_recipe_widget`; `...settings_profile_widget` → `...recipes.settings_profile_widget`
- `settings_tab/widget.py`: `..settings_recipe_widget` → `..recipes.settings_recipe_widget`
- `managers/app_recipe_aggregate.py`: абсолютный импорт `...widgets.settings_recipe_widget.schemas` → `...widgets.recipes.settings_recipe_widget.schemas`
- `configs/frontend_config.py`: абсолютный импорт `...widgets.settings_recipe_widget.schemas` → `...widgets.recipes.settings_recipe_widget.schemas`
- `_base/recipe_panel_base.py` (уже перемещён в Task 1.2): импорт из `recipes_widget` или `settings_recipe_widget` — не использует их (только ими наследуется)

### 1.7. Processing → `processing/` (Task 1.6)

| Пакет | Старый путь | Новый путь | Файлы-импортёры |
|---|---|---|---|
| `processing_panel_widget` | `widgets/processing_panel_widget/` | `widgets/processing/processing_panel_widget/` | `tabs_setting/processing_tab/__init__.py:8` `from ...processing_panel_widget import ProcessingPanelWidget, ProcessingTabUiConfig`; `managers/app_recipe_aggregate.py:18` `from multiprocess_prototype_v3.frontend.widgets.processing_panel_widget.schemas import ProcessingTabUiConfig` |
| `post_processing_widget` | `widgets/post_processing_widget/` | `widgets/processing/post_processing_widget/` | `tabs_setting/post_processing_tab/widget.py:10` `from ...post_processing_widget import PostProcessingPanelWidget`; `tabs_setting/post_processing_tab/widget.py:11` `from ...post_processing_widget.schemas import PostProcessingTabUiConfig`; `configs/frontend_config.py:33` `from multiprocess_prototype_v3.frontend.widgets.post_processing_widget.schemas import PostProcessingTabUiConfig` |
| `cropped_regions_widget` | `widgets/cropped_regions_widget/` | `widgets/processing/cropped_regions_widget/` | `tabs_setting/cropped_regions_tab/__init__.py:8-25` большой реэкспорт из `...cropped_regions_widget`; `configs/frontend_config.py:29` `from multiprocess_prototype_v3.frontend.widgets.cropped_regions_widget.schemas import CroppedRegionsTabUiConfig` |

**Обновить при Task 1.6:**
- `tabs_setting/processing_tab/__init__.py`: `...processing_panel_widget` → `...processing.processing_panel_widget`
- `tabs_setting/post_processing_tab/widget.py`: `...post_processing_widget` → `...processing.post_processing_widget`
- `tabs_setting/cropped_regions_tab/__init__.py`: `...cropped_regions_widget` → `...processing.cropped_regions_widget`
- `managers/app_recipe_aggregate.py:18`: абсолютный импорт → `...widgets.processing.processing_panel_widget.schemas`
- `configs/frontend_config.py` строки 29, 33: абсолютные импорты → `...widgets.processing.cropped_regions_widget.schemas`, `...widgets.processing.post_processing_widget.schemas`

### 1.8. Settings → `settings/` (Task 1.7)

`settings_tab/` переезжает целиком как `settings/settings_tab/`.

| Пакет | Старый путь | Новый путь | Файлы-импортёры |
|---|---|---|---|
| `settings_tab` | `widgets/settings_tab/` | `widgets/settings/settings_tab/` | `windows/main_window/tab_factory.py:19` `from multiprocess_prototype_v3.frontend.widgets.settings_tab import SettingsContainerWidget`; `managers/app_recipe_aggregate.py:27` `from multiprocess_prototype_v3.frontend.widgets.settings_tab.ui_preferences_schema import UiPreferencesConfig`; `tabs_setting/recipes_settings_tab/widget.py:38` (TYPE_CHECKING или прямой) `from ..tabs_setting.recipes_settings_tab.schemas import SettingsTabConfig`; `settings_tab/widget.py:38` `from ..tabs_setting.recipes_settings_tab.schemas import SettingsTabConfig` |

Внутри `settings_tab/` уже есть относительные импорты — при переезде они не меняются, т.к. относительные пути внутри пакета сохраняются. Меняются только **внешние** импортёры:

**Обновить при Task 1.7:**
- `tab_factory.py:19`: `...widgets.settings_tab import SettingsContainerWidget` → `...widgets.settings.settings_tab import SettingsContainerWidget`
- `managers/app_recipe_aggregate.py:27`: `...widgets.settings_tab.ui_preferences_schema` → `...widgets.settings.settings_tab.ui_preferences_schema`
- `settings_tab/widget.py:38` (внутренний относительный путь `from ..tabs_setting.recipes_settings_tab.schemas`) — при переезде `settings_tab/widget.py` в `settings/settings_tab/widget.py` этот путь меняется с `..tabs_setting...` на `...tabs_setting...` (добавляется один уровень вверх)

> Важно: внутри `settings_tab/` строка `from ..tabs_setting.recipes_settings_tab.schemas import SettingsTabConfig` (в `widget.py:38` и `settings_tab/*.py`) — при переезде в `settings/settings_tab/` путь `..tabs_setting` превращается в `...tabs_setting`. Нужно заменить все `..tabs_setting` на `...tabs_setting` внутри перемещённых файлов.

### 1.9. Pipeline → `pipeline/` (Task 1.8)

`pipeline_tab/` переезжает как `pipeline/pipeline_tab/` и разбивается на подпакеты.

#### Разбивка файлов pipeline_tab по подпакетам

| Файл (сейчас) | Подпакет (новый) | Ключевые внутренние зависимости |
|---|---|---|
| `adapter.py` | `canvas/` | TYPE_CHECKING импортирует `model.GraphEditorModel`, `inspector_node.InspectorBaseNode` |
| `model.py` | `canvas/` | чистый Python, нет зависимостей внутри pipeline_tab |
| `auto_layout.py` | `canvas/` | `from ._layout_constants import GRID_SIZE`; TYPE_CHECKING: `registers.pipeline.processing_node.ProcessingNode` |
| `linearity_check.py` | `canvas/` | нет зависимостей внутри pipeline_tab |
| `inspector_node.py` | `inspector/` | `from .constants import THUMBNAIL_HEIGHT, THUMBNAIL_WIDTH, THUMBNAIL_Z_OFFSET` |
| `inspector_panel.py` | `inspector/` | `from .display_target_combo import DisplayTargetCombo`; `from .params_form import ParamsForm`; `from .process_id_combo import ProcessIdCombo`; `from .model import GraphEditorModel` |
| `params_form.py` | `inspector/` | нет зависимостей внутри pipeline_tab |
| `library_palette.py` | `library/` | нет зависимостей внутри pipeline_tab |
| `context_menu.py` | `library/` | нет зависимостей внутри pipeline_tab |
| `table_view.py` | `views/` | `from .linearity_check import get_linearity_warning`; `from ._layout_constants import ...` (нет, проверить) |
| `view_switch.py` | `views/` | TYPE_CHECKING: `from .adapter import NodeGraphQtAdapter`; TYPE_CHECKING: `from .table_view import PipelineTableView` |
| `_layout_constants.py` | `views/` | нет зависимостей |
| `preview_bridge.py` | `bridges/` | `from .constants import THUMBNAIL_HEIGHT, ...`; TYPE_CHECKING: `inspector_node.InspectorBaseNode` |
| `display_target_combo.py` | `bridges/` | нет зависимостей внутри pipeline_tab |
| `process_id_combo.py` | `bridges/` | нет зависимостей внутри pipeline_tab |
| `widget.py` | корень `pipeline_tab/` | импортирует из `adapter`, `inspector_panel`, `library_palette`, `model`, `table_view`, `view_switch`, `inspector_node` |
| `__init__.py` | корень `pipeline_tab/` | реэкспортирует всё публичное |
| `constants.py` | корень `pipeline_tab/` | нет зависимостей |

#### Обновление внутренних импортов pipeline_tab

После разбивки файлы используют новые относительные пути. Все `from .X import` заменяются на кросс-подпакетные ссылки:

| Файл | Старый импорт | Новый импорт |
|---|---|---|
| `canvas/adapter.py` | TYPE_CHECKING: `from frontend.widgets.pipeline_tab.model import GraphEditorModel` | `from frontend.widgets.pipeline.pipeline_tab.canvas.model import GraphEditorModel` |
| `canvas/adapter.py` | TYPE_CHECKING: `from frontend.widgets.pipeline_tab.inspector_node import InspectorBaseNode` | `from frontend.widgets.pipeline.pipeline_tab.inspector.inspector_node import InspectorBaseNode` |
| `canvas/auto_layout.py` | `from ._layout_constants import GRID_SIZE` | `from ..views._layout_constants import GRID_SIZE` |
| `inspector/inspector_node.py` | `from .constants import ...` | `from ..constants import ...` |
| `inspector/inspector_panel.py` | `from .display_target_combo import ...` | `from ..bridges.display_target_combo import ...` |
| `inspector/inspector_panel.py` | `from .params_form import ParamsForm` | `from .params_form import ParamsForm` (остаётся в inspector/) |
| `inspector/inspector_panel.py` | `from .process_id_combo import ProcessIdCombo` | `from ..bridges.process_id_combo import ProcessIdCombo` |
| `inspector/inspector_panel.py` | `from .model import GraphEditorModel` (абсолютный) | `from frontend.widgets.pipeline.pipeline_tab.canvas.model import GraphEditorModel` |
| `bridges/preview_bridge.py` | `from .constants import ...` | `from ..constants import ...` |
| `bridges/preview_bridge.py` | TYPE_CHECKING: `from frontend.widgets.pipeline_tab.inspector_node import InspectorBaseNode` | `from frontend.widgets.pipeline.pipeline_tab.inspector.inspector_node import InspectorBaseNode` |
| `views/view_switch.py` | TYPE_CHECKING: `from frontend.widgets.pipeline_tab.adapter import ...` | `from frontend.widgets.pipeline.pipeline_tab.canvas.adapter import ...` |
| `views/view_switch.py` | TYPE_CHECKING: `from frontend.widgets.pipeline_tab.table_view import ...` | `from frontend.widgets.pipeline.pipeline_tab.views.table_view import ...` |
| `widget.py` (корень) | `from frontend.widgets.pipeline_tab.adapter import ...` | `from .canvas.adapter import ...` |
| `widget.py` (корень) | `from frontend.widgets.pipeline_tab.inspector_panel import ...` | `from .inspector.inspector_panel import ...` |
| `widget.py` (корень) | `from frontend.widgets.pipeline_tab.library_palette import ...` | `from .library.library_palette import ...` |
| `widget.py` (корень) | `from frontend.widgets.pipeline_tab.model import ...` | `from .canvas.model import ...` |
| `widget.py` (корень) | `from frontend.widgets.pipeline_tab.table_view import ...` | `from .views.table_view import ...` |
| `widget.py` (корень) | `from frontend.widgets.pipeline_tab.view_switch import ...` | `from .views.view_switch import ...` |
| `widget.py` (корень) | `from NodeGraphQt import NodeGraph; from frontend.widgets.pipeline_tab.inspector_node import InspectorBaseNode` | `from .inspector.inspector_node import InspectorBaseNode` |
| `__init__.py` (корень) | `from .auto_layout import ...` | `from .canvas.auto_layout import ...` |
| `__init__.py` (корень) | `from .library_palette import ...` | `from .library.library_palette import ...` |
| `__init__.py` (корень) | `from .linearity_check import ...` | `from .canvas.linearity_check import ...` |
| `__init__.py` (корень) | `from .model import GraphEditorModel` | `from .canvas.model import GraphEditorModel` |
| `__init__.py` (корень) | `from .display_target_combo import ...` | `from .bridges.display_target_combo import ...` |
| `__init__.py` (корень) | `from .inspector_panel import InspectorPanel` | `from .inspector.inspector_panel import InspectorPanel` |
| `__init__.py` (корень) | `from .params_form import ParamsForm` | `from .inspector.params_form import ParamsForm` |
| `__init__.py` (корень) | `from .process_id_combo import ProcessIdCombo` | `from .bridges.process_id_combo import ProcessIdCombo` |
| `__init__.py` (корень) | `from .table_view import PipelineTableView` | `from .views.table_view import PipelineTableView` |
| `__init__.py` (корень) | `from .view_switch import PipelineViewSwitch` | `from .views.view_switch import PipelineViewSwitch` |

#### Внешние импортёры pipeline_tab

| Файл | Строка импорта | После Task 1.8 |
|---|---|---|
| `widgets/__init__.py:67` | `from .pipeline_tab.widget import PipelineTabWidget` | `from .pipeline.pipeline_tab.widget import PipelineTabWidget` |
| `widgets/__init__.py:16` (TYPE_CHECKING) | `from .pipeline_tab.widget import PipelineTabWidget` | `from .pipeline.pipeline_tab.widget import PipelineTabWidget` |
| `tab_factory.py:83` | `from multiprocess_prototype_v3.frontend.widgets.pipeline_tab.widget import PipelineTabWidget` | `...widgets.pipeline.pipeline_tab.widget import PipelineTabWidget` |

Каждый подпакет (`canvas/`, `inspector/`, `library/`, `views/`, `bridges/`) получает собственный `__init__.py` с реэкспортами публичных имён.

---

## Часть 2. Стратегия для `widgets/__init__.py` (Task 1.9)

### Текущее состояние

`widgets/__init__.py` реализует ленивый `__getattr__` для:
- `PipelineTabWidget` — из `pipeline_tab.widget`
- Всего из `tabs_setting` (17 имён: `TabsConfig`, `RecipesTabWidget`, и т.д.)

### После реорганизации

Нужно обновить только **два пути**:
1. `from .pipeline_tab.widget` → `from .pipeline.pipeline_tab.widget`
2. `tabs_setting` — **не меняется**, `tabs_setting/` остаётся на месте

### Публичные реэкспорты для feature-widgets

Добавлять публичные реэкспорты для `chrome/`, `sources/`, `recipes/`, `processing/` в `widgets/__init__.py` — **не нужно**. Мотивация:
- Внешние импортёры (`window.py`, `frontend_config.py`, `app_recipe_aggregate.py`, `tab_factory.py`) используют абсолютные пути (`from multiprocess_prototype_v3.frontend.widgets.X import Y`).
- После переезда они обновятся до `...widgets.chrome.X`, `...widgets.sources.X` и т.д. напрямую.
- `tabs_setting` использует относительные пути (`from ...X import Y`) — они обновляются там.
- Добавление реэкспортов в `widgets/__init__.py` только усложнит поддержку.

### Что остаётся в `__init__.py`

```python
# Меняется только эта строка (строки 66-67 и 16-17 TYPE_CHECKING):
from .pipeline_tab.widget import PipelineTabWidget
# → становится:
from .pipeline.pipeline_tab.widget import PipelineTabWidget
```

Ленивый `__getattr__` для `tabs_setting` — **без изменений**. `_LAZY_NAMES` — **без изменений**.

---

## Часть 3. Целевая структура

```
widgets/
├── __init__.py                          # обновлён: путь к pipeline_tab
├── _archive/
│   ├── __init__.py                      # пустой
│   ├── _hikvision_widget_legacy/
│   ├── catalog_editor/
│   ├── chain_editor/
│   └── recipes_cards/
├── _base/
│   ├── __init__.py                      # реэкспорты NavigationPanelBase, RecipePanelBase, create_field_widget
│   ├── navigation_panel_base.py         # был _navigation_panel_base.py
│   ├── recipe_panel_base.py             # был _recipe_panel_base.py
│   └── cards_field_factory/             # был widgets/cards_field_factory/
│       ├── __init__.py
│       └── factory.py
├── chrome/
│   ├── __init__.py
│   ├── app_header/
│   ├── recording_indicator/
│   ├── search_filter_bar/
│   ├── side_panels/
│   ├── view_mode_toggle/
│   └── watchdog_overlay/
├── sources/
│   ├── __init__.py
│   ├── camera_common/
│   ├── display_window/
│   └── hikvision_camera_mvp/
├── recipes/
│   ├── __init__.py
│   ├── recipes_slot_buttons/
│   ├── recipes_widget/
│   ├── settings_profile_widget/
│   └── settings_recipe_widget/
├── processing/
│   ├── __init__.py
│   ├── cropped_regions_widget/
│   ├── post_processing_widget/
│   └── processing_panel_widget/
├── pipeline/
│   ├── __init__.py
│   └── pipeline_tab/
│       ├── __init__.py                  # обновлённые реэкспорты
│       ├── constants.py
│       ├── widget.py
│       ├── canvas/
│       │   ├── __init__.py
│       │   ├── adapter.py
│       │   ├── auto_layout.py
│       │   ├── linearity_check.py
│       │   └── model.py
│       ├── inspector/
│       │   ├── __init__.py
│       │   ├── inspector_node.py
│       │   ├── inspector_panel.py
│       │   └── params_form.py
│       ├── library/
│       │   ├── __init__.py
│       │   ├── context_menu.py
│       │   └── library_palette.py
│       ├── views/
│       │   ├── __init__.py
│       │   ├── _layout_constants.py
│       │   ├── table_view.py
│       │   └── view_switch.py
│       └── bridges/
│           ├── __init__.py
│           ├── display_target_combo.py
│           ├── preview_bridge.py
│           └── process_id_combo.py
├── settings/
│   ├── __init__.py
│   └── settings_tab/                    # весь текущий settings_tab/
│       ├── __init__.py
│       ├── admin_section.py
│       ├── history_section.py
│       ├── prefs_store.py
│       ├── settings_cards.py
│       ├── settings_nav_panel.py
│       ├── settings_table.py
│       ├── system_section.py
│       ├── ui_preferences_schema.py
│       ├── ui_section.py
│       └── widget.py
└── tabs_setting/                        # БЕЗ ИЗМЕНЕНИЙ
    ├── __init__.py
    ├── tab_item_config.py
    ├── tabs_config.py
    ├── camera_tab/
    ├── cropped_regions_tab/
    ├── display_tab/
    ├── post_processing_tab/
    ├── processing_tab/
    ├── recipes_settings_tab/
    ├── recipes_tab/
    └── sources_tab/
```

---

## Часть 4. Декомпозиция на задачи (Task X.Y)

### Task 1.0 — Создать worktree и snapshot-тег

**Уровень:** Senior (Opus, normal)
**Исполнитель:** teamlead
**Цель:** Изолировать рефакторинг в отдельном git-worktree; создать тег `widgets-reorg-start`.

**Файлы:** только git-операции, никаких файлов проекта.

**Шаги:**
1. Создать worktree: `git -C /Users/twokrai/Project_code/obsidian/projects/Inspector_bottles worktree add ../Inspector_bottles_reorg main`
2. Создать тег: `git -C .../Inspector_bottles tag widgets-reorg-start main`
3. Проверить, что в worktree работает `python -c "from multiprocess_prototype_v3.frontend.windows.main_window.window import MainWindow"` (без Qt, только синтаксис импортов — если падает на Qt, это ожидаемо; важен `ModuleNotFoundError`)

**Критерии приёмки:**
- [ ] Worktree создан, ветка `feat/widgets-reorg` оформлена
- [ ] Тег `widgets-reorg-start` присутствует

**Вне scope:** любые изменения в коде.

---

### Task 1.1 — Создать `_archive/`, переместить dead-code

**Уровень:** Middle (Sonnet, normal)
**Исполнитель:** developer
**Цель:** Убрать 4 dead/empty пакета в `_archive/` без изменения импортов.

**Файлы:**
- Создать `widgets/_archive/__init__.py` (пустой)
- Переместить: `recipes_cards/`, `_hikvision_widget_legacy/`, `catalog_editor/`, `chain_editor/`

**Шаги:**
1. `mkdir widgets/_archive && touch widgets/_archive/__init__.py`
2. `mv widgets/recipes_cards widgets/_archive/`
3. `mv widgets/_hikvision_widget_legacy widgets/_archive/`
4. `mv widgets/catalog_editor widgets/_archive/`
5. `mv widgets/chain_editor widgets/_archive/`
6. Убедиться: `grep -rn "catalog_editor\|chain_editor\|hikvision_widget_legacy\|recipes_cards" frontend/ --include="*.py"` возвращает **нулевые** прямые импорты (возможны упоминания в комментариях — OK).

**Критерии приёмки:**
- [ ] `python -c "import multiprocess_prototype_v3.frontend.widgets"` не падает с ImportError
- [ ] Перечисленные пакеты отсутствуют в корне `widgets/`
- [ ] Git commit: `feat(widgets): перенести dead-code в _archive/`

**Вне scope:** изменения в живом коде.
**Зависимости:** Task 1.0

---

### Task 1.2 — Создать `_base/`, перенести base-файлы

**Уровень:** Middle+ (Sonnet, extended)
**Исполнитель:** developer
**Цель:** Перенести `_navigation_panel_base.py`, `_recipe_panel_base.py`, `cards_field_factory/` в `_base/`; обновить все импорты наследников.

**Файлы:**
- Создать `widgets/_base/__init__.py`
- Переместить `widgets/_navigation_panel_base.py` → `widgets/_base/navigation_panel_base.py`
- Переместить `widgets/_recipe_panel_base.py` → `widgets/_base/recipe_panel_base.py`
- Переместить `widgets/cards_field_factory/` → `widgets/_base/cards_field_factory/`
- Изменить:
  - `widgets/recipes_slot_buttons/panel.py`
  - `widgets/settings_tab/settings_nav_panel.py`
  - `widgets/recipes_widget/panel_widget.py`
  - `widgets/settings_recipe_widget/panel_widget.py`
  - `widgets/settings_tab/settings_cards.py`

**Шаги:**
1. Создать `widgets/_base/` + `__init__.py` с реэкспортами (см. §1.3).
2. Переместить `_navigation_panel_base.py` → `_base/navigation_panel_base.py`.
3. Переместить `_recipe_panel_base.py` → `_base/recipe_panel_base.py`.
4. Переместить `cards_field_factory/` → `_base/cards_field_factory/`.
5. В `recipes_slot_buttons/panel.py`: `from .._navigation_panel_base` → `from .._base.navigation_panel_base`
6. В `settings_tab/settings_nav_panel.py`: аналогично.
7. В `recipes_widget/panel_widget.py`: `from .._recipe_panel_base` → `from .._base.recipe_panel_base`
8. В `settings_recipe_widget/panel_widget.py`: аналогично.
9. В `settings_tab/settings_cards.py`: `from ..cards_field_factory` → `from .._base.cards_field_factory`
10. Прогнать `grep -rn "_navigation_panel_base\|_recipe_panel_base\|cards_field_factory" frontend/ --include="*.py"` — убедиться, что всё заменено.

**Критерии приёмки:**
- [ ] `python -c "from multiprocess_prototype_v3.frontend.widgets._base import NavigationPanelBase, RecipePanelBase, create_field_widget"` (pure-python, без Qt) — импорт проходит (могут быть Qt-ошибки при исполнении, но не ModuleNotFoundError)
- [ ] Git commit: `feat(widgets): создать _base/, перенести base-классы`

**Зависимости:** Task 1.1

---

### Task 1.3 — Создать `chrome/`, мигрировать 6 пакетов

**Уровень:** Middle+ (Sonnet, extended)
**Исполнитель:** developer
**Цель:** Сгруппировать chrome-виджеты в `chrome/`; обновить импорты во всех потребителях.

**Файлы:**
- Создать `widgets/chrome/__init__.py`
- Переместить: `app_header/`, `side_panels/`, `watchdog_overlay/`, `recording_indicator/`, `view_mode_toggle/`, `search_filter_bar/`
- Изменить:
  - `windows/main_window/window.py` (строки 21, 22, 27)
  - `tabs_setting/recipes_tab/widget.py` (строка 72: `view_mode_toggle`)
  - `settings_tab/widget.py` (строка 39: `view_mode_toggle`)
  - `settings_tab/ui_section.py` (строка 13: `search_filter_bar`)
  - `settings_tab/system_section.py` (строка 23: `search_filter_bar`)
  - Если `display_window/widget.py` импортирует `recording_indicator` — обновить (grep необходим; `display_window` переезжает в Task 1.4, поэтому при обнаружении относительного импорта `..recording_indicator` надо заменить на `..chrome.recording_indicator` — **с учётом будущего переезда display_window в sources/**: после Task 1.4 станет `...chrome.recording_indicator`)

**Шаги:**
1. `mkdir widgets/chrome && touch widgets/chrome/__init__.py`
2. Переместить 6 пакетов.
3. Выполнить `grep -rn "from.*view_mode_toggle\|from.*search_filter_bar\|from.*app_header\|from.*side_panels\|from.*watchdog_overlay\|from.*recording_indicator" frontend/ --include="*.py"` — получить полный список.
4. Обновить все найденные импорты.
5. Проверить: нет ни одного импорта из старых путей (кроме `_archive/`).

**Критерии приёмки:**
- [ ] `grep -rn "widgets.app_header\|widgets.side_panels\|widgets.watchdog_overlay" frontend/ --include="*.py"` возвращает 0 результатов за пределами `_archive/`
- [ ] Git commit: `feat(widgets): создать chrome/, перенести chrome-виджеты`

**Зависимости:** Task 1.2

---

### Task 1.4 — Создать `sources/`, мигрировать camera + display

**Уровень:** Middle+ (Sonnet, extended)
**Исполнитель:** developer
**Цель:** Сгруппировать источники данных в `sources/`; особое внимание — `window_manager.py` использует нестандартный путь `from frontend.widgets.display_window.widget`.

**Файлы:**
- Создать `widgets/sources/__init__.py`
- Переместить: `camera_common/`, `hikvision_camera_mvp/`, `display_window/`
- Изменить:
  - `tabs_setting/camera_tab/widget.py` (`from ...camera_common`)
  - `tabs_setting/camera_tab/__init__.py` (`from ...camera_common`)
  - `tabs_setting/camera_tab/widget.py` (Hikvision — уточнить grep)
  - `managers/window_manager.py:85` (`from frontend.widgets.display_window.widget`)
  - Если в `display_window/widget.py` есть импорт `recording_indicator` — обновить: `from ..recording_indicator` → `from ..chrome.recording_indicator` (поскольку display_window теперь в `sources/`, а chrome — в `chrome/`)

**Шаги:**
1. `mkdir widgets/sources && touch widgets/sources/__init__.py`
2. Переместить `camera_common/`, `hikvision_camera_mvp/`, `display_window/`.
3. Выполнить `grep -rn "from.*camera_common\|from.*hikvision_camera_mvp\|from.*display_window" frontend/ --include="*.py"` — получить полный список.
4. Обновить все найденные импорты.
5. Обновить `managers/window_manager.py:85`.
6. Проверить наличие импорта `recording_indicator` в `display_window/widget.py`, обновить при необходимости.

**Критерии приёмки:**
- [ ] `grep -rn "widgets.camera_common\|widgets.hikvision_camera_mvp\|widgets.display_window" frontend/ --include="*.py"` возвращает 0 за пределами `_archive/`
- [ ] Git commit: `feat(widgets): создать sources/, перенести camera + display`

**Зависимости:** Task 1.3

---

### Task 1.5 — Создать `recipes/`, мигрировать 4 пакета

**Уровень:** Middle+ (Sonnet, extended)
**Исполнитель:** developer
**Цель:** Сгруппировать recipes-кластер; обновить абсолютные и относительные импорты, в т.ч. в `configs/frontend_config.py` и `managers/app_recipe_aggregate.py`.

**Файлы:**
- Создать `widgets/recipes/__init__.py`
- Переместить: `recipes_widget/`, `settings_recipe_widget/`, `settings_profile_widget/`, `recipes_slot_buttons/`
- Изменить:
  - `tabs_setting/recipes_tab/__init__.py`
  - `tabs_setting/recipes_tab/widget.py`
  - `tabs_setting/recipes_settings_tab/widget.py`
  - `settings_tab/widget.py`
  - `managers/app_recipe_aggregate.py`
  - `configs/frontend_config.py`

**Шаги:**
1. `mkdir widgets/recipes && touch widgets/recipes/__init__.py`
2. Переместить 4 пакета.
3. Выполнить `grep -rn "settings_recipe_widget\|recipes_widget\|settings_profile_widget\|recipes_slot_buttons" frontend/ --include="*.py"` — полный список.
4. Обновить все относительные пути: `...X` → `...recipes.X` (где X — один из 4 пакетов).
5. Обновить абсолютные: `...widgets.settings_recipe_widget` → `...widgets.recipes.settings_recipe_widget`.
6. Убедиться: `python -c "from multiprocess_prototype_v3.frontend.widgets.recipes.settings_recipe_widget.schemas import RecipesTabConfig"` (pure-python без Qt).

**Критерии приёмки:**
- [ ] `grep -rn "widgets.recipes_widget\|widgets.settings_recipe_widget\|widgets.settings_profile_widget\|widgets.recipes_slot_buttons" frontend/ --include="*.py"` возвращает 0 за пределами `_archive/`
- [ ] `python -c "from multiprocess_prototype_v3.frontend.managers.app_recipe_aggregate import app_recipe_schema_names"` работает (pure-python)
- [ ] Git commit: `feat(widgets): создать recipes/, перенести recipes-кластер`

**Зависимости:** Task 1.4

---

### Task 1.6 — Создать `processing/`, мигрировать 3 пакета

**Уровень:** Middle+ (Sonnet, extended)
**Исполнитель:** developer
**Цель:** Сгруппировать processing-кластер; обновить импорты в `tabs_setting/`, `configs/frontend_config.py`, `managers/`.

**Файлы:**
- Создать `widgets/processing/__init__.py`
- Переместить: `processing_panel_widget/`, `post_processing_widget/`, `cropped_regions_widget/`
- Изменить:
  - `tabs_setting/processing_tab/__init__.py`
  - `tabs_setting/post_processing_tab/widget.py`
  - `tabs_setting/cropped_regions_tab/__init__.py`
  - `configs/frontend_config.py`
  - `managers/app_recipe_aggregate.py`

**Шаги:**
1. `mkdir widgets/processing && touch widgets/processing/__init__.py`
2. Переместить 3 пакета.
3. `grep -rn "processing_panel_widget\|post_processing_widget\|cropped_regions_widget" frontend/ --include="*.py"` — полный список.
4. Обновить все относительные: `...processing_panel_widget` → `...processing.processing_panel_widget` и т.д.
5. Обновить абсолютные в `configs/frontend_config.py` и `managers/app_recipe_aggregate.py`.

**Критерии приёмки:**
- [ ] `grep -rn "widgets.processing_panel_widget\|widgets.post_processing_widget\|widgets.cropped_regions_widget" frontend/ --include="*.py"` возвращает 0 за пределами `_archive/`
- [ ] Git commit: `feat(widgets): создать processing/, перенести processing-кластер`

**Зависимости:** Task 1.5

---

### Task 1.7 — Создать `settings/`, мигрировать settings_tab

**Уровень:** Middle+ (Sonnet, extended)
**Исполнитель:** developer
**Цель:** Переместить `settings_tab/` в `settings/settings_tab/`; исправить уровни относительных путей внутри пакета.

**Файлы:**
- Создать `widgets/settings/__init__.py`
- Переместить `settings_tab/` → `settings/settings_tab/`
- Изменить:
  - `windows/main_window/tab_factory.py:19`
  - `managers/app_recipe_aggregate.py:27`
  - Внутри `settings/settings_tab/widget.py:38` — путь `from ..tabs_setting.recipes_settings_tab.schemas` → `from ...tabs_setting.recipes_settings_tab.schemas` (добавить один уровень `..`)

**Шаги:**
1. `mkdir widgets/settings && touch widgets/settings/__init__.py`
2. `mv widgets/settings_tab widgets/settings/settings_tab`
3. Обновить `tab_factory.py:19`: `...widgets.settings_tab` → `...widgets.settings.settings_tab`
4. Обновить `managers/app_recipe_aggregate.py:27`: `...widgets.settings_tab.ui_preferences_schema` → `...widgets.settings.settings_tab.ui_preferences_schema`
5. Внутри перемещённого `settings/settings_tab/widget.py`: `from ..tabs_setting.` → `from ...tabs_setting.`
6. Выполнить полный grep по `settings_tab` в `frontend/` для поиска пропущенных ссылок.

**Критерии приёмки:**
- [ ] `grep -rn "widgets.settings_tab" frontend/ --include="*.py"` возвращает 0 за пределами `_archive/` (кроме самого пакета внутри `settings/`)
- [ ] `python -c "from multiprocess_prototype_v3.frontend.widgets.settings.settings_tab import SettingsContainerWidget"` — нет ModuleNotFoundError (Qt-ошибки допустимы)
- [ ] Git commit: `feat(widgets): создать settings/, перенести settings_tab`

**Зависимости:** Task 1.6

---

### Task 1.8 — Создать `pipeline/`, мигрировать и разбить pipeline_tab

**Уровень:** Senior+ (Opus, extended)
**Исполнитель:** teamlead
**Цель:** Переместить `pipeline_tab/` в `pipeline/pipeline_tab/` и разбить 18 файлов на 5 подпакетов; обновить все внутренние и внешние импорты.

**Файлы:**
- Создать `widgets/pipeline/__init__.py`
- Создать `widgets/pipeline/pipeline_tab/` со структурой из §1.9 выше
- Создать `canvas/__init__.py`, `inspector/__init__.py`, `library/__init__.py`, `views/__init__.py`, `bridges/__init__.py`
- Переместить файлы по подпакетам согласно таблице §1.9
- Обновить `widgets/__init__.py` (строки 16-17, 66-68)
- Обновить `tab_factory.py:83`
- Обновить всё внутри `pipeline_tab/` согласно таблице §1.9

**Шаги:**
1. Создать структуру папок `pipeline/pipeline_tab/{canvas,inspector,library,views,bridges}/`.
2. Создать `__init__.py` для каждой папки.
3. Переместить файлы согласно таблице (18 файлов).
4. Обновить внутренние импорты пофайлово (таблица §1.9 — 20+ замен).
5. Обновить `pipeline_tab/__init__.py` — все реэкспорты (таблица §1.9, строки `__init__.py`).
6. Обновить `pipeline_tab/widget.py` — импорты адаптера, инспектора, палитры, модели, view_switch, table_view.
7. Обновить `widgets/__init__.py`: `from .pipeline_tab.widget` → `from .pipeline.pipeline_tab.widget`
8. Обновить `tab_factory.py:83`: `...widgets.pipeline_tab.widget` → `...widgets.pipeline.pipeline_tab.widget`
9. Прогнать `grep -rn "widgets.pipeline_tab\|from .pipeline_tab\|from ..pipeline_tab" frontend/ --include="*.py"` — должно быть 0 за пределами нового пути.

**Критерии приёмки:**
- [ ] `python -c "from multiprocess_prototype_v3.frontend.widgets.pipeline.pipeline_tab.canvas.model import GraphEditorModel"` — нет ModuleNotFoundError
- [ ] `python -c "from multiprocess_prototype_v3.frontend.widgets.pipeline.pipeline_tab.widget import PipelineTabWidget"` — нет ModuleNotFoundError (Qt-ошибки допустимы)
- [ ] `python -c "from multiprocess_prototype_v3.frontend.widgets import PipelineTabWidget"` через `__getattr__` — нет ModuleNotFoundError
- [ ] Git commit: `feat(widgets): создать pipeline/, разбить pipeline_tab на подпакеты`

**Зависимости:** Task 1.7

---

### Task 1.9 — Финальное обновление `widgets/__init__.py`

**Уровень:** Middle (Sonnet, normal)
**Исполнитель:** developer
**Цель:** Убедиться, что ленивые реэкспорты в `widgets/__init__.py` корректны; провести smoke-test без PyQt.

**Файлы:**
- `widgets/__init__.py` (финальная проверка)

**Шаги:**
1. Проверить, что строки 16-17 (TYPE_CHECKING) и 66-68 (`__getattr__`) указывают на `pipeline.pipeline_tab.widget`.
2. Проверить, что `tabs_setting` импорт в строках 17-36 и `__getattr__` не изменился (tabs_setting не переезжал).
3. Smoke-test без Qt:
   ```python
   import sys; sys.modules['PySide6'] = None  # грубый mock
   import multiprocess_prototype_v3.frontend.widgets as w
   assert 'PipelineTabWidget' in w.__all__
   assert 'RecipesTabWidget' in w.__all__
   ```
   Либо более мягкий вариант: проверить, что `_LAZY_NAMES` содержит ожидаемые имена.
4. Полный grep на оставшиеся старые пути.

**Критерии приёмки:**
- [ ] `python -c "import multiprocess_prototype_v3.frontend.widgets"` без Qt не вызывает ImportError
- [ ] `_LAZY_NAMES` и `__all__` содержат все ожидаемые имена
- [ ] Git commit: `feat(widgets): финализировать __init__.py после реорганизации`

**Зависимости:** Task 1.8

---

### Task 1.10 — Финальный smoke-test и верификация

**Уровень:** Senior (Opus, normal)
**Исполнитель:** teamlead
**Цель:** Прогнать все acceptance criteria; убедиться, что ничего не упущено; смержить в main.

**Шаги:**
1. `python -c "from multiprocess_prototype_v3.frontend.windows.main_window.window import MainWindow"` (с Qt в окружении, или убедиться что нет ModuleNotFoundError).
2. `python Inspector_prototype/scripts/validate.py` из `Inspector_prototype/`.
3. `python Inspector_prototype/scripts/run_framework_tests.py`.
4. `pytest Inspector_prototype/ -v --tb=short`.
5. Полный grep: `grep -rn "from.*frontend.widgets\." Inspector_prototype/ --include="*.py" | grep -v "_archive\|\.pyc"` — проверить, что нет старых путей.
6. Проверить, что все 28 исходных пакетов находятся либо в `_archive/`, либо в новом расположении: `find widgets/ -name "__init__.py" | grep -v __pycache__ | sort`.
7. При прохождении всех критериев: `git -C .../Inspector_bottles merge feat/widgets-reorg --no-ff`.

**Критерии приёмки:**
- [ ] `python -c "from multiprocess_prototype_v3.frontend.windows.main_window.window import MainWindow"` — нет ImportError/ModuleNotFoundError
- [ ] `python Inspector_prototype/scripts/validate.py` — PASS
- [ ] `python Inspector_prototype/scripts/run_framework_tests.py` — PASS
- [ ] `pytest` из `Inspector_prototype/` — 0 упавших тестов (или те же, что были до начала реорганизации)
- [ ] Все 28 пакетов учтены (4 в `_archive/`, 24 в новых папках)
- [ ] `widgets/__init__.py` ленивые реэкспорты работают

**Зависимости:** Task 1.9

---

## Часть 5. Acceptance criteria всей реорганизации

- [ ] `python -c "from multiprocess_prototype_v3.frontend.windows.main_window.window import MainWindow"` — нет ModuleNotFoundError
- [ ] `python Inspector_prototype/scripts/validate.py` — PASS
- [ ] `python Inspector_prototype/scripts/run_framework_tests.py` — PASS
- [ ] `pytest` из `Inspector_prototype/` — не хуже baseline (до начала работ зафиксировать baseline)
- [ ] Прототип запускается: `python -m multiprocess_prototype_v3.run` (или `/run-proto`)
- [ ] Все 28 исходных пакетов либо в новой папке, либо в `_archive/` — ничего не потеряно
- [ ] `widgets/__init__.py` smoke-test без PyQt: `python -c "import importlib; m = importlib.util.find_spec('multiprocess_prototype_v3.frontend.widgets'); print('OK' if m else 'FAIL')"` — OK
- [ ] Grep на старые пути возвращает 0 результатов в `frontend/` (кроме `_archive/` и комментариев)

---

## Часть 6. Риски и точки отказа

### Риск 1: Ленивые реэкспорты `widgets/__init__.py` (высокий)

`widgets/__init__.py` содержит `__getattr__` для `PipelineTabWidget` и всего из `tabs_setting`. При обновлении строк 16-17 и 66-68 на новый путь `pipeline.pipeline_tab.widget` важно:
- Не нарушить имена в `_LAZY_NAMES` (они не содержат путей — только имена классов, т.е. этот риск ниже)
- Не трогать `tabs_setting` блок (он не изменяется)
- TYPE_CHECKING блок (строки 16-36) — нужно обновить `from .pipeline_tab.widget` на `from .pipeline.pipeline_tab.widget`

**Mitigation:** в Task 1.8 после переезда pipeline немедленно запустить smoke-test `widgets/__init__.py`.

### Риск 2: Тесты с прямыми путями импорта (средний)

`recipes_widget/__init__.py` экспортирует `RecipeSlotComboModel` как pure-Python объект без Qt-зависимостей. Если тесты импортируют его по пути `multiprocess_prototype_v3.frontend.widgets.recipes_widget.slot_combo_model`, после переезда путь станет `...widgets.recipes.recipes_widget.slot_combo_model`.

Тесты находятся в `Inspector_prototype/tests/` (путь из `pyproject.toml`): `testpaths = ["Inspector_prototype/multiprocess_framework/refactored", "Inspector_prototype/multiprocess_prototype/tests"]`. Эти пути — архивные версии, не v3.

**Action:** в Task 1.5 (recipes) выполнить `grep -rn "recipes_widget\|slot_combo_model\|recipe_rows" Inspector_prototype/ --include="test_*.py"` чтобы найти тесты v3. Если найдутся — обновить пути.

### Риск 3: `window_manager.py` — нестандартный путь (высокий)

Строка `from frontend.widgets.display_window.widget import DisplayWindow` использует путь без `multiprocess_prototype_v3`-префикса. Это работает, потому что `Inspector_prototype/multiprocess_prototype_v3/` в sys.path. После переезда `display_window` в `sources/` путь станет `from frontend.widgets.sources.display_window.widget`. Если sys.path другой — может упасть.

**Action:** в Task 1.4 изменить строку 85, после чего проверить `python -c "from multiprocess_prototype_v3.frontend.managers.window_manager import DisplayWindowManager"`.

### Риск 4: Перекрёстная зависимость `display_window` ↔ `recording_indicator` (средний)

`display_window/` может иметь относительный импорт `from ..recording_indicator import RecordingIndicator`. После Task 1.3 `recording_indicator` переедет в `chrome/`. До Task 1.4 `display_window` ещё в старом месте. В Task 1.3 нужно одновременно обновить `display_window/widget.py` — иначе после Task 1.3 и до Task 1.4 будет сломан импорт `display_window`.

**Mitigation:** В Task 1.3 обновить `display_window/widget.py` вместе с остальными chrome-потребителями: `from ..recording_indicator` → `from ..chrome.recording_indicator`.

### Риск 5: Внутренние импорты `pipeline_tab` — абсолютные пути (высокий)

Файлы `pipeline_tab` используют два стиля путей:
- Абсолютный: `from frontend.widgets.pipeline_tab.X import ...`
- Относительный: `from .X import ...`

После разбивки оба стиля требуют изменений. Абсолютные пути `from frontend.widgets.pipeline_tab.X` превращаются в `from frontend.widgets.pipeline.pipeline_tab.subpkg.X`. Это ~20 замен в 15 файлах.

**Mitigation:** В Task 1.8 TeamLead создаёт временный `pipeline_tab/compat.py` с реэкспортами для обратной совместимости, который удаляется в конце Task 1.8 после верификации. Альтернатива — работать построчно по таблице §1.9.

### Риск 6: Pickling (низкий)

Pickle сохраняет полный путь класса. Если где-то пикклируется `ProcessingPanelWidget`, `GraphEditorModel` и т.д. — после переезда unpickle сломается. В текущей архитектуре Dict at Boundary — pickle widget-классов не используется. Но `pipeline_tab/model.py` оперирует dict'ами, не схемами. **Проверить:** `grep -rn "pickle\|cloudpickle" Inspector_prototype/ --include="*.py"` — если нет, риск нулевой.

### Риск 7: Qt resource paths (низкий)

Если виджеты используют `__file__`-relative пути к QSS/иконкам — переезд папки сломает их. **Action:** `grep -rn "__file__\|Path(__file__)" frontend/widgets/ --include="*.py"` — если найдутся, обновить перед переездом соответствующего пакета.

### Риск 8: `settings_tab/widget.py` — относительный путь к `tabs_setting` (средний)

Строка 38: `from ..tabs_setting.recipes_settings_tab.schemas import SettingsTabConfig`. Сейчас `settings_tab` находится в `widgets/settings_tab/`, и `..` указывает на `widgets/`. После переезда в `widgets/settings/settings_tab/` путь `..` указывает на `widgets/settings/`, а не на `widgets/`. Нужно изменить на `...tabs_setting.recipes_settings_tab.schemas` (три точки вместо двух).

**Action:** В Task 1.7 это прямо указано в шагах; нужно grep'нуть все `..tabs_setting` внутри `settings_tab/*.py`.

---

## Часть 7. Стратегия исполнения

### Worktree isolation

```bash
# TeamLead создаёт worktree
git -C /Users/twokrai/Project_code/obsidian/projects/Inspector_bottles \
    worktree add ../Inspector_bottles_reorg feat/widgets-reorg
```

Developer работает только в worktree. После прохождения Task 1.10:
```bash
git -C /Users/twokrai/Project_code/obsidian/projects/Inspector_bottles \
    merge feat/widgets-reorg --no-ff -m "feat(widgets): реорганизация frontend/widgets/ по доменам"
git -C .../Inspector_bottles worktree remove ../Inspector_bottles_reorg
```

### Порядок коммитов

Каждая Task X.Y — один коммит на русском языке. Пример:
- `feat(widgets): перенести dead-code в _archive/ [Task 1.1]`
- `feat(widgets): создать _base/, перенести base-классы [Task 1.2]`
- `feat(widgets): создать chrome/, перенести chrome-виджеты [Task 1.3]`
- и т.д.

### Остановка на произвольной Task

После каждого коммита приложение должно оставаться работоспособным. Это обеспечивается тем, что:
- Task 1.1 не затрагивает живой код
- Task 1.2-1.9 каждая обновляет импорты одновременно с перемещением пакетов

### Debugger-агент

Если после любой Task падают тесты — TeamLead запускает отдельного агента-debugger с заданием: `root-cause import error в ФАЙЛ.py` с полным traceback.

---

## Порядок выполнения фаз

```
Phase 1 (риск ~0):  Task 1.0 → Task 1.1
Phase 2 (риск низкий): Task 1.2
Phase 3 (риск средний): Task 1.3 → Task 1.4 → Task 1.5 → Task 1.6 → Task 1.7
Phase 4 (риск высокий): Task 1.8
Phase 5 (финализация): Task 1.9 → Task 1.10
```

**Оценка объёма правок:**
- Task 1.1: 0 правок в py-файлах (только git mv)
- Task 1.2: ~5 файлов, ~5 строк
- Task 1.3: ~7 файлов, ~12 строк
- Task 1.4: ~5 файлов, ~8 строк
- Task 1.5: ~8 файлов, ~15 строк (самый широкий: managers + configs)
- Task 1.6: ~6 файлов, ~10 строк
- Task 1.7: ~4 файла, ~8 строк (риск относительных уровней)
- Task 1.8: ~18 файлов перемещений + ~20 правок импортов (~45 строк)
- Task 1.9: 1 файл, 2 строки
- Task 1.10: только верификация

**Итого:** ~54 файла, ~103 строки изменений. Основная сложность — Task 1.8.
