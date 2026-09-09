# Frozen natural preparation inputs

`natural-540-v1.zip` preserves nine public evidence files in a deterministic
archive: the original candidate manifest and protocol, the first prepared
manifest, and six ordered API history receipts. Its SHA-256 and decompression
bound are pinned by `../natural-context-repair-v1.json`. The loader verifies
the archive before reading members, rejects duplicates or unexpected paths,
and reads bytes without filesystem extraction.

Provenance:

- Original intake: [run 34320615128](https://github.com/taipei49314/checkwash/actions/runs/34320615128), manifest SHA-256
  `6f44fa4836a903bad3bba4eea2667dde954abc81304e4fcfc02e4290606bcd32`.
- First preparation: [run 34328792279](https://github.com/taipei49314/checkwash/actions/runs/34328792279), manifest SHA-256
  `2d59eff5f2e3039f608dfd59eec7153de91440f9ec00dd0d41ceb2b58429f10c`.
- Archive SHA-256:
  `8fae0ec1235a9bac59f5e0531f423f05fc4832bfb9cb4ae44790e7edeb4e3876`;
  1,045,774 compressed bytes, 17,392,186 expanded bytes.

These inputs are retained independently of GitHub Actions retention. Context
bytes are reacquired from the same public Git revisions and compared with all
previous source hashes; upstream Git availability is still required. This is
not an offline Git archive. A missing revision or changed source fails the
preparation and preserves the error instead of selecting a replacement.

All labels remain UNREVIEWED and predictions remain NOT_RUN. The earlier
manifest is historical evidence, including its documented collection gaps;
new packets supplement it without overwriting that history.
