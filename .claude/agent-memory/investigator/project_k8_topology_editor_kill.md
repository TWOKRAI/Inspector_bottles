---
name: k8-topology-editor-kill
description: K8 TopologyEditorWidget dead-code verdict + the __init__.py re-export trap that guards the live TopologyPresenter (constructor-master Ф8)
metadata:
  type: project
---

K8 `TopologyEditorWidget` + 4 children (`process_list`/`wire_list`/`plugin_selector`/`validation_panel`) в `multiprocess_prototype/frontend/widgets/topology/` — подтверждён DEAD (2026-07-09 расследование). Единственные ссылки на виджет: пакетный `__init__.py` (re-export) + один тест `frontend/tests/test_topology_editor.py`. Дети — только внутри `editor.py`. Ноль прод-инстанциаций, ноль tab-wiring, ноль динамических/register/YAML ссылок.

`TopologyPresenter` (тот же пакет, `presenter.py`) — ЖИВ: `frontend/widgets/tabs/pipeline/presenter.py:133` лениво импортит его для load/save YAML. Presenter НЕ импортит виджет/детей (только framework blueprint+registry) — независим.

**Ловушка (не из кода очевидная):** живой потребитель импортит `...topology.presenter` (подмодуль), но импорт подмодуля ВСЁ РАВНО исполняет пакетный `__init__.py`, а он делает `from .editor import TopologyEditorWidget`. Значит, удалив `editor.py`, ОБЯЗАТЕЛЬНО убрать строку re-export виджета из `__init__.py` (оставить только presenter), иначе прод-импорт presenter упадёт ModuleNotFoundError.

**Why:** roadmap SC-8 / K8b помечают presenter как HAS-CONSUMERS «не трогать»; kill целится в виджет+детей, не в пакет.
**How to apply:** при исполнении Ф8 удалять 5 файлов (editor + 4 ребёнка), править `__init__.py` (снять re-export виджета, `__all__=["TopologyPresenter"]`), и в `test_topology_editor.py` снять import виджета + 3 GUI-теста (сохранить 11 presenter-тестов). См. [[constructor-master-progress]].
