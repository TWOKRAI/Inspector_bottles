# settings_recipe_widget

Пакет вкладки **settings** (app/UI-рецепт). **App recipe** panel: UI presets (`RecipesTabConfig` + `ProcessingTabUiConfig` aggregate), table of `SchemaBase` fields, load/save per slot via `RecipeManager` app snapshots.

## Классы и MVP

```mermaid
classDiagram
    direction TB
    class AppRecipePanelWidget {
        +BaseWidget
        parse_slot()
        refresh_table_rows()
    }
    class AppRecipePresenter
    class AppRecipeModel
    class AppRecipePanelViewProtocol {
        <<Protocol>>
    }
    class StructuredTableWidget

    AppRecipePanelWidget --|> BaseWidget : extends
    AppRecipePanelWidget ..|> AppRecipePanelViewProtocol : implements
    AppRecipePresenter --> AppRecipePanelViewProtocol : view
    AppRecipePresenter --> AppRecipeModel : model
    AppRecipePanelWidget --> StructuredTableWidget : _table
```

## Поток данных

```mermaid
sequenceDiagram
    participant U as Пользователь
    participant W as AppRecipePanelWidget
    participant Pr as AppRecipePresenter
    participant M as AppRecipeModel
    participant Y as RecipeManager / YAML

    U->>W: Load / Save / Default
    W->>Pr: on_load_clicked / save / default
    Pr->>Y: load_app_recipe_snapshot / save_app_recipe_snapshot
    Y-->>Pr: dict snapshot
    Pr->>M: app_aggregate update
    Pr->>W: refresh_table_rows
    U->>W: правка ячейки таблицы
    W->>Pr: on_table_value_changed
    Pr->>M: update_field / model_copy
```

## Files

| Файл | Классы / содержимое |
|------|---------------------|
| `panel_widget.py` | `AppRecipePanelWidget` — UI: слот, кнопки, `StructuredTableWidget` |
| `presenter.py` | `AppRecipePresenter` — слоты, таблица, агрегат |
| `model.py` | `AppRecipeModel` — `app_aggregate`, `recipe_manager`, `access_ctx` |
| `view.py` | `AppRecipePanelViewProtocol` — контракт для презентера |
| `app_recipe_rows.py` | `build_app_recipe_rows`, `_field_editable` — строки таблицы |

## Dependencies

- **`RecipeManagerProtocol`** — `load_app_recipe_snapshot` / `save_app_recipe_snapshot` / current app slot
- **`app_recipe_aggregate`** for default/merge semantics

## Embedding

`tabs_setting.recipes_settings_tab.SettingsTabWidget` embeds this panel next to draw controls.
