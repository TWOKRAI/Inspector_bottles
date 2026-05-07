# Plan: Phase 8 -- StateStore + Reaktivnost

**Date:** 2026-05-07
**Status:** DRAFT

## Overview

Integracia StateStore iz frejmvorka v prototype_2. Tri napravlenija:
1. Bootstrap nachalnogo dereva sostojanija iz topology YAML
2. Integracija StateStoreManager v ProcessManagerProcess + StateProxy v GenericProcess
3. Plaginy publikujut svoe sostojanie cherez StateProxy

Frejmvork (state_store_module) uzhe gotov polnostju -- TreeStore, StateStoreManager,
StateProxy, middleware (Validation, Throttle). Menjat frejmvork minimalno:
tolko dobavlenie `state_proxy` v PluginContext.

---

## Porjadok vypolnenija

### Faza 1: Bootstrap
- Task 8.1: State Bootstrap iz Topology [PENDING]

### Faza 2: Integracija v runtime
- Task 8.2: PluginContext -- dobavlenie state_proxy (frejmvork, minimalnoe izmenenie) [PENDING]
- Task 8.3: StateStore integracija v main.py + ProcessManagerApp [PENDING] (zavisit ot 8.1, 8.2)

### Faza 3: Plugin state publishing
- Task 8.4: CapturePlugin -- state publishing [PENDING] (zavisit ot 8.3)
- Task 8.5: ColorMaskPlugin -- state publishing [PENDING] (zavisit ot 8.3)

## Riski i ogranichenija
- Frejmvork menjat MINIMALNO (tolko PluginContext.state_proxy)
- Dict at Boundary -- mezhdu processami tolko dict
- StateProxy trebuet router dlja IPC -- v GenericProcess router_manager uzhe est
- Throttle middleware neobhodim chtoby ne zasorit StateStore vysokochastotnymi metrikami (fps kazhdyj kadr)
- smoke-test trebuet zapusk realnyh processov -- v unit-testah ispolzovat mock router

---

## Zadachi

### Task 8.1 -- State Bootstrap iz Topology

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Funkcija `build_initial_state(topology, sys_config)` stroit nachalnoe derevo sostojanija iz topology YAML i system.yaml
**Context:** StateStoreManager prinimaet `initial_state: dict` v konstruktore. Nuzhno postroit eto derevo do zapuska sistemy, chtoby StateStore srazu soderzhal informaciju o vseh processah i ih konfiguracijah.

**Files:**
- `multiprocess_prototype_2/state/__init__.py` -- sozdat (pustyj modul s importom)
- `multiprocess_prototype_2/state/bootstrap.py` -- sozdat
- `multiprocess_prototype_2/state/tests/__init__.py` -- sozdat
- `multiprocess_prototype_2/state/tests/test_bootstrap.py` -- sozdat

**Steps:**
1. Sozdat `multiprocess_prototype_2/state/__init__.py` s importom `build_initial_state`
2. V `bootstrap.py` sozdat funkciju `build_initial_state(topology_dict: dict, sys_config_dict: dict) -> dict`:
   - Prinimaet topology kak dict (rezultat yaml.safe_load, DO validacii SystemBlueprint)
   - Prinimaet sys_config kak dict (rezultat SystemConfig.model_dump())
   - Vozvrashchaet derevo vida:
     ```python
     {
         "processes": {
             "<process_name>": {
                 "config": {
                     "plugins": [{"plugin_name": "capture", "category": "source", ...}],
                     "chain_targets": [...],
                     "priority": "normal",
                 },
                 "state": {
                     "status": "stopped",
                     "pid": None,
                     "fps": 0.0,
                     "frame_count": 0,
                     "error": None,
                 },
             },
         },
         "system": {
             "stop_timeout": 5.0,
             "shm_budget_mb": 512,
             "log_dir": "",
         },
         "wires": {
             "<source>-><target>": {
                 "source": "camera_0.capture.frame",
                 "target": "preprocessor.resize.frame",
                 "status": "pending",
             },
         },
     }
     ```
3. Helper `_build_process_entry(process_dict: dict) -> dict` -- izvlekaet iz topology process ego config i stroit nachalnyj state
4. Helper `_build_system_section(sys_config_dict: dict) -> dict` -- izvlekaet system-sekciju
5. Helper `_build_wires_section(wires: list[dict]) -> dict` -- stroit kartu wire-ov

