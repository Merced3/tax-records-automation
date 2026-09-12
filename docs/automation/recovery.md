# Backup, recovery, and interruption safety

## Two complementary protections

### Snapshots

Before a durable annotation or generated output is replaced, the existing file
is copied under:

```text
backups/<UTC timestamp>/<reason>/<original path>
```

Snapshots restore a coherent whole-file state after accidental deletion, bad
rules, or an unwanted migration.

### Journal and baseline

`backups/journal.jsonl` records automated rewrites and human-column changes
detected since the last machine-written annotation baseline. The baseline lives
under `backups/state/annotations/`. If an entire annotated row is accidentally
deleted, the next `annotate` run restores both the transaction and its last
human fields from this baseline.

Snapshots answer "restore yesterday." The journal answers "what changed?"
Per-row backup files are avoided because they are harder to restore coherently.

## Crash safety

Writes use a temporary file in the destination directory, flush and fsync it,
read it back to validate headers/row count, then atomically replace the current
file. A crash may leave a harmless temporary file but should not truncate the
last good file.

## Migrations

An identity or schema migration can change Transaction IDs for unchanged source
rows, which risks orphaning irreplaceable human text. Required order:

1. Snapshot `annotations/` to `backups/<name>/` before running anything.
2. Run `annotate` for every year; the safety stop aborts (leaving files
   byte-identical) if any human-annotated row cannot be matched.
3. Prove preservation, do not assume it:

   ```powershell
   python tools/verify_human_preservation.py backups/<snapshot-dir>
   ```

   It compares human text by financial content rather than by ID, and reports
   both lost and unexpectedly gained values.

Never test deletion or migration behaviour against live human annotations; use
synthetic rows in a temporary directory.

## Recovery procedure

1. Stop running commands.
2. Do not delete the damaged/current file.
3. Find the newest relevant snapshot under `backups/`.
4. Compare it with the current file.
5. Copy the chosen snapshot back only after preserving both versions.
6. Run `audit`, then `annotate`, then `build`.

## Future network ingestion

Plaid or another network source must follow a staged-commit rule:

1. Download to a staging file.
2. Preserve the previously accepted local data.
3. Validate authentication response, expected schema, account identity, date
   coverage, and record count.
4. Hash and journal the staged data.
5. Commit with atomic replacement only after validation.
6. On timeout/Wi-Fi loss, retain the last good state and resume/retry without
   duplicating records.

A network failure must never mean an empty successful import.
