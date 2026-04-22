# Phase 6: Display (0..N windows) + Recording UI -- Plan

**Date:** 2026-04-22
**Status:** DONE

## Context

**Phases 0-5c done.** System has: multi-camera orchestration (Phase 3), frame routing with fan-out (AD-2/AD-6), per-camera regions (Phase 4), processing chain with thread workers and cross-process worker pool (Phase 5a/5b/5c), RecorderWorker (AD-10, Phase 3), CameraRegistry (frontend).

**Phase 3.5 (Frame History / AD-9) NOT DONE.** Task "Rewind scrubber" is **DEFERRED** -- requires `FrameHistoryProcess` and `history.get_frame()` API which do not exist yet.

**Current display:** Single `RendererProcess` -> `GuiProcess` -> `MainWindow.ImagePanelWidget` with 2 fixed slots (original + mask). No dynamic windows, no source selection, no layout presets.

**Goal Phase 6:** Replace fixed 2-slot rendering with flexible 0..N display windows. Each window subscribes to any `source_ref` (raw camera, processor intermediate/final). Layout presets (0/1/2/4/custom). Headless mode (N=0). FPS throttling for display channels. Recording indicator (AD-10 UI). WindowManager for lifecycle. Lazy SHM allocation.

**Base path:** `Inspector_prototype/multiprocess_prototype_v3/`

---

## Execution order

### Batch 1: Data model + Backend (parallel, no frontend dependencies)
- Task 6.1: DisplaySubscription schema [DONE]
- Task 6.2: FrameThrottleMiddleware [DONE]

### Batch 2: Core managers (depends on 6.1)
- Task 6.3: DisplayRouter (frontend manager) [DONE]
- Task 6.4: WindowManager (lifecycle) [DONE]

### Batch 3: UI widgets (depends on 6.3, 6.4)
- Task 6.5: DisplayWindow widget [DONE]
- Task 6.6: RecordingIndicator widget [DONE]
- Task 6.7: Display tab (settings) [DONE]

### Batch 4: Integration + Headless (depends on all above)
- Task 6.8: Headless mode (N=0) [DONE]
- Task 6.9: Integration -- launcher + tab_factory + GuiProcess wiring [DONE]

### Batch 5: Tests (depends on all above)
- Task 6.10: Unit + integration tests [DONE]

---

## Tasks

### Task 6.1 -- DisplaySubscription schema

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** SchemaBase model for display subscription -- links source_ref to window_id with transform params
**Context:** AD-4 defines `DisplaySubscription(source_ref, window_id, transform)`. This is the data contract between DisplayRouter, WindowManager, and Display tab UI. `source_ref` format: `camera_{id}` (raw), `processor_{id}.{region}.{step}`, `processor_{id}.{region}.final`.

**Files (new):**
- `registers/display/schemas.py` -- `DisplaySubscription(SchemaBase)`: `subscription_id (UUID auto)`, `source_ref: str`, `window_id: str`, `transform: DisplayTransform`
- `registers/display/transform.py` -- `DisplayTransform(SchemaBase)`: `resize_width: int | None`, `resize_height: int | None`, `overlay_enabled: bool = True`, `fps_limit: int = 30`
- `registers/display/__init__.py`
- `registers/display/presets.py` -- `LayoutPreset` enum (`NONE`, `SINGLE`, `DUAL`, `QUAD`, `CUSTOM`) + `preset_subscriptions(preset, camera_ids) -> list[DisplaySubscription]` factory

**Files (modify):**
- `registers/__init__.py` -- export new schemas

**Steps:**
1. Create `DisplayTransform(SchemaBase)` with fields for resize, overlay toggle, fps_limit (default 30)
2. Create `DisplaySubscription(SchemaBase)` with auto-UUID `subscription_id`, `source_ref: str`, `window_id: str`, `transform: DisplayTransform = DisplayTransform()`
3. Create `LayoutPreset` enum and `preset_subscriptions()` factory that generates subscription lists for 0/1/2/4 windows from camera_ids list
4. Register all schemas via `@register_schema`