**Acceptance criteria:**
- [ ] `build_initial_state` stroit korrektnoe derevo iz ljubogo topology YAML (proverit na region_pipeline.yaml i camera_gui.yaml)
- [ ] Kazhdyj process imeet `config` + `state` podderevja
- [ ] `state.status` = "stopped" dlja vseh processov pri bootstrap
- [ ] `system.*` kljuchi zapolneny iz sys_config
- [ ] `wires.*` kljuchi zapolneny iz topology
- [ ] Testy: 7+ (pustoj topology, odin process, mnogo processov, s wire-ami, bez wire-ov, sys_config defaults, sys_config custom)
- [ ] Zapusk testov: `python -m pytest multiprocess_prototype_2/state/tests/test_bootstrap.py -v`

**Out of scope:** Runtime-obnovlenija (Task 8.3+), GUI-podpiski, persistence
**Edge cases:** Pustoj topology (0 processov) -> pustoe derevo. Process bez plaginov -> pustoj plugins list. Topology bez wires -> pustoj wires dict.

---

### Task 8.2 -- PluginContext: dobavlenie state_proxy

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Dobavit pole `state_proxy` v PluginContext i SubPluginContext (frejmvork), chtoby plaginy mogli publikovat sostojanie
**Context:** Eto EDINSTVENNOE izmenenie frejmvorka v Phase 8. PluginContext -- fasad nad ProcessModule, plaginy ispolzujut ego dlja vseh operacij. state_proxy dolzhen byt optional (None po umolchaniju) dlja obratnoj sovmestimosti.

**Files:**
- `multiprocess_framework/modules/process_module/plugins/base.py` -- dobavit state_proxy v PluginContext i SubPluginContext
- `multiprocess_framework/modules/process_module/generic/generic_process.py` -- prokidyvat state_proxy v PluginContext

**Steps:**
1. V `PluginContext.__init__()` dobavit parametr `state_proxy: Any = None` i pole `self.state_proxy = state_proxy`
   Signatura stanet:
   ```python
   def __init__(
       self,
       process_name: str,
       config: dict[str, Any],
       process: Any,
       io: ProcessIO,
       registers: Any | None = None,
       state_proxy: Any | None = None,
   ) -> None:
   ```
2. V `PluginContext.with_config()` -- prokidyvat state_proxy v novyj kontekst.
   VAZHNO: nelzja menjat signaturu with_config (lomaet API). Prisvaivat posle sozdanija:
   ```python
   def with_config(self, plugin_config, registers=None):
       ctx = PluginContext(
           process_name=self.process_name,
           config=plugin_config,
           process=self._process,
           io=self.io,
           registers=registers,
           state_proxy=self.state_proxy,
       )
       return ctx
   ```
   Zdes mozhno peredat cherez konstruktor, t.k. parametr state_proxy -- keyword s default=None, eto NE lomaet API.

3. V `SubPluginContext` dataclass dobavit pole: `state_proxy: Any = None`

4. V `GenericProcess._init_custom_managers()` -- posle sozdanija base_ctx, do Fazy 1 (configure):
   ```python
   state_proxy = getattr(self, '_state_proxy', None)
   if state_proxy is not None:
       base_ctx.state_proxy = state_proxy
   ```
   Atribut `self._state_proxy` budet ustanavlivatsja v Task 8.3 cherez GenericProcessApp podklass.

**Acceptance criteria:**
- [ ] `PluginContext.state_proxy` dostupno (default = None)
- [ ] `SubPluginContext.state_proxy` dostupno (default = None)
- [ ] `with_config()` prokidyvaet state_proxy
- [ ] Sushchestvujushchie testy NE lomajutsja (state_proxy = None po umolchaniju)
- [ ] Zapusk: `python scripts/run_framework_tests.py` -- vse testy prohodjat

**Out of scope:** Sozdanie StateProxy v GenericProcess (eto Task 8.3). Izmenenie signatur with_config().
**Dependencies:** Net zavisimostej

---

### Task 8.3 -- StateStore integracija v bootstrap (main.py + ProcessManagerApp)

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Goal:** Integrirovat StateStoreManager v ProcessManagerProcess i StateProxy v GenericProcess cherez prototype_2 bootstrap
**Context:** ProcessManagerProcess imeet hook `_setup_state_store()` (pustoj po umolchaniju). SystemLauncher podderzhivaet `orchestrator_class_path` dlja zameny klassa orkestratora i `orchestrator_config` dlja dopolnitelnyh nastroek (kljuchi popadajut v process_config orkestratora cherez ProcessSpawner). Nuzhno sozdat podklass ProcessManagerProcessApp s pereopredelennym _setup_state_store().

Dlja GenericProcess -- sozdat GenericProcessApp s StateProxy. Kazhdyj process v topology (krome gui) dolzhen ispolzovat GenericProcessApp.

