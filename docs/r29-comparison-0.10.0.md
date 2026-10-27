# R29 comparison and current 0.10.0 cost decision

Status, 2026-10-27: **the source-bound comparison and required movement review
are closed for the exact engine below**. This is a Codex delegated decision
for 0.10.0. Formal PR/main/tag/release-event/public-visitor acceptance and public
publication remain pending. **1.0 readiness is NOT_MET.**

Nelson's current continuation is:

> 照著繼續做 完整spec在裡面 一樣我只卡1.0發佈前 其餘你可以自主推

Codex performed the technical admissions, independent source/data reviews and
current-version cost decisions under that delegation. This record does not
claim Nelson personally reviewed each case, source hash, clock discrepancy or
platform cell. The stop
before 1.0 and the normal protected publication requirements remain.

## Exact engines, membership and execution

The previous engine is the actual published v0.9.0 pyz, source
`d6eda4f695fabb8e7d138f7a87b099d2028f0294`, 914,407 bytes, SHA256
`7319152cdf4889df4d58b454dc63072bb2e923823e1b2ce09677e4381dbccd5c`.
The candidate is the qualified 0.10.0 pyz at development source
`9678e8de564ed47f7ff92867d5c7d09358c04fcb`, 951,549 bytes, SHA256
`ee55344ccf0832dab2a6c54fccf4a1f26f17fdff0f867269f889a236c0c5713d`.
Its complete `src/` tree is `ee6716662fe264b5425958f00835567a4ffca4d6`.
Later documentation/tool heads with this same engine tree still require their
own exact whole-head formal stage receipts.

Attempt B uses frozen harness source
`1838fa2943c804a7c40b9dfbdc75d2c50bd21b71`, tree
`2c17c52759b75ef3f39f601bcc79d1d55f7e005d`, manifest SHA256
`2ab51e0332e8285564fc64f34c9447f86b9fde42f6e6a57dbbdbd21d5a8ace1e`
and once admission SHA256
`bc97adfdfd8e941c4466aeee6a1ad03be709d8d19b3886631c2ca7923b7e39ea`.
The current 3,600-member semantic selection retains original fields/order from
the 6,354-member source ledger (SHA256 `89d74c73c359b09eb4f3f0971cd850c053c3211e3c8d7afbbaa5b55fa2de13be`);
its combined members file has SHA256
`f6281caad596c5d6f054dd8f0050abb21d63a803fa7bf2fa3f6c694d05559de2`.
Each of the two fixed sets has six repositories and 300 non-merge first-parent
inputs per repository. Native Git metadata proves every current window,
commit, first parent and label. This does not assert byte identity with the
unavailable legacy R29 3,600-member file.

Actual venue: WSL2/Linux on LAPTOP-16NUA5I8, Windows CPython3.11.9 launcher
and private Linux CPython3.11.17;
`HUMAN_AUTHORIZED_LOCAL_16NU_NOT_EC_POOL`. It is not native Linux, Docker, PJU
or EC-pool qualification. The frozen bound is 21,600 seconds including
closure, with six repository workers, four CPU quota, 6GiB memory, no swap,
1,024 pids, 240-second historical CLI calls and an 8GiB raw budget. The
original once started at 2026-10-27T06:37:14Z and ended at09:12:43Z; it was
not retried or resumed.

## Complete recorded results

| Published v0.9.0 -> candidate | Python standard | JS/TS |
|---|---:|---:|
| pass -> pass | 1,734 | 1,759 |
| block -> block | 48 | 38 |
| pass -> block | 18 | 0 |
| error -> block | 0 | 1 |
| error -> error | 0 | 2 |
| **paired members** | **1,800** | **1,800** |

All 3,600 pairs and 7,200 historical CLI calls have original terminal records.
The latter retain 7,004 native exit0, 191 exit1 and five exit2 calls. The full
Capture population is 11,203: those calls, 3,992 native metadata commands,
five owned Git setup commands and six owned engine controls. The original
operator/WSL/namespace phases exited zero. Original cleanup is
`PROVEN_EMPTY_REMOVED`, with zero recorded OOM events. These counts are
in-sample outcomes, not a false-positive rate or a claim every input was analysed.

The unchanged generic audit and separate strict-B audit returned zero. They
bind all original raw bytes, native intents/observations, fixed inputs,
source/runtime identities, every pair and the complete mandatory list.
Root separately checked the exact 46-command mount route (22 pre-wiring,
24 sorted corpus bind/remount commands), all three final authority categories
and the exact two operator plus two WSL stream descriptors/custody. Independent
source/data review confirmed those checks. No re-run of the represented
projects/tests was performed.

