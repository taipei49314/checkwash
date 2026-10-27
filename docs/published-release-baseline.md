# Native published-release identity for the verdict baseline

The regression gate's previous engine is the actual previous published release,
with fixed source, pyz bytes, labels, baseline-blocked set and T3 map. A public
Git tag alone does not establish that an engine was delivered. The failed
v0.9.1 tag remains unchanged; the verified public v0.9.0 pin remains unchanged.
This repair changes tag-stage metadata selection, not detector behavior or any
case/acceptance/pin. It was selected by Codex under Nelson's current pre-1.0
delegation; it does not claim that Nelson personally designed this protocol.

On `--tag-run`, `tools/verdict_gate.py` separately obtains metadata from the fixed
`api.github.com/repos/taipei49314/checkwash` origin. Its case engines keep their
zero-network Git/CLI contract. Runs without `--tag-run` make no new metadata
requests. No caller URL, ignore list or CLI evidence override is available.

`published_release_identity.py` captures two complete traversals of the public
Releases catalog. Every page keeps original response bytes, SHA256, byte count,
HTTP status, Link header and UTC start/finish times. Requests never follow a
redirect, including when the native verifier uses its token. Pagination must be
sequential and terminal, with no duplicates, unknown/foreign Link target, partial
page, byte/page cap or failed request. The two full identity projections must
agree. Download counts and unrelated mutable descriptive fields are excluded
from that projection, while their original response bytes remain retained.
GitHub's real Link headers use `/repositories/1320152564/releases`; only that
audited immutable ID/name pair is accepted as a pagination alias. Every request
still goes to the fixed named-repository endpoint, rather than following a Link
or redirect to a caller-selected location.

The selected baseline needs a non-draft, non-prerelease, published stable Release
and exactly one uploaded canonical `checkwash.pyz` asset whose digest and size
equal the existing pin. The engine's independent actual-byte, source-member,
version and clean/invalid-control checks still apply. A higher merged published
Release stays in selection even if its pyz is missing, duplicated or malformed:
that asset failure blocks the gate instead of making the older baseline pass.
A stable-name public Release marked prerelease is refused explicitly. A private
draft is not published; anonymous public metadata does not prove no draft exists.

All relevant native tag refs and annotated peels are captured by exact API
endpoint and bound to local object IDs and peeled commits. Native compare
metadata binds their ancestry to the pushed tag's exact commit; it must agree
with the local merged-tag view. A missing local ref or incomplete/shallow ancestry
cannot hide a higher published Release. `release.target_commitish` is not used
as an identity or ancestry proof. Native compare requests use `per_page=1` for
the request-bound base, merge-base and status fields; their original Link headers
remain retained, but the unrelated paginated commit/diff list is neither traversed
nor called complete historical analysis. The pushed tag is still excluded from previous
release selection and must still point to exactly HEAD. Its future Release/assets
are not prerequisites for checking the tag before publication.

Merged tags without a currently public Release remain visible in the report.
This is evidence of the current public catalog, not proof that a tag was never
published, and not a claim about private drafts. Historical failed receipts and
tags remain immutable. Public GitHub Release identity also does not prove PyPI
delivery; protected deployment approval and actual GitHub/PyPI public visitors
remain separate release requirements.

For tag, release-event and public-visitor stages, the data-only release bridge
checks the original evidence against its full gate execution window, re-evaluates
the tag rule, and independently captures authenticated native catalog/ref/peel/
ancestry evidence. Relevant positive published fields and native identities must
match the original observation. A forged, omitted or stale higher Release cannot
be admitted by a caller-supplied catalog. The refreshed original responses are
retained in the verification report, including partial evidence on failure.
Both sources must contain the same reviewed metadata helper. Existing stage,
App/head/manifest, raw-exit, full-suite, qualification, distribution and publication
authority requirements remain in force. This is the existing owner-admitted
native API metadata trust boundary, not hardware or historical attestation.

GitHub documents the distinction between Releases and ordinary tags in its
[Releases API](https://docs.github.com/en/rest/releases/releases#list-releases).
The [asset API](https://docs.github.com/en/rest/releases/assets#get-a-release-asset)
supplies native upload identity, size and digest; actual downloaded bytes retain
their own pin checks. Metadata-only probes are not a real release-stage admission.
