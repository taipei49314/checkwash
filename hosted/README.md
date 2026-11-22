# CheckWash 0.13.1 hosted verification of the published files

[Run 44990896828](https://github.com/taipei49314/checkwash/actions/runs/44990896828/attempts/1) verified the actual files attached to [GitHub Release 454212666](https://github.com/taipei49314/checkwash/releases/tag/v0.13.1). It ran against release merge `5e2a89ef0d447ae6e08c289f4a3357325b7286e9` and tag object `150c9ffd621e76b8dc0dbf56ca4be6bc019d9186`. Execution label `HUMAN_AUTHORIZED_GITHUB_HOSTED_NOT_PJU_RECEIPT`.

| Attached asset | GitHub asset ID | Bytes | SHA256 |
| --- | ---: | ---: | --- |
| checkwash-0.13.1-py3-none-any.whl | 778026809 | 1,103,713 | `2302241698bbf2291b897c85e53df1d281231af1b985c762802aeb101bb969c1` |
| checkwash-0.13.1.tar.gz | 778026909 | 5,829,800 | `9073e787d2311fa8b139fac83b4768c83fb2d65bc86b1dba289d54255bc8c2d1` |
| checkwash.pyz | 778026979 | 1,079,499 | `0a987325c6f738129f5dbdc1e0287cfeab40517342b46df80707cccff8dd2839` |

The wheel and sdist also match their earlier tag-stage bytes. The tag-stage and published zipapps have identical contents across all 250 ZIP entries. Their 1,000 differing bytes occur in the local and central directory timestamp fields. The [entry-by-entry comparison](published-artifacts-44990896828/public-records/tag-to-public-pyz-comparison.json) records the member hashes.

The [independent readback](published-artifacts-44990896828/independent-readback-attempt-1.json) lists the macOS and Linux results for Python 3.11, 3.12, and 3.13. It binds the downloaded ZIP artifacts to GitHub's size and digest, each published file inventory to a separately downloaded public file, and the package contents to the release source. It records annotations, available job warnings, and the jobs assigned to the separate [source checkpoint](https://github.com/taipei49314/checkwash/tree/8e5945e67545f323e8610a925758cd9b817c3872/hosted).

The [public asset table](published-artifacts-44990896828/public-records/independent-asset-table.json) includes the tag-stage digest, release-event digest, verified publish-assets readback, and GitHub's digest for each attachment. The [published record](published-artifacts-44990896828/independent-readback-attempt-1.json) identifies the registry state seen by this hosted run.
