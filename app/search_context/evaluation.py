"""Deterministic H3-06 quality and latency evidence calculations."""

from __future__ import annotations

import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class SearchEvaluation:
    query_count: int
    recall_at_10: float
    ndcg_at_10: float
    unauthorized_candidates: int
    citation_coverage: float

    @property
    def accepted(self) -> bool:
        return (
            self.query_count >= 100
            and self.recall_at_10 >= 0.95
            and self.ndcg_at_10 >= 0.75
            and self.unauthorized_candidates == 0
            and self.citation_coverage == 1.0
        )


def evaluate(
    *,
    rankings: Mapping[str, Sequence[uuid.UUID]],
    relevant: Mapping[str, frozenset[uuid.UUID]],
    authorized: Mapping[str, frozenset[uuid.UUID]],
    cited: frozenset[uuid.UUID],
) -> SearchEvaluation:
    if set(rankings) != set(relevant) or set(rankings) != set(authorized):
        raise ValueError("evaluation query sets must match")
    recalls: list[float] = []
    ndcgs: list[float] = []
    unauthorized = 0
    returned: set[uuid.UUID] = set()
    for key, ranking in rankings.items():
        top = tuple(ranking[:10])
        returned.update(top)
        unauthorized += sum(item not in authorized[key] for item in top)
        truth = relevant[key]
        recalls.append(len(set(top) & truth) / len(truth) if truth else 1.0)
        dcg = sum((1 / math.log2(rank + 2)) for rank, item in enumerate(top) if item in truth)
        ideal = sum(1 / math.log2(rank + 2) for rank in range(min(10, len(truth))))
        ndcgs.append(dcg / ideal if ideal else 1.0)
    coverage = len(returned & cited) / len(returned) if returned else 1.0
    count = len(rankings)
    return SearchEvaluation(
        query_count=count,
        recall_at_10=sum(recalls) / count if count else 0,
        ndcg_at_10=sum(ndcgs) / count if count else 0,
        unauthorized_candidates=unauthorized,
        citation_coverage=coverage,
    )
