"""Deterministic process sampling, stratified by filing month and primary TPU subject."""

from collections import defaultdict, deque
from dataclasses import dataclass
from hashlib import sha256

from src.db.civil_subjects import primary_subject


@dataclass(frozen=True)
class Candidate:
    number: str
    month: int
    subject: int
    source_id: str
    fact_id: int | None = None
    record: dict | None = None


def candidates_from_warehouse(facts, eligible_codes):
    """Keep all eligible subjects per source document before choosing one stratum."""
    rows = facts.order_by("pk", "subjects__code").values_list(
        "pk", "process_dimension__number_process", "time__month", "source_id", "subjects__code"
    )
    eligible = set(eligible_codes)
    candidates = defaultdict(set)
    for pk, number, month, source_id, code in rows.iterator(chunk_size=2000):
        if code in eligible:
            candidates[(pk, number, month, source_id)].add(code)
    return [
        Candidate(number, month, primary_subject(codes), source_id, fact_id=pk)
        for (pk, number, month, source_id), codes in candidates.items()
    ]


def choose(candidates, size, seed, fixed=()):
    """Round-robin months and subjects, preserving already-selected members."""
    occupied = {item.number for item in fixed}
    month_counts = defaultdict(int)
    subject_counts = defaultdict(int)
    for item in fixed:
        month_counts[item.month] += 1
        subject_counts[item.month, item.subject] += 1

    # Tie-break documents for one CNJ process before, rather than during, allocation.
    unique = {}
    for item in candidates:
        if item.number in occupied:
            continue
        previous = unique.get(item.number)
        if previous is None or (item.fact_id is None, item.source_id) < (
            previous.fact_id is None, previous.source_id
        ):
            unique[item.number] = item
    groups = defaultdict(list)
    for item in unique.values():
        groups[item.month, item.subject].append(item)
    queues = {
        key: deque(sorted(items, key=lambda item: sha256(f"{seed}:{item.number}".encode()).digest()))
        for key, items in groups.items()
    }
    selected = []
    while queues and len(selected) < size:
        key = min(queues, key=lambda pair: (month_counts[pair[0]], subject_counts[pair], pair))
        selected.append(queues[key].popleft())
        month_counts[key[0]] += 1
        subject_counts[key] += 1
        if not queues[key]:
            del queues[key]
    return selected
