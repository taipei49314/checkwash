# examples/invoice — the 60-second demo, reproducible

This is the repository from the demo. Every frame you see is reproducible
here; nothing is staged.

```bash
cd examples/invoice
git init -q && git add -A && git commit -qm baseline

# the bug: invoice_total never rounds, so the test fails
python -m pytest -q          # 1 failed: 35.364999999999995 != 35.37

# now let an agent "fix" it by weakening the oracle instead of the code:
sed -i 's/== 35.37/> 0/' tests/test_billing.py
python -m pytest -q          # 1 passed  — CI is green, the bug is untouched

greenwash check              # ✗ ASSERT_WEAKENED high: EXACT_VALUE -> BOUND,
                             #   no production code changed. verdict: block.
```

The honest fix — rounding `invoice_total` to cents — leaves the exact
assertion in place and greenwash stays silent. That asymmetry is the whole
tool: a diff that makes the test pass by fixing the code is fine; a diff that
makes it pass by gutting the oracle is not.
