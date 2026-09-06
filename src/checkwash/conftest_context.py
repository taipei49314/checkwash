"""First-party patch identity comes from snapshot files, not changed paths."""

from checkwash.change import EngineError
from checkwash.roles import is_artifact


class ConftestContext:
    def __init__(self, changes, reader):
        self.changed = {c.path.replace("\\", "/"): (c.before, c.after) for c in changes}
        self.reader = reader
        self.cache = {}

    def contains(self, dotted, side):
        parts = dotted.split(".")
        if not all(part.isidentifier() for part in parts):
            return False
        # The tail can be a class or attribute below an imported module.
        # Resolve a real Python source file at root or the conventional src/.
        for size in range(len(parts), 0, -1):
            module = "/".join(parts[:size])
            for prefix in ("", "src/"):
                for suffix in (".py", "/__init__.py"):
                    path = prefix + module + suffix
                    if is_artifact(path):
                        continue
                    if path in self.changed:
                        data = self.changed[path][side]
                    else:
                        if path not in self.cache:
                            if self.reader is None:
                                raise EngineError("conftest patch targets require a complete strict snapshot reader")
                            if len(self.cache) >= 128:
                                raise EngineError("conftest patch target resolution exceeds the snapshot read budget")
                            self.cache[path] = self.reader(path)
                        data = self.cache[path]
                    if data is not None:
                        return True
        return False
