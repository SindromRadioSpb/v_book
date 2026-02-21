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
11. `Play Audio` on rows with ready assets starts internal in-app playback.
12. `Play Audio` on rows without ready assets shows non-fatal guidance.
13. Switch provider mode to `force:<provider>` and verify activity log shows chosen provider.
14. Use write mode `MISSING_ONLY` and verify existing ready assets are skipped.
15. Use write mode `REGENERATE_ALL` and verify assets are regenerated.
16. Confirm source-only contract by generating on rows where translation is empty/non-empty and output behavior is identical.
17. Validate TM `Audio` sorting still works and remains stable across pages.
18. Open `Tools -> Translation -> Audio Provider Settings...` and verify `mms_tts_local` is disabled by default.
19. Verify tabs exist: `Rate Limits`, `Provider Chain`, `Advanced Settings`, `Playback`.
20. In `Advanced Settings` for `Google Cloud TTS` click `Load from File...`, load Service Account JSON, verify preview shows configured project.
21. Click `Clear` and verify credential preview returns to \"No Service Account JSON configured\".
22. In `Advanced Settings` verify `Budget Guards` fields can be edited and saved.
23. Click `Refresh Usage` and verify current minute/day/month counters are shown.
24. In Batch Audio dialog choose `force:mms_tts_local` without accepted license and verify license-gate prompt appears.
25. Accept license gate, re-run `force:mms_tts_local`, and verify provider is allowed (if local deps exist) or fails with explicit dependency message.
26. In any lexical view, run `Mispronounced -> Add Pronunciation...`, save manual niqqud/IPA/reading override, then regenerate audio and verify status refresh.
27. Export pronunciation dictionary to TSV, import back, and verify `manual override > auto` remains unchanged.
28. Export pronunciation to PLS (IPA profile), import back, and verify `source=import_pls` rows are merged safely.
28. Verify `Play Audio Selected (N rows)` exists in context menu for UD/Dictionary/Terms/Term Cards/TM.
29. Verify row-level play control is visible in Audio column and uses delegate rendering (no widget-per-row lag).
30. Click row-level play on `ready` item and confirm internal playback starts in-app (no external player by default).
31. Click row-level play on `missing|failed` item and confirm safe non-fatal guidance.
32. Select 3 rows and run `Play Audio Selected (N rows)` in enqueue mode; verify queued sequential playback.
33. Open mini-player panel and verify `Now Playing`, queue list, and `Pause/Resume/Stop`.
34. Change cadence (`pre/gap/post`) in playback settings and verify interval behavior changes on next queue.
35. Switch playback mode `interrupt` and verify new play request stops current queue and starts immediate playback.
36. Switch playback mode `enqueue` and verify new play request appends to queue.
37. Confirm no UI freeze while playback queue advances.
38. Open `Tools -> Translation -> Pronunciation Bootstrap...` and verify model path controls are visible.
39. Run `Health Check` with no model path and verify mode shows `fallback` or `error` (explicit, non-ambiguous).
40. Configure model path, run `Health Check` again, verify mode and sample output are shown with latency.
41. Run bootstrap in `Dry-run` mode and verify V3 progress + final rollback summary.
42. Run bootstrap in write mode (`Fill missing auto`) and verify `source=auto_phonikud` rows increase without overriding manual entries.
43. Verify prefix retention case: source `התחנה הבאה` keeps full surface in generated niqqud (no dropped leading `ה`).
44. Verify malformed niqqud safety: value containing `_` or `|` never reaches spoken payload (provider receives sanitized text).
45. Regenerate provider switch sequence (`google -> mms -> google`) and verify playback resolves the latest generated asset.
46. Verify Niqqud column is present in `User Dictionaries`, `Dictionary`, `Terms`, `Term Cards`, and `Translation Management`.
47. Hover Niqqud cells and verify tooltip includes `source`, `confidence`, and `qc`.
48. Run `python scripts/diag_tts_payload.py --db-path "<db>" --lang he --src-text "רכב"` and verify output has no `HEBREW ACCENT ...` codepoints.
49. Run `python scripts/diag_tts_payload.py --db-path "<db>" --lang he --src-text "מהירות המותרת" --ssml` and verify output has no bidi/joiner `Cf` symbols (`U+200E/U+200F/U+200C/U+200D/U+2066..U+2069`).

50. In each table workspace (`Dictionary`, `Terms`, `User Dictionaries`, `Term Cards`, `Translation Management`) select rows and verify button `Pronunciation Bootstrap...` is enabled.
51. In each table workspace context menu verify action `Pronunciation Bootstrap Selected (N rows)...` opens bootstrap dialog with `Selection scope` hint.
52. For a row with legacy `norm_text` mismatch verify Niqqud still renders in table (fallback via `raw_src_norm`).

## Non-functional evidence checklist

- No per-row blocking calls in UI thread during generation.
- Worker-only long ops (`UserDictGenerateAudioWorker`, `BatchGenerateAudioWorker`).
- DB writes are chunked and cancellable at safe boundaries.
- `audio_rel_path` remains relative and sanitized.
- Provider failures are aggregated in activity log/final summary (no modal spam in loop).
- Playback actions resolve paths in one batch-safe call path and never trust absolute/parent paths.
- Delegate-based play controls are used (no `setIndexWidget` per row).
- Pronunciation bootstrap health mode is explicit (`real_inference/fallback/error`) in UI and persisted in settings.
- Effective spoken payload sanitizer removes taamim (`U+0591..U+05AF`) and bidi/joiner format chars while preserving niqqud marks.
- Playback latest-ready resolution is deterministic by refreshed `updated_at`.
- Cross-view pronunciation overlay supports canonical lookup with legacy fallback (`raw_src_norm`) to avoid false missing Niqqud rows.

## Screenshot/log checklist

- Batch dialog with provider + write mode.
- V3 progress dialog mid-run.
- Post-run table with `ready` and `failed` statuses.
- Context menu in each workspace with Generate/Play actions.
- TM sorted by `Audio` column.
- Audio Provider Settings dialog with MMS license-gate state.
- Audio Provider Settings dialog with 3 tabs and Google credentials preview.
- Mispronounced -> Add Pronunciation dialog and regenerated audio result.
- Audio column with delegate play icon in each main workspace.
- Mini-player panel with active queue and now-playing item.
- Playback settings controls (`pre/gap/post`, `interrupt/enqueue`).
- Pronunciation Bootstrap dialog: model path + health status + V3 progress summary.
