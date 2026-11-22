# Decision log archive 7
D-214, archived at the v0.13.1 publication from 62656df812372c085b4d32c7864fcdfaccd0318a; original line numbers retained.
Entries D-001 to D-140, everything up to and including the v0.8.0 release
entry, are in [DECISIONS-archive-1.md](DECISIONS-archive-1.md). They moved
there unchanged on 2026-10-20, when this file had passed 1,000,000 bytes,
checkwash's source byte limit, above which it sets a documentation file
aside unread (F40). The archive keeps the line numbers they had here: read
against `94953c83`, the last commit before the move, a reference
`DECISIONS.md:N` with N up to 10833 is `DECISIONS-archive-1.md:N`. Any
other line reference written before the move reads against that commit.
Entry numbers do not change, and new entries are added here.

Entries D-141 to D-172 moved unchanged at v0.9.0 publication to [DECISIONS-archive-2.md](DECISIONS-archive-2.md), except its prescribed archive title and single-line provenance; old line references read against release commit d6eda4f6.

Entries D-173 to D-187 moved unchanged at v0.10.0 publication to [DECISIONS-archive-3.md](DECISIONS-archive-3.md), except its prescribed archive title and single-line provenance; line references to those entries written before the move read against release commit 10069979.

Entries D-188 to D-196 moved unchanged at v0.11.0 publication to [DECISIONS-archive-4.md](DECISIONS-archive-4.md), except its prescribed archive title and single-line provenance; line references to those entries written before the move read against release commit 34555301.

Entries D-197 to D-201 moved unchanged at v0.12.0 publication to [DECISIONS-archive-5.md](DECISIONS-archive-5.md), except its prescribed archive title and single-line provenance; line references to those entries written before the move read against tag commit 532f74ab, where the file is the same as at release merge ffaf4ed8.

Entries D-202 to D-213 moved unchanged at v0.13.0 publication to [DECISIONS-archive-6.md](DECISIONS-archive-6.md), except its prescribed archive title and single-line provenance; line references to those entries written before the move read against tag commit 9ada8cfa, where the file is the same as at release merge 7d458142.

## D-214 (2026-11-18): post-publication verdict baseline v0.13.0