**Acceptance criteria:**
- [ ] `DisplaySubscription` round-trip through `model_dump` / `model_validate`
- [ ] `preset_subscriptions(LayoutPreset.QUAD, [0,1,2,3])` returns 4 subscriptions with correct source_refs
- [ ] `preset_subscriptions(LayoutPreset.NONE, [0,1])` returns empty list
- [ ] `DisplayTransform` validates `fps_limit` range (1..120)

**Out of scope:** Rewind-related fields, history integration

---

### Task 6.2 -- FrameThrottleMiddleware

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Router middleware that throttles frame delivery to display subscribers based on fps_limit
**Context:** Display windows don't need full camera FPS (30-120). FrameThrottleMiddleware drops excess frames for display channels, reducing CPU/GPU load. Follows the existing `FrameShmMiddleware` pattern -- plugs into `RouterManager.add_send_middleware()`.

**Files (new):**
- `backend/routing/throttle_middleware.py` -- `FrameThrottleMiddleware` class

**Steps:**
1. Create `FrameThrottleMiddleware` with constructor `(channel_fps_limits: dict[str, int])` -- maps channel name -> max FPS
2. Implement `on_send(msg) -> Optional[dict]`:
   - Extract target channel from `msg`
   - If channel has fps_limit, check time since last frame passed for that channel
   - If interval < `1/fps_limit` -> return `None` (drop frame)
   - Otherwise -> pass through and update timestamp
3. Use `time.monotonic()` for timing (no clock drift)
4. Support dynamic update: `set_fps_limit(channel, fps)` and `remove_fps_limit(channel)`
5. Thread-safe: use `threading.Lock` for limits dict access (middleware may be called from different threads)

**Acceptance criteria:**
- [ ] At 60fps input, `fps_limit=15` passes ~15 frames/sec (tolerance +/- 2)
- [ ] Channel without limit passes all frames
- [ ] `set_fps_limit` / `remove_fps_limit` work at runtime
- [ ] Returning `None` from `on_send` drops the message (verify with RouterManager integration)

**Out of scope:** Per-subscription throttling (throttle is per-channel for simplicity)
**Edge cases:** First frame always passes. Zero fps_limit means block all. Negative values treated as no limit.

---

### Task 6.3 -- DisplayRouter (frontend manager)

**Level:** Senior (Opus)
**Assignee:** teamlead
**Goal:** Frontend-side manager that handles display subscriptions -- subscribe/unsubscribe through RouterManager with lazy SHM allocation
**Context:** DisplayRouter is the bridge between UI (Display tab, WindowManager) and backend (RouterManager, MemoryManager). When a subscription is created, DisplayRouter calls `subscribe_to_camera()` (from `frame_router_setup.py`) to register the display channel. When destroyed, it unsubscribes. Lazy SHM: SHM regions for display are allocated only when at least one subscription exists for that source.

**Files (new):**
- `frontend/managers/display_router.py` -- `DisplayRouter` class

**Files (use, no modify):**
- `backend/routing/frame_router_setup.py` -- `subscribe_to_camera()`, `unsubscribe_from_camera()`
- `registers/display/schemas.py` -- `DisplaySubscription`

**Steps:**
1. Create `DisplayRouter` class with constructor `(router_manager, memory_manager, throttle_middleware)`
2. `subscribe(sub: DisplaySubscription) -> bool`:
   - Parse `source_ref` to extract `camera_id` (or processor source)
   - Generate unique display channel name: `display_{window_id}`
   - Call `subscribe_to_camera(router_manager, camera_id, channel_name)`
   - If `sub.transform.fps_limit` set -> `throttle_middleware.set_fps_limit(channel_name, fps_limit)`
   - Store subscription in internal `_active: dict[str, DisplaySubscription]` (key = subscription_id)
   - Allocate SHM if first subscription for this source (lazy)