**Arhitekturnoe reshenie:**
- `orchestrator_class_path` = "multiprocess_prototype_2.orchestrator.ProcessManagerProcessApp"
- `orchestrator_config` = {"initial_state": dict, "state_throttle_rules": dict}
- Processy v topology ispolzujut `process_class: multiprocess_prototype_2.generic_process_app.GenericProcessApp`

**Files:**
- `multiprocess_prototype_2/orchestrator.py` -- sozdat: ProcessManagerProcessApp
- `multiprocess_prototype_2/generic_process_app.py` -- sozdat: GenericProcessApp
- `multiprocess_prototype_2/state/manager_setup.py` -- sozdat: helpers dlja nastrojki middleware
- `multiprocess_prototype_2/main.py` -- obnovit bootstrap
- `multiprocess_prototype_2/topology/region_pipeline.yaml` -- obnovit process_class
- `multiprocess_prototype_2/state/tests/test_integration.py` -- sozdat

**Steps:**

1. **`multiprocess_prototype_2/state/manager_setup.py`** -- helpers:
   - `build_throttle_rules() -> dict` -- default throttle pravila:
     ```python
     {
         "processes.**.state.fps": 1.0,
         "processes.**.state.frame_count": 2.0,
         "processes.**.state.drops": 5.0,
     }
     ```
   - `build_validation_rules(topology_dict: dict) -> dict` -- bazovye pravila validacii:
     ```python
     {
         "processes.**.state.status": {"type": str, "enum": ["stopped", "running", "paused", "error"]},
         "processes.**.state.fps": {"type": (int, float), "min": 0, "max": 1000},
     }
     ```

2. **`multiprocess_prototype_2/orchestrator.py`** -- ProcessManagerProcessApp:
   ```python
   from multiprocess_framework.modules.process_manager_module.process import ProcessManagerProcess
   
   class ProcessManagerProcessApp(ProcessManagerProcess):
       """PM s StateStoreManager dlja prototype_2."""
       
       def _setup_state_store(self) -> None:
           initial_state = self.get_config("initial_state") or {}
           throttle_rules = self.get_config("state_throttle_rules")
           
           from multiprocess_framework.modules.state_store_module.manager import StateStoreManager
           from multiprocess_framework.modules.state_store_module.middleware.throttle import ThrottleMiddleware
           
           self._state_store_manager = StateStoreManager(
               router=self.router_manager,
               initial_state=initial_state,
               logger=self,
           )
           
           if throttle_rules:
               self._state_store_manager.use(ThrottleMiddleware(throttle_rules))
           
           self._state_store_manager.initialize()
           
           if self.command_manager:
               self._state_store_manager.register_commands(self.command_manager)
           
           self._log_info(
               f"StateStore inicializirovan, kljuchej v dereve: "
               f"{len(self._state_store_manager.store.get_subtree(''))}"
           )
   ```

3. **`multiprocess_prototype_2/generic_process_app.py`** -- GenericProcessApp:
   ```python
   from multiprocess_framework.modules.process_module.generic import GenericProcess
   
   class GenericProcessApp(GenericProcess):
       """GenericProcess s StateProxy dlja prototype_2."""
       
       def _init_custom_managers(self) -> None:
           super()._init_custom_managers()
           
           from multiprocess_framework.modules.state_store_module.proxy import StateProxy
           
           self._state_proxy = StateProxy(
               process_name=self.name,
               router=self.router_manager,
               server_target="ProcessManager",
               logger=self,
           )
           self._state_proxy.initialize()
           
           # Handler dlja vhodjaschih state.changed ot StateStoreManager
           if self.router_manager:
               self.router_manager.register_message_handler(
                   "state.changed", self._state_proxy.on_state_changed
               )
       
       def shutdown(self) -> bool:
           if hasattr(self, '_state_proxy') and self._state_proxy:
               self._state_proxy.shutdown()
           return super().shutdown()
   ```

4. **`multiprocess_prototype_2/main.py`** -- obnovit:
   - Posle zagruzki topology (bp_dict) i sys_config:
     ```python
     from multiprocess_prototype_2.state.bootstrap import build_initial_state
     from multiprocess_prototype_2.state.manager_setup import build_throttle_rules
     
     initial_state = build_initial_state(bp_dict, sys_config.model_dump())
     print(f"[bootstrap] initial state: {len(initial_state.get('processes', {}))} processov")
     ```
   - SystemLauncher:
     ```python
     launcher = SystemLauncher(
         stop_timeout=sys_config.system.stop_timeout,
         orchestrator_class_path="multiprocess_prototype_2.orchestrator.ProcessManagerProcessApp",
         orchestrator_config={
             "initial_state": initial_state,
             "state_throttle_rules": build_throttle_rules(),
         },
     )
     ```

