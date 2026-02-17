# User Dictionaries Integration Points

## UI Entry Points

- `app/ui/dictionary_view.py`
  - Context menu: `Add Selected to User Dictionary (...)`
- `app/ui/terms_view.py`
  - Context menu: `Add Selected to User Dictionary (...)`
- `app/ui/term_card_view.py`
  - Queue context menu: `Add Selected to User Dictionary (...)`
- `app/ui/translation_management_panel.py`
  - Context menu: `Add Selected to User Dictionary (...)`
- `app/ui/project_view.py`
  - New tab registration: `User Dictionaries`

## Main User Dictionaries UI

- `app/ui/user_dictionaries_view.py`
  - Left: dictionary list
  - Right: item table + filters + pagination + actions
  - Actions: add manual, remove selected, translate selected, refresh

## Services

- `app/services/user_dictionary_service.py`
  - Dictionary CRUD
  - Bulk add/remove
  - Filtered query + safe sort
  - Translation eligibility count/fetch for all-filtered scope
- `app/services/audio_asset_service.py`
  - Bulk status lookup for audio indicator
- `app/services/tm_global_service.py`
  - Canonical upsert + propagation for translate selected write path

## Workers

- `app/ui/workers.py`
  - `UserDictionaryBulkAddWorker`
  - `UserDictionaryBulkRemoveWorker`
  - `UserDictTranslateWorker`
