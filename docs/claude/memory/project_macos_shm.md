---
name: macOS SHM skipped tests
description: T2.1 — 15 skipped тестов MemoryManager на macOS (Apple Silicon spawn fork). Не блокер, но нужно решить для кроссплатформенности.
type: project
originSessionId: 019d4472-622d-40f2-83de-511ec9dcc0cb
---
T2.1 из assessment-плана (2026-05-07): MemoryManager имеет 15 skipped тестов на macOS из-за нестабильности multiprocessing.shared_memory на Apple Silicon.

**Why:** Пользователь работает на Windows днём и macOS вечерами. Кроссплатформенность важна — не должно ломать друг друга.

**How to apply:** Отложено, не блокер. При работе с MemoryManager/SHM — проверять что изменения не ломают macOS. Когда будет время — решить: либо фикс через POSIX resource_tracker workaround, либо пометить модуль platform=linux,windows и снять skips.
