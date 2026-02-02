"""Term Extraction Service (M5 Base + M5.1 Clustering)."""
import logging
from typing import List, Optional, Tuple
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select, func, and_, or_, text
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


def normalize_search_query(query: str) -> List[str]:
    """
    Normalize search query and generate search variants for Hebrew term matching.

    Generates multiple normalized variants to handle:
    - Definite article variations ("הספר" vs "ספר")
    - Space vs underscore separators ("בית ספר" vs "בית_ספר")
    - Attached vs standalone articles ("בית הספר" vs "בית ה ספר")

    Args:
        query: Raw search query from user

    Returns:
        List of normalized search variants

    Examples:
        "בית הספר" → ["בית הספר", "בית ספר", "בית_הספר", "בית_ספר"]
        "הספר" → ["הספר", "ספר", "הספר", "ספר"]
    """
    from app.domain.hebrew_utils import strip_nikud, strip_cantillation, normalize_whitespace

    if not query or not query.strip():
        return []

    # Basic normalization
    normalized = strip_nikud(query)
    normalized = strip_cantillation(normalized)
    normalized = normalize_whitespace(normalized)
    normalized = normalized.strip()

    variants = set()

    # Original normalized query
    variants.add(normalized)

    # Underscore version (for canonical_key matching)
    underscore_version = normalized.replace(' ', '_')
    variants.add(underscore_version)

    # Article-stripped variants
    # Remove standalone "ה" tokens
    tokens = normalized.split()
    filtered_tokens = [t for t in tokens if t != 'ה']
    if filtered_tokens != tokens:
        article_stripped = ' '.join(filtered_tokens)
        variants.add(article_stripped)
        variants.add(article_stripped.replace(' ', '_'))

    # Also strip attached articles (הX → X) for each token
    article_stripped_tokens = []
    for token in tokens:
        if token.startswith('ה') and len(token) > 1:
            # Strip leading ה
            article_stripped_tokens.append(token[1:])
        else:
            article_stripped_tokens.append(token)

    if article_stripped_tokens != tokens:
        article_stripped_2 = ' '.join(article_stripped_tokens)
        variants.add(article_stripped_2)
        variants.add(article_stripped_2.replace(' ', '_'))

    return list(variants)


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

            # DocFreq: Maximum doc_freq among cluster members
            # This gives a conservative (lower-bound) estimate of documents containing the term
            # NOTE: Exact count would require ngram_doc_stat table, which is not populated
            # For variants of same term, max is typically accurate since they appear in similar contexts
            total_doc_freq = max(stat.doc_freq for _, stat in members)

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
            preset: Ranking preset ('freq', 'strong', 'balanced', 'termhood')
            min_freq: Minimum frequency filter
            source_filter: Source kind filter ('ngram', 'np', or None for all)

        Returns:
            List of ClusterStats
        """
        # M5.4: Termhood preset requires reference corpus
        if preset == 'termhood':
            reference_project_id = self.get_reference_project(session, project_id)
            if reference_project_id:
                return self._list_clusters_with_termhood(
                    session,
                    project_id,
                    reference_project_id,
                    top_n=top_n,
                    search=search,
                    min_freq=min_freq,
                    source_filter=source_filter
                )
            else:
                # No reference set - fall back to freq preset
                logger.warning(f"Termhood preset requested but no reference project set for {project_id}")
                preset = 'freq'
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
            # Generate normalized search variants (handles articles, spaces, etc.)
            search_variants = normalize_search_query(search)

            if search_variants:
                # Build OR clause across multiple fields and variants
                search_conditions = []

                for variant in search_variants:
                    # Match against representative Hebrew term (display)
                    search_conditions.append(TermCluster.representative_he.contains(variant))

                    # Match against canonical key (normalized form)
                    search_conditions.append(TermCluster.canonical_key.contains(variant))

                    # Match against representative lemma (normalized lemma)
                    if TermCluster.representative_lemma is not None:
                        search_conditions.append(TermCluster.representative_lemma.contains(variant))

                # Combine with OR (match any variant in any field)
                stmt = stmt.where(or_(*search_conditions))
            else:
                # Fallback: original behavior if normalization fails
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

    # ===================================================================
    # M5.4: Termhood vs Reference Corpus
    # ===================================================================

    def set_reference_project(
        self,
        session: Session,
        project_id: int,
        reference_project_id: Optional[int]
    ) -> None:
        """
        Set the reference (general) corpus for termhood comparison.

        Args:
            session: DB session
            project_id: Domain project ID
            reference_project_id: Reference project ID (or None to clear)
        """
        project = session.get(DictProject, project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        project.general_corpus_id = reference_project_id
        session.commit()
        logger.info(f"Set reference project for {project_id}: {reference_project_id}")

    def get_reference_project(self, session: Session, project_id: int) -> Optional[int]:
        """
        Get the reference (general) corpus ID for a project.

        Args:
            session: DB session
            project_id: Project ID

        Returns:
            Reference project ID or None
        """
        project = session.get(DictProject, project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        return project.general_corpus_id

    def list_projects(self, session: Session) -> List[Tuple[int, str]]:
        """
        List all projects for reference selection.

        Args:
            session: DB session

        Returns:
            List of (project_id, name) tuples
        """
        stmt = select(DictProject.project_id, DictProject.name).order_by(
            DictProject.name
        )
        results = session.execute(stmt).all()
        return [(r[0], r[1]) for r in results]

    def _get_total_cluster_tokens(self, session: Session, project_id: int) -> int:
        """
        Get total tokens in all clusters for a project (N_d or N_r).

        This is the sum of freq_abs across all clusters.

        Args:
            session: DB session
            project_id: Project ID

        Returns:
            Total cluster token count
        """
        stmt = select(func.sum(TermCluster.freq_abs)).where(
            TermCluster.project_id == project_id
        )
        result = session.execute(stmt).scalar()
        return result or 0

    def _compute_weirdness(
        self,
        f_d: int,
        N_d: int,
        f_r: int,
        N_r: int
    ) -> float:
        """
        Compute weirdness ratio with smoothing.

        Weirdness = (f_d / N_d) / (f_r / N_r)

        High weirdness (> 1.0) indicates term is more frequent in domain vs reference.

        Args:
            f_d: Cluster frequency in domain
            N_d: Total cluster tokens in domain
            f_r: Cluster frequency in reference
            N_r: Total cluster tokens in reference

        Returns:
            Weirdness ratio
        """
        # Smoothing to avoid division by zero
        f_d_s = f_d + 0.5
        f_r_s = f_r + 0.5
        N_d_s = N_d + 1.0
        N_r_s = N_r + 1.0

        weirdness = (f_d_s / N_d_s) / (f_r_s / N_r_s)
        return weirdness

    def _compute_keyness_llr(
        self,
        f_d: int,
        N_d: int,
        f_r: int,
        N_r: int
    ) -> float:
        """
        Compute keyness using log-likelihood ratio (2x2 contingency table).

        Contingency table:
                   | Domain | Reference |
        -----------|--------|-----------|
        Term       |   a    |     c     |
        Not term   |   b    |     d     |

        where:
        a = f_d
        b = N_d - f_d
        c = f_r
        d = N_r - f_r

        G2 = 2 * Σ O_ij * ln(O_ij / E_ij)

        Args:
            f_d: Cluster frequency in domain
            N_d: Total cluster tokens in domain
            f_r: Cluster frequency in reference
            N_r: Total cluster tokens in reference

        Returns:
            Keyness LLR value (higher = more domain-specific)
        """
        import math

        a = f_d
        b = N_d - f_d
        c = f_r
        d = N_r - f_r

        # Total
        n = a + b + c + d

        if n == 0:
            return 0.0

        # Expected values
        e_a = (a + b) * (a + c) / n
        e_b = (a + b) * (b + d) / n
        e_c = (c + d) * (a + c) / n
        e_d = (c + d) * (b + d) / n

        # Compute LLR with safe handling of log(0)
        def safe_log_term(obs, exp):
            if obs == 0:
                return 0.0
            if exp == 0:
                return 0.0
            return obs * math.log(obs / exp)

        llr = 2 * (
            safe_log_term(a, e_a) +
            safe_log_term(b, e_b) +
            safe_log_term(c, e_c) +
            safe_log_term(d, e_d)
        )

        return llr

    def _compute_termhood_score(
        self,
        weirdness: float,
        keyness_llr: float,
        freq: int
    ) -> float:
        """
        Compute composite termhood score for ranking.

        Score = log1p(keyness) * log1p(weirdness) * log1p(freq)

        Combines:
        - Statistical significance (keyness)
        - Domain specificity (weirdness)
        - Frequency evidence (freq)

        Args:
            weirdness: Weirdness ratio
            keyness_llr: Keyness LLR
            freq: Cluster frequency

        Returns:
            Composite termhood score
        """
        import math

        score = (
            math.log1p(max(0, keyness_llr)) *
            math.log1p(max(0, weirdness)) *
            math.log1p(freq)
        )

        return score

    def _list_clusters_with_termhood(
        self,
        session: Session,
        project_id: int,
        reference_project_id: int,
        *,
        top_n: int = 500,
        search: Optional[str] = None,
        min_freq: Optional[int] = None,
        source_filter: Optional[str] = None,
    ) -> List[ClusterStats]:
        """
        List clusters with termhood metrics vs reference corpus.

        Args:
            session: DB session
            project_id: Domain project ID
            reference_project_id: Reference (general) project ID
            top_n: Limit results
            search: Search term
            min_freq: Minimum frequency filter
            source_filter: Source kind filter

        Returns:
            List of ClusterStats with termhood fields populated
        """
        from sqlalchemy import alias

        # Get total cluster tokens for both projects
        N_d = self._get_total_cluster_tokens(session, project_id)
        N_r = self._get_total_cluster_tokens(session, reference_project_id)

        if N_d == 0:
            logger.warning(f"No clusters found in domain project {project_id}")
            return []

        if N_r == 0:
            logger.warning(f"No clusters found in reference project {reference_project_id}")
            N_r = 1  # Avoid division by zero, treat as very small reference

        # Alias for reference clusters
        RefCluster = alias(TermCluster.__table__, name='ref_cluster')

        # Query domain clusters
        stmt = select(TermCluster).where(TermCluster.project_id == project_id)

        # Filter by source kind if specified
        if source_filter:
            stmt = stmt.join(TermClusterMember).join(Ngram).where(
                Ngram.source_kind == source_filter
            ).distinct()

        # Apply filters
        if min_freq:
            stmt = stmt.where(TermCluster.freq_abs >= min_freq)

        if search:
            search_variants = normalize_search_query(search)
            if search_variants:
                search_conditions = []
                for variant in search_variants:
                    search_conditions.append(TermCluster.representative_he.contains(variant))
                    search_conditions.append(TermCluster.canonical_key.contains(variant))
                    if TermCluster.representative_lemma is not None:
                        search_conditions.append(TermCluster.representative_lemma.contains(variant))
                stmt = stmt.where(or_(*search_conditions))
            else:
                stmt = stmt.where(TermCluster.representative_he.contains(search))

        # Execute query to get domain clusters
        domain_clusters = session.execute(stmt).scalars().all()

        # For each domain cluster, find matching reference cluster and compute termhood
        results = []

        for d_cluster in domain_clusters:
            f_d = d_cluster.freq_abs

            # Find matching reference cluster by canonical_key
            ref_stmt = select(TermCluster).where(
                and_(
                    TermCluster.project_id == reference_project_id,
                    TermCluster.canonical_key == d_cluster.canonical_key
                )
            )
            r_cluster = session.execute(ref_stmt).scalar_one_or_none()

            # Get reference frequency (0 if not found)
            f_r = r_cluster.freq_abs if r_cluster else 0

            # Compute termhood metrics
            weirdness = self._compute_weirdness(f_d, N_d, f_r, N_r)
            keyness_llr = self._compute_keyness_llr(f_d, N_d, f_r, N_r)
            termhood_score = self._compute_termhood_score(weirdness, keyness_llr, f_d)

            results.append(ClusterStats(
                cluster_id=d_cluster.cluster_id,
                canonical_key=d_cluster.canonical_key,
                representative_he=d_cluster.representative_he,
                representative_lemma=d_cluster.representative_lemma,
                freq_abs=d_cluster.freq_abs,
                doc_freq=d_cluster.doc_freq,
                members_count=d_cluster.members_count,
                best_pmi=d_cluster.best_pmi,
                best_llr=d_cluster.best_llr,
                best_dice=d_cluster.best_dice,
                best_tscore=d_cluster.best_tscore,
                weirdness=weirdness,
                keyness_llr=keyness_llr,
                termhood_score=termhood_score,
            ))

        # Sort by termhood score (deterministic)
        results.sort(
            key=lambda c: (
                -c.termhood_score if c.termhood_score else 0,
                -c.keyness_llr if c.keyness_llr else 0,
                -c.weirdness if c.weirdness else 0,
                -c.doc_freq,
                -c.freq_abs,
                c.canonical_key  # Stable tiebreaker
            )
        )

        # Limit results
        return results[:top_n]
