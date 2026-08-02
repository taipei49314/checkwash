# Tracked sweep output

The false-positive corpus is six third-party repositories, which this clone
cannot contain. These JSONs are the raw output of

```bash
greenwash sweep HEAD --limit 300 --repo <path-to-clone>
```

for each of them, tracked so `benchmarks/RESULTS.md` can be regenerated from a
clone and so the numbers can be checked by someone who is not the author.

Each file records, under `corpus`, the newest and oldest commit of the range
it covered and the greenwash version that produced it. To reproduce: clone the
project, `git checkout <newest_commit>`, and re-run the command above. The
`commits_with_opaque_prod_change` count is how many commits carried a
production change greenwash cannot read (non-Python, deleted, unparseable) and
therefore received the blanket conservative exemption of THREATMODEL #4 — the
share of the pass rate that rests on a documented blind spot rather than on
analysis.

`make_results.py` refuses to publish the false-positive decomposition unless
the adjudication file describes exactly the set of commits these sweeps
blocked.
