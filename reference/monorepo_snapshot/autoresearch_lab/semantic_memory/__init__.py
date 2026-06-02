"""Decision provenance sidecar — ingest chat, bind patterns, promote lessons to HyperTachi."""
from autoresearch_lab.semantic_memory.ingest import ingest_transcript, extract_decision_atoms
from autoresearch_lab.semantic_memory.promote import promote_validated_lesson

__all__ = [
    "ingest_transcript",
    "extract_decision_atoms",
    "promote_validated_lesson",
]