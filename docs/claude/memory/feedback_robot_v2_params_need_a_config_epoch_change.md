---
name: feedback_robot_v2_params_need_a_config_epoch_change
description: параметры робота v2 из рецепта не доходят до робота без смены config_epoch, а data/robot/<id>/params.yaml перекрывает robot_params / robot params from recipe ignored, stale stored params shadow
metadata:
  type: feedback
  module: [services/device_hub, services/robot_comm]
  mechanism: [config, persistence]
---

Robot protocol v2: changed parameters are not written to the controller unless `config_epoch` changes, and a stored `data/robot/<id>/params.yaml` takes priority over the recipe `robot_params`.

**Why:** an edited recipe looks applied while the robot keeps the old values (relevant for `P_ZONE_MAX` and speeds).

**How to apply:** before claiming a value reaches the real robot, check the stored params file and the epoch. Source: reading during R2 analysis (2026-11-26); verify on the sim before relying on it.
