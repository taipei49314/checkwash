# CheckWash v0.13.1 hosted source verification

GitHub-hosted run [44970495987](https://github.com/taipei49314/checkwash/actions/runs/44970495987/attempts/1) verified the release source at merge `5e2a89ef0d447ae6e08c289f4a3357325b7286e9` before tagging. The successful attempt was 1. Original artifact ZIPs carry their GitHub digests in the artifact inventory. The attempt directories retain those ZIP bytes. The run and job records, job annotations, and downloadable logs are retained alongside them.

Execution label `HUMAN_AUTHORIZED_GITHUB_HOSTED_NOT_PJU_RECEIPT`. Each of the six legs qualified the source assertion contracts and verified its inventory. The six emitted corpus payloads were byte-identical and matched the PJU release batch digest `3fc8e34c4c9bfe9cfda3645e36c15e9cdbab8888fa8d432e949924be00dcc848`.

| Hosted runner | Python | Test cases | Subtests | Skips | New or changed skips since 0.13.0 |
| --- | --- | ---: | ---: | ---: | ---: |
| ubuntu-latest | 3.11.18 | 23,367 | 67 | 15 | 0 |
| ubuntu-latest | 3.12.16 | 23,367 | 67 | 15 | 0 |
| ubuntu-latest | 3.13.18 | 23,367 | 67 | 15 | 0 |
| macos-latest | 3.11.9 | 23,367 | 67 | 17 | 0 |
| macos-latest | 3.12.10 | 23,367 | 67 | 17 | 0 |
| macos-latest | 3.13.17 | 23,367 | 67 | 17 | 0 |

The composite Action at `62656df812372c085b4d32c7864fcdfaccd0318a` checked `0477013159face076a2c6a887f9d5b235c76d5e5..5e2a89ef0d447ae6e08c289f4a3357325b7286e9` with the default `high` threshold and exited 0. The [independent readback](source-at-M-44970495987/independent-readback-attempt-1.json) records each skip and reason, job conclusions, system and Python identities, test-count comparisons with the PJU batch, and the verified Action package digest.