3. `unsubscribe(subscription_id: str) -> bool`:
   - Remove from `_active`
   - Call `unsubscribe_from_camera()`
   - If no more subscriptions for this source -> release SHM (lazy cleanup)
   - Remove throttle limit
4. `get_active_subscriptions() -> list[DisplaySubscription]`
5. `apply_preset(preset: LayoutPreset, camera_ids: list[int])`:
   - Unsubscribe all current
   - Generate subscriptions via `preset_subscriptions()`
   - Subscribe all
6. Callback mechanism: `add_frame_callback(window_id, callback)` -- DisplayWindow registers a callable to receive frames

**Acceptance criteria:**
- [ ] `subscribe()` adds channel to frame_router fan-out
- [ ] `unsubscribe()` removes channel from fan-out
- [ ] Double subscribe same subscription_id -- idempotent (no duplicate channels)
- [ ] `apply_preset(QUAD, [0,1,2,3])` creates 4 subscriptions
- [ ] SHM allocated on first subscribe, released when last unsubscribe for source

**Out of scope:** Cross-process DisplayRouter (it lives in GUI process). History source_ref parsing.
**Dependencies:** Task 6.1

---

### Task 6.4 -- WindowManager (display window lifecycle)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Manager for creating/destroying/tracking display windows (QWidget instances) with leak-proof lifecycle
**Context:** WindowManager owns all display QWidget instances. It creates windows on demand (from DisplayRouter subscriptions or Display tab UI), tracks them by window_id, handles close events, and ensures SHM cleanup on destroy.

**Files (new):**
- `frontend/managers/window_manager.py` -- `DisplayWindowManager` class

**Steps:**
1. Create `DisplayWindowManager` class with constructor `(display_router: DisplayRouter)`
2. `create_window(window_id: str, source_ref: str, transform: DisplayTransform | None = None) -> QWidget`:
   - Create `DisplayWindow` widget (Task 6.5)
   - Store in `_windows: dict[str, QWidget]`
   - Create `DisplaySubscription` and call `display_router.subscribe()`
   - Connect window close signal to `destroy_window()`
   - Return widget reference
3. `destroy_window(window_id: str)`:
   - Call `display_router.unsubscribe()` for all subscriptions of this window
   - Remove from `_windows`
   - Call `widget.deleteLater()` (Qt-safe cleanup)
4. `destroy_all()`:
   - Destroy all windows (called on shutdown)
5. `get_window(window_id: str) -> QWidget | None`
6. `list_windows() -> list[str]`
7. `window_count() -> int`
8. Callback support: `add_on_create(callback)`, `add_on_destroy(callback)` for Display tab UI sync

**Acceptance criteria:**
- [ ] `create_window("win_0", "camera_0")` creates widget + subscription
- [ ] `destroy_window("win_0")` unsubscribes + removes widget
- [ ] `destroy_all()` cleans up everything
- [ ] 100 create/destroy cycles without memory leaks (widget references released)
- [ ] Close button on window triggers `destroy_window()`

**Out of scope:** Window positioning/layout (Display tab handles grid arrangement)
**Edge cases:** `create_window` with duplicate `window_id` -- destroy old first, then create new. `destroy_window` with unknown id -- no-op.
**Dependencies:** Task 6.3

---

### Task 6.5 -- DisplayWindow widget

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Standalone QWidget for displaying a single video source with source selector, recording indicator slot, and close button
**Context:** Each display window shows frames from one `source_ref`. It reuses the framework's `ImagePanelWidget` (1 slot) for rendering. Source selector ComboBox allows switching to another camera or processor output at runtime. Close button triggers WindowManager cleanup.

**Files (new):**
- `frontend/widgets/display_window/__init__.py`
- `frontend/widgets/display_window/schemas.py` -- `DisplayWindowConfig(SchemaBase)`
- `frontend/widgets/display_window/widget.py` -- `DisplayWindow(QWidget)` main widget
- `frontend/widgets/display_window/source_selector.py` -- `SourceSelectorCombo(QComboBox)` for choosing source_ref
- `frontend/widgets/display_window/view.py` -- layout composition (ImagePanel + header bar with source selector, close button, recording indicator placeholder)

