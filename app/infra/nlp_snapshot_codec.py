"""Codec helpers for persisted sentence-level NLP snapshots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from app.infra.nlp_engines.base import Sentence, Token


def build_sentence_text_hash(text: str) -> str:
    encoded = str(text or "").encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def serialize_nlp_sentences(sentences: Iterable[Sentence]) -> str:
    payload: list[dict[str, Any]] = []
    for sentence in sentences:
        sentence_text = str(getattr(sentence, "text", "") or "")
        payload.append(
            {
                "text": sentence_text,
                "tokens": [
                    {
                        "text": str(getattr(token, "text", "") or ""),
                        "lemma": str(getattr(token, "lemma", "") or ""),
                        "pos": str(getattr(token, "pos", "") or ""),
                        "morph": str(getattr(token, "morph", "") or ""),
                    }
                    for token in getattr(sentence, "tokens", [])
                ],
            }
        )
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def deserialize_nlp_sentences(payload_json: str) -> list[Sentence]:
    raw_payload = json.loads(str(payload_json or "[]"))
    if not isinstance(raw_payload, list):
        raise ValueError("sentence NLP snapshot payload must be a list")

    sentences: list[Sentence] = []
    for raw_sentence in raw_payload:
        if not isinstance(raw_sentence, dict):
            raise ValueError("sentence NLP snapshot item must be an object")
        raw_tokens = raw_sentence.get("tokens") or []
        if not isinstance(raw_tokens, list):
            raise ValueError("sentence NLP snapshot tokens must be a list")
        tokens = [
            Token(
                text=str(raw_token.get("text") or ""),
                lemma=str(raw_token.get("lemma") or ""),
                pos=str(raw_token.get("pos") or ""),
                morph=str(raw_token.get("morph") or ""),
            )
            for raw_token in raw_tokens
            if isinstance(raw_token, dict)
        ]
        sentences.append(
            Sentence(
                text=str(raw_sentence.get("text") or ""),
                tokens=tokens,
            )
        )
    return sentences


def count_snapshot_tokens(sentences: Iterable[Sentence]) -> int:
    return sum(len(sentence.tokens) for sentence in sentences)
