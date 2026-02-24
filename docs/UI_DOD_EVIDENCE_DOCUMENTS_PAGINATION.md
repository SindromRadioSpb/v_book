# UI DoD Evidence — Documents Server-Side Pagination

## Scope

This document covers premium UX behavior for Documents in large projects:

- Server-side pagination (`LIMIT/OFFSET`) only.
- Global sorting and filtering (`ORDER BY` / `WHERE`) before page slicing.
- Background loading with stale-request protection (`request_id`).

## Functional checks

- Opening a large project loads only the current page rows (no full-table materialization).
- Header sorting applies globally and is stable across pages.
- Title search and Tag filter apply globally and update both rows and total count.
- Page size / page index controls work with first/prev/next/last navigation.

## Smoke matrix

| Scenario | Steps | Expected |
|---|---|---|
| Huge project open | Open project → Documents | UI remains responsive; status shows loading; first page appears |
| Global sort | Click `File Name` header, then go to page 2 | Rows remain globally sorted, not locally re-sorted page-only |
| Global title search | Type 2+ chars in title search | After debounce, total count + rows update globally |
| Global tag filter | Enter tag in Tag filter | Total count changes globally; rows all match tag filter |
| Rapid changes | Quickly type search + toggle sort | Only latest response is applied (no stale flicker back) |
| Pagination controls | Use first/prev/next/last and page spin | Range label and controls stay consistent with total |

## Non-functional checks

- No per-row SQL from table paint/render path.
- No UI-thread blocking DB scans for count/page fetch.
- Worker results are ignored if `request_id` is stale.

## Notes

- Sort stability is guaranteed with secondary `doc_id ASC`.
- Filter/sort changes reset page to 1.
