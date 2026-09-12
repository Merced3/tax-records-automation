"""Crash-safe writes, automatic snapshots, hashing, and a change journal."""

import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Iterable, Sequence


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def backup_file(path, repo_root, reason="rewrite"):
    path = Path(path)
    if not path.exists():
        return None
    root = Path(repo_root)
    try:
        relative = path.resolve().relative_to(root.resolve())
    except ValueError:
        relative = Path(path.name)
    destination = root / "backups" / timestamp() / reason / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    return destination


def atomic_write_csv(path, header: Sequence[str], rows: Iterable[Sequence],
                     repo_root=None, backup_reason="rewrite"):
    """Write beside the destination, fsync, validate, then os.replace.

    Existing files are snapshotted first. A crash can leave a harmless .tmp,
    but cannot truncate the current good file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if repo_root is not None:
        backup_file(path, repo_root, backup_reason)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                                    dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            count = 0
            for row in rows:
                writer.writerow(row)
                count += 1
            f.flush()
            os.fsync(f.fileno())
        with open(tmp_name, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            actual_header = next(reader, None)
            actual_count = sum(1 for _ in reader)
        if actual_header != list(header) or actual_count != count:
            raise IOError("temporary CSV failed post-write validation")
        os.replace(tmp_name, path)
        return count
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def atomic_write_json(path, value, repo_root=None, backup_reason="rewrite"):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if repo_root is not None:
        backup_file(path, repo_root, backup_reason)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                                    dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        with open(tmp_name, encoding="utf-8") as f:
            json.load(f)     # validate before replacing the good file
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def journal(repo_root, event, details):
    """Append-only operational journal; fsynced before returning."""
    path = Path(repo_root) / "backups" / "journal.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"at": datetime.now(timezone.utc).isoformat(), "event": event,
             "details": details}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())