5. **Topology YAML obnovlenie** -- v region_pipeline.yaml i drugih topologijah:
   - Processy BEZ process_class (camera_0, preprocessor, i td) dolzhny poluchit:
     ```yaml
     process_class: multiprocess_prototype_2.generic_process_app.GenericProcessApp
     ```
   - gui process ostaetsja s process_class: multiprocess_prototype_2.frontend.process.GuiProcess
   - ALTERNATIVA: esli ProcessConfig.process_class == "" to SystemBlueprint ispolzuet GenericProcess po umolchaniju. Mozhno pomenjat default v blueprint na GenericProcessApp -- NO eto izmenenie frejmvorka. Poetomu -- javno ukazyvat v topology.

6. **Testy `test_integration.py`**:
   - test_process_manager_app_creates_state_store: mock ProcessManagerProcess, proverit chto _setup_state_store sozdaet StateStoreManager
   - test_state_store_has_initial_state: proverit chto store soderzit processy iz topology
   - test_generic_process_app_creates_state_proxy: proverit chto _state_proxy sozdaetsja
   - test_bootstrap_builds_launcher_with_orchestrator: proverit chto main.py stroiit launcher s pravilnym orchestrator_class_path
   - test_state_store_middleware_attached: proverit chto ThrottleMiddleware podkljuchen
   - test_commands_registered: proverit chto state.set/get/subscribe zaregistrirovany
   - Ispolzovat mock router i mock shared_resources

**Acceptance criteria:**
- [ ] ProcessManagerProcessApp pereopredeljaet _setup_state_store() i sozdaet StateStoreManager
- [ ] StateStoreManager inicializiruetsja s initial_state iz topology
- [ ] Middleware Throttle podkljuchen
- [ ] Komandy state.set/get/subscribe zaregistrirovany v CommandManager
- [ ] GenericProcessApp sozdaet StateProxy i registriruet state.changed handler
- [ ] GenericProcessApp.shutdown() vyzyvaet state_proxy.shutdown()
- [ ] main.py bootstrap integriruet build_initial_state -> orchestrator_config
- [ ] Topology YAML obnovleny s process_class: GenericProcessApp
- [ ] Testy: 8+ (mock-based, bez realnyh processov)
- [ ] Zapusk: `python -m pytest multiprocess_prototype_2/state/tests/test_integration.py -v`

**Out of scope:** GUI-podpiski (GuiStateProxy -- Phase 9+). Persistence StateStore. Hot-reload topology.
**Edge cases:** Topology bez processov -> StateStore s pustym derevom. Process bez router_manager -> StateProxy s router=None.
**Dependencies:** Task 8.1 (build_initial_state), Task 8.2 (PluginContext.state_proxy)

---

### Task 8.4 -- CapturePlugin: state publishing

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** CapturePlugin publikuet metriki cherez state_proxy: fps, frame_count, status, drops
**Context:** Posle Task 8.3 kazhdyj plugin poluchaet ctx.state_proxy (StateProxy | None). Plugin dolzhen periodicheski publikovat svoe sostojanie. Publikacija neblokijushchaja (fire-and-forget) i throttled (ne na kazhdyj kadr).

**Files:**
- `multiprocess_prototype_2/plugins/capture/plugin.py` -- dobavit state publishing
- `multiprocess_prototype_2/state/tests/test_capture_state.py` -- sozdat

**Steps:**
1. V `CapturePlugin.configure()` -- sohranit ssylku na state_proxy i dobavit schetchiki:
   ```python
   self._state_proxy = ctx.state_proxy  # mozhet byt None
   self._fps_counter = 0
   self._fps_timer = time.monotonic()
   self._actual_fps = 0.0
   self._drops = 0
   ```

2. V `CapturePlugin.produce()` -- posle uspeshnogo zahvata kadra, inkrementirovat schetchik:
   ```python
   self._fps_counter += 1
   now = time.monotonic()
   elapsed = now - self._fps_timer
   if elapsed >= 1.0:
       self._actual_fps = self._fps_counter / elapsed
       self._fps_counter = 0
       self._fps_timer = now
       self._publish_state()
   ```
   Pri neudachnom read (ret=False) -- inkrementirovat self._drops

3. Novyj metod `_publish_state()`:
   ```python
   def _publish_state(self) -> None:
       if self._state_proxy is None:
           return
       path = f"processes.{self._ctx.process_name}.state"
       self._state_proxy.merge(path, {
           "status": "running" if self._is_capturing else "stopped",
           "fps": round(self._actual_fps, 1),
           "frame_count": self._frame_count,
           "drops": self._drops,
           "paused": self._paused,
       })
   ```

