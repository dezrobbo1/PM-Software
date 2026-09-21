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

The current eight-activity project in this fixture uses the semantically
equivalent empty-list forms so the bounded browser editor can display and open
it under its existing 8–15 activity trial limit. Five zero-duration filler
milestones have explicit `NOT_STARTED` statuses and add no compatibility
semantics. Every retained X execution context keeps `requirements: {}` and
every retained M execution context keeps `daily_windows: {}`. This explicit
project edit did not rewrite captured history. The oracle then calculated and
approved the browser projection, so the currently displayed approved plan also
uses the equivalent list forms; its retained baseline history still carries its
own original source snapshot and hash.

Frozen empty-iterable fixture SHA-256:
`998e3c8e7914202cdecfad163b2d90619191acaea28410b2b0f06783ef633117`

Trusted-input hash:
`68179ebf1b313e05f3ebc0f912356bbd2c2f2d0d90f45a4c716ddea70b3b9586`

Approved recovery hash:
`159e1818dfb78fa6c3bbe853587685e3ebebf758a41cc0e645174f52519c0d0d`

Retained baseline history hash:
`d7cddfee4571f2657bc1bfe1cdb1e0c739341d792bee0944f3c486c2c18b50d5`

The oracle also rejected non-empty mappings for either field. Tests preserve
that boundary and apply scheduling-feasibility checks only to current accepted
assertions; structurally sound corrected factual errors remain provenance.
