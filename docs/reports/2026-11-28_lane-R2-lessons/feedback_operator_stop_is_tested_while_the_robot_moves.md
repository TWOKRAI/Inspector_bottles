---
name: feedback-operator-stop-is-tested-while-the-robot-moves
description: "СТОП оператора проверять во время движения: правка одного конфига (on_connect.servo=false) сняла СТОП на повторном connect, а тест на стоящем роботе или свежем симе это не видит / test operator STOP during motion, standing-robot test is vacuous"
metadata:
  type: feedback
  module: [services/device_hub, services/robot_comm]
  mechanism: [lifecycle, test-assertions]
---

**Trap.** A test of STOP or park on a robot that is not moving (or on a fresh sim) passes whether or not the command reaches the robot. A config-only change can remove operator STOP while every existing test stays green.

**Measured (2026-11-27, sim v2).** `on_connect: {servo: false}` in a recipe: a repeated connect or a reconnect during motion left the driver not ready, and `robot_stop` was refused after about 2.4 s while the robot kept moving. Found only by the stage-5 review run; the 21 blind recipe tests were green. A `park` test on a freshly started sim passed without any park happening.

**How to apply.** For any change that touches connect, readiness, servo or on-connect actions: start motion first, then press STOP, and assert both the frame on the wire and that the robot stopped. For park: move the robot away from home first.

**Trigger.** A diff in `on_connect`, driver readiness, `needs_link`, or a recipe that configures a robot device.
