# Merged v2 compatibility fixture

`merged-v2-metadata-duplicates.json` is synthetic test data generated using
`project/planning_workspace.py` from merged base
`62be7e0635776c257b1b7a93ed382af04da2a423`. It passed that implementation's
report, acceptance, save and load paths before PR #30's correction was applied.

The native named-resource demo retains its original approved v0 plan. Its v2
project includes calendar display metadata, repeated named-resource capabilities
and repeated requirement qualifications. All eight statuses were explicitly
reported and accepted using the merged implementation. No private source data
or operational execution is represented.

Frozen fixture SHA-256:
`3cd832702e114ad01d5a64ecd793623490d5f0ff8721c3e1b77ff9c37a519d4f`

Trusted-input hash:
`96cdd690d9f09e83a909f4c6f9fe2b6196d34970e6b081db147636b923bee8cb`

Retained approval hash:
`e41133340a29f8fa3273dded833e53ea904eabf905bc45a218340fd219e1f828`

Tests require load/save to preserve these values and the serialized bytes. They
also verify that recovery uses the semantic qualification sets without modifying
the captured arrays or historical snapshots.
