# PM-Software working mode

This repository is in **proof-of-concept mode**. The root `README.md` is the current direction.

Build working scheduling behaviour before infrastructure. Use the smallest direct implementation that lets us run an example and inspect the result.

For normal development:

- implement the main path first;
- add only focused tests for that path and bugs actually encountered;
- leave unsupported cases documented rather than generalising prematurely;
- reuse existing code where it helps, and bypass historical machinery where it does not;
- stop once the proof of concept works well enough to evaluate.

Unless explicitly requested, do not add or extend protocol versions, evidence registers, whole-repository manifests, provenance frameworks, native Microsoft Project/P6 automation, compatibility programmes, production hardening, broad security frameworks or speculative edge-case handling.

The numbered Phase 0 documents, registers, native-validation material and archived workflows are historical research references. They are not current delivery gates and must not block proof-of-concept development.

The current next target is a small OR-Tools CP-SAT experiment for roughly 10–30 activities with precedence and shared resources, producing a readable feasible schedule and a simple comparison with a baseline.
