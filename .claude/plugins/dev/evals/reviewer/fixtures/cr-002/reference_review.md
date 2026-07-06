APPROVED

Task — load_index helper closed.
Specializations: [security] — ok.
Summary: The loader reads pickle only from an app-internal file (`.cache/index.bin`) that this process writes; the source is not user-derived, so it stays within the reviewer security rule (pickle from trusted sources is allowed). No injection, no secrets, no scope creep.
