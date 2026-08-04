import uuid

from app.config.settings import RetrievalSettings
from app.knowledge.confidence import ConfidenceEstimator, LowConfidenceDetector
from app.knowledge.contracts import RetrievedChunk


def make_chunk(retrieval_score: float = 0.5, reranker_score: float | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        version_number=1,
        document_title="Doc",
        category="POLICY",
        text="x",
        retrieval_score=retrieval_score,
        reranker_score=reranker_score,
    )


def test_confidence_mean_of_reranker_scores():
    chunks = [make_chunk(reranker_score=0.6), make_chunk(reranker_score=0.8)]
    assert ConfidenceEstimator().estimate(chunks) == 0.7


def test_confidence_falls_back_to_retrieval_scores():
    chunks = [make_chunk(retrieval_score=0.25), make_chunk(retrieval_score=0.75)]
    assert ConfidenceEstimator().estimate(chunks) == 0.5


def test_confidence_empty_is_zero():
    assert ConfidenceEstimator().estimate([]) == 0.0


def test_low_confidence_below_threshold():
    detector = LowConfidenceDetector(RetrievalSettings(confidence_threshold=0.5))
    assert detector.is_low(0.3, chunk_count=2) is True
    assert detector.is_low(0.7, chunk_count=2) is False


def test_low_confidence_below_min_sources():
    detector = LowConfidenceDetector(RetrievalSettings(min_sources=2))
    assert detector.is_low(0.9, chunk_count=1) is True
    assert detector.is_low(0.9, chunk_count=2) is False