Final host closure is 9,329.079695 seconds from its original Windows wall
start; guest export is 9,213.256318 seconds, within the existing21,600/21,300
bounds. The guest's recorded monotonic snapshot exceeds guest finish minus the
earlier Windows start by **109.8258495365 seconds**. That positive discrepancy
remains unexplained; different starts alone do not explain its sign. Root
accepts source-consistent bounded closure from the unchanged guarded native
success/final authority and ordered finite wall anchors. No synchronized or
stable-clock claim, cause, exact reconstructed real duration, tolerance,
grace period or corrected timestamp is introduced.

## Required movement review and delegated disposition

The complete final mandatory list exactly matches all 19 independently
source-read cases:18 pass-to-block and one previous-error-to-block. The final
join verified486 input files before/after, with no mutation, and binds the
original rows, commands, raw streams, copied source diffs and review proposals.
There are87 candidate HIGH occurrences in these19 members. They remain HIGH
and BLOCK. All16 unchanged repair-credit WARN occurrences remain, including
D1 changed-symbol relevance, whose contract does not prove oracle equivalence.
Its known lost-guarantee/unknown-context limitations remain disclosed risks.

**Codex accepts the disclosed conservative blocking costs and remaining scope
for 0.10 only**, after reviewing each source change below. This closes this
exact engine's pre-tag R29 comparison/movement requirement. It does not classify
every finding true/false, assert the old or new tests universally equivalent,
change an outcome/allowance/fixture/severity/proof rule, or waive formal release
gates. Local equal bodies and larger test tables do not prove startup,
producer, fixture, directory, observer, concrete-input or execution equivalence.

