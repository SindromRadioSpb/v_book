"""UI parity tests for translate scope current_page/all_filtered entrypoints."""

from types import SimpleNamespace

from app.ui.dictionary_view import DictionaryView
from app.ui.terms_view import TermsView
from app.ui.translation_management_panel import TranslationManagementPanel


class DummySignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, cb):
        self._callbacks.append(cb)


class DummyProgressDialog:
    created = 0
    totals = []

    def __init__(self, parent=None, total=0):
        DummyProgressDialog.created += 1
        self.total = total
        DummyProgressDialog.totals.append(total)
        self.cancel_requested = DummySignal()
        self.pause_requested = DummySignal()
        self.resume_requested = DummySignal()

    def show(self):
        return None

    def update_progress(self, *_args):
        return None

    def update_counts(self, *_args):
        return None

    def add_recent_item(self, *_args):
        return None

    def set_stage(self, *_args):
        return None

    def set_completed(self):
        return None

    def accept(self):
        return None

    def reject(self):
        return None


class DummyWorker:
    captured = None

    def __init__(self, items, options, tab_type):
        DummyWorker.captured = {
            "items": items,
            "options": options,
            "tab_type": tab_type,
        }
        self.progress = DummySignal()
        self.stats_updated = DummySignal()
        self.row_translated = DummySignal()
        self.stage_updated = DummySignal()
        self.finished = DummySignal()
        self.error = DummySignal()

    def start(self):
        return None

    def cancel(self):
        return None

    def pause(self):
        return None

    def resume(self):
        return None


class DummyAllFilteredWorker:
    captured = None

    def __init__(
        self,
        entity_type,
        project_id,
        filters,
        provider_mode,
        write_mode,
        id_fetch_chunk,
        translation_chunk,
        src_lang=None,
        tgt_lang=None,
    ):
        DummyAllFilteredWorker.captured = {
            "entity_type": entity_type,
            "project_id": project_id,
            "filters": filters,
            "provider_mode": provider_mode,
            "write_mode": write_mode,
            "id_fetch_chunk": id_fetch_chunk,
            "translation_chunk": translation_chunk,
            "src_lang": src_lang,
            "tgt_lang": tgt_lang,
        }
        self.progress = DummySignal()
        self.stats_updated = DummySignal()
        self.row_translated = DummySignal()
        self.stage_updated = DummySignal()
        self.finished = DummySignal()
        self.error = DummySignal()

    def start(self):
        return None

    def cancel(self):
        return None

    def pause(self):
        return None

    def resume(self):
        return None


class FakeIndex:
    def __init__(self, row):
        self._row = row

    def row(self):
        return self._row


class FakeSelectionModel:
    def __init__(self, rows):
        self._rows = rows

    def selectedRows(self, *_args):
        return [FakeIndex(r) for r in self._rows]


class FakeTable:
    def __init__(self, rows):
        self._selection_model = FakeSelectionModel(rows)

    def selectionModel(self):
        return self._selection_model


class FakeButton:
    def __init__(self):
        self.enabled = True

    def setEnabled(self, value):
        self.enabled = value


class DummySessionCtx:
    def __enter__(self):
        return object()

    def __exit__(self, exc_type, exc, tb):
        return False


class DummyDB:
    def get_session(self):
        return DummySessionCtx()


def test_dictionary_current_page_uses_v3_progress(monkeypatch):
    DummyProgressDialog.created = 0
    DummyProgressDialog.totals = []
    DummyWorker.captured = None

    panel = DictionaryView.__new__(DictionaryView)
    panel.lemma_table = FakeTable(rows=[1, 0])
    panel.proxy_model = SimpleNamespace(map_to_source_row=lambda row: row)
    panel.lemma_model = SimpleNamespace(
        lemmas=[
            SimpleNamespace(lemma_text="alpha", translation=""),
            SimpleNamespace(lemma_text="beta", translation="EXISTING"),
        ]
    )
    panel.project_id = 7
    panel.batch_translate_btn = FakeButton()
    panel.build_filters = lambda: {}
    panel.on_selection_changed = lambda: None

    monkeypatch.setattr(
        "app.ui.dialogs.show_batch_translate_dialog",
        lambda **kwargs: (True, "chain", "FILL_EMPTY", "current_page"),
    )
    monkeypatch.setattr(
        "app.ui.dialogs.batch_progress_dialog_v3.BatchProgressDialogV3", DummyProgressDialog
    )
    monkeypatch.setattr("app.ui.workers.BatchTranslateWorker", DummyWorker)
    monkeypatch.setattr("app.services.db_service.DBService.get_instance", lambda: DummyDB())
    monkeypatch.setattr(
        "app.services.dictionary_service.DictionaryService.count_lemma_ids_for_translation",
        lambda self, session, project_id, filters, write_mode: 2,
    )

    DictionaryView.on_batch_translate(panel)

    assert DummyProgressDialog.created == 1
    assert DummyWorker.captured is not None
    assert DummyWorker.captured["tab_type"] == "dictionary"
    assert DummyWorker.captured["options"].chunk_size == 1
    assert [item.entity_type for item in DummyWorker.captured["items"]] == ["lemma", "lemma"]


