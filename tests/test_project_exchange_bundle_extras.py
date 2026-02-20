"""Bundle-format coverage for optional pronunciation metadata sidecar."""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path

from app.services.project_exchange import bundle_format
from app.services.project_exchange.constants import PRONUNCIATION_METADATA_FILENAME
from app.services.project_exchange.dto import ManifestInfo


def _workspace_temp_dir(prefix: str) -> Path:
    root = Path("build") / "tmp_tests"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=prefix, dir=str(root)))


def test_bundle_allows_optional_pronunciation_sidecar():
    temp_dir = _workspace_temp_dir("bundle_pron_")
    payload = temp_dir / "payload.sqlite"
    bundle = temp_dir / "bundle.hdleproj"
    extract_dir = temp_dir / "extract"
    extra = temp_dir / PRONUNCIATION_METADATA_FILENAME
    try:
        conn = sqlite3.connect(str(payload))
        conn.execute("CREATE TABLE dummy (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO dummy (id) VALUES (1)")
        conn.commit()
        conn.close()

        extra.write_text(
            "lang\tsrc_norm\tniqqud_text\tipa\treading_text\tsource\tconfidence\tis_override\tnotes\n"
            "he\tshalom\t\tʃaˈlom\t\timport_csv\t0.8\t0\tseed\n",
            encoding="utf-8",
        )

        manifest = ManifestInfo(
            bundle_format_version=1,
            app_version="1.0.0",
            schema_version=22,
            project_name="P",
            project_src_lang="he",
            project_tgt_lang="ru",
            exported_at="2026-02-20T00:00:00Z",
            table_counts={"dummy": 1},
            pronunciation_metadata_count=1,
        )

        bundle_format.create_bundle(
            payload,
            manifest,
            bundle,
            extra_files={PRONUNCIATION_METADATA_FILENAME: extra},
        )

        loaded_manifest, loaded_payload = bundle_format.read_bundle(bundle, extract_dir)
        assert loaded_payload.exists()
        assert loaded_manifest.pronunciation_metadata_count == 1
        assert (extract_dir / PRONUNCIATION_METADATA_FILENAME).exists()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
