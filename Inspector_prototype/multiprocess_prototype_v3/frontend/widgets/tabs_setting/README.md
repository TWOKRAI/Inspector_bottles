# tabs_setting — полоса вкладок и оболочки

Здесь живут **`TabItemConfig`**, **`TabsConfig`** и тонкие вкладки **`BaseTab`**, которые либо показывают placeholder без `RegistersManager`, либо встраивают фиче-виджеты из `widgets/`.

Папки **`recipes_tab/`** и **`recipes_settings_tab/`** — оболочки вкладок; ключи фабрики по-прежнему **`recipes`** и **`settings`** (см. `tab_factory.py`).

## Состав пакета

```mermaid
flowchart TB
    subgraph root["Корень tabs_setting"]
        TIC[tab_item_config.py TabItemConfig]
        TC[tabs_config.py TabsConfig]
        INIT[__init__.py реэкспорт]
    end

    subgraph shells["Оболочки"]
        CAM[camera_tab]
        REC[recipes_tab]
        SET[recipes_settings_tab]
        PRO[processing_tab]
        CRO[cropped_regions_tab]
    end

    TC --> TIC
    CAM --> CTW[CameraTabWidget]
    REC --> RTW[RecipesTabWidget]
    SET --> STW[SettingsTabWidget]
    PRO --> PTW[ProcessingTabWidget]
    CRO --> CRTW[CroppedRegionsTabWidget]
```

## Подпакеты

| Папка | Виджет | Встраиваемый фиче-пакет | README |
|-------|--------|-------------------------|--------|
| `camera_tab/` | `CameraTabWidget` | `camera_common`, `hikvision_widget` | [camera_tab/README.md](camera_tab/README.md) |
| `recipes_tab/` | `RecipesTabWidget` | `recipes_widget` | [recipes_tab/README.md](recipes_tab/README.md) |
| `recipes_settings_tab/` | `SettingsTabWidget` | `settings_recipe_widget` | [recipes_settings_tab/README.md](recipes_settings_tab/README.md) |
| `processing_tab/` | `ProcessingTabWidget` | `processing_panel_widget` | [processing_tab/README.md](processing_tab/README.md) |
| `cropped_regions_tab/` | `CroppedRegionsTabWidget` | `cropped_regions_widget` | [cropped_regions_tab/README.md](cropped_regions_tab/README.md) |

## Файлы верхнего уровня

| Файл | Назначение |
|------|------------|
| `tab_item_config.py` | `TabItemConfig` — `id`, `title`, `widget` (ключ фабрики) |
| `tabs_config.py` | `TabsConfig` — список вкладок по умолчанию, `to_tabs_dict_list()` |
| `__init__.py` | Публичный API для `widgets/__init__.py` |

## Связь с `tab_factory`

Ключ **`widget`** в `TabItemConfig` сопоставляется фабрике главного окна (`recipes`, `settings`, `processing`, `cropped_regions`, `camera`). См. документацию лаунчера / `FRONTEND_MAP.md`.

## Документация фреймворка

- [TAB_STRUCTURE.md](../../../../multiprocess_framework/modules/frontend_module/widgets/tabs/TAB_STRUCTURE.md)
