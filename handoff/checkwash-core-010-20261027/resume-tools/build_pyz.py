"""Build zipapp from the sealed tracked source closure, without ignored caches."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipapp
import zipfile

HERE = Path(__file__).resolve().parent
seal = json.loads((HERE / "seal/source-seal.json").read_text(encoding="utf-8"))
archive = Path(seal["source_archive"])
assert hashlib.sha256(archive.read_bytes()).hexdigest() == seal["archive_sha256"]
stage = HERE / "pyz-source-stage"
stage.mkdir(exist_ok=False)
rows = {row["path"]: row for row in seal["files"] if row["path"].startswith("src/")}
with zipfile.ZipFile(archive) as bundle:
    for name, row in rows.items():
        parts = PurePosixPath(name).parts
        assert not PurePosixPath(name).is_absolute() and not set(parts) & {"", ".", ".."}
        target = stage.joinpath(*parts)
        assert target.resolve().is_relative_to(stage.resolve())
        data = bundle.read(name)
        assert hashlib.sha256(data).hexdigest() == row["sha256"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
target = HERE / "artifacts/checkwash.pyz"
assert not target.exists()
zipapp.create_archive(stage / "src", target=target, main="checkwash.zipapp_entry:run", compressed=True)
record = {"source_sha": seal["source_sha"], "tracked_source_files": len(rows),
          "source_archive_sha256": seal["archive_sha256"], "ignored_cache_members_included": False,
          "artifact": str(target), "bytes": target.stat().st_size,
          "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
(HERE / "artifacts/pyz-build-identity.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
print(json.dumps(record, indent=2))
