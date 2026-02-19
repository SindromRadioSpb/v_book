# UI DoD Evidence: SRS and Unified Statuses

## Smoke Matrix (minimum)

1. Cold start -> open `User Dictionaries` -> Browse mode renders with no crash
2. Add manual item -> origin marker shows `manual`
3. Add from `Dictionary` -> origin marker shows `project`
4. Add from `Terms` -> item appears in `User Dictionaries`
5. Browse table shows Study chip text+icon (not color-only)
6. Browse table shows status icons (translation/audio/noise)
7. Hover status column -> tooltip includes translation tier/audio/noise text
8. Hide noise default ON -> noise rows hidden by default
9. Toggle hide noise OFF -> noise rows visible with noise icon
10. Review mode opens and loads due queue
11. `Good` review updates interval/due and moves card forward
12. `Again` review increments lapse and sets due to next day
13. Suspended item is excluded from due queue
14. Dictionary/Terms show saved-to-UD indicator and tooltip
15. TM panel row tooltip shows study state for matching canonical key
16. Cross-view UD marker switches from `*` to `*!` when row is due
17. User Dictionaries context menu supports Suspend/Resume and due queue updates immediately
18. User Dictionaries `Mark Due Now` action moves selected reviewed items into due queue after refresh
19. User Dictionaries top summary strip updates totals by state for opened dictionary
20. User Dictionaries rows have study-state background highlighting (not color-only; tooltip/text still present)

## Non-Functional Evidence

- No per-row SQL for status data on page render
- Status metadata is loaded in batch per page
- Shared batch resolver: `UserDictionaryService.resolve_cross_view_status(...)`
- No UI freeze during long operations
- Existing long operations continue to use worker + `BatchProgressDialogV3`
- Table content remains scrollable at small window sizes
- Semantic color layer is additive only (icons/text/tooltip remain primary semantic carriers)

## Evidence Artifacts

- Test logs for new SRS/status test suite
- Manual screenshots for:
  - UD Browse
  - UD Review
  - Dictionary saved-to-UD indicator
  - TM tooltip example
- Suggested smoke capture set:
  - Review mode: `Again` then `Good` on same item, verify interval/lapse transition
  - Scope switch (`Current Project` -> `All`) in UD and TM, verify tooltip/state remains deterministic