**Steps:**
1. Create `DisplayWindowConfig(SchemaBase)`: `window_id: str`, `initial_source: str = ""`, `title: str = "Display"`
2. Create `SourceSelectorCombo(QComboBox)`:
   - Populate from available sources: `camera_{id}` for each camera in CameraRegistry + `processor_{id}.{region}.final` for each active region
   - Signal `source_changed(str)` on selection change
   - Method `refresh_sources(cameras: list, processors: list)` to update list
3. Create `DisplayWindow(QWidget)`:
   - Layout: top bar (QLabel title + SourceSelectorCombo + RecordingIndicator placeholder + QPushButton close) + ImagePanelWidget (1 slot)
   - `update_frame(frame: np.ndarray)` -- delegates to ImagePanelWidget
   - `closeEvent` override -> emit `closed(window_id)` signal
   - Property `source_ref` -> current source from selector
   - Signal `source_changed(window_id, new_source_ref)` -- WindowManager/DisplayRouter re-subscribe
4. Create `DisplayWindowView` -- pure layout builder (no logic)

**Acceptance criteria:**
- [ ] Widget renders frames via `update_frame()`
- [ ] Source selector shows available cameras from CameraRegistry
- [ ] Changing source emits `source_changed` signal
- [ ] Close button emits `closed` signal
- [ ] Widget has placeholder area for RecordingIndicator (Task 6.6)

**Out of scope:** Actual frame routing (DisplayRouter handles it). Rewind scrubber placeholder.
**Dependencies:** Task 6.1 (DisplayWindowConfig), Task 6.4 (lifecycle integration)

---

### Task 6.6 -- RecordingIndicator widget

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Small widget showing recording state per camera: red dot, duration counter, file size, toggle button
**Context:** AD-10 UI. RecorderWorker (Phase 3) already exposes `stats` property with `recording_active`, `duration_sec`, `file_size_mb`. Camera registers have `record_video` boolean. The indicator reads these values and provides a toggle button to start/stop recording.

**Files (new):**
- `frontend/widgets/recording_indicator/__init__.py`
- `frontend/widgets/recording_indicator/widget.py` -- `RecordingIndicator(QWidget)`
- `frontend/widgets/recording_indicator/schemas.py` -- `RecordingIndicatorConfig(SchemaBase)`

**Steps:**
1. Create `RecordingIndicator(QWidget)`:
   - Layout: QHBoxLayout with red dot (QLabel with colored circle stylesheet), duration QLabel, file_size QLabel, QPushButton toggle ("REC" / "STOP")
   - `set_camera_id(camera_id: int)` -- bind to specific camera
   - `update_stats(recording_active: bool, duration_sec: float, file_size_mb: float)` -- refresh UI
   - Signal `record_toggled(camera_id: int, start: bool)` -- emitted when user clicks toggle
2. Red dot: visible only when `recording_active=True`, blinking animation (QTimer, 500ms toggle visibility)
3. Duration format: `MM:SS`
4. File size format: `X.X MB`
5. When not recording: hide duration/file_size labels, show only toggle button with "REC" text

**Acceptance criteria:**
- [ ] Red dot visible and blinking when `recording_active=True`
- [ ] Red dot hidden when `recording_active=False`
- [ ] Duration updates every second when recording
- [ ] Toggle button emits `record_toggled` signal
- [ ] File size displays correctly

**Out of scope:** Actual register write (the parent widget / DisplayRouter handles the `record_video` register update on `record_toggled`)
**Edge cases:** Camera not found in registry -- indicator stays in inactive state.
**Dependencies:** None (standalone widget, integrated in Task 6.5 and 6.9)

---

