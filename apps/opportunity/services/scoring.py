# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： scoring.py
    @date：2026/9/3
    @desc: 确定性评分与硬约束
"""
from typing import List, Tuple

PRIORITY_WEIGHT = {
    'must': 5,
    'should': 3,
    'nice_to_have': 1,
}
STATUS_COEFFICIENT = {
    'FULL': 1.0,
    'PARTIAL': 0.5,
    'INSUFFICIENT': 0.0,
    'NO': 0.0,
}
RULE_VERSION = 'scoring-v1'


def _priority_weight(priority: str) -> int:
    return PRIORITY_WEIGHT.get(priority or 'should', 3)


def _status_coefficient(status: str) -> float:
    return STATUS_COEFFICIENT.get(status or 'INSUFFICIENT', 0.0)


def calculate_requirement_score(requirements: List[dict], match_items: List[dict]) -> float:
    if not requirements:
        return 0.0
    match_map = {item.get('requirement_id'): item for item in match_items}
    numerator = 0.0
    denominator = 0.0
    for requirement in requirements:
        weight = _priority_weight(requirement.get('priority'))
        item = match_map.get(requirement.get('id'), {})
        numerator += weight * _status_coefficient(item.get('status'))
        denominator += weight
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator * 100, 1)


def calculate_evidence_completeness(match_items: List[dict]) -> float:
    if not match_items:
        return 0.0
    covered = 0
    for item in match_items:
        evidence = item.get('evidence') or []
        if evidence:
            covered += 1
    return round(covered / len(match_items) * 100, 1)


def calculate_total_score(requirement_score: float, evidence_completeness: float) -> float:
    return round(requirement_score * 0.9 + evidence_completeness * 0.1, 1)


def hard_constraint_failed(requirements: List[dict], match_items: List[dict]) -> bool:
    match_map = {item.get('requirement_id'): item for item in match_items}
    for requirement in requirements:
        if requirement.get('priority') != 'must':
            continue
        item = match_map.get(requirement.get('id')) or {}
        if item.get('status') == 'NO':
            return True
    return False


def recommendation_level(requirements: List[dict], match_items: List[dict], failed: bool) -> str:
    if failed:
        return 'NOT_RECOMMENDED'
    statuses = {(item.get('status') or 'INSUFFICIENT') for item in match_items}
    if 'PARTIAL' in statuses or 'INSUFFICIENT' in statuses:
        return 'TECHNICAL_CONFIRMATION'
    if statuses and statuses.issubset({'FULL'}):
        return 'RECOMMENDED'
    return 'TECHNICAL_CONFIRMATION'


def sort_candidates(candidates: List[dict]) -> List[dict]:
    return sorted(
        candidates,
        key=lambda item: (
            -float(item.get('score') or 0),
            -float((item.get('score_detail') or {}).get('evidence_completeness') or 0),
            item.get('product_code') or '',
        ),
    )


def apply_ranking(candidates: List[dict], max_candidates: int = 5) -> Tuple[List[dict], List[dict]]:
    ranked = sort_candidates(candidates)
    failed = []
    scored = []
    zero = []
    for item in ranked:
        if item.get('hard_constraint_failed'):
            item['rank'] = None
            item['recommendation_level'] = 'NOT_RECOMMENDED'
            failed.append(item)
            continue
        if float(item.get('score') or 0) <= 0:
            item['rank'] = None
            item['exclude_reason'] = 'ZERO_SCORE'
            zero.append(item)
            continue
        scored.append(item)
    for index, item in enumerate(scored, start=1):
        item['rank'] = index
        item.pop('exclude_reason', None)
    limit = max(0, max_candidates)
    return scored[:limit], failed + zero
