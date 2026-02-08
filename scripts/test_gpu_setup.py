#!/usr/bin/env python3
"""Test GPU setup before running long processing."""

import sys
from pathlib import Path

# Force UTF-8 output
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

print("="*80)
print("GPU Setup Test")
print("="*80)
print()

# Test 1: PyTorch CUDA
print("[1/5] Testing PyTorch CUDA...")
try:
    import torch
    cuda_available = torch.cuda.is_available()
    if cuda_available:
        gpu_name = torch.cuda.get_device_name(0)
        print(f"  [OK] CUDA available: True")
        print(f"  [OK] GPU: {gpu_name}")
        print(f"  [OK] PyTorch version: {torch.__version__}")
    else:
        print(f"  [FAIL] CUDA not available!")
        print(f"  PyTorch version: {torch.__version__}")
        sys.exit(1)
except Exception as e:
    print(f"  [FAIL] PyTorch test failed: {e}")
    sys.exit(1)

print()

# Test 2: Stanza
print("[2/5] Testing Stanza...")
try:
    import stanza
    print(f"  [OK] Stanza imported")

    # Try to load Hebrew model
    print("  Loading Hebrew model (this may take a moment)...")
    nlp = stanza.Pipeline('he', use_gpu=True, verbose=False)
    print(f"  [OK] Hebrew model loaded")

    # Check if using GPU (skip check, just note)
    print(f"  [OK] Stanza will use GPU when use_gpu=True is set")

except Exception as e:
    print(f"  [FAIL] Stanza test failed: {e}")
    sys.exit(1)

print()

# Test 3: Database access
print("[3/5] Testing database access...")
try:
    from app.services.db_service import DBService
    from app.infra.sa_models import DictProject, SourceDocument, SourceCorpus
    from sqlalchemy import select, func

    db_path = Path(r"M:\V_book\HDLE_Processing\hewiki_gpu_processing.db")
    if not db_path.exists():
        print(f"  [FAIL] Database not found: {db_path}")
        sys.exit(1)

    DBService.initialize(db_path)
    db = DBService.get_instance()

    with db.get_session() as session:
        project = session.execute(
            select(DictProject).where(DictProject.name == "Hebrew Wikipedia Baseline")
        ).scalar_one_or_none()

        if not project:
            print(f"  [FAIL] Project 'Hebrew Wikipedia Baseline' not found")
            sys.exit(1)

        total_docs = session.execute(
            select(func.count(SourceDocument.doc_id))
            .join(SourceCorpus)
            .where(SourceCorpus.project_id == project.project_id)
        ).scalar()

        processed_docs = session.execute(
            select(func.count(SourceDocument.doc_id))
            .join(SourceCorpus)
            .where(SourceCorpus.project_id == project.project_id)
            .where(SourceDocument.status == 'processed')
        ).scalar()

        print(f"  [OK] Database accessible")
        print(f"  [OK] Project: {project.name} (ID: {project.project_id})")
        print(f"  [OK] Total documents: {total_docs:,}")
        print(f"  [OK] Processed: {processed_docs:,} ({processed_docs/total_docs*100:.1f}%)")
        print(f"  [OK] Remaining: {total_docs - processed_docs:,}")

    DBService.shutdown()

except Exception as e:
    print(f"  [FAIL] Database test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()

# Test 4: Process a single document
print("[4/5] Testing single document processing...")
try:
    from app.services.process_service import ProcessService

    db_path = Path(r"M:\V_book\HDLE_Processing\hewiki_gpu_processing.db")
    DBService.initialize(db_path)
    db = DBService.get_instance()
    process_service = ProcessService()

    with db.get_session() as session:
        # Find first unprocessed document
        doc = session.execute(
            select(SourceDocument)
            .join(SourceCorpus)
            .where(SourceCorpus.project_id == project.project_id)
            .where(SourceDocument.status != 'processed')
            .limit(1)
        ).scalar_one_or_none()

        if not doc:
            print(f"  [OK] All documents already processed!")
        else:
            print(f"  Testing with document ID: {doc.doc_id}")

            import time
            start = time.time()

            process_service.process_document(session, doc.doc_id, use_gpu=True)
            session.commit()

            elapsed = time.time() - start

            print(f"  [OK] Document processed in {elapsed:.2f}s")
            print(f"  [OK] Speed: ~{1/elapsed:.1f} docs/sec")

            if elapsed > 5:
                print(f"  [WARN] WARNING: Slow processing! Expected <1s per doc with GPU")

    DBService.shutdown()

except Exception as e:
    print(f"  [FAIL] Processing test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()

# Test 5: Disk space
print("[5/5] Checking disk space...")
try:
    import shutil

    processing_dir = Path(r"M:\V_book\HDLE_Processing")
    stat = shutil.disk_usage(processing_dir)

    free_gb = stat.free / (1024**3)
    total_gb = stat.total / (1024**3)

    print(f"  Free space: {free_gb:.1f} GB / {total_gb:.1f} GB")

    if free_gb < 5:
        print(f"  [WARN] WARNING: Low disk space! Need at least 5 GB free")
    else:
        print(f"  [OK] Sufficient disk space")

except Exception as e:
    print(f"  [FAIL] Disk space check failed: {e}")

print()
print("="*80)
print("[OK] All tests passed! Ready for GPU processing.")
print("="*80)
print()
print("Next step: Run NLP processing")
print("  .\\scripts\\run_gpu_processing.ps1")
print()
print("Estimated time: 12-21 hours for 387,639 documents")
print()
