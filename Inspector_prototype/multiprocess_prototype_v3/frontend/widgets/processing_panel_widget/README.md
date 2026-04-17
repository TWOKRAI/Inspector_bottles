# processing_panel_widget

Feature widget: processor + renderer **register** fields (sliders / checkboxes) bound via `RegistersManager`.

## Устройство UI (блоки)

```mermaid
flowchart TB
    subgraph P["ProcessingPanelWidget"]
        G1["QGroupBox: BGR lower / upper"]
        G2["QGroupBox: min_area, max_area"]
        G3["QGroupBox: renderer checkboxes"]
    end

    subgraph Reg["Регистры"]
        PR[PROCESSOR_REGISTER]
        RR[RENDERER_REGISTER]
    end

    G1 -->|CompoundNumericControl| PR
    G2 -->|NumericControl| PR
    G3 -->|CheckboxControl| RR
```

## Классы

```mermaid
classDiagram
    class ProcessingPanelWidget {
        +BaseWidget
    }
    class ProcessingPanelModel
    class ProcessingPanelPresenter
    class ProcessingTabUiConfig

    ProcessingPanelWidget --|> BaseWidget
    ProcessingPanelWidget --> ProcessingPanelModel
    ProcessingPanelWidget --> ProcessingPanelPresenter
    ProcessingPanelModel --> ProcessingTabUiConfig : ui
```

| Файл | Классы / содержимое |
|------|---------------------|
| `panel_widget.py` | `ProcessingPanelWidget` — разметка и `*Control.create` |
| `presenter.py` | `ProcessingPanelPresenter` — заготовка под команды |
| `model.py` | `ProcessingPanelModel` — `registers_manager`, `ui` |
| `schemas.py` | `ProcessingTabUiConfig`, `default_tab_item()` |

## Dependencies

- **`registers.schemas.processing_tab`** — `ProcessorRegisters`, `RendererRegisters`
- Embedded by **`tabs_setting.processing_tab.ProcessingTabWidget`** (thin shell + placeholder when no RM)
