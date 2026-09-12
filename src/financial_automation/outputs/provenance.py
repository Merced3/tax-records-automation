"""Manifest provenance: what code, config, decisions, and evidence produced
this export, and whether that state was reproducible at all.

A manifest that records only source hashes and a Git commit is misleading when
the working tree is dirty: the commit does not describe the code that ran.
Every input class is therefore hashed from the bytes actually used:

- code:        every tracked .py file under src/ and run.py
- config:      app.yaml, the private rules file, and rule approvals
- annotations: the human decision files
- sources:     the statement files (hashed by the ingestion plugins)

and the working tree's dirty state is recorded explicitly.
"""

from pathlib import Path
import subprocess

from ..safety import sha256_file


def _run(root, *args):
    try:
        return subprocess.check_output(["git", "-C", str(root), *args],
                                       text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return None


def git_state(root):
    commit = _run(root, "rev-parse", "HEAD")
    status = _run(root, "status", "--porcelain")
    state = {
        "commit": commit.strip() if commit else None,
        "branch": (_run(root, "rev-parse", "--abbrev-ref", "HEAD") or "").strip() or None,
    }
    if status is None:
        state["dirty"] = None
        state["dirty_files"] = None
        state["reproducible_from_commit"] = False
        state["note"] = "git unavailable: the running code cannot be identified by commit"
        return state
    changed = [line[3:].strip() for line in status.splitlines() if line.strip()]
    state["dirty"] = bool(changed)
    state["dirty_files"] = changed
    state["reproducible_from_commit"] = not changed
    if changed:
        state["note"] = ("working tree had uncommitted changes; this output is NOT "
                         "reproducible from the recorded commit alone")
    return state


def _hash_tree(root, relative_dir, pattern):
    base = Path(root) / relative_dir
    out = {}
    if not base.exists():
        return out
    for path in sorted(base.rglob(pattern)):
        if "__pycache__" in path.parts or not path.is_file():
            continue
        out[str(path.relative_to(root)).replace("\\", "/")] = sha256_file(path)
    return out


def input_hashes(root, config, year):
    """Hash the code, configuration, and human decisions that shaped output."""
    root = Path(root)
    code = _hash_tree(root, "src", "*.py")
    if (root / "run.py").exists():
        code["run.py"] = sha256_file(root / "run.py")

    config_files = {}
    for relative in ("config/app.yaml",
                     config.get("rules_path", "config/rules.yaml"),
                     config.get("rule_approvals_path", "annotations/rule-approvals.yaml")):
        path = root / relative
        if path.exists():
            config_files[str(relative).replace("\\", "/")] = sha256_file(path)

    annotation_path = root / "annotations" / f"{year}.csv"
    annotations = ({f"annotations/{year}.csv": sha256_file(annotation_path)}
                   if annotation_path.exists() else {})
    return {"code": code, "config": config_files, "annotations": annotations}


def decision_provenance(resolved):
    """Count where each exported field's value actually came from, so a
    rule-generated value is never presented as human-typed text."""
    counts = {}
    for result in resolved.values():
        for field, source in (("category", result.category_source),
                              ("note", result.note_source),
                              ("tax_treatment", result.tax_treatment_source)):
            counts.setdefault(field, {})
            counts[field][source] = counts[field].get(source, 0) + 1
    return counts