def test_terms_current_page_uses_v3_progress(monkeypatch):
    DummyProgressDialog.created = 0
    DummyProgressDialog.totals = []
    DummyWorker.captured = None

    panel = TermsView.__new__(TermsView)
    panel.terms_table = FakeTable(rows=[0, 2])
    panel.proxy_model = SimpleNamespace(map_to_source_row=lambda row: row)
    panel.terms_model = SimpleNamespace(
        clusters=[
            SimpleNamespace(representative_he="t1", translation=""),
            SimpleNamespace(representative_he="t2", translation="X"),
            SimpleNamespace(representative_he="t3", translation=""),
        ]
    )
    panel.project_id = 11
    panel.batch_translate_btn = FakeButton()
    panel.build_filters = lambda: {}
    panel.on_selection_changed = lambda: None

    monkeypatch.setattr(
        "app.ui.terms_view.show_batch_translate_dialog",
        lambda **kwargs: (True, "chain", "FILL_EMPTY", "current_page"),
    )
    monkeypatch.setattr(
        "app.ui.dialogs.batch_progress_dialog_v3.BatchProgressDialogV3", DummyProgressDialog
    )
    monkeypatch.setattr("app.ui.terms_view.BatchTranslateWorker", DummyWorker)
    monkeypatch.setattr("app.services.db_service.DBService.get_instance", lambda: DummyDB())
    monkeypatch.setattr(
        "app.services.term_extraction_service.TermExtractionService.count_cluster_ids_for_translation",
        lambda self, session, project_id, filters, write_mode: 3,
    )

    TermsView.on_batch_translate(panel)

    assert DummyProgressDialog.created == 1
    assert DummyWorker.captured is not None
    assert DummyWorker.captured["tab_type"] == "terms"
    assert DummyWorker.captured["options"].chunk_size == 1
    assert [item.entity_type for item in DummyWorker.captured["items"]] == [
        "term_cluster",
        "term_cluster",
    ]


def test_dictionary_all_filtered_recomputes_total_for_write_mode(monkeypatch):
    DummyProgressDialog.created = 0
    DummyProgressDialog.totals = []
    DummyAllFilteredWorker.captured = None
    calls = []

    panel = DictionaryView.__new__(DictionaryView)
    panel.lemma_table = FakeTable(rows=[0])
    panel.project_id = 7
    panel.batch_translate_btn = FakeButton()
    panel.build_filters = lambda: {"q": "x"}
    panel.on_selection_changed = lambda: None

    monkeypatch.setattr(
        "app.ui.dialogs.show_batch_translate_dialog",
        lambda **kwargs: (True, "chain", "OVERWRITE", "all_filtered"),
    )
    monkeypatch.setattr(
        "app.ui.dialogs.batch_progress_dialog_v3.BatchProgressDialogV3", DummyProgressDialog
    )
    monkeypatch.setattr("app.ui.workers.TranslateAllFilteredWorker", DummyAllFilteredWorker)
    monkeypatch.setattr("app.services.db_service.DBService.get_instance", lambda: DummyDB())

    def fake_count(self, session, project_id, filters, write_mode):
        calls.append(write_mode)
        if write_mode == "FILL_EMPTY":
            return 10
        if write_mode == "OVERWRITE":
            return 25
        return 0

    monkeypatch.setattr(
        "app.services.dictionary_service.DictionaryService.count_lemma_ids_for_translation",
        fake_count,
    )
    DictionaryView.on_batch_translate(panel)

    assert calls == ["FILL_EMPTY", "OVERWRITE"]
    assert DummyProgressDialog.totals[-1] == 25
    assert DummyAllFilteredWorker.captured is not None
    assert DummyAllFilteredWorker.captured["entity_type"] == "lemma"
    assert DummyAllFilteredWorker.captured["write_mode"] == "OVERWRITE"
    assert DummyAllFilteredWorker.captured["translation_chunk"] == 1


