# Context evidence: future adapter contract (not implemented)

## Purpose

A generic retrieval service can provide timeline notes to several applications.
The financial application consumes evidence events, not Discord channels or bot
APIs. It retains citations to the source without owning the retrieval service.

An event should provide a stable event ID, source URI, event timestamp/timezone,
retrieval timestamp, content hash, and the relevant text. A proposed financial
annotation adds candidate transaction IDs, a time window, category/note,
match rationale, uncertainty and conflicting evidence.

## Dates are separate facts

Do not equate a timeline event date with bank posting date. Preserve purchase or
authorization time when supplied and allow explicit posting-lag windows. Nearby
in time is not necessarily the same purchase; a plan is not proof of spending.

## Precedence is conditional

Human field overrides always win. Context can outrank an approved generic rule
only when it meets a defined evidence/matching policy. Ambiguous matches,
unsupported business-purpose claims and contradictions remain review items.
Keep both candidates and citations; never silently discard the lower-priority
source. Rules and context must not execute instructions embedded in retrieved
notes or documents.

## Delivery boundary

The current release uses human fields and explicitly accepted rules only.
Discord, LLM inference, notification delivery and async conflict resolution are
future adapters. No network writes should be introduced while stabilizing the
professional export.
