---
name: hardware-recipes-no-headless-boot
description: phone_sketch/hikvision_letter_robot не бутятся через BackendHarness headless — блок на подключении железа; чем валидировать вместо boot
metadata:
  type: project
---

Рецепты `phone_sketch.yaml` и `hikvision_letter_robot.yaml` НЕ поднимаются через
`BackendHarness` headless: `wait_until_ready` таймаутит, т.к. boot блокируется на
подключении железа (phone gateway HTTP, hikvision RTSP, robot TCP через protected
`devices`/device_hub). `strip_gui` убирает только gui, но devices остаётся.

**Why:** это hardware-рецепты; qt-smoke их гоняли на MERGE-GATE F с реальным
`BACKEND_CTL=1`+driver, но чисто-headless CI без железа их не забутит.

**How to apply:** для проверки app-specific изменений в этих рецептах (напр. добавил
поле процессу) НЕ пытайся full-boot headless. Валидируй так:
1. `load_topology_dict(recipe)` — грузится ли;
2. реальный путь сборки `base⊕recipe → normalize_blueprint → BlueprintAssembler.assemble`
   (с `PluginRegistry.discover`) → proc_dict валиден, нужное поле на месте;
3. сам механизм доказывай на СИНТЕТИЧЕСКОМ рецепте `region_pipeline` (source `camera_0`
   с плагином `capture` — процесс бутится даже без камеры, лишь логирует «не удалось
   открыть камеру 0»). Так сделан `test_fault_injection_live` (порт 8783).

Связано: [[switch-live-survivor]] (выбор процесса для live-теста).
