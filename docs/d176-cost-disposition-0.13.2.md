# D-176 remaining-history risk for 0.13.2

**Independent recommendation.** Accept the remaining risk that D-176 can block an honest Python change for 0.13.2. This recommendation covers candidate `096b5362a838929ea33c625bba15f9d3bd5faa52`, its `src/` tree `a586058d56c399d5709a215b98c40b15d9507a30`, and the version and Action pin edits permitted by D-196. The release coordinator records the decision for this candidate. [Release procedure](https://github.com/taipei49314/checkwash/blob/096b5362a838929ea33c625bba15f9d3bd5faa52/docs/RELEASING.md#before-the-tag-the-fixed-corpus-comparison)

## Risk and implementation

For 0.13.2, the release coordinator accepts the remaining unmeasured cost on the reviewed engine. The three paired replays below agree, the relevant gating and failure-relay code matches the published version, and the fixed corpus contains no verdict moves. The earlier incomplete history remains outside these measurements.

A test or `conftest.py` can add a broad exception handler that hands an assertion failure to another caller. If the recognizer cannot prove that the failure still reaches the test, an accompanying production edit in an opaque language such as Cython cannot establish that the test still works. A high-severity `BROAD_EXCEPT_ADDED` can then block an honest edit. The earlier R4 census completed 881 comparisons and left 6,554 incomplete, including one partial member. The rate of honest blocks in that remaining history is unknown. [Previous disposition and history](https://github.com/taipei49314/checkwash/blob/096b5362a838929ea33c625bba15f9d3bd5faa52/docs/d176-cost-disposition-0.13.1.md)

I checked the two Git blob IDs in the 0.13.1 tag's source, the published 0.13.1 zipapp, and the frozen candidate. The gating implementation is `c1b9a6e31dc6ba5c7011ccc088f271341de67f7d` in all three. The Python failure-relay recognizer is `89e4947faa6cfd6a7452b6edddbcc77dcf5ffca8` in all three. [Gating implementation](https://github.com/taipei49314/checkwash/blob/096b5362a838929ea33c625bba15f9d3bd5faa52/src/checkwash/gating.py#L1244) · [Failure-relay recognizer](https://github.com/taipei49314/checkwash/blob/096b5362a838929ea33c625bba15f9d3bd5faa52/src/checkwash/frontends/python/failure_relays.py)

## Replay of the three known uvloop cases

On 2026-11-23 from 12:16:49 to 12:17:02 UTC, the published 0.13.1 zipapp and the frozen candidate each ran `check <first-parent>..<commit> --format json` on the three pre-existing uvloop pairs. Each of the six CLI processes exited 0 with a pass verdict, an empty findings list and empty stderr. Each pair had byte-identical stdout. I also checked the six saved streams from the 0.13.1 preparation against their original hashes. Their JSON matched the current results after changing only `run.checkwash_version` from 0.13.0 to 0.13.1, and their exits and stderr matched. [Frozen historical inputs](https://github.com/taipei49314/checkwash-lab/blob/ec15f59d592bf82ffb6f4d9ee68fe2a626568af3/notes/r29-comparison-013-antigravity-20261116/uvloop/members.json)

| uvloop commit | First parent | SHA256 of stdout from either engine |
| --- | --- | --- |
| `7b202ccf644396a4ae8ff8053578058f5023ac63` | `ae44ec2d9d3b13c708bd65cf91c52178c37f34a4` | `e87efdc7c96db82752f678627c1eb8998c33437dd596697573de469c27524524` |
| `2081db8927dc2d3a66b7c8d7aa317d71aba198f9` | `c808a663b297bb2aee745523c277d6fafecebbeb` | `f66538d18e7cfd0ad8e0f525788e7cf2b2002d5c9719ba5641b3caceaa0a06f6` |
| `9cba7493a152e5a77bbde9a32143d84433d1cd3d` | `ee054206b00c15988f0f71c4a947cb4d13d2af5a` | `48e4ef4c8f4638d6c592dbdbb0fbc63b5765331ded2a8a22f48dcd7ee0bf7432` |

The replay ran on LAPTOP-01AGNPJU, Windows build 26200, CPython 3.11.9, `HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`. All 239 candidate source blobs matched Git before and after execution. The published zipapp was 1,079,499 bytes, SHA256 `0a987325c6f738129f5dbdc1e0287cfeab40517342b46df80707cccff8dd2839`. The frozen membership SHA256 was `a376cc17121882d82c196e26dac031e191e494027a23eb40d188c37410d74969`. The replay receipt SHA256 is `b873e379f647fde631fa288652a3cee182b1c09b245d2192323718545451b3f0`. The evidence archive `D176-uvloop-096b5362.zip` contains the commands, raw outputs, exits, input identities and receipt, SHA256 `33725be06ca6204ba394ca6fb0962503454e6c497cd543a61f391a67ca8d799c`. [Published zipapp](https://github.com/taipei49314/checkwash/releases/download/v0.13.1/checkwash.pyz)

The three known relays continue to pass. D-176 preserves the requirement for evidence that the assertion can still fail. A maintainer can review an individual block and approve an expiring base-side exemption. Other handlers in the same file with the same fingerprint also match that exemption. These three selected pairs supply no frequency estimate for the remaining history. [Prior cost review](https://github.com/taipei49314/checkwash/blob/096b5362a838929ea33c625bba15f9d3bd5faa52/docs/d176-cost-disposition-0.13.1.md#grounds-for-the-recommendation)
