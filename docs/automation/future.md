# Future integrations

## Google Sheets

Build in stages:

1. Read-only authentication and tab discovery.
2. Read existing rows and produce a local diff.
3. Verify the diff against the final CSV hash.
4. Batch-write a rectangular range in one API request per tab.
5. Re-read and compare every written row.
6. Keep writing disabled until explicitly approved.

Google Sheets is an output, not the annotation database.

## Bank ingestion APIs

Chase does not offer a simple personal-account statement API for small
projects. Plaid or similar aggregators can provide structured transactions for
future years, but official PDFs remain tax evidence. API data becomes another
ingestion plugin and must use staged, resumable, atomic acceptance described in
`recovery.md`.

## Discord or another interface

The reusable boundary is the human-work queue: transaction evidence + current
suggestion + rule provenance. A UI may approve, override, defer, or explain a
row. It writes through the annotation service using Transaction ID and appends
to the journal. It does not parse statements or decide tax treatment itself.

The same core should support a CLI, Discord bot, desktop view, or web UI without
copying financial rules into those interfaces.