def test_terms_all_filtered_recomputes_total_for_write_mode(monkeypatch):
    DummyProgressDialog.created = 0
    DummyProgressDialog.totals = []
    DummyAllFilteredWorker.captured = None
    calls = []

    panel = TermsView.__new__(TermsView)
    panel.terms_table = FakeTable(rows=[0])
    panel.project_id = 11
    panel.batch_translate_btn = FakeButton()
    panel.build_filters = lambda: {"q": "x"}
    panel.on_selection_changed = lambda: None

    monkeypatch.setattr(
        "app.ui.terms_view.show_batch_translate_dialog",
        lambda **kwargs: (True, "chain", "OVERWRITE", "all_filtered"),
    )
    monkeypatch.setattr(
        "app.ui.dialogs.batch_progress_dialog_v3.BatchProgressDialogV3", DummyProgressDialog
    )
    monkeypatch.setattr("app.ui.workers.TranslateAllFilteredWorker", DummyAllFilteredWorker)
    monkeypatch.setattr("app.services.db_service.DBService.get_instance", lambda: DummyDB())

    def fake_count(self, session, project_id, filters, write_mode):
        calls.append(write_mode)
        if write_mode == "FILL_EMPTY":
            return 8
        if write_mode == "OVERWRITE":
            return 19
        return 0

    monkeypatch.setattr(
        "app.services.term_extraction_service.TermExtractionService.count_cluster_ids_for_translation",
        fake_count,
    )
    TermsView.on_batch_translate(panel)

    assert calls == ["FILL_EMPTY", "OVERWRITE"]
    assert DummyProgressDialog.totals[-1] == 19
    assert DummyAllFilteredWorker.captured is not None
    assert DummyAllFilteredWorker.captured["entity_type"] == "term_cluster"
    assert DummyAllFilteredWorker.captured["write_mode"] == "OVERWRITE"
    assert DummyAllFilteredWorker.captured["translation_chunk"] == 1


def test_tm_all_filtered_recomputes_total_for_write_mode(monkeypatch):
    DummyProgressDialog.created = 0
    DummyProgressDialog.totals = []
    DummyAllFilteredWorker.captured = None
    calls = []

    class FakeTableTM(FakeTable):
        pass

    fake_entries = {
        0: SimpleNamespace(
            tm_id=101,
            src_text="s1",
            src_lang="he",
            tgt_lang="ru",
            translation="",
            project_id=1,
        )
    }

    panel = TranslationManagementPanel.__new__(TranslationManagementPanel)
    panel.table_view = FakeTableTM(rows=[0])
    panel.model = SimpleNamespace(get_entry=lambda row: fake_entries.get(row))
    panel.batch_translate_btn = FakeButton()
    panel.project_id = None
    panel.batch_translate_worker = None
    panel.build_filters = lambda: {"q": "x"}
    panel.perform_search = lambda: None
    panel.on_selection_changed = lambda: None

    monkeypatch.setattr(
        "app.ui.dialogs.show_batch_translate_dialog",
        lambda **kwargs: (True, "chain", "OVERWRITE", "all_filtered"),
    )
    monkeypatch.setattr(
        "app.ui.dialogs.batch_progress_dialog_v3.BatchProgressDialogV3", DummyProgressDialog
    )
    monkeypatch.setattr("app.ui.workers.TranslateAllFilteredWorker", DummyAllFilteredWorker)
    monkeypatch.setattr("app.services.db_service.DBService.get_instance", lambda: DummyDB())

    def fake_count(self, session, filters, write_mode):
        calls.append(write_mode)
        if write_mode == "FILL_EMPTY":
            return 12
        if write_mode == "OVERWRITE":
            return 21
        return 0

    monkeypatch.setattr(
        "app.services.translation_admin_service.TranslationAdminService.count_tm_ids_for_translation",
        fake_count,
    )
    TranslationManagementPanel.on_batch_translate(panel)

    assert calls == ["FILL_EMPTY", "OVERWRITE"]
    assert DummyProgressDialog.totals[-1] == 21
    assert DummyAllFilteredWorker.captured is not None
    assert DummyAllFilteredWorker.captured["entity_type"] == "tm_entry"
    assert DummyAllFilteredWorker.captured["write_mode"] == "OVERWRITE"
    assert DummyAllFilteredWorker.captured["translation_chunk"] == 1
