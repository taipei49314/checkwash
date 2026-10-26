"""Seal clean existing checkout bytes against Git; retain a complete source archive."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parent / "checkwash-ux"
OUT = HERE / "seal"
OUT.mkdir(exist_ok=False)


def git(*args):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, check=True).stdout


assert not git("status", "--porcelain", "--untracked-files=all")
head = git("rev-parse", "HEAD").decode().strip()
algorithm = git("rev-parse", "--show-object-format").decode().strip()
assert algorithm in {"sha1", "sha256"}
rows = []
for entry in git("ls-tree", "-rz", "--full-tree", "HEAD").split(b"\0"):
    if not entry:
        continue
    metadata, name_raw = entry.split(b"\t", 1)
    mode, kind, oid_raw = metadata.split()
    assert mode in {b"100644", b"100755"} and kind == b"blob", name_raw
    name = name_raw.decode("utf-8")
    data = (REPO / name).read_bytes()
    actual = hashlib.new(algorithm, b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    rows.append({"path": name, "mode": mode.decode(), "git_blob": oid_raw.decode(),
                 "actual_git_blob": actual, "matches": actual == oid_raw.decode(),
                 "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
assert all(row["matches"] for row in rows), [row["path"] for row in rows if not row["matches"]]
source_zip = OUT / ("source-" + head[:8] + ".zip")
with zipfile.ZipFile(source_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for row in rows:
        archive.write(REPO / row["path"], row["path"])
assert not git("status", "--porcelain", "--untracked-files=all")
assert git("rev-parse", "HEAD").decode().strip() == head
pin = HERE / "final-source-sha.txt"
assert not pin.exists()
pin.write_text(head + "\n", encoding="utf-8")
record = {"source_sha": head, "source_directory": str(REPO), "git_object_format": algorithm,
          "reuse_existing_active_checkout": True, "all_tracked_bytes_match_git": True,
          "tracked_files": len(rows), "files": rows, "host": platform.node(), "python": sys.version,
          "provenance": "HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL",
          "created_utc": datetime.now(timezone.utc).isoformat(), "source_archive": str(source_zip),
          "archive_sha256": hashlib.sha256(source_zip.read_bytes()).hexdigest()}
(OUT / "source-seal.json").write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
print(json.dumps({key: value for key, value in record.items() if key != "files"}, indent=2))
