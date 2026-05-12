---
name: Workers architecture and GUI control
description: Workers are real Python threads managed by WorkerManager inside each process. GUI can CRUD workers via IPC except the default main worker (router polling).
type: project
originSessionId: 2ed0c757-d56b-40b4-b6d8-e47cf654ed2f
---
Workers in each process are **real Python threads**, managed by `WorkerManager` inside the process.

- WorkerManager can start/stop threads via commands received through RouterManager
- Initial worker configuration can be set in config (how many, which types)
- At runtime, commands arrive via RouterManager → WorkerManager creates/stops workers
- **GUI must be able to add/delete workers through IPC**
- **PROTECTED:** The default main worker (where RouterManager polls) cannot be stopped or deleted — it's the process's lifeline

**Why:** Each process has a main loop thread that polls RouterManager for messages. Stopping it would kill the process's ability to receive commands. Other workers are disposable.

**How to apply:** ProcessEditorModel must mark the default worker as `protected: true`. CreateDialog should not offer deletion of protected workers. ProcessConfigBridge must send worker CRUD commands via RouterManager → WorkerManager path.