The v0.13.0 decision-log cut and this verdict-baseline rotation change
agent-read-only (`L1`) files (`DECISIONS.md`, `DECISIONS-archive-6.md` and
`tests/gates/verdict_gate_accepted.toml`). The v0.13.0 release section of
[RELEASING](docs/RELEASING.md#v0130-release-authorization-and-preparation-2026-11-1516)
recorded a mandatory stop (Gate 4) before Step 9.

**Approval and authorization chain (human verbatim words separated from agent
scope interpretation).**

- **Human verbatim words:**
  1. Earlier in Antigravity session `6f80cd00-4149-4060-a094-563025975764` on
     `2026-11-18`: at `12:21:13Z` (`20:21:13+08:00`) Nelson wrote
     「我上面有開issue 先不要解」 (do not work on the issues I opened above yet),
     and at `12:22:25Z` (`20:22:25+08:00`) 「幫我做13.0收尾就好 謝謝哈基米」
     (just finish the 0.13.0 closeout for me, thanks).
  2. In the same session at `2026-11-18T15:07:02Z` (`23:07:02+08:00`), after
     Step 8 pull request `#632` merged as `f81928a717ddae07cfb7c0e074be06ef685f8445`,
     Antigravity stopped at Gate 4 (`【必停人工關卡 4】：Step 9（L1 切檔與 Verdict
     Baseline 輪替）確認`) and listed two items, quoted here without their bold
     and code markup:
     「DECISIONS.md 切檔：將 D-202～D-213 原封移至 DECISIONS-archive-6.md（保留舊行號與單行溯源標頭），更新指向這些條目的文件連結，並新增 D-214 記錄本次輪替。」
     (the archive cut, link updates and `D-214`) and
     「tests/verdict_gate/baseline.toml 輪替：將 verdict baseline 由 v0.12.0 輪替至 v0.13.0（commit 9ada8cfa...、checkwash.pyz 326e2a0c...、1,077,802 B；五階段 verdict gate 已確認 185 筆案例對 v0.12.0 為 0 筆變動，預期 baseline_blocked 維持 161 不變）。」
     (the baseline rotation to `v0.13.0`, expecting zero case movement and
     `baseline_blocked` unchanged at `161`), ending
     「請問是否要授權繼續執行 Step 9，或今天到此收工即可？」 (authorize continuing
     Step 9, or stop here for today?). Antigravity wrote those items and that
     question, with no buttons.
  3. At `2026-11-18T15:08:53Z` (`2026-11-18T23:08:53+08:00`) Nelson replied in
     his own words: 「執行」 (execute), and at `2026-11-18T15:09:07Z`
     (`2026-11-18T23:09:07+08:00`) added: 「換個sassion 執行」 (switch to a new
     session to execute), followed by the `/goal` handover prompt in Antigravity
     session `24d0281f-c2d0-4493-a2a5-ea727cbbe01a` (`2026-11-18T15:10:50Z`).
- **Agent scope interpretation:** Nelson's replies authorize executing the
  bounded Step 9 work in session `24d0281f-c2d0-4493-a2a5-ea727cbbe01a` on
  `LAPTOP-01AGNPJU`: moving `D-202` to `D-213` unchanged to
  `DECISIONS-archive-6.md`, updating document links to those moved entries,
  rotating the verdict baseline (`tests/verdict_gate/baseline.toml` and the
  `baseline` header in `tests/gates/verdict_gate_accepted.toml`) to `v0.13.0`
  provided the PJU proposal run observes zero case movements and keeps
  `baseline_blocked` at `161` (stopping immediately on any unexpected drift,
  without editing `labels.toml` or re-adjudicating cases), recording `D-214`,
  verifying the pull request with a full PJU release-stage `pr` receipt and its
  five checks, and stopping before merge so Nelson can confirm the verbatim `L1`
  diff and green checks. Newly opened issues `#624`–`#631` and `#622` remain
  untouched, downstream re-pins (`smallestlie`, `checkwash-corpus`) remain
  unauthorized, `1.0` remains `NOT_MET`, and this entry grants no standing
  authority for another release or case ruling.

The cut moves `D-202` to `D-213`, the whole log at tag commit `9ada8cfa` (the
same blob `75bebae6` at release merge `7d458142` and at main `f81928a7`), to
[DECISIONS-archive-6.md](DECISIONS-archive-6.md): line 1 retitled, line 2 one
provenance line, lines 3–2550 byte-identical to `DECISIONS.md` at `f81928a7`
and at their old numbers. Across 15 documents, 105 links named after a moved
entry pointed at `DECISIONS.md`, and the v0.13.0 release guide linked its
`D-202` to `D-213` of `DECISIONS` record there; all 106 now point at
`DECISIONS-archive-6.md`. No document links to an anchor in a moved entry, and
no older link to `D-001`–`D-201` pointed at `DECISIONS.md`.

The baseline becomes public `v0.13.0`, version `0.13.0`, commit
`9ada8cfaa618b002b5d0d829c7ddbe1b8e8ae638`, the tag's peeled commit and the
release's Action commit `A` (tag object
`f8ff8258d2e2a9a68488d5c1894f1518dfe02bce`). Its Release `checkwash.pyz` is
`1,077,802` bytes, SHA256
`326e2a0c1e5e983869893a4c11c4f0ddba5e75e7c23a8984a3357042a87fbeff`: the asset
the `release-event` receipt built and the `public-visitor` stage downloaded and
verified
([publication record](docs/releases/v0.13.0-publication-verification.md)), and
the digest the GitHub Releases API reports on Release `447438064`. The pyz is
built from the release merge `M` = `7d45814211bbb458d310607b3a241761c7d5f7e3`;
under [D-200](DECISIONS-archive-5.md) the gate binds its members to `A`'s
`src/checkwash` with `doctor.py`'s own Action pin line set to `A`, `A`'s two pin
lines being equal. The proposal run below verified that binding: the public
pyz's 237 `checkwash/*` members (`fbaff80e...`) equal `A`'s with that line set,
and its CLI reports `checkwash 0.13.0`. Because Step 8 (`#632`, `f81928a7`)
already moved the recommended Action pin and `release/advertised.toml` `commit`
to `A`, the Action pin, the advertised commit and the baseline commit are again
one commit, `A`, so a release-stage receipt takes the baseline's source from the
pinned Action checkout.

