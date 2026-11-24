# Known issues for CheckWash 0.13.2

These limits apply to the released 0.13.2 CLI and Action. [Installation guide](install.md) · [Publication record](releases/v0.13.2-publication-verification.md)

The Python changes cover supported project layouts and import resolution in the reviewed test-move and sibling-module cases. Dynamic imports, indirect fixture dispatch and unrecognised test collection settings can still limit analysis. Read analysis diagnostics in the CLI output, particularly when running on a project with custom test discovery. [Reviewed import changes](releases/v0.13.2-public-launch.md) · [Coverage and collection limits](../README.md#know-the-limits)

Two JS/TS commits in the 3,600-case comparison still exit 2 because the strict snapshot reader encounters symlinks. Both engines reported the same error in Apollo Client and Undici. The Django results describe two measured ranges and include their original analysis diagnostics. [Comparison](releases/v0.13.2-public-launch.md#measured-scan-time-and-verdicts)

The separate work on imported helpers that skip or mark a test as an expected failure remains tracked in [issue #622](https://github.com/taipei49314/checkwash/issues/622). Other limits include false blocks on legitimate refactors and the remaining risk from broad exception handlers in tests. [Refactor measurements](../README.md#know-the-limits) · [D-176 disposition](d176-cost-disposition-0.13.2.md)
