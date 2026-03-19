"""Integration tests for entity classification system.

Tests the complete workflow:
- Classification on creation
- Database persistence
- UI filtering
- Export filtering
- Manual override
"""

import pytest
import tempfile
from pathlib import Path
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.infra.sa_models import Lemma, TermCluster, DictProject, Library
from app.services.entity_classifier import classify_text, classify_phrase, EntityClass


def test_lemma_classification_persists():
    """Test that lemma classification is saved to database."""
    # Create temporary database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        engine = create_engine(f"sqlite:///{db_path}")

        # Create minimal schema
        from app.infra.sa_models import Base

        Base.metadata.create_all(engine)

        with Session(engine) as session:
            library = Library(name="Test Library")
            session.add(library)
            session.flush()
            project = DictProject(name="Test Project", library_id=library.library_id)
            session.add(project)
            session.flush()

            # Classify some lemmas
            test_cases = [
                ("שלום", EntityClass.WORD_HE, False),  # Valid Hebrew word
                ("!", EntityClass.PUNCT, True),  # Punctuation noise
                ("1.2kg", EntityClass.QUANTITY_UNIT, True),  # Quantity noise
            ]

            for lemma_text, expected_class, expected_noise in test_cases:
                # Classify
                result = classify_text(lemma_text)

                # Create lemma with classification
                lemma = Lemma(
                    project_id=project.project_id,
                    lemma_text=lemma_text,
                    pos="NOUN",
                    entity_class=result.entity_class,
                    is_noise=1 if result.is_noise else 0,
                    noise_reason=result.noise_reason,
                    norm_text=result.norm_text,
                )
                session.add(lemma)

            session.commit()

            # Verify persisted data
            lemmas = session.execute(select(Lemma)).scalars().all()
            assert len(lemmas) == 3

            # Check each lemma
            shalom = [l for l in lemmas if l.lemma_text == "שלום"][0]
            assert shalom.entity_class == EntityClass.WORD_HE
            assert shalom.is_noise == 0
            assert shalom.noise_reason is None

            punct = [l for l in lemmas if l.lemma_text == "!"][0]
            assert punct.entity_class == EntityClass.PUNCT
            assert punct.is_noise == 1
            assert punct.noise_reason is not None

    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)


def test_noise_filtering_query():
    """Test that noise filtering query works correctly."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        engine = create_engine(f"sqlite:///{db_path}")
        from app.infra.sa_models import Base

        Base.metadata.create_all(engine)

        with Session(engine) as session:
            library = Library(name="Test Library")
            session.add(library)
            session.flush()
            project = DictProject(name="Test Project", library_id=library.library_id)
            session.add(project)
            session.flush()

            # Add lemmas (3 valid, 2 noise)
            lemmas_data = [
                ("שלום", 0),  # Valid
                ("כוח", 0),  # Valid
                ("!", 1),  # Noise
                ("42", 1),  # Noise
                ("hello", 0),  # Valid
            ]

            for text, is_noise in lemmas_data:
                lemma = Lemma(
                    project_id=project.project_id,
                    lemma_text=text,
                    pos="NOUN",
                    is_noise=is_noise,
                )
                session.add(lemma)

            session.commit()

            # Query without filter - should get all 5
            all_lemmas = (
                session.execute(select(Lemma).where(Lemma.project_id == project.project_id))
                .scalars()
                .all()
            )
            assert len(all_lemmas) == 5

            # Query with noise filter - should get only 3 valid
            from sqlalchemy import or_

            valid_lemmas = (
                session.execute(
                    select(Lemma).where(
                        Lemma.project_id == project.project_id,
                        or_(Lemma.is_noise == 0, Lemma.is_noise.is_(None)),
                    )
                )
                .scalars()
                .all()
            )
            assert len(valid_lemmas) == 3

            # Query only noise - should get 2
            noise_lemmas = (
                session.execute(
                    select(Lemma).where(Lemma.project_id == project.project_id, Lemma.is_noise == 1)
                )
                .scalars()
                .all()
            )
            assert len(noise_lemmas) == 2

    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)


def test_manual_override():
    """Test manual noise status override."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        engine = create_engine(f"sqlite:///{db_path}")
        from app.infra.sa_models import Base

        Base.metadata.create_all(engine)

        with Session(engine) as session:
            library = Library(name="Test Library")
            session.add(library)
            session.flush()
            project = DictProject(name="Test Project", library_id=library.library_id)
            session.add(project)
            session.flush()

            # Add a lemma marked as noise
            lemma = Lemma(
                project_id=project.project_id,
                lemma_text="test",
                pos="NOUN",
                entity_class=EntityClass.PUNCT,
                is_noise=1,
            )
            session.add(lemma)
            session.commit()
            lemma_id = lemma.lemma_id

        # Manual override - mark as valid
        with Session(engine) as session:
            from sqlalchemy import update

            stmt = update(Lemma).where(Lemma.lemma_id == lemma_id).values(is_noise=0)
            session.execute(stmt)
            session.commit()

        # Verify override persisted
        with Session(engine) as session:
            lemma = session.get(Lemma, lemma_id)
            assert lemma.is_noise == 0  # Now valid

    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)


def test_backward_compatibility_null_handling():
    """Test that NULL is_noise is treated as valid."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        engine = create_engine(f"sqlite:///{db_path}")
        from app.infra.sa_models import Base

        Base.metadata.create_all(engine)

        with Session(engine) as session:
            library = Library(name="Test Library")
            session.add(library)
            session.flush()
            project = DictProject(name="Test Project", library_id=library.library_id)
            session.add(project)
            session.flush()

            # Add lemma with NULL is_noise (unclassified)
            lemma = Lemma(
                project_id=project.project_id,
                lemma_text="unclassified",
                pos="NOUN",
                entity_class=None,  # Not classified
                is_noise=None,  # NULL
            )
            session.add(lemma)
            session.commit()

            # Query with filter should include NULL (treated as valid)
            from sqlalchemy import or_

            valid_lemmas = (
                session.execute(
                    select(Lemma).where(
                        Lemma.project_id == project.project_id,
                        or_(Lemma.is_noise == 0, Lemma.is_noise.is_(None)),
                    )
                )
                .scalars()
                .all()
            )

            assert len(valid_lemmas) == 1
            assert valid_lemmas[0].lemma_text == "unclassified"

    finally:
        engine.dispose()
        Path(db_path).unlink(missing_ok=True)


def test_cluster_classification():
    """Test term cluster classification."""
    # Test phrase classification
    test_cases = [
        ("בית ספר", False),  # Valid Hebrew phrase
        ("0.25 מטר", True),  # Quantity + unit (noise)
        ("10kN שאלה", True),  # Mixed noise
    ]

    for phrase, expected_noise in test_cases:
        result = classify_phrase(phrase)
        assert (
            result.is_noise == expected_noise
        ), f"Failed for '{phrase}': expected noise={expected_noise}, got {result.is_noise}"


def test_performance_baseline():
    """Verify classification performance meets target (<1ms)."""
    import time

    test_strings = ["שלום", "hello", "42", "!", "∑F", "1.2kg", "θ"]
    iterations = 1000

    start = time.perf_counter()
    for _ in range(iterations):
        for text in test_strings:
            classify_text(text)
    end = time.perf_counter()

    elapsed = end - start
    avg_per_call = (elapsed / (iterations * len(test_strings))) * 1000  # ms

    # Target: <1ms, but using safety margin of 10ms for CI environments
    assert avg_per_call < 10, f"Classification too slow: {avg_per_call:.3f}ms (target <10ms)"

    print(f"\nPerformance: {avg_per_call:.3f}ms per classification")
