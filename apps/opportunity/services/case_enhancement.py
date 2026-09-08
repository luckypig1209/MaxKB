# coding=utf-8
"""第二阶段案例检索编排与受限辅助评分。"""
import logging

from opportunity.services.case_retrieval import retrieve_case_paragraphs

logger = logging.getLogger('maxkb')

CASE_WEIGHT = 0.1
MAX_CASE_REFERENCES = 3


def build_case_query(profile: dict, fallback='') -> str:
    context = profile.get('customer_context') or {}
    parts = [
        context.get('industry'),
        context.get('customer_type'),
        *(profile.get('business_scenarios') or []),
        *(profile.get('pain_points') or []),
    ]
    text = '；'.join(str(item).strip() for item in parts if str(item or '').strip())
    return text or fallback


def _must_statuses(requirements, candidate):
    must_ids = {
        item.get('id') for item in (requirements or []) if item.get('priority') == 'must'
    }
    return {
        item.get('status')
        for item in (candidate.get('match_items') or [])
        if item.get('requirement_id') in must_ids
    }


def case_score_block_reason(requirements, candidate):
    if candidate.get('hard_constraint_failed'):
        return 'HARD_CONSTRAINT_FAILED'
    statuses = _must_statuses(requirements, candidate)
    if 'NO' in statuses:
        return 'MUST_NO'
    if 'INSUFFICIENT' in statuses:
        return 'MUST_INSUFFICIENT'
    return None


def _group_references(case_hits, product_code, product_version):
    grouped = {}
    for hit in case_hits:
        if product_code not in (hit.get('product_codes') or []):
            continue
        case_id = str(hit.get('case_id') or '')
        if not case_id:
            continue
        versions = hit.get('product_versions') or {}
        case_product_version = str(versions.get(product_code) or '')
        version_compatible = not case_product_version or not product_version or case_product_version == product_version
        evidence = {
            'knowledge_id': hit.get('knowledge_id'),
            'document_id': hit.get('document_id'),
            'paragraph_id': hit.get('paragraph_id'),
            'document_name': hit.get('document_name'),
            'title': hit.get('title'),
            'content_excerpt': hit.get('content_excerpt'),
            'similarity': round(float(hit.get('similarity') or 0), 4),
            'document_version': hit.get('document_version'),
        }
        reference = grouped.setdefault(case_id, {
            'case_id': case_id,
            'case_code': hit.get('case_code'),
            'case_name': hit.get('case_name'),
            'industry': hit.get('industry'),
            'scenario': hit.get('scenario'),
            'project_scale': hit.get('project_scale') or {},
            'outcomes': hit.get('outcomes') or [],
            'applicability_boundary': hit.get('applicability_boundary') or '',
            'product_version': case_product_version,
            'version_compatible': version_compatible,
            'similarity': 0.0,
            'evidence': [],
        })
        if len(reference['evidence']) < 3 and evidence['paragraph_id'] not in {
            item.get('paragraph_id') for item in reference['evidence']
        }:
            reference['evidence'].append(evidence)
        reference['similarity'] = max(reference['similarity'], evidence['similarity'])
        reference['version_compatible'] = reference['version_compatible'] and version_compatible
    return sorted(grouped.values(), key=lambda item: (-item['similarity'], item.get('case_code') or ''))


def apply_case_enhancement(candidates, requirements, case_hits, weight=CASE_WEIGHT):
    """案例最多贡献 10 分，且不修改产品逐项匹配事实。"""
    safe_weight = min(max(float(weight or 0), 0.0), CASE_WEIGHT)
    for candidate in candidates:
        detail = candidate.setdefault('score_detail', {})
        base_score = float(candidate.get('score') or 0)
        detail.setdefault('product_score', base_score)
        detail['case_weight'] = safe_weight
        product_version = str(candidate.get('product_version') or '')
        references = _group_references(case_hits, candidate.get('product_code'), product_version)
        candidate['case_references'] = references[:MAX_CASE_REFERENCES]
        blocked_reason = case_score_block_reason(requirements, candidate)
        compatible = [item for item in references if item.get('version_compatible')]
        if blocked_reason or not compatible:
            detail['case_score'] = 0.0
            if blocked_reason:
                detail['case_score_blocked_reason'] = blocked_reason
            elif references:
                detail['case_score_blocked_reason'] = 'PRODUCT_VERSION_MISMATCH'
            candidate['score'] = base_score
            continue
        similarity = sum(item['similarity'] for item in compatible[:MAX_CASE_REFERENCES]) / min(
            len(compatible), MAX_CASE_REFERENCES,
        )
        case_score = round(similarity * 100 * safe_weight, 1)
        detail['case_score'] = min(case_score, 10.0)
        detail.pop('case_score_blocked_reason', None)
        candidate['score'] = round(min(100.0, base_score + detail['case_score']), 1)
    return candidates


def run_case_enhancement(
    workspace_id,
    knowledge_id,
    profile,
    candidates,
    requirements,
    original_requirement='',
    search_mode='blend',
    top_n=10,
    similarity=0.3,
    user_id=None,
    department_ids=None,
    retrieve_func=None,
):
    """案例链路故障只降级案例能力，不中断产品推荐。"""
    if not knowledge_id:
        return candidates, {'status': 'NOT_CONFIGURED', 'count': 0, 'warning': '未配置案例知识库'}
    product_codes = [
        item.get('product_code') for item in candidates if not item.get('hard_constraint_failed')
    ]
    if not product_codes:
        return candidates, {'status': 'SKIPPED', 'count': 0, 'warning': None}
    context = profile.get('customer_context') or {}
    retrieve = retrieve_func or retrieve_case_paragraphs
    try:
        hits = retrieve(
            workspace_id=workspace_id,
            knowledge_id=knowledge_id,
            question=build_case_query(profile, original_requirement),
            product_codes=product_codes,
            industry=context.get('industry'),
            search_mode=search_mode,
            top_n=min(max(int(top_n or 10), 3), 20),
            similarity=similarity,
            user_id=user_id,
            department_ids=department_ids,
        )
        apply_case_enhancement(candidates, requirements, hits)
        reference_count = len({item.get('case_id') for item in hits if item.get('case_id')})
        status = 'APPLIED' if hits else 'NO_MATCH'
        return candidates, {'status': status, 'count': reference_count, 'warning': None}
    except Exception:
        logger.exception('case enhancement degraded workspace=%s', workspace_id)
        return candidates, {
            'status': 'DEGRADED',
            'count': 0,
            'warning': '案例参考暂不可用，当前结果仅依据产品资料生成',
        }
