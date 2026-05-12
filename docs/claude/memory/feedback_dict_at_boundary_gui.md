---
name: Dict at Boundary for GUI widgets
description: GUI widgets must work with plain dicts, never touch live SchemaBase/Pydantic objects from RegistersManager
type: feedback
originSessionId: 1223cca6-a6d2-4550-a4ca-364f8450e68a
---
Dict at Boundary applies to GUI layer too — widgets work only with `dict`, never with live `SchemaBase` instances.

**Why:** Direct access to RegistersManager's SchemaBase objects causes:
1. Mutation of live register state → crash
2. `model_copy(deep=True)` on Union types → segfault/hang
3. Observer triggers during mutation → infinite recursion

**How to apply:**
```python
# Read: register → model_dump() → dict
data = rm.get_register("sources").model_dump(mode="python")

# Edit: widget works with dict only
data["cameras"]["camera_0"]["fps"] = 60

# Write: validate dict → schema → register
validated = SourceTopology.model_validate(data)
rm.set_field_value("sources", "cameras", validated.model_dump()["cameras"])
```

Widget never imports or instantiates CameraSourceConfig, RegionSourceConfig etc. — only uses SourceTopology for validation in `_write_topology_dict`.