- [`typeorm 1f9d001b752650395796e3865a52397793dfe864`](https://github.com/typeorm/typeorm/commit/1f9d001b752650395796e3865a52397793dfe864) (parent `7929b1a72d9a1738a415df2e88d65c4188e6bd4b`), error -> block, 2 HIGH: Previous head-search error becomes two candidate HIGHs: consistent shown local rename and a removed inverse-cascade fixture with different replacement APIs/data/oracles. Old coverage/findings unknown; new entity metadata/hooks absent and two-sided/literal-ID obligations not all retained. The current conservative blocking cost is accepted for0.10; those obligations remain unproved.

- [`attrs 1921da6eac6231b7bc058b076c0648b2d1b5c042`](https://github.com/python-attrs/attrs/commit/1921da6eac6231b7bc058b076c0648b2d1b5c042) (parent `58cd3ae112abf36fcd8c1cdf2a55e21b3a5734d3`), pass -> block, 1 HIGH: Frozen-exception test renamed/extended with old assertions retained; production permits more mutable exception attributes. Decorator/factory/runtime context equivalence and exact internal refusal cause remain unproved. The current conservative blocking cost is accepted for0.10; those obligations remain unproved.

- [`click 10b43c211b825181cb81ef383e8091fd41750150`](https://github.com/pallets/click/commit/10b43c211b825181cb81ef383e8091fd41750150) (parent `cfa01eeb7894a408af70b29d28c0b24f8680f9fb`), pass -> block, 2 HIGH: Nine old warning module/name pairs appear in22 rows with target equality and added cases. New imports, target reads, metadata lookup and ids callback add collection dependencies; runtime equivalence unknown. The current conservative blocking cost is accepted for0.10; those obligations remain unproved.

- [`click 1103c5cac2a9336dad3b4b5ce1a25a0bcff49ec0`](https://github.com/pallets/click/commit/1103c5cac2a9336dad3b4b5ce1a25a0bcff49ec0) (parent `182944f90a0103b87570dbc5a55eff873ca9a4c2`), pass -> block, 4 HIGH: Three full functions move; removed confirm-repeat has a source-equal duplicate added by its copied direct parent182944. Local equality and cross-diff survivor do not prove directory/import/fixture/collection context. The current conservative blocking cost is accepted for0.10; those obligations remain unproved.

- [`click 182944f90a0103b87570dbc5a55eff873ca9a4c2`](https://github.com/pallets/click/commit/182944f90a0103b87570dbc5a55eff873ca9a4c2) (parent `a391797d00d2ef32ebc4fb0034462a2ec5e6d3d4`), pass -> block, 3 HIGH: Three moved units retain full local ASTs,35 style rows and six prompt input/default cases; duplicate/additional tests added. New modules/directory and caller runner/startup context are unproved. The current conservative blocking cost is accepted for0.10; those obligations remain unproved.

- [`click 18400b2495347c684c8182f775b4aaec0838cc0e`](https://github.com/pallets/click/commit/18400b2495347c684c8182f775b4aaec0838cc0e) (parent `1103c5cac2a9336dad3b4b5ce1a25a0bcff49ec0`), pass -> block, 2 HIGH: Filename-format and sentinel units move with equal local function/decorator/body ASTs and input tables. Imports/module identity/startup observers remain unknown. The current conservative blocking cost is accepted for0.10; those obligations remain unproved.

- [`click 1aa2d53d63ff68bf14b35931177aac9270e39713`](https://github.com/pallets/click/commit/1aa2d53d63ff68bf14b35931177aac9270e39713) (parent `e94e8dc40da6fc3975fe4931ecd8ecbac87f7cc9`), pass -> block, 2 HIGH: Pager tests merge with changed capfd/native-pager IO setup and removed WIN skip; two older WARN guarantees really disappear. External pager/stream context and obsolete-guarantee intent unproved; unchanged D1 WARN is not equivalence. The current conservative blocking cost is accepted for0.10; those obligations remain unproved.

- [`click 39413d9b1d782317e72e82ec09d437bef8359078`](https://github.com/pallets/click/commit/39413d9b1d782317e72e82ec09d437bef8359078) (parent `607316f9dea85ee81f8a215f5d5ae20f7f4fff71`), pass -> block, 1 HIGH: One prompt-display case becomes seven rows; literal defaults/input, command body and first-line output projection change; production docstring changes. Old exact input obligations and collection/observer effects are not proved retained. The current conservative blocking cost is accepted for0.10; those obligations remain unproved.

- [`click 47cc96fb1fcaca88f55c1937afc50ba518d0ca8a`](https://github.com/pallets/click/commit/47cc96fb1fcaca88f55c1937afc50ba518d0ca8a) (parent `700798252a509ca57bc7a12f7aa7fd67f9f8fd25`), pass -> block, 3 HIGH: Three unit bodies split with equal local ASTs;11 represented package files move byte-equally. Single-module/package namespace, imports, fixture/CWD/collection effects remain unknown. The current conservative blocking cost is accepted for0.10; those obligations remain unproved.

- [`click 700798252a509ca57bc7a12f7aa7fd67f9f8fd25`](https://github.com/pallets/click/commit/700798252a509ca57bc7a12f7aa7fd67f9f8fd25) (parent `18400b2495347c684c8182f775b4aaec0838cc0e`), pass -> block, 10 HIGH: Ten file/resource tests move with equal function/decorator/body ASTs, IO/permission rows retained. New module context unknown; pre-existing nested callback placement does not establish an active outer oracle. The current conservative blocking cost is accepted for0.10; those obligations remain unproved.

- [`click 7c7ec36354f49d1a092cb077fa4881ea4d70ba01`](https://github.com/pallets/click/commit/7c7ec36354f49d1a092cb077fa4881ea4d70ba01) (parent `92129c552da88ac30b578132031efa4b003ecc46`), pass -> block, 9 HIGH: Nine native assertion/raises ownership changes follow a same-file split; visible tail text remains with fresh local classes/Context. Full old class/setup/prior execution and fresh-state equivalence are absent. The current conservative blocking cost is accepted for0.10; those obligations remain unproved.

- [`click 955ca492a6b9e8de0660dae1c415568ca6f9c4b3`](https://github.com/pallets/click/commit/955ca492a6b9e8de0660dae1c415568ca6f9c4b3) (parent `91de59c6c8abc8251e7af551cd4546cc964288af`), pass -> block, 2 HIGH: Flag matrix broadens, but old string'1'→int conversion/range command is replaced by already-int1 and echo. A concrete local conversion input is not retained; broader coverage/intent unknown. The current conservative blocking cost is accepted for0.10; those obligations remain unproved.

- [`click b64ea07128a6368b5f6f93035c75d5693c7ba572`](https://github.com/pallets/click/commit/b64ea07128a6368b5f6f93035c75d5693c7ba572) (parent `1f4002096439d6661f1df5ceff7eccd3862153ac`), pass -> block, 1 HIGH: UNSET/default/flag API redesign retires old nargs=-1/default constructor rejection; two None-missing errors become UNSET-only. Validation timing/input/oracles materially change; matrices are not equivalence. Older repair WARN losses remain distinct. The current conservative blocking cost is accepted for0.10; those obligations remain unproved.

- [`click d36de6fc67882f23d7a7d61cd4c0e25e0f88b0ac`](https://github.com/pallets/click/commit/d36de6fc67882f23d7a7d61cd4c0e25e0f88b0ac) (parent `10b77f98f2b2334943cd80b14717a935650cb3d6`), pass -> block, 1 HIGH: Help/error checks strengthen channel/exit assertions, but enum inputs/default values are substituted and expanded. Not every old concrete enum input or collection identity is retained; no universal equivalence. The current conservative blocking cost is accepted for0.10; those obligations remain unproved.

- [`flask c17f379390731543eea33a570a47bd4ef76a54fa`](https://github.com/pallets/flask/commit/c17f379390731543eea33a570a47bd4ef76a54fa) (parent `27be9338405382445a7cb01151e084559b98d602`), pass -> block, 1 HIGH: Session access tracking changes; renamed test adds Vary/untouched cases and observes private storage after requests. Old inside-view flag timing and raw-byte oracle become different after-request/text observations; context unknown. The current conservative blocking cost is accepted for0.10; those obligations remain unproved.

- [`flask c7a53888a1a514619b0611fd8b7928592f4ed612`](https://github.com/pallets/flask/commit/c7a53888a1a514619b0611fd8b7928592f4ed612) (parent `62c56e08c43f5eb174d15dd050591cfba9aed548`), pass -> block, 1 HIGH: Request limits gain per-request/config properties; old limit test changes64→50, route/payload and removes before_request parsing. Final b'42' does not preserve old hook/boundary/setup obligations; wider coverage unknown. The current conservative blocking cost is accepted for0.10; those obligations remain unproved.

- [`flask e82db2ca3a22c9614c1987392c9cfaa8c6ce99ad`](https://github.com/pallets/flask/commit/e82db2ca3a22c9614c1987392c9cfaa8c6ce99ad) (parent `d3b78fd18a8d9e224cb9ef58a23cec9b1ffc9ce9`), pass -> block, 1 HIGH: Explicit automatic-OPTIONS feature fix splits fixture-based tests with changed allowsets; old HTTP/setup obligations are not all shown retained. Two unchanged D1 WARN old losses remain; changed-symbol relevance is not equality. CLI negative checks strengthen. The current conservative blocking cost is accepted for0.10; those obligations remain unproved.

- [`httpx 5b5f6d8e172910371b5901f6e21717097274c513`](https://github.com/encode/httpx/commit/5b5f6d8e172910371b5901f6e21717097274c513) (parent `724eced022299c1beacce399f41dd9091e16a65a`), pass -> block, 37 HIGH: 36 deleted public-URL tests map to35 equal bodies plus basic repr extension; separate old combined copy_with(port=None) obligation is unmatched in additions. Directory/module context and coverage by unchanged tests are unknown; not a low-level→public API change. The current conservative blocking cost is accepted for0.10; those obligations remain unproved.

- [`httpx a11fc3849b94157274c98d99501acad05cbfb221`](https://github.com/encode/httpx/commit/a11fc3849b94157274c98d99501acad05cbfb221) (parent `3b9060ee1121b48669e0b30045c9344065f4f2ae`), pass -> block, 4 HIGH: Percent-encoding implementation changes; path/fragment literal cases remain in matrix, query slash oracle changes, exact old encoded-path input disappears. Interim incorrect-behavior source comment and unknown wider coverage/context remain; no strict coverage superset. The current conservative blocking cost is accepted for0.10; those obligations remain unproved.

## Coverage and preserved errors

Previous-engine config-errors/skipped-files vectors are known empty for3,597
paired members and unknown for three; candidate vectors are known empty
for3,598 and unknown for two. No nonempty vector was returned where known.
An analysed native verdict and an empty returned omission vector do not prove
full source coverage or eliminate unsupported/latent detector blind spots.

- Apollo-client `8a51ea636600dbe4b48477d32f30469b7d36b152`, parent
  `46a45c3bcef2d21cb16a75d34d366a0807240d4e`: both native exit2, empty stdout
  and equal120-byte stderr refusing symlink `.agents/skills/apollo-client`.
- Undici `0f1f8903189d2353fd42be35e7bbc0aa9fb4b26f`, parent
  `445522ba1bc22bcef2971bfdc30c883531e84e84`: both native exit2, empty stdout
  and equal106-byte stderr refusing symlink `docs/README.md`.
- TypeORM `1f9d001b752650395796e3865a52397793dfe864`, parent
  `7929b1a72d9a1738a415df2e88d65c4188e6bd4b`: previous exit2, empty stdout
  and55-byte `head search could not complete` error. It supplies no verdict,
  findings or coverage vectors. Candidate exits1/BLOCK with two HIGH findings
  and empty returned vectors. This is the sole paired coverage-review flag,
  **error-to-block**, never pass-to-block or a harness timeout.

The two unchanged errors remain **NOT_ANALYZED**, with unknown vectors.
Codex accepts this disclosed residual scope for0.10, without converting errors
into passes or unknown coverage into empty coverage.

The old D176 R4 stays consumed and partial:881 completed comparisons comprise
879 envelopes and two not-analysed errors; three parse-gap members retain seven
omitted-file occurrences; one partial plus6,553 unattempted leave6,554
incomplete comparisons. Only one of its nine retained named identity fragments
joins an actual B pair: Apollo8a51, old ordinal593, still not analysed. The full
old7,435-member identity ledger is unavailable locally, so further cross-run
overlap is unknown. The separate three-uvloop/six-call diagnostic and its
[0.10 cost decision](d176-cost-disposition-0.10.0.md) remain separate. New
observations neither complete/rewrite R4 nor imply every old incomplete member
must remain without any independent observation forever.

Attempt A remains consumed, failed before corpus/history because its owned
invalid-ref stderr matcher was too narrow for the actual native error. Its
three previous-engine controls/five owned Git setup commands and original
failure/cleanup states stay unchanged. B uses its separately reviewed new
source/admission; no failed or partial record becomes a passing comparison.

## Evidence custody and remaining gates

The original complete B packet contains48,594 files/103,619,263 bytes. Its
session-inventory SHA256 is
`f0c385e8a625d85ef69e7b86fd8c4dc2c52281b67fbeca8327c29a31bdd46c57`.
The private [Lab archive PR30](https://github.com/taipei49314/checkwash-lab/pull/30)
now retains the preparation/source/readings and the complete final bundle at
[immutable commit e0fe01a1](https://github.com/taipei49314/checkwash-lab/tree/e0fe01a1154636b4841a5f6c9c2685c3128f7004/notes/r29-010-20261027/attempt-b/final-closed),
tree `41717c3d42aa482b549f3d7bb74b811fda6493c2`. The complete selection is
48,684 files/139,397,212 bytes, packed into a34,395,769-byte ZIP with a per-file
inventory. All3,870 previous tracked blob/mode entries remain unchanged;
only19 new archive files were added. Fresh remote Git readback, full ZIP
roundtrip and root's independent native REST tree/fresh-Git byte verification
all passed. Private archival custody/readback is **DONE before any new tag**.
This storage proof preserves the original decisions and does not add run,
coverage, platform or publication acceptance. Hashes below identify actual
closed records and bytes, not reconstructed summaries.

| Record | SHA256 |
|---|---|
| Original operator terminal | `0b095977643ac71d5b53819fc38327f6ddcb83f33f7fd10f82e2355506f647f3` |
| Final host authority | `6ce53a1e3f98c4f575e06c64b6a0f43bcb38c6fd6dacd084773be3ea60f0bff5` |
| Final export authority | `58e241b928a776c602ea8cc6cc23b0dd4c1166f7ca35a305b470c0e09950a79e` |
| Generic data audit | `4df193ca61a30c919e98a0f26400c4ce12362222f2d29be75a5f3fe737b3fff3` |
| Strict B data audit | `5d4411b07f9290359efdf36d009a1101dc863cd10b3fd9dc11a39b7fb92a618e` |
| Root explicit manual closure | `deff14efc1600558c8543c2bdb4182405d1138d75ff3c597e72ea36c3423c828` |
| Final selected19 join | `5e673af96c275b98da4b499eb2ddabda5e2d1826922cb719ef4944c7a4aaa64d` |
| Root current0.10 cost/risk decision | `f809e3bd74edd19e2512118fcd152685e6475181f418fc211310288e884e2c1b` |
| Actual old-R4 identity-fragment join | `5999cf292f4184b00c04a65b5bf728dec3f5a6613e4ea679eccf483d09492f22` |
| Private whole-bundle ZIP | `12d8ef33a57ec48f3620b57f936497c7c9468987dc8dca6d1ba90172e30debf4` |
| Private archive custody | `3eacae404a9fc69184858bbfb57af94f9f1a5627194d49f53cd8e2b96f8ee747` |
| Root native remote-byte/archive review | `62e7073968bf67d350a9aea0da3c55b067e1f171d2ffee47ee39313f02a6f897` |

This R29 and cost decision do not supply later whole-source receipts, missing
platforms, cross-platform bytes, adoption or held-out/adjudicated rates.
Fresh final PR/main/tag/release-event/public-visitor evidence, normal checks
and merge, actual public artifact verification and protected deployment remain
required. Public pins remain at verified v0.9.0 until actual0.10 public bytes
are verified. **1.0 is NOT_MET and is not authorized for publication.**
