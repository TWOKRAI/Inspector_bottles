---
name: Register routing causes GUI hang
description: FieldRouting on new registers without corresponding IPC channels causes GUI freeze on set_field_value
type: feedback
originSessionId: 1223cca6-a6d2-4550-a4ca-364f8450e68a
---
Adding `routing=FieldRouting(channel="control_X", process_targets=("Y",))` to register fields triggers automatic IPC dispatch via FrontendRegistersBridge when `set_field_value()` is called. If channel "control_X" has no registered queue, the send blocks indefinitely → GUI hang.

**Why:** Added TOPOLOGY_ROUTING to SourceTopology fields before creating the actual IPC channels in ProcessManager. GUI froze on first write.

**How to apply:** Don't add `routing=` to FieldMeta until the corresponding IPC channel is registered in the target process. For topology: routing will be added when `topology.apply` command flow is connected end-to-end. Until then, widget writes to register without routing, and explicit commands send topology to PM.