4. V `_start_capture()` i `_stop_capture()` -- vyzyvat `_publish_state()` dlja obnovlenija statusa

5. V `cmd_pause_capture()` i `cmd_resume_capture()` -- vyzyvat `_publish_state()`

**Acceptance criteria:**
- [ ] CapturePlugin publikuet state kazhduju sekundu vo vremja zahvata
- [ ] State soderzit: status, fps, frame_count, drops, paused
- [ ] Esli state_proxy = None -- plugin rabotaet kak ranshe (bez state publishing)
- [ ] Drops schitajutsja pri neudachnom capture
- [ ] state obnovljaetsja pri start/stop/pause/resume
- [ ] Testy: 6+ (mock state_proxy, proverka merge vyzovov, fps calculation, drops, None state_proxy, start/stop status)
- [ ] Zapusk: `python -m pytest multiprocess_prototype_2/state/tests/test_capture_state.py -v`

**Out of scope:** GUI-otobrazhenie metrik. SHM-statistika. Detalizirovannye metriki latency.
**Edge cases:** state_proxy = None (obratnaja sovmestimost). Kamera ne otkrylas -> status = "stopped", drops ne rastut.
**Dependencies:** Task 8.2 (PluginContext.state_proxy), Task 8.3 (StateProxy v GenericProcessApp)

---

### Task 8.5 -- ColorMaskPlugin: state publishing

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** ColorMaskPlugin publikuet metriki obrabotki: processed_count, avg_latency_ms
**Context:** Analogichno Task 8.4, no dlja processing plagina. Processing pluginy vyzyvajutsja sinhronno iz PipelineExecutor, poetomu latency = vremja vypolnenija process().

**Files:**
- `multiprocess_prototype_2/plugins/color_mask/plugin.py` -- dobavit state publishing
- `multiprocess_prototype_2/state/tests/test_colormask_state.py` -- sozdat

**Steps:**
1. V `ColorMaskPlugin.configure()` -- dobavit:
   ```python
   self._state_proxy = ctx.state_proxy
   self._processed_count = 0
   self._latency_sum_ms = 0.0
   self._latency_count = 0
   self._last_publish = time.monotonic()
   ```

2. Refaktor process metoda: pereimenovat dekorirovannyj metod v `_process_item`:
   ```python
   @for_each
   def _process_item(self, item: dict) -> dict | None:
       # ... sushchestvujushchij kod obrabotki (bez izmenenij) ...
   
   def process(self, items: list[dict]) -> list[dict]:
       t0 = time.monotonic()
       result = self._process_item(items)  # for_each dekorator primenjatsja k _process_item
       elapsed_ms = (time.monotonic() - t0) * 1000
       
       self._processed_count += len(result)
       self._latency_sum_ms += elapsed_ms
       self._latency_count += 1
       
       now = time.monotonic()
       if now - self._last_publish >= 1.0:
           self._publish_state()
           self._last_publish = now
       
       return result
   ```

3. Novyj metod `_publish_state()`:
   ```python
   def _publish_state(self) -> None:
       if self._state_proxy is None:
           return
       avg_latency = (
           self._latency_sum_ms / self._latency_count
           if self._latency_count > 0 else 0.0
       )
       path = f"processes.{self._ctx.process_name}.state"
       self._state_proxy.merge(path, {
           "status": "running",
           "processed_count": self._processed_count,
           "avg_latency_ms": round(avg_latency, 2),
       })
       self._latency_sum_ms = 0.0
       self._latency_count = 0
   ```

**Acceptance criteria:**
- [ ] ColorMaskPlugin publikuet state kazhduju sekundu
- [ ] State soderzit: status, processed_count, avg_latency_ms
- [ ] Esli state_proxy = None -- plugin rabotaet kak ranshe
- [ ] avg_latency_ms otrazhaet srednjuju latency za poslednij interval
- [ ] for_each dekorator po-prezhnemu rabotaet (per-item obrabotka)
- [ ] Testy: 5+ (mock state_proxy, latency calculation, None proxy, processed_count, empty items)
- [ ] Zapusk: `python -m pytest multiprocess_prototype_2/state/tests/test_colormask_state.py -v`

**Out of scope:** Per-item latency. GPU timing. Queue wait time.
**Edge cases:** state_proxy = None. Pustoj items list (process([]) -> latency korrektnaja). Ochen bystraja obrabotka (latency < 0.01ms).
**Dependencies:** Task 8.2 (PluginContext.state_proxy), Task 8.3 (StateProxy v GenericProcessApp)
