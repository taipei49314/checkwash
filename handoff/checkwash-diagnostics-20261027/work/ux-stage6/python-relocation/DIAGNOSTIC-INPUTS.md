# Read-only diagnostic arms, not executed here

Pinned product source: `fbc9374dc3bcbfc47f403aec0c36e6b51dd7b86c`.
Files in `fixtures/` are inert text, copied from the two existing normal-unit
fixture constructors. Do not import/execute the fixture code. The root-owned
driver may read their bytes and call the unchanged analyzer statically.

These four arms suffice; no changed judge or pytest is requested:

1. **263-original:** one modified `tests/test_calc.py`, 263-before→263-after;
   Config(), Contract(), empty allow, date 2026-10-06; original call has neither
   root_reader nor head_reader. Native full-suite XML already reports BLOCK.
   Record optional proof fields, with source inference that startup is unknown.
2. **263-closed-root:** identical bytes and arguments, but explicit closed HEAD
   map `{'tests/test_calc.py': after_bytes}` supplies head_reader/root_reader
   via `.get`; all unlisted startup paths are known absent. BASE test bytes
   remain the change.before bytes. Do not silently add a root to arm1. Source
   reasoning predicts proof still missing: the new nonliteral `old_python`
   assignment rejects the environment; class/receiver identity are additional
   independent obligations if that first rejection is safely addressed.
3. **358-original:** old path `tests/test_billing.py`, modified before→empty-old;
   added `tests/test_other.py`, None→same before bytes. Closed HEAD map contains
   those two HEAD files plus `app/__init__.py=b''` and
   `app/billing.py=b'def total():\n    return 78.75\n'`; root_reader/head_reader
   are map.get. Date2026-10-08. Native full XML already reports BLOCK; source
   reasoning predicts the module-wide Name(request) guard empties both proofs.
4. **358-no-gate-control:** remove the complete exact GATE declaration from all
   358 sides, preserving imports/test/original paths and the same closed root.
   This is a separate pure-move control, not permission to remove the fixture
   from the original test or product. Record actual result without predicting
   it as PASS in evidence until executed.

Record verdict, all findings/de-escalators, before/after optional proof fields,
path/unit admission and startup lookup calls. A root-owned API observation is
not a native CLI or execution of the subject and should say so explicitly.
No altered-proof helper or proposed product is to be imported/compiled/run.
