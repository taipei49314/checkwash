# Private completed-artifact checkpoint / restore map

This snapshot preserves exact committed candidate 1be28ce5de72dcb617818077aaf11e3b1cf7a976, source version
0.10.0/IR3, its four completed source/distribution artifacts and nine terminal
build/install/smoke/identity captures. It is not a release, PyPI upload, merge,
new 1.0 authorization, full-suite result or assertion-qualification result.
Separate full-suite and all three qualification workers are excluded even if
they later finish. No active/partial qualification payload is in this archive.
The prior evidence checkpoint is 815dc12b7786783a7f6004d5360640d37ee49309; its metadata product
root is not the separate candidate source. Historical results stay immutable.

Extract into a new task root, preserving the work/ux-stage9 and work/trusted
layout. MANIFEST source_path/path names identify original/transport .py/.xml/.diff
copies: restore those exact original filenames explicitly before using a
controller. Restore BUNDLE-TOOLS files only to their listed stage11 paths.
The selected source ZIP contains all 3087 tracked source members and the wheel,
sdist and pyz contain the verified 213 package source members. The sdist also
contains generated PKG-INFO; the wheel retains RECORD/METADATA identity proof.

Fetch exact candidate 1be28ce5de72dcb617818077aaf11e3b1cf7a976 and trusted baseline 1ffe283d7d947fecc426dea99323b0a2620a9482 into a clean
work/checkwash-inactive-fixture checkout. A source ZIP alone does not restore
Git objects/history. Use task-local core.autocrlf=false/core.eol=lf for checkout;
do not change host-global Git settings. Verify all physical bytes/blob IDs
against the stage9 seal before any new work. Runtimes are rebuildable from the
retained version/install receipts and distributions; no venv/cache is copied.
Nothing from this archive is automatically imported, installed or executed.

The seven stage10 #263 files are READ_ONLY / NOT_IMPLEMENTED analysis. The old
fixture lacks a supplied producer; do not infer add(a,b)=a+b or erase class/self
without the documented source/call-effect/marker/context obligations.
Build/smoke exit0 and source identity establish only their bounded named checks.
The goal remains incomplete, integration remains BLOCK in prior stage7 evidence,
and Nelson must decide before 1.0. Privacy scans are bounded checks, not a
universal guarantee. This is a private checkpoint, not a published product.
