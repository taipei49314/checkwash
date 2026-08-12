# Corpus expansion candidates (2026-08-13)

The false-positive corpus is six repositories — flask, httpx, attrs, click,
rich, starlette. Two of them are pallets projects and two are encode projects.
Every false-positive number this project publishes rests on that sample.

This page exists because 2026-08-13 produced a number that the sample cannot
carry: `TEST_PATCHES_SUBJECT`'s cost was bounded by measuring how often a human
commit adds a stand-in to a test that already existed — **once in 1800 commits**
(THREATMODEL 90). That bound is only as good as how much the corpus mocks, and
the corpus barely mocks: **≈128 patch call sites at HEAD across all six**.

The twenty repositories below were selected and counted by cloning, with

```
monkeypatch\.set|mock\.patch|patch\.object|mocker\.patch|respx|responses\.|freeze_time
```

They carry **31,641** patch call sites — a median of 373 each, against roughly
21 each in the current corpus. Re-running the T1.4 base rate here is the way to
find out whether "once in 1800" is a property of test-tampering or a property of
six libraries that rarely stub anything.

| name | commits | test dir | patch sites | domain |
|---|---|---|---|---|
| apache/airflow | 40,395 | `airflow-core/tests/` | 15,784 | workflow orchestration |
| mlflow/mlflow | 12,985 | `tests/` | 6,060 | ML lifecycle |
| saltstack/salt | 125,585 | `tests/` | 2,741 | devops configuration |
| ray-project/ray | 31,370 | `python/ray/tests/` | 1,174 | distributed computing |
| getsentry/sentry-python | 4,402 | `tests/` | 830 | error monitoring SDK |
| django/django | 34,865 | `tests/` | 649 | web framework |
| getmoto/moto | 10,790 | `tests/` | 481 | AWS mock SDK |
| python-poetry/poetry | 3,835 | `tests/` | 469 | CLI package manager |
| aio-libs/aiohttp | 14,009 | `tests/` | 457 | async HTTP |
| great-expectations/great_expectations | 13,734 | `tests/` | 374 | data quality |
| Azure/azure-cli | 13,715 | `src/azure-cli-core/.../tests/` | 372 | cloud CLI |
| huggingface/transformers | 23,630 | `tests/` | 310 | NLP / deep learning |
| localstack/localstack | 7,855 | `tests/` | 272 | cloud testing |
| pytest-dev/pytest | 17,612 | `testing/` | 271 | testing framework |
| bokeh/bokeh | 21,118 | `tests/` | 169 | visualization |
| scrapy/scrapy | 11,338 | `tests/` | 167 | web scraping |
| sqlalchemy/sqlalchemy | 18,214 | `test/` | 152 | ORM |
| pandas-dev/pandas | 38,623 | `pandas/pandas/tests/` | 109 | data manipulation |
| fastapi/typer | 1,747 | `tests/` | 104 | CLI framework |
| boto/boto3 | 7,811 | `tests/` | 75 | AWS SDK |

All permissive (MIT / BSD / Apache-2.0), all ≥800 commits, all with a manifest
at the root. `googleapis/google-cloud-python` was rejected as a monorepo
(396k+ sites over 100+ packages, which would dominate any aggregate).

`respx` appears in **none** of them, which is worth knowing before building a
detector for it: it is an httpx-specific mock and the corpus that would have
justified it is the one repository already excluded.

## Before running this

These are large. A full clone of all twenty is tens of gigabytes; the sweep
reads 300 commits per repository, so `--depth 400` is enough and is what should
be used. Adding them changes every published false-positive number, so it is a
round of its own with its own red-zone reconciliation — not something to fold
into an unrelated release.
