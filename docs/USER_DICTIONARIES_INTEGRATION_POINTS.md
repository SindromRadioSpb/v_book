# User Dictionaries Integration Points

## Workspace Entry Points

- `app/ui/app_window.py`
  - Premium menu action: `User Dictionaries` (`Ctrl+Shift+U`)
  - Sidebar action: `workspace.user_dictionaries`
- `app/ui/project_view.py`
  - Project tab: `User Dictionaries`

## Main User Dictionaries UI

- `app/ui/user_dictionaries_view.py`
  - Scope chip: `Current Project` / `All`
  - Deep-link CTA: `Open Translation Management`
  - Actions: add manual, remove selected, translate selected, refresh

## Translation Management Deep Link

- `app/ui/translation_management_panel.py`
  - Header CTA: `Open User Dictionaries`
  - Scope chip: `Current Project` / `Global`

## Source Integrations (Add to User Dictionary)

- `app/ui/dictionary_view.py`
- `app/ui/terms_view.py`
- `app/ui/term_card_view.py`
- `app/ui/translation_management_panel.py`

## Services and Workers

- `app/services/user_dictionary_service.py`
  - CRUD, bulk add/remove, filtered query, safe sort, scope by `origin_project_id`
- `app/services/audio_asset_service.py`
  - Audio status lookup (`missing|ready|failed`)
- `app/services/tm_global_service.py`
  - Canonical upsert + propagation
- `app/ui/workers.py`
  - `UserDictionaryBulkAddWorker`
  - `UserDictionaryBulkRemoveWorker`
  - `UserDictTranslateWorker`