### Task 6.7 -- Display tab (settings)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Settings tab for managing display windows: table of active windows + layout presets + add/remove controls
**Context:** Display tab is a new tab in `TabWidget` (like Camera tab, Recipes tab, etc.). It shows a table of current display windows with columns: `window_id`, `source_ref`, `fps_limit`, `status`. Layout presets row (0/1/2/4/custom) with one-click apply. Add/Remove buttons.

**Files (new):**
- `frontend/widgets/tabs_setting/display_tab/__init__.py`
- `frontend/widgets/tabs_setting/display_tab/schemas.py` -- `DisplayTabConfig`, `default_tab_item()`
- `frontend/widgets/tabs_setting/display_tab/widget.py` -- `DisplayTabWidget(QWidget)` with table + preset buttons + add/remove
- `frontend/widgets/tabs_setting/display_tab/presenter.py` -- `DisplayTabPresenter` -- bridges UI actions to WindowManager and DisplayRouter
- `frontend/widgets/tabs_setting/display_tab/view.py` -- layout

**Files (modify):**
- `frontend/widgets/tabs_setting/tabs_config.py` -- add display tab to `_default_tabs()` list
- `frontend/widgets/__init__.py` -- export `DisplayTabWidget`

**Steps:**
1. Create `DisplayTabConfig(SchemaBase)` with default presets and add `default_tab_item()` returning `TabItemConfig(id="display", widget="display", title="Display")`
2. Create `DisplayTabWidget(QWidget)`:
   - Top section: layout preset buttons (0 / 1 / 2 / 4 / Custom) as QButtonGroup
   - Middle section: QTableWidget with columns [ID, Source, FPS Limit, Status, Actions(close)]
   - Bottom section: "Add Window" button
3. Create `DisplayTabPresenter`:
   - Connects preset buttons to `display_router.apply_preset()`
   - Connects add button to `window_manager.create_window()`
   - Connects table close buttons to `window_manager.destroy_window()`
   - Listens to `window_manager.on_create/on_destroy` callbacks to refresh table
   - Populates source ComboBox from `camera_registry.all_entries()`
4. Add to `_default_tabs()` in `tabs_config.py` after camera tab
5. Export from `frontend/widgets/__init__.py`

**Acceptance criteria:**
- [ ] Display tab appears in MainWindow TabWidget
- [ ] Clicking preset "4" creates 4 windows
- [ ] Clicking preset "0" destroys all windows
- [ ] Add button creates window with default source (camera_0)
- [ ] Close button in table row destroys specific window
- [ ] Table refreshes on create/destroy events

**Out of scope:** Window positioning/tiling on screen. Drag-and-drop in table. Persisting window layout to profile.
**Dependencies:** Task 6.3, Task 6.4, Task 6.5

---

### Task 6.8 -- Headless mode (N=0)

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Ensure pipeline works correctly with zero display windows -- detections saved to DB, no SHM allocated for display
**Context:** AD-4 states N=0 is valid (headless/CI). When no display subscriptions exist, DisplayRouter should not allocate any display SHM. Processing pipeline (Camera -> Processor -> Database) must continue running. This is mainly a validation task -- ensure existing code paths handle zero display subscriptions gracefully.

**Files (modify):**
- `frontend/managers/display_router.py` -- ensure `_active` empty dict is valid startup state, no crash on zero subscriptions
- `backend/routing/frame_router_setup.py` -- verify fan-out works with only "processor" subscriber (no display)

**Steps:**
1. Add `headless` mode flag to `DisplayRouter.__init__(headless: bool = False)` -- when True, skip all subscribe operations
2. Verify `setup_frame_routes()` works with only `_DEFAULT_SUBSCRIBERS = ["processor"]` (no display)
3. Verify `GuiProcess._handle_new_frame()` does not crash when no display windows exist
4. Verify RendererProcess is optional when N=0 (can be excluded from `all_process_configs()`)
5. Add config option `display_enabled: bool = True` in AppConfig -- when False, exclude RendererProcess from process list

