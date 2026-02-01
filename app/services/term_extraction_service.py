"""Term Extraction Service (M5 Base + M5.1 Clustering)."""
import logging
from typing import List, Optional, Tuple
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select, func, and_
from sqlalchemy.orm import Session

from app.infra.sa_models import (
    DictProject,
    Ngram,
    NgramProjectStat,
    NgramComponent,
    DocumentSentence,
    Lemma,
    SourceDocument,
    SourceCorpus,
    TermCluster,
    TermClusterMember,
)
from app.domain.dto import ExtractReport, ClusterStats
from app.domain.term_extraction.ngram_extractor import extract_ngrams_from_sentence
from app.domain.term_extraction.np_extractor import extract_np_chunks_from_sentence
from app.domain.term_extraction.association_measures import compute_all_measures
from app.domain.term_extraction.canonicalizer import get_cluster_key, choose_representative_term
from app.services.db_service import DBService
from app.infra.nlp_engines.base import NLPEngine

logger = logging.getLogger(__name__)


class TermExtractionService:
    """Service for term extraction and clustering (M5+)."""

    def __init__(self):
        self.db_service = DBService.get_instance()
        self._engine: Optional[NLPEngine] = None

    def get_nlp_engine(self, use_gpu: bool = False, use_mock: bool = False) -> NLPEngine:
        """
        Get or create NLP engine for re-parsing sentences.

        Args:
            use_gpu: Whether to use GPU
            use_mock: Use mock engine instead of Stanza

        Returns:
            NLPEngine instance
        """
        if self._engine is None:
            if use_mock:
                logger.info("Creating Mock NLP engine for term extraction...")
                from app.infra.nlp_engines.mock_engine import create_mock_engine
                self._engine = create_mock_engine()
            else:
                logger.info("Creating Stanza NLP engine for term extraction...")
                try:
                    from app.infra.nlp_engines.stanza_engine import create_stanza_engine
                    self._engine = create_stanza_engine(use_gpu=use_gpu)
                except (ImportError, RuntimeError) as e:
                    logger.warning(f"Stanza not available: {e}")
                    logger.info("Falling back to Mock engine")
                    from app.infra.nlp_engines.mock_engine import create_mock_engine
                    self._engine = create_mock_engine()

            logger.info(f"NLP engine ready: {self._engine.get_name()} v{self._engine.get_version()}")
        return self._engine

    def extract_terms_for_project(
        self,
        session: Session,
        project_id: int,
        *,
        enable_ngrams: bool = True,
        include_np: bool = False,
        min_freq: int = 2,
        ngram_ns: Tuple[int, ...] = (2, 3),
        np_max_len: int = 5,
        overwrite: bool = True,
    ) -> ExtractReport:
        """
        Extract terms (n-grams + NP chunks + clustering) for a project.

        Args:
            session: DB session
            project_id: Project ID
            enable_ngrams: Extract n-grams
            include_np: Extract NP chunks (M5.3)
            min_freq: Minimum frequency threshold
            ngram_ns: N-gram sizes (default: bigrams + trigrams)
            np_max_len: Maximum NP chunk length (2-5, default 5)
            overwrite: Clear existing ngrams before extraction

        Returns:
            ExtractReport with counts
        """
        logger.info(f"Starting term extraction for project {project_id}")

        try:
            # Get project
            project = session.get(DictProject, project_id)
            if not project:
                raise ValueError(f"Project {project_id} not found")

            # Clear existing if overwrite
            if overwrite:
                self._clear_existing_terms(session, project_id)

            # Extract n-grams
            ngrams_extracted = 0
            if enable_ngrams:
                ngrams_extracted = self._extract_ngrams(
                    session, project_id, ngram_ns, min_freq
                )

            # Extract NP chunks (M5.3)
            np_chunks_extracted = 0
            if include_np:
                np_chunks_extracted = self._extract_np_chunks(
                    session, project_id, np_max_len, min_freq
                )

            # Cluster terms
            clusters_created = self._cluster_terms(session, project_id)

            session.commit()

            logger.info(
                f"Extraction complete: {ngrams_extracted} ngrams, "
                f"{np_chunks_extracted} NP chunks, {clusters_created} clusters"
            )

            return ExtractReport(
                project_id=project_id,
                ngrams_extracted=ngrams_extracted,
                np_chunks_extracted=np_chunks_extracted,
                clusters_created=clusters_created,
                success=True,
            )

        except Exception as e:
            logger.exception(f"Term extraction failed for project {project_id}")
            session.rollback()
            return ExtractReport(
                project_id=project_id,
                ngrams_extracted=0,
                np_chunks_extracted=0,
                clusters_created=0,
                success=False,
                error_message=str(e),
            )

    def _clear_existing_terms(self, session: Session, project_id: int) -> None:
        """Clear existing ngrams and clusters for project."""
        # Delete clusters (CASCADE handles members)
        session.execute(
            TermCluster.__table__.delete().where(
                TermCluster.project_id == project_id
            )
        )

        # Delete ngrams (CASCADE handles stats and components)
        session.execute(
            Ngram.__table__.delete().where(
                Ngram.project_id == project_id
            )
        )

        session.flush()
        logger.info(f"Cleared existing terms for project {project_id}")

    def _extract_ngrams(
        self,
        session: Session,
        project_id: int,
        ngram_ns: Tuple[int, ...],
        min_freq: int
    ) -> int:
        """
        Extract n-grams from processed documents.

        Returns:
            Number of unique n-grams extracted
        """
        logger.info(f"Extracting n-grams (sizes: {ngram_ns})")

        # Get all processed documents for project
        stmt = select(SourceDocument).join(SourceCorpus).where(
            and_(
                SourceCorpus.project_id == project_id,
                SourceDocument.status == 'processed'
            )
        )
        docs = session.execute(stmt).scalars().all()

        if not docs:
            logger.warning(f"No processed documents found for project {project_id}")
            return 0

        # Get project to check which engine was used
        project = session.get(DictProject, project_id)
        use_mock = (project.nlp_engine.lower() == "mock" if project and project.nlp_engine else False)

        # Get NLP engine for re-parsing sentences
        engine = self.get_nlp_engine(use_mock=use_mock)

        # Extract n-grams from all sentences
        ngram_counts = Counter()
        ngram_doc_freq = Counter()
        ngram_meta = {}  # (surface, n) -> {lemma_phrase, pos_pattern}

        for doc in docs:
            # Get sentences for document
            sent_stmt = select(DocumentSentence).where(
                DocumentSentence.doc_id == doc.doc_id
            )
            sentences = session.execute(sent_stmt).scalars().all()

            # Track ngrams seen in this doc
            doc_ngrams_seen = set()

            for sent in sentences:
                # Re-parse sentence with NLP to get tokens
                nlp_sentences = engine.process(sent.text)

                if not nlp_sentences:
                    continue

                # Process each NLP sentence (usually one)
                for nlp_sent in nlp_sentences:
                    # Convert NLP tokens to format expected by extract_ngrams_from_sentence
                    tokens = [
                        {
                            'text': token.text,
                            'lemma': token.lemma,
                            'pos': token.pos,
                        }
                        for token in nlp_sent.tokens
                    ]

                    # Extract ngrams from this sentence
                    ngrams = extract_ngrams_from_sentence(tokens, list(ngram_ns))

                    for ng in ngrams:
                        key = (ng['surface_text'], ng['n'])

                        # Count frequency
                        ngram_counts[key] += 1

                        # Track document frequency
                        if key not in doc_ngrams_seen:
                            ngram_doc_freq[key] += 1
                            doc_ngrams_seen.add(key)

                        # Store metadata
                        if key not in ngram_meta:
                            ngram_meta[key] = {
                                'lemma_phrase': ng['lemma_phrase'],
                                'pos_pattern': ng['pos_pattern'],
                            }

        # Filter by min_freq and store in DB
        ngrams_stored = 0
        for (surface_text, n), freq in ngram_counts.items():
            if freq < min_freq:
                continue

            meta = ngram_meta[(surface_text, n)]

            # Get canonical key
            canonical_key = get_cluster_key(surface_text, meta['lemma_phrase'])

            # Create Ngram
            ngram = Ngram(
                project_id=project_id,
                n=n,
                surface_text=surface_text,
                he_canonical=canonical_key,
                lemma_phrase=meta['lemma_phrase'],
                source_kind='ngram',
                pos_pattern=meta['pos_pattern'],
            )
            session.add(ngram)
            session.flush()  # Get ngram_id

            # Create NgramProjectStat with association measures
            doc_freq = ngram_doc_freq[(surface_text, n)]

            # Compute association measures (for bigrams)
            if n == 2:
                # Get component lemma counts
                lemmas = meta['lemma_phrase'].split()
                if len(lemmas) == 2:
                    l1, l2 = lemmas
                    c_x = self._get_lemma_freq(session, project_id, l1)
                    c_y = self._get_lemma_freq(session, project_id, l2)
                    total_tokens = self._get_total_tokens(session, project_id)

                    measures = compute_all_measures(freq, c_x, c_y, total_tokens)
                else:
                    measures = {'pmi': None, 'tscore': None, 'llr': None, 'dice': None}
            else:
                # Trigrams: compute simplified measures
                measures = {'pmi': None, 'tscore': None, 'llr': None, 'dice': None}

            stat = NgramProjectStat(
                project_id=project_id,
                ngram_id=ngram.ngram_id,
                freq_abs=freq,
                doc_freq=doc_freq,
                pmi_cache=measures['pmi'],
                tscore_cache=measures['tscore'],
                llr_cache=measures['llr'],
                dice_cache=measures['dice'],
            )
            session.add(stat)

            ngrams_stored += 1

        session.flush()
        logger.info(f"Stored {ngrams_stored} n-grams (min_freq={min_freq})")
        return ngrams_stored

    def _extract_np_chunks(
        self,
        session: Session,
        project_id: int,
        np_max_len: int,
        min_freq: int
    ) -> int:
        """
        Extract NP chunks from processed documents (M5.3).

        Returns:
            Number of unique NP chunks extracted
        """
        logger.info(f"Extracting NP chunks (max_len={np_max_len})")

        # Get all processed documents for project
        stmt = select(SourceDocument).join(SourceCorpus).where(
            and_(
                SourceCorpus.project_id == project_id,
                SourceDocument.status == 'processed'
            )
        )
        docs = session.execute(stmt).scalars().all()

        if not docs:
            logger.warning(f"No processed documents found for project {project_id}")
            return 0

        # Get project to check which engine was used
        project = session.get(DictProject, project_id)
        use_mock = (project.nlp_engine.lower() == "mock" if project and project.nlp_engine else False)

        # Get NLP engine for re-parsing sentences
        engine = self.get_nlp_engine(use_mock=use_mock)

        # Extract NP chunks from all sentences
        np_counts = Counter()
        np_doc_freq = Counter()
        np_meta = {}  # (surface, n) -> {lemma_phrase, pos_pattern}

        for doc in docs:
            # Get sentences for document
            sent_stmt = select(DocumentSentence).where(
                DocumentSentence.doc_id == doc.doc_id
            )
            sentences = session.execute(sent_stmt).scalars().all()

            # Track NPs seen in this doc
            doc_nps_seen = set()

            for sent in sentences:
                # Re-parse sentence with NLP to get tokens
                nlp_sentences = engine.process(sent.text)

                if not nlp_sentences:
                    continue

                # Process each NLP sentence (usually one)
                for nlp_sent in nlp_sentences:
                    # Convert NLP tokens to format expected by extractor
                    tokens = [
                        {
                            'text': token.text,
                            'lemma': token.lemma,
                            'pos': token.pos,
                        }
                        for token in nlp_sent.tokens
                    ]

                    # Extract NP chunks from this sentence
                    np_chunks = extract_np_chunks_from_sentence(
                        tokens, min_len=2, max_len=np_max_len
                    )

                    for np in np_chunks:
                        key = (np['surface_text'], np['n'])

                        # Count frequency
                        np_counts[key] += 1

                        # Track document frequency
                        if key not in doc_nps_seen:
                            np_doc_freq[key] += 1
                            doc_nps_seen.add(key)

                        # Store metadata
                        if key not in np_meta:
                            np_meta[key] = {
                                'lemma_phrase': np['lemma_phrase'],
                                'pos_pattern': np['pos_pattern'],
                            }

        # Filter by min_freq and store in DB
        nps_stored = 0
        for (surface_text, n), freq in np_counts.items():
            if freq < min_freq:
                continue

            meta = np_meta[(surface_text, n)]

            # Get canonical key
            canonical_key = get_cluster_key(surface_text, meta['lemma_phrase'])

            # Create Ngram with source_kind='np'
            ngram = Ngram(
                project_id=project_id,
                n=n,
                surface_text=surface_text,
                he_canonical=canonical_key,
                lemma_phrase=meta['lemma_phrase'],
                source_kind='np',
                pos_pattern=meta['pos_pattern'],
            )
            session.add(ngram)
            session.flush()  # Get ngram_id

            # Create NgramProjectStat (no association measures for NPs)
            doc_freq = np_doc_freq[(surface_text, n)]

            stat = NgramProjectStat(
                project_id=project_id,
                ngram_id=ngram.ngram_id,
                freq_abs=freq,
                doc_freq=doc_freq,
                pmi_cache=None,  # Not computed for NP chunks
                tscore_cache=None,
                llr_cache=None,
                dice_cache=None,
            )
            session.add(stat)

            nps_stored += 1

        session.flush()
        logger.info(f"Stored {nps_stored} NP chunks (min_freq={min_freq})")
        return nps_stored

    def _cluster_terms(self, session: Session, project_id: int) -> int:
        """
        Cluster terms by canonical key (M5.1).

        Returns:
            Number of clusters created
        """
        logger.info("Clustering terms by canonical key")

        # Get all ngrams for project
        stmt = select(Ngram, NgramProjectStat).join(NgramProjectStat).where(
            Ngram.project_id == project_id
        )
        results = session.execute(stmt).all()

        # Group by canonical key
        clusters_data = {}  # canonical_key -> list[(ngram, stat)]

        for ngram, stat in results:
            canonical = ngram.he_canonical
            if not canonical:
                canonical = get_cluster_key(ngram.surface_text, ngram.lemma_phrase)

            if canonical not in clusters_data:
                clusters_data[canonical] = []

            clusters_data[canonical].append((ngram, stat))

        # Create clusters
        clusters_created = 0

        for canonical_key, members in clusters_data.items():
            # Aggregate stats
            total_freq = sum(stat.freq_abs for _, stat in members)
            total_doc_freq = sum(stat.doc_freq for _, stat in members)

            # Get best scores
            pmis = [stat.pmi_cache for _, stat in members if stat.pmi_cache is not None]
            llrs = [stat.llr_cache for _, stat in members if stat.llr_cache is not None]
            dices = [stat.dice_cache for _, stat in members if stat.dice_cache is not None]
            tscores = [stat.tscore_cache for _, stat in members if stat.tscore_cache is not None]

            best_pmi = max(pmis) if pmis else None
            best_llr = max(llrs) if llrs else None
            best_dice = max(dices) if dices else None
            best_tscore = max(tscores) if tscores else None

            # Choose representative term
            terms_for_rep = [
                {'surface_text': ng.surface_text, 'freq_abs': st.freq_abs}
                for ng, st in members
            ]
            representative_he = choose_representative_term(terms_for_rep)
            representative_lemma = members[0][0].lemma_phrase  # Use first lemma

            # Create cluster
            cluster = TermCluster(
                project_id=project_id,
                canonical_key=canonical_key,
                representative_he=representative_he,
                representative_lemma=representative_lemma,
                freq_abs=total_freq,
                doc_freq=total_doc_freq,
                members_count=len(members),
                best_pmi=best_pmi,
                best_llr=best_llr,
                best_dice=best_dice,
                best_tscore=best_tscore,
                source_kinds='ngram',
            )
            session.add(cluster)
            session.flush()

            # Create cluster members
            for ngram, stat in members:
                member = TermClusterMember(
                    cluster_id=cluster.cluster_id,
                    ngram_id=ngram.ngram_id,
                    member_freq_abs=stat.freq_abs,
                    member_doc_freq=stat.doc_freq,
                )
                session.add(member)

            clusters_created += 1

        session.flush()
        logger.info(f"Created {clusters_created} clusters")
        return clusters_created

    def _get_lemma_freq(self, session: Session, project_id: int, lemma_text: str) -> int:
        """Get total frequency of a lemma."""
        from app.infra.sa_models import Lemma, LemmaProjectStat

        stmt = select(LemmaProjectStat.freq_abs).join(Lemma).where(
            and_(
                Lemma.project_id == project_id,
                Lemma.lemma_text == lemma_text
            )
        )
        result = session.execute(stmt).scalar()
        return result or 1  # Avoid division by zero

    def _get_total_tokens(self, session: Session, project_id: int) -> int:
        """Get total token count for project."""
        from app.infra.sa_models import LemmaProjectStat

        stmt = select(func.sum(LemmaProjectStat.freq_abs)).where(
            LemmaProjectStat.project_id == project_id
        )
        result = session.execute(stmt).scalar()
        return result or 1  # Avoid division by zero

    def list_term_clusters(
        self,
        session: Session,
        project_id: int,
        *,
        top_n: int = 500,
        search: Optional[str] = None,
        preset: str = 'freq',
        min_freq: Optional[int] = None,
        source_filter: Optional[str] = None,
    ) -> List[ClusterStats]:
        """
        List term clusters with filtering and ranking.

        Args:
            session: DB session
            project_id: Project ID
            top_n: Limit results
            search: Search term (LIKE)
            preset: Ranking preset ('freq', 'strong', 'balanced')
            min_freq: Minimum frequency filter
            source_filter: Source kind filter ('ngram', 'np', or None for all)

        Returns:
            List of ClusterStats
        """
        stmt = select(TermCluster).where(TermCluster.project_id == project_id)

        # Filter by source kind if specified (M5.3)
        if source_filter:
            # Join with members to filter by source_kind
            stmt = stmt.join(TermClusterMember).join(Ngram).where(
                Ngram.source_kind == source_filter
            ).distinct()

        # Apply filters
        if min_freq:
            stmt = stmt.where(TermCluster.freq_abs >= min_freq)

        if search:
            stmt = stmt.where(TermCluster.representative_he.contains(search))

        # Apply ranking preset
        if preset == 'freq':
            stmt = stmt.order_by(
                TermCluster.freq_abs.desc(),
                TermCluster.doc_freq.desc(),
                TermCluster.best_pmi.desc()
            )
        elif preset == 'strong':
            stmt = stmt.where(TermCluster.freq_abs >= 2).order_by(
                TermCluster.best_llr.desc(),
                TermCluster.best_pmi.desc()
            )
        elif preset == 'balanced':
            # M5.2: Balanced ranking using multiple signals
            stmt = stmt.order_by(
                TermCluster.best_llr.desc(),
                TermCluster.best_dice.desc(),
                TermCluster.doc_freq.desc(),
                TermCluster.freq_abs.desc()
            )

        stmt = stmt.limit(top_n)

        clusters = session.execute(stmt).scalars().all()

        # Convert to DTOs
        results = []
        for c in clusters:
            results.append(ClusterStats(
                cluster_id=c.cluster_id,
                canonical_key=c.canonical_key,
                representative_he=c.representative_he,
                representative_lemma=c.representative_lemma,
                freq_abs=c.freq_abs,
                doc_freq=c.doc_freq,
                members_count=c.members_count,
                best_pmi=c.best_pmi,
                best_llr=c.best_llr,
                best_dice=c.best_dice,
                best_tscore=c.best_tscore,
            ))

        return results

    def get_cluster_members(self, session: Session, cluster_id: int) -> List[dict]:
        """
        Get cluster members (surface variants).

        Returns:
            List of dicts with ngram details
        """
        stmt = select(Ngram, NgramProjectStat, TermClusterMember).join(
            TermClusterMember, Ngram.ngram_id == TermClusterMember.ngram_id
        ).join(
            NgramProjectStat,
            and_(
                NgramProjectStat.ngram_id == Ngram.ngram_id,
                NgramProjectStat.project_id == Ngram.project_id
            )
        ).where(TermClusterMember.cluster_id == cluster_id)

        results = session.execute(stmt).all()

        members = []
        for ngram, stat, member in results:
            members.append({
                'surface_text': ngram.surface_text,
                'lemma_phrase': ngram.lemma_phrase,
                'freq_abs': stat.freq_abs,
                'doc_freq': stat.doc_freq,
                'pmi': stat.pmi_cache,
                'llr': stat.llr_cache,
            })

        return members
