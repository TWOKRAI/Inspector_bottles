# Handoff — батч Ф5/Ф4-хвост готов к ревью (2026-07-10)

**Для чата-ревью (Fable / `/code-review ultra`).** Весь батч влит в main, зелёный.

## Baseline ревью

```
git log --oneline f839c34f..HEAD    # f839c34f = состояние на старте сессии
```

`f839c34f` (до батча) → текущий `main`. Всё влито `--no-ff`, main НЕ запушен (owner-gated).

## Что ревьюить (код)

| Задача | Коммит | Суть | Файлы |
|--------|--------|------|-------|
| **5.21** наблюдаемость | `0e64ddb9` | поле `process` в record-модели (стор+миграция+display+колонка); единый нормализатор `hub_record_to_display` (стор делегирует, json на границе БД); `BaseAdminPanel` → `widgets/primitives/`; закрытие стора на `aboutToQuit`; счётчик усечения live-хвоста | `channel_routing_module/observability/*`, `process_module/managers/observability_wiring.py`, `frontend/widgets/tabs/observability/*`, `widgets/primitives/base_admin_panel.py` |
| **5.8** RuntimeDeps | `71a1cbee` | двухслойный контракт `FrameworkRuntime` (база) + `RuntimeDeps(FrameworkRuntime)` (app-extras) через наследование frozen-dataclass | `frontend/runtime_deps.py`, `tab_factory.py` |
| **4.1** multi-register | `117182d2` | `reg_name = SchemaBase.REGISTER_NAME or plugin_name`; коллизия → loud + первый выживает; `REGISTER_NAME: ClassVar` (UPPER, не затеняет поле `register_name`) | `process_module/generic/plugin_orchestrator.py`, `data_schema_module/core/schema_base.py` |

Docs-only (контекст, не код): `5.18` (depth-метрика непрозрачна, отложена), `5.6a` + вердикт G2 (freeze не kill), память `feedback_sentrux_depth_opaque` / `feedback_freeze_over_kill`.

## Известные моменты (не регресс, для ревьюера)

- **7 плагинных `test_registered` падают в полном sweep'е `Plugins`** — ПРЕД-СУЩЕСТВУЮЩАЯ flakiness (на чистом дереве `f839c34f` те же 7; global-state PluginRegistry между тест-файлами). НЕ из этого батча. Кандидат в H.4 (изоляция тестов).
- **5.8**: `FrameworkRuntime` физически в прототипе; переезд во framework/`app_module` (через Protocol'ы для мостов) — задача 5.11.
- **4.1**: multi-register плагинов в проде пока нет — новое поведение форвард-луки; одиночный регистр адресуется как раньше (`plugin_name`).
- **G2 вердикт**: 7b/7c/7d формы НЕ удалять (freeze-tier → H.1). Ревью-находки «удалить мёртвое» по формам — учитывать вердикт.

## Гейт батча

framework (channel_routing/process/data_schema/registers/actions) + prototype (frontend/widgets/forms) зелёные; ruff/pyright 0; sentrux 9/9, quality 7078.

## NEXT (после ревью)

- **5.3** recipe-orchestrator carve (M+M) — критический путь к app_module; тянуть рецептовый блок Ф4 (4.5/4.6/4.7/4.8) в один заход.
- Независимый Ф4-хвост: 4.3/4.4 (плагинные контракты), 4.9 (StateStore ревизии).
- Ф4 закрыта на 2/10 (4.1, 4.2); остальное открыто.
