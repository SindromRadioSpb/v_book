# UI DoD Evidence: Audio Pipeline

## Smoke matrix

1. Open `User Dictionaries` and verify `Audio` column renders.
2. Select rows -> context menu contains `Generate Audio Selected (N rows)...`.
3. Select rows -> context menu contains `Play Audio Selected (N rows)`.
4. Run `Generate Audio...` in `User Dictionaries` and verify V3 progress (stage, counters, activity, cancel/pause/resume).
5. After generation, refresh and verify status transitions `missing -> ready|failed`.
6. Run `Generate Audio...` in `Dictionary`.
7. Run `Generate Audio...` in `Terms`.
8. Run `Generate Audio...` in `Term Cards`.
9. Run `Generate Audio...` in `Translation Management`.
10. Verify all views keep UI responsive while worker is running.
11. `Play Audio` on rows with ready assets opens system player.
12. `Play Audio` on rows without ready assets shows non-fatal guidance.
13. Switch provider mode to `force:<provider>` and verify activity log shows chosen provider.
14. Use write mode `MISSING_ONLY` and verify existing ready assets are skipped.
15. Use write mode `REGENERATE_ALL` and verify assets are regenerated.
16. Confirm source-only contract by generating on rows where translation is empty/non-empty and output behavior is identical.
17. Validate TM `Audio` sorting still works and remains stable across pages.
18. Open `Tools -> Translation -> Audio Provider Settings...` and verify `mms_tts_local` is disabled by default.
19. Verify tabs exist: `Rate Limits`, `Provider Chain`, `Advanced Settings`.
20. In `Advanced Settings` for `Google Cloud TTS` click `Load from File...`, load Service Account JSON, verify preview shows configured project.
21. Click `Clear` and verify credential preview returns to \"No Service Account JSON configured\".
22. In `Advanced Settings` verify `Budget Guards` fields can be edited and saved.
23. Click `Refresh Usage` and verify current minute/day/month counters are shown.
24. In Batch Audio dialog choose `force:mms_tts_local` without accepted license and verify license-gate prompt appears.
25. Accept license gate, re-run `force:mms_tts_local`, and verify provider is allowed (if local deps exist) or fails with explicit dependency message.
26. In any lexical view, run `Edit Pronunciation...`, save manual niqqud/IPA override, then regenerate audio and verify status refresh.
27. Export pronunciation dictionary to TSV, import back, and verify `manual override > auto` remains unchanged.
28. Verify `Play Audio Selected (N rows)` exists in context menu for UD/Dictionary/Terms/Term Cards/TM.

## Non-functional evidence checklist

- No per-row blocking calls in UI thread during generation.
- Worker-only long ops (`UserDictGenerateAudioWorker`, `BatchGenerateAudioWorker`).
- DB writes are chunked and cancellable at safe boundaries.
- `audio_rel_path` remains relative and sanitized.
- Provider failures are aggregated in activity log/final summary (no modal spam in loop).

## Screenshot/log checklist

- Batch dialog with provider + write mode.
- V3 progress dialog mid-run.
- Post-run table with `ready` and `failed` statuses.
- Context menu in each workspace with Generate/Play actions.
- TM sorted by `Audio` column.
- Audio Provider Settings dialog with MMS license-gate state.
- Audio Provider Settings dialog with 3 tabs and Google credentials preview.
- Edit Pronunciation dialog and regenerated audio result.
