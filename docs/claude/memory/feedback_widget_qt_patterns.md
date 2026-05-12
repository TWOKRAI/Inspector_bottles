---
name: Qt widget editing patterns
description: Critical Qt/PySide6 patterns for inline editing in QTreeWidget — setFlags recursion, blockSignals, EditTriggers
type: feedback
originSessionId: 1223cca6-a6d2-4550-a4ca-364f8450e68a
---
## QTreeWidget inline editing — три ловушки

### 1. setFlags() вызывает itemChanged → рекурсия
`item.setFlags(flags & ~ItemIsEditable)` внутри `_on_item_edited` триггерит `itemChanged` сигнал → бесконечная рекурсия → stack overflow (exitcode 0xC000001D на Windows).
**Fix:** `blockSignals(True)` вокруг `setFlags`:
```python
self._tree.blockSignals(True)
item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
self._tree.blockSignals(False)
```

### 2. editItem() требует EditTriggers
Программный вызов `self._tree.editItem(item, column)` молча фейлит (`editing failed`) если у QTreeWidget не задан EditTrigger. По умолчанию — `NoEditTriggers`.
**Fix:** `self._tree.setEditTriggers(QTreeWidget.EditTrigger.AllEditTriggers)`

### 3. _populate_tree внутри _write вызывает itemChanged
`setText()` при перестроении дерева вызывает `itemChanged`. Нужен `_writing` guard или `blockSignals` в `_populate_tree`.

**Why:** Три раза столкнулись при разработке SourcesTabWidget (2026-04-28). Stack overflow crash на Windows проявляется как exitcode 3221225725 = 0xC000001D.

**How to apply:** Любой QTreeWidget с inline editing и программной мутацией items.
