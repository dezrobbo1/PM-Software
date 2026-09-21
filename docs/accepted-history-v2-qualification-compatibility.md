# Captured v2 qualification compatibility

The existing project validator interprets resource `capabilities` and requirement
`pool_ids` using Python set semantics. Accepted execution captures those values
verbatim. Historical validation must not impose a new representation contract.

| JSON representation | Existing interpretation | Captured validation |
| --- | --- | --- |
| Array of hashable scalar values | Set of values, including numbers, booleans, null and strings | Preserve every item, type, order and duplicate |
| String | Set of characters | Preserve the scalar string |
| Object | Set of keys; values do not contribute qualifications | Preserve keys and values |
| Non-iterable scalar | Cannot form a qualification set | Reject |
| Array containing arrays or objects | Contains unhashable items | Reject |

No trimming, string conversion, sorting, deduplication, migration or historical
hash rewriting occurs. Existing equality semantics also remain: for example,
`true`, `1` and `1.0` compare equal in a qualification set. This documents legacy
compatibility, not a new recommended authoring format.

Requirements must have a nonempty qualification set, as at the project boundary.
Capability structure is set-convertible; the current accepted assignment must
satisfy every required qualification. An empty or insufficient capability set in
a superseded assertion can remain as corrected factual provenance. Malformed
structures are rejected for both current and superseded accepted assertions.

The project/editor validator is unchanged. Historical execution calendars,
occupancy, continuity and precedence still apply only to current assertions.
Eligibility remains a separate nonempty/unique resource-ID constraint.
Its existing v2 iterable forms are arrays of IDs, strings of single-character
IDs, and objects whose keys are IDs. Object values are retained verbatim as
metadata; they do not determine eligibility. Captured validation accepts all
three forms without converting them. Current assignments must still be eligible.

The regression matrix exercises project replacement, report/accept, supersession,
independent recovery validation, unchanged captured representations and exact
save/reopen bytes and trusted-state hashes. Negative cases cover non-iterable
containers, unhashable array items and unsatisfied current qualifications.
