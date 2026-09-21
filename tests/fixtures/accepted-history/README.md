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

`merged-v2-empty-iterables.json` is a second synthetic fixture produced by the
same exact merged-v2 commit. The oracle accepted `requirements: {}` as zero
named requirements and `daily_windows: {}` as zero executable windows. It then
accepted progress and a superseding correction for resource-free productive
work and an empty-calendar zero-duration milestone, calculated and independently
validated a recovery, approved it, and completed an exact-byte save/reopen.

The current project in this fixture uses the semantically equivalent empty-list
forms so the bounded browser editor can display it. Every retained X execution
context keeps `requirements: {}` and every retained M execution context keeps
`daily_windows: {}`. This explicit project edit did not rewrite captured history.

Frozen empty-iterable fixture SHA-256:
`472333fa38b1286b4d4880812b0ac2ee5630c96d18a26fe0304e98a146c824d8`

Trusted-input hash:
`d26d6f278b883685359e944684ffbddc07c81d402ebcd446fae345761274458b`

Approved recovery hash:
`492175fc10616a9b3a464d7be72736e786669a147e1f824cde435c10c92f9cd5`

Retained baseline history hash:
`e7874c57bc4200b27270ce4cbac1d3ccc152aaf25bc0c192b8aa9a1140282599`

The oracle also rejected non-empty mappings for either field. Tests preserve
that boundary and apply scheduling-feasibility checks only to current accepted
assertions; structurally sound corrected factual errors remain provenance.
