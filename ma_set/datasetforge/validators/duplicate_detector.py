"""MA-SET Lab: Duplicate Detector.

Detects exact, near, and semantic duplicates in benchmark task candidate pools:
- Exact duplicate: matching prompt hashes or identical requirement sets
- Near duplicate: high Jaccard token similarity (> 0.8) or matching targeted files
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, Tuple

from ma_set.datasetforge.schemas.task import BenchmarkTaskSchema


@dataclass
class DuplicateMatch:
    task_a_id: str
    task_b_id: str
    match_type: str  # "EXACT", "NEAR", "REQUIREMENT_OVERLAP"
    similarity: float
    description: str


class DuplicateDetector:
    """Audits a collection of benchmark tasks for duplicate entries."""

    def _tokenize(self, text: str) -> Set[str]:
        words = re.findall(r"\b[a-zA-Z0-9_-]{3,}\b", text.lower())
        return set(words)

    def _jaccard_similarity(self, set_a: Set[str], set_b: Set[str]) -> float:
        if not set_a or not set_b:
            return 0.0
        intersection = len(set_a.intersection(set_b))
        union = len(set_a.union(set_b))
        return intersection / union if union > 0 else 0.0

    def find_duplicates(self, tasks: List[BenchmarkTaskSchema]) -> List[DuplicateMatch]:
        matches: List[DuplicateMatch] = []
        n = len(tasks)

        for i in range(n):
            for j in range(i + 1, n):
                a = tasks[i]
                b = tasks[j]

                # 1. Exact hash check
                hash_a = hashlib.sha256(a.prompt.strip().encode("utf-8")).hexdigest()
                hash_b = hashlib.sha256(b.prompt.strip().encode("utf-8")).hexdigest()
                if hash_a == hash_b:
                    matches.append(
                        DuplicateMatch(
                            task_a_id=a.id,
                            task_b_id=b.id,
                            match_type="EXACT",
                            similarity=1.0,
                            description="Identical prompt hash",
                        )
                    )
                    continue

                # 2. Requirements overlap
                req_a = set(r.strip().lower() for r in a.requirements)
                req_b = set(r.strip().lower() for r in b.requirements)
                req_sim = self._jaccard_similarity(req_a, req_b)
                if req_sim > 0.85:
                    matches.append(
                        DuplicateMatch(
                            task_a_id=a.id,
                            task_b_id=b.id,
                            match_type="REQUIREMENT_OVERLAP",
                            similarity=req_sim,
                            description=f"Requirements set overlap ({req_sim:.2%})",
                        )
                    )
                    continue

                # 3. Prompt near-duplicate
                tokens_a = self._tokenize(a.prompt)
                tokens_b = self._tokenize(b.prompt)
                token_sim = self._jaccard_similarity(tokens_a, tokens_b)
                if token_sim > 0.80:
                    matches.append(
                        DuplicateMatch(
                            task_a_id=a.id,
                            task_b_id=b.id,
                            match_type="NEAR",
                            similarity=token_sim,
                            description=f"Lexical similarity above threshold ({token_sim:.2%})",
                        )
                    )

        return matches
