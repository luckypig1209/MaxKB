# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： candidate_aggregation.py
    @date：2026/9/3
    @desc: 按产品聚合召回证据
"""
from collections import defaultdict

from django.db.models import QuerySet

from opportunity.models import ProductProfile, ProductStatus
from opportunity.services.retrieval_optimization import dedupe_evidence_hits


def _similarity(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def build_search_queries(profile: dict) -> list:
    queries = []
    for item in profile.get('requirements') or []:
        description = (item.get('description') or '').strip()
        if description:
            queries.append(description)
    for item in profile.get('business_scenarios') or []:
        if item:
            queries.append(item)
    for item in profile.get('pain_points') or []:
        if item:
            queries.append(item)
    if not queries and profile.get('source_requirement'):
        queries.append(profile.get('source_requirement'))
    return queries[:12]


def aggregate_by_product(workspace_id, hits: list) -> dict:
    grouped = defaultdict(list)
    for hit in hits:
        product_code = hit.get('product_code')
        if not product_code:
            continue
        grouped[product_code].append(hit)
    products = {
        item.code: item
        for item in QuerySet(ProductProfile).filter(
            workspace_id=workspace_id,
            code__in=list(grouped.keys()),
            status=ProductStatus.ACTIVE,
        )
    }
    result = {}
    for product_code, evidence in grouped.items():
        product = products.get(product_code)
        if product is None:
            continue
        evidence = dedupe_evidence_hits(evidence)
        evidence.sort(
            # Python's sort is stable: equal scores retain retrieval order.
            key=lambda item: -_similarity(item.get('similarity')),
        )
        result[product_code] = {
            'product': product,
            'evidence': evidence[:20],
        }
    # Retrieval order can vary by backend shard.  Product preprocessing must
    # remain deterministic without changing final scoring or ranking rules.
    return dict(sorted(
        result.items(),
        key=lambda item: (
            -max((_similarity(hit.get('similarity')) for hit in item[1]['evidence']), default=0),
            str(item[0]),
        ),
    ))
