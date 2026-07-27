# 0004 — Decoded event table column projection contract

Status: accepted

## Context

`load_decoded_events` (the light *Decoded event table* path — registry codes
resolved to labels, no people/venue joins) takes an optional `columns` argument so
a Consumer can pull only the fields it needs and skip the upstream work the rest
would cost. The `.h5` stores registry-indexed columns as raw `*_id` fields
(`encounter_type_id`, `infector_symptom_id`), which the decode step turns into
label columns under the `*_id`-stripped names (`encounter_type`,
`infector_symptom`). So a projection argument could plausibly speak either
vocabulary — the raw field names on disk, or the decoded output names — and the two
have different ergonomics and failure modes.

## Decision

`columns` names **decoded OUTPUT** columns (`encounter_type`, `infector_symptom`)
or raw passthrough fields (`time`, `person_id`) — **never** the raw `*_id` fields.

- Requesting a decoded column decodes **only** its registry (others are not even
  loaded) and **drops** the source `*_id` from the result.
- Passthrough-only requests (e.g. `["time"]`) load **no** registry at all.
- Names are validated against a header-only peek of the dataset's compound dtype
  (`dtype.names`, no row data read); an unknown name raises `KeyError` listing the
  valid columns.
- Internally a **superset** of raw columns is read — the requested passthroughs,
  each requested decoded column's source `*_id`, plus `infector_id` whenever
  `infector_symptom_id` is read (the no-infector mask needs it) — then the frame is
  narrowed to exactly `columns`, in requested order. So masking/decoding stay
  correct regardless of what the caller asked for.
- Field projection pushes down into the raw read (`h5py` `dset.fields(...)`), so
  peak RAM scales with the selected fields, not the whole record.
- `columns=None` returns the whole decoded table (all default registries decoded,
  `*_id` kept), unchanged from before.

## Consequences

- Consumers speak in resolved labels, the vocabulary they actually reason about —
  not file-internal id encodings that are an implementation detail of the log.
- The output-name → `*_id` → registry mapping is the inverse of the decode step
  (`_decoded_column_name` + `DEFAULT_REGISTRY_COLUMNS`); the two must stay in step.
- A caller cannot request a raw `*_id` column by name — if the encoded index is
  ever wanted, that is a deliberate future extension, not the default.
- The `infector_id` mask dependency is implicit: asking for `infector_symptom`
  quietly reads `infector_id` too (then discards it). Documented here and in the
  `load_decoded_events` docstring so it is not surprising.
- Validation for projected **lookup** reads (`load_venues_lookup` /
  `load_people_lookup`) now lives in `load_raw_table`, sharing this same
  friendly-`KeyError` contract — the check runs from the single open read handle,
  so a projected lookup read no longer re-peeks the header (was one open per read).