The protected `tests/gates/verdict_gate_accepted.toml` changes only its
`baseline` header and comment from `v0.12.0` to `v0.13.0`. It has no
`[[accept]]` entries; none is added, retired or re-adjudicated. `labels.toml`,
fixture expectations and the rule that a still-passing `block`-labelled case
needs acceptance remain unchanged.

A PJU proposal run of the gate (`LAPTOP-01AGNPJU`, Windows 11, CPython 3.11.9,
`HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`; the gate from main `f81928a7`) used
candidate `861394681453d228eb533dcdb400ce97a62dc462`, the rotation's pins
commit, whose `src/` tree equals main `f81928a7`'s, with main's cases and labels
and, as its baseline engine, the public `v0.13.0` pyz: the copy the
`public-visitor` stage downloaded from the Release
(`cw013pubvis1/r/release/network/github-pyz.bin`), whose size and SHA256 equal
the pin. It ran all 185 cases (159 T1, 26 T3) from `2026-11-18T15:26:56Z` to
`15:31:17Z` (4 minutes 21 seconds), exiting `0` (`status: "passed"`): `161`
`block -> block`, `24` `pass -> pass`, `0` failures and `0` reported, so it
proposed no accept entry, engine pin, `baseline_blocked`, T3 or canary change.
`v0.13.0` blocks the exact same 161 cases as `v0.12.0` (160 labelled `block`,
plus `i197/Q5a` keeping its `pass` label from D-188), so `baseline_blocked`
stays `161` /
`55aed7f5f15d00352d838f49f9d21e86e1f3dffbf09452c3d16455e6dde90245`. The
canary's 71 `block -> pass` IDs are unchanged. The chai input file is the same
blob (`4f363109`, SHA256 `f10a5ef8...`) at `9ada8cfa` as at `532f74ab`, so the
26-case T3 map stays, and the `v0.4.2` to `v0.5.0` canary is not rotated. The
run's receipt (SHA256
`14dd72c68788c9b5eb26b57111da84aad546bbba16379c1a1b8c7e7767e1f842`), summary
(`368800b0...`), stdout (`4e0f81d9...`) and stderr (`e3b0c442...`) are kept on
`evidence/v0130-rotation-proposal-20261118`
(`838be0d0be6a508465e4ae5041a467b86b54c07a`). That receipt records the host and
the four engines; the gate's commit (`f81928a7`), the wall-clock timestamps and
runtime, and the outer exit code (`0`) come from the run's directory on PJU
(`cw013-prop`), which is not published.

Hosted product-test workflows remain disabled. Accepting this configuration
requires the rotation pull request's own PJU release-stage `pr` receipt, which
downloads the public `v0.13.0` pyz again over HTTPS and runs the full gate with
these pins with zero failures, plus the pull request's five checks (`checkwash`,
the three candidate assertion contracts and `PJU release evidence (pr)`),
followed by Nelson's final merge confirmation on the verbatim `L1` diff. The
proposal run is the basis, not a substitute. No public tag change, issue edit or
downstream re-pin is part of this rotation.