**Acceptance criteria:**
- [ ] Pipeline starts with `display_enabled=False` -- camera captures, processor runs, detections saved to DB
- [ ] No SHM allocated for display channels
- [ ] No errors/warnings about missing display subscribers in logs
- [ ] `DisplayRouter` in headless mode -- `subscribe()` returns False, no-op

**Out of scope:** CLI-only mode without GuiProcess (GUI process still exists for settings UI, just no display windows)
**Edge cases:** Switching from headless to display at runtime (deferred -- requires restart)
**Dependencies:** Task 6.3

---

### Task 6.9 -- Integration: launcher + tab_factory + GuiProcess wiring

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Wire all Phase 6 components together: DisplayRouter + WindowManager + DisplayTab + RecordingIndicator into the existing launcher/GuiProcess architecture
**Context:** This is the integration task. It connects: (1) DisplayRouter creation in launcher with RouterManager + MemoryManager refs, (2) WindowManager in FrontendAppContext, (3) DisplayTabWidget in tab_factory, (4) RecordingIndicator in DisplayWindow, (5) frame delivery from GuiProcess to DisplayWindows via DisplayRouter callbacks, (6) recording stats polling from registers to RecordingIndicator.

**Files (modify):**
- `frontend/launcher.py` -- create DisplayRouter, WindowManager, FrameThrottleMiddleware; pass to FrontendAppContext; wire frame delivery
- `frontend/app_context.py` -- add `display_router`, `window_manager` fields
- `frontend/windows/main_window/tab_factory.py` -- add `"display"` case to factory
- `backend/processes/gui/process.py` -- extend `_handle_new_frame()` to dispatch frames to DisplayRouter (not only to MainWindow.image_panel)
- `backend/processes/gui/handlers.py` -- add handler for recorder stats updates
- `frontend/widgets/display_window/widget.py` -- integrate RecordingIndicator (replace placeholder)
- `config/app.py` -- add `display_enabled: bool = True`

**Steps:**
1. In `launcher.py`:
   - Create `FrameThrottleMiddleware()` and add to GuiProcess router
   - Create `DisplayRouter(router_manager, memory_manager, throttle_middleware)`
   - Create `DisplayWindowManager(display_router)`
   - Add both to `FrontendAppContext`
   - Wire `display_router.add_frame_callback()` for each window to `DisplayWindow.update_frame()`
2. In `app_context.py`:
   - Add `display_router: Optional[Any] = None`
   - Add `window_manager: Optional[Any] = None`
   - Add `get_display_tab_ui() -> Any`
3. In `tab_factory.py`:
   - Add `"display"` branch that creates `DisplayTabWidget` with `ctx.window_manager`, `ctx.display_router`, `ctx.camera_registry`
4. In `GuiProcess._handle_new_frame()`:
   - After existing MainWindow update, dispatch frame to DisplayRouter for all active subscriptions matching the source
5. In `handlers.py`:
   - Add `handle_recorder_stats(window, data)` that updates RecordingIndicator per camera
6. In `DisplayWindow.widget.py`:
   - Replace RecordingIndicator placeholder with actual widget
   - Connect `record_toggled` signal to register write via `registers_manager.set_field_value("camera", "record_video", value)`
7. In `app.py`:
   - Add `display_enabled: bool = True`; when False exclude RendererProcess from `all_process_configs()`

**Acceptance criteria:**
- [ ] Application starts with Display tab visible
- [ ] Preset "2" from Display tab opens 2 windows showing live camera feeds
- [ ] Source selector in display window switches between cameras
- [ ] RecordingIndicator shows red dot when recording is active
- [ ] Toggle recording from display window starts/stops recording
- [ ] Closing all windows (preset "0") does not crash pipeline
- [ ] Display tab table reflects actual window state in real time

**Out of scope:** Rewind scrubber integration (Phase 3.5 not ready). Persisting display layout between app restarts. Multi-monitor window placement.
**Dependencies:** Task 6.1-6.8 (all)

