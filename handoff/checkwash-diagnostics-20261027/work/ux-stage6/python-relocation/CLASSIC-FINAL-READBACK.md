# Classic follow-up commit and actual self-check outcomes

Follow-up commit `15ac804593bc41db8f904e7921667bd6c276fa9a` has parent fbc.
Independent commit provenance: `classic-commit-provenance.json`, SHA256
`bd6748d4f545665cb091c192f1829246ce717386a3592c8883e2e4c5ee7c6a87`.
The reader exited0; all3084 physical tracked bytes equal the reviewed6580 input
map and their computed Git blobs equal the15ac tree. Only the ordinary classic
test changes. The fixed-source native targeted JUnit records31passed/exit0,
unchanged source, matching the earlier reviewed development bytes.

Final self-check readback: **classic-selfcheck-readback-r2.json**, SHA256
`139ea0ad78c3ea3c46cfe9b9c155477221da845b426f8a991cb18c2fa423f6fb`.
Pure stdlib/read-only Git reader exit0,62 checks, product/pytest/fixture calls0.

| Actual range | Native exit / verdict | Actual findings |
|---|---|---|
| fbc..15ac | 1 / BLOCK | 3high/0warn: two ASSERT_SUBSTITUTED and one EXPECTED_VALUE_CHANGED |
| 1ffe..15ac | 1 / BLOCK | 3high/9warn: classic ASSERT_SUBSTITUTED plus the two original issue266 TEST_DISABLED highs |

The parent-range dictionary-equality is paired to preserved.after.span; the
len(native_fields)==17 guard is paired to the full-name-set guard. The checker
reports substitution for both and expected value17→the17-name set. These are
actual findings, not rewritten as green by the independent semantic assessment.
The integrated classic substitution pairs the old whole UnitSide equality to
the new set guard. Every finding dictionary, message, fingerprint, strength/
escalation/de-escalation field, before/after text and span is retained in JSON.
All six high-finding source carriers were checked against the exact committed
sources. TEST_DISABLED has a whole-unit span containing a representative
assertion, not an assertion-only span. The integrated two issue266 high objects
and all nine warning objects equal the prior fbc self-check objects exactly.

The final reader scope does not re-prove heterogeneous warning-summary span
semantics. Two initial read-only validator drafts incorrectly generalized span
formats and exited1; their sources/failure records are preserved. An initial
successful report also used overly broad wording that old expected values were
unchanged. Its original e75a bytes remain; the final r2 explicitly corrects this:
the ordinary assertion's literal17 changed to a complete17-name set. No existing
verdict/golden-label authority, exemption, strength, gating or alignment changed.
This editorial correction is not a product rerun or a changed native finding.

**15ac full suite, source/wheel/pyz distribution qualifications, formal bridge
and published checks are NOT_RUN.** fbc's successful three283-case qualifications
are not qualifications for15ac. The fbc full15 failures, original3high self-check
and stage5 backup remain source-bound historical evidence. The branch is an
independently reviewable ordinary-consumer follow-up, not accepted integration
or release. Version1.0 still requires Nelson's explicit decision.
