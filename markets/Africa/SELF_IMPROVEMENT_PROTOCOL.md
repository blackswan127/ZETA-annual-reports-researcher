# SELF_IMPROVEMENT_PROTOCOL.md
Failure -> reproduce -> classify root cause -> write regression test -> implement generalized fix -> run unit tests -> run adapter smoke test -> compare coverage/false positives -> document change.

Do not add permanent company-specific hacks when the correct fix belongs in source_profiles, aliases or a generic adapter.

Compare before/after:
- discovery success %
- true-AR precision
- FY-resolution precision
- download success %
- median requests per completed slot
- median seconds per completed slot
- missing slot count
- source-blocked count
- duplicate count