---

### Task 6.10 -- Unit + integration tests

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** tester
**Goal:** Tests covering all Phase 6 components: schemas, middleware, managers, widgets
**Context:** Follow the testing pattern from Phase 5c (see `tests/unit/` structure). Tests must run without a live camera (mock frame data). Qt widget tests use `pytest-qt` or manual QApplication setup.

**Files (new):**
- `tests/unit/test_display_subscription.py` -- schema round-trip, preset generation, transform validation
- `tests/unit/test_frame_throttle_middleware.py` -- throttling logic, dynamic limits, edge cases
- `tests/unit/test_display_router.py` -- subscribe/unsubscribe, apply_preset, lazy SHM, idempotency
- `tests/unit/test_window_manager.py` -- create/destroy lifecycle, destroy_all, duplicate window_id
- `tests/unit/test_recording_indicator.py` -- state updates, toggle signal (if pytest-qt available)
- `tests/integration/test_display_headless.py` -- pipeline runs with N=0 windows, detections saved

**Steps:**
1. `test_display_subscription.py`:
   - Round-trip `model_dump` / `model_validate`
   - All presets generate correct number of subscriptions
   - Invalid fps_limit raises validation error
2. `test_frame_throttle_middleware.py`:
   - Mock clock (`time.monotonic`) to test throttling deterministically
   - Verify frame drop at high input FPS
   - Verify first frame always passes
   - Verify dynamic `set_fps_limit` / `remove_fps_limit`
3. `test_display_router.py`:
   - Mock RouterManager and MemoryManager
   - Subscribe -> verify `subscribe_to_camera` called
   - Unsubscribe -> verify `unsubscribe_from_camera` called
   - Apply preset -> correct number of subscriptions
   - Lazy SHM: first subscribe allocates, last unsubscribe releases
4. `test_window_manager.py`:
   - Mock DisplayRouter
   - Create window -> stored in `_windows`
   - Destroy -> removed from `_windows`
   - `destroy_all` clears everything
   - Duplicate `window_id` -> old destroyed first
5. `test_recording_indicator.py` (optional, if pytest-qt):
   - `update_stats(True, 60.0, 25.5)` -> labels show "01:00" and "25.5 MB"
   - `update_stats(False, ...)` -> red dot hidden
6. `test_display_headless.py`:
   - Start with headless=True
   - Verify no display SHM allocated
   - Verify processor still receives frames

**Acceptance criteria:**
- [ ] All tests pass: `python Inspector_prototype/scripts/run_framework_tests.py`
- [ ] Schema tests: >= 6 cases
- [ ] Middleware tests: >= 5 cases
- [ ] Router tests: >= 6 cases
- [ ] Manager tests: >= 5 cases
- [ ] Headless integration test: 1 case

**Out of scope:** Performance/stress tests (100 create/destroy cycles -- manual validation)
**Dependencies:** Task 6.1-6.9 (all code must exist)

---

## Risks and constraints

1. **Phase 3.5 not done** -- rewind scrubber widget is deferred. DisplayWindow has no scrubber placeholder for now. When Phase 3.5 lands, it will be a separate integration task.
2. **RendererProcess coupling** -- current architecture routes all frames through RendererProcess -> GuiProcess. Phase 6 may need to bypass RendererProcess for raw camera feeds in display windows. Integration task (6.9) must handle this carefully.
3. **SHM leak risk** -- multiple create/destroy cycles of display windows must not leak SHM. WindowManager.destroy_all() in shutdown hook is critical safety net.
4. **Qt thread safety** -- frame updates from GuiProcess polling must stay on Qt main thread. DisplayRouter callbacks must use `QTimer.singleShot(0, ...)` or `QMetaObject.invokeMethod` for thread-safe delivery.
5. **RecorderWorker stats polling** -- currently RecorderWorker.stats is a property on the worker class inside CameraProcess. Getting stats to GUI requires IPC message (register update or dedicated stats channel). Integration task must define this path.
