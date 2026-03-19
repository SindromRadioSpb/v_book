"""Copy Hebrew Wikipedia Baseline project from dev DB to production DB.

This script copies the entire Hebrew Wikipedia reference corpus project
from the development database to the production database, so users can
see both reference and working projects together.
"""

import sqlite3
import sys
from pathlib import Path


def copy_project(source_db: Path, target_db: Path, project_name: str = "Hebrew Wikipedia Baseline"):
    """Copy project from source to target database."""

    print(f"Source DB: {source_db}")
    print(f"Target DB: {target_db}")
    print(f"Project: {project_name}\n")

    # Connect to target database
    target_conn = sqlite3.connect(str(target_db))
    target_cur = target_conn.cursor()

    # Attach source database
    target_cur.execute(f"ATTACH DATABASE '{source_db}' AS source_db")

    try:
        # Check if project already exists in target
        target_cur.execute("SELECT project_id FROM dict_project WHERE name = ?", (project_name,))
        if target_cur.fetchone():
            print(f"[WARNING] Project '{project_name}' already exists in target database!")
            response = input("Overwrite? (yes/no): ")
            if response.lower() != "yes":
                print("Aborted.")
                return False

            # Delete existing project (CASCADE will handle related data)
            target_cur.execute("DELETE FROM dict_project WHERE name = ?", (project_name,))
            print("[OK] Deleted existing project")

        # Get source project info
        target_cur.execute(
            "SELECT project_id, library_id FROM source_db.dict_project WHERE name = ?",
            (project_name,),
        )
        row = target_cur.fetchone()
        if not row:
            print(f"[ERROR] Project '{project_name}' not found in source database!")
            return False

        source_project_id, source_library_id = row
        print(f"[OK] Found source project (ID: {source_project_id})")

        # Check document count
        target_cur.execute(
            """
            SELECT COUNT(*) FROM source_db.source_document sd
            JOIN source_db.source_corpus sc ON sd.corpus_id = sc.corpus_id
            WHERE sc.project_id = ?
        """,
            (source_project_id,),
        )
        doc_count = target_cur.fetchone()[0]
        print(f"[OK] Source has {doc_count:,} documents")

        # Ensure library exists in target (create if needed)
        target_cur.execute(
            "SELECT library_id FROM library WHERE library_id = ?", (source_library_id,)
        )
        if not target_cur.fetchone():
            target_cur.execute(
                """
                INSERT INTO library (library_id, name, created_at)
                SELECT library_id, name, created_at
                FROM source_db.library
                WHERE library_id = ?
            """,
                (source_library_id,),
            )
            print(f"[OK] Created library (ID: {source_library_id})")

        # Get max IDs from target to avoid conflicts
        target_cur.execute("SELECT COALESCE(MAX(project_id), 0) FROM dict_project")
        max_project_id = target_cur.fetchone()[0]

        target_cur.execute("SELECT COALESCE(MAX(corpus_id), 0) FROM source_corpus")
        max_corpus_id = target_cur.fetchone()[0]

        target_cur.execute("SELECT COALESCE(MAX(doc_id), 0) FROM source_document")
        max_doc_id = target_cur.fetchone()[0]

        print(
            f"\n[INFO] Target DB max IDs: project={max_project_id}, corpus={max_corpus_id}, doc={max_doc_id}"
        )

        # Copy dict_project (let SQLite auto-assign new project_id)
        print("\n[1/6] Copying dict_project...")
        target_cur.execute(
            """
            INSERT INTO dict_project
            (library_id, name, description, is_general_corpus,
             general_corpus_id, created_at, updated_at)
            SELECT library_id, name, description, is_general_corpus,
                   general_corpus_id, created_at, updated_at
            FROM source_db.dict_project
            WHERE project_id = ?
        """,
            (source_project_id,),
        )

        new_project_id = target_cur.lastrowid
        print(f"[OK] Project copied (new ID: {new_project_id})")

        # Copy source_corpus with new project_id
        print("\n[2/6] Copying source_corpus...")
        target_cur.execute(
            """
            INSERT INTO source_corpus
            (project_id, name, description, created_at)
            SELECT ?, name, description, created_at
            FROM source_db.source_corpus
            WHERE project_id = ?
        """,
            (new_project_id, source_project_id),
        )
        corpus_count = target_cur.rowcount

        # Get mapping of old corpus_id -> new corpus_id
        target_cur.execute(
            "SELECT corpus_id FROM source_corpus WHERE project_id = ? ORDER BY corpus_id",
            (new_project_id,),
        )
        new_corpus_ids = [row[0] for row in target_cur.fetchall()]

        target_cur.execute(
            "SELECT corpus_id FROM source_db.source_corpus WHERE project_id = ? ORDER BY corpus_id",
            (source_project_id,),
        )
        old_corpus_ids = [row[0] for row in target_cur.fetchall()]

        corpus_id_map = dict(zip(old_corpus_ids, new_corpus_ids))
        print(f"[OK] Copied {corpus_count} corpus/corpora (ID mapping: {corpus_id_map})")

        # Copy source_document (batch by batch to handle ID mapping)
        print(f"\n[3/6] Copying source_document ({doc_count:,} documents)...")

        # For large datasets, copy in batches
        batch_size = 10000
        total_copied = 0

        for old_corpus_id, new_corpus_id in corpus_id_map.items():
            # Get count for this corpus
            target_cur.execute(
                """
                SELECT COUNT(*) FROM source_db.source_document
                WHERE corpus_id = ?
            """,
                (old_corpus_id,),
            )
            corpus_doc_count = target_cur.fetchone()[0]

            if corpus_doc_count == 0:
                continue

            print(
                f"  - Copying {corpus_doc_count:,} documents from corpus {old_corpus_id} to {new_corpus_id}..."
            )

            # Copy documents for this corpus
            target_cur.execute(
                """
                INSERT INTO source_document
                (corpus_id, file_name, file_path, file_ext, file_size_bytes,
                 sha256, status, imported_at, processed_at, error_message)
                SELECT ?, file_name, file_path, file_ext, file_size_bytes,
                       sha256, status, imported_at, processed_at, error_message
                FROM source_db.source_document
                WHERE corpus_id = ?
            """,
                (new_corpus_id, old_corpus_id),
            )

            total_copied += target_cur.rowcount

            if total_copied % 50000 == 0:
                print(f"  - Progress: {total_copied:,}/{doc_count:,} documents")

        print(f"[OK] Copied {total_copied:,} documents")

        # Copy document_text (need to map doc_ids)
        print("\n[4/6] Copying document_text...")

        # Get old doc_ids from source
        target_cur.execute(
            """
            SELECT sd.doc_id, sd.file_path
            FROM source_db.source_document sd
            JOIN source_db.source_corpus sc ON sd.corpus_id = sc.corpus_id
            WHERE sc.project_id = ?
            ORDER BY sd.doc_id
        """,
            (source_project_id,),
        )
        old_docs = target_cur.fetchall()

        # Get new doc_ids from target (matching by file_path for uniqueness)
        doc_id_map = {}
        for old_doc_id, file_path in old_docs:
            target_cur.execute(
                """
                SELECT sd.doc_id
                FROM source_document sd
                JOIN source_corpus sc ON sd.corpus_id = sc.corpus_id
                WHERE sc.project_id = ? AND sd.file_path = ?
            """,
                (new_project_id, file_path),
            )
            row = target_cur.fetchone()
            if row:
                doc_id_map[old_doc_id] = row[0]

        print(f"  - Mapped {len(doc_id_map):,} document IDs")

        # Copy text records in batches
        text_count = 0
        batch_size = 5000
        old_doc_ids = list(doc_id_map.keys())

        for i in range(0, len(old_doc_ids), batch_size):
            batch = old_doc_ids[i : i + batch_size]
            placeholders = ",".join("?" * len(batch))

            target_cur.execute(
                f"""
                SELECT doc_id, raw_text, ocr_text, created_at
                FROM source_db.document_text
                WHERE doc_id IN ({placeholders})
            """,
                batch,
            )

            texts = target_cur.fetchall()
            if texts:
                for old_doc_id, raw_text, ocr_text, created_at in texts:
                    new_doc_id = doc_id_map[old_doc_id]
                    target_cur.execute(
                        """
                        INSERT INTO document_text (doc_id, raw_text, ocr_text, created_at)
                        VALUES (?, ?, ?, ?)
                    """,
                        (new_doc_id, raw_text, ocr_text, created_at),
                    )
                    text_count += 1

            if text_count % 50000 == 0 and text_count > 0:
                print(f"  - Progress: {text_count:,} text records")

        print(f"[OK] Copied {text_count:,} text records")

        # Copy lemmas (if any) with new project_id
        print("\n[5/6] Copying lemmas...")
        target_cur.execute(
            """
            INSERT INTO lemma
            (project_id, lemma_text, pos, created_at)
            SELECT ?, lemma_text, pos, created_at
            FROM source_db.lemma
            WHERE project_id = ?
        """,
            (new_project_id, source_project_id),
        )
        lemma_count = target_cur.rowcount
        print(f"[OK] Copied {lemma_count:,} lemmas")

        # Copy ngrams (if any) with new project_id
        print("\n[6/6] Copying ngrams...")
        target_cur.execute(
            """
            INSERT INTO ngram
            (project_id, surface_text, n, created_at)
            SELECT ?, surface_text, n, created_at
            FROM source_db.ngram
            WHERE project_id = ?
        """,
            (new_project_id, source_project_id),
        )
        ngram_count = target_cur.rowcount
        print(f"[OK] Copied {ngram_count:,} n-grams")

        # Commit changes
        target_conn.commit()

        print("\n" + "=" * 80)
        print("[SUCCESS] Project copied successfully!")
        print("=" * 80)
        print(f"Project ID: {new_project_id}")
        print(f"Documents: {doc_count:,}")
        print(f"Texts: {text_count:,}")
        print(f"Lemmas: {lemma_count:,}")
        print(f"N-grams: {ngram_count:,}")

        return True

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback

        traceback.print_exc()
        target_conn.rollback()
        return False

    finally:
        target_cur.execute("DETACH DATABASE source_db")
        target_conn.close()


if __name__ == "__main__":
    source_db = Path(__file__).parent / "hdle_premium.db"

    # Determine target DB path
    import platform

    if platform.system() == "Windows":
        target_db = Path("M:/V_book/HDLE/hdle.db")
    elif platform.system() == "Darwin":
        target_db = Path.home() / "Library" / "Application Support" / "HDLE" / "hdle.db"
    else:  # Linux
        target_db = Path.home() / ".local" / "share" / "hdle" / "hdle.db"

    if not source_db.exists():
        print(f"[ERROR] Source database not found: {source_db}")
        sys.exit(1)

    if not target_db.exists():
        print(f"[ERROR] Target database not found: {target_db}")
        print("Please run the application once to create the database.")
        sys.exit(1)

    success = copy_project(source_db, target_db)
    sys.exit(0 if success else 1)
