# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： matching.py
    @date：2026/9/3
    @desc: 逐项比对与证据绑定
"""
import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage
from rest_framework import serializers

from common.exception.app_exception import AppApiException
from models_provider.tools import get_model_instance_by_model_workspace_id
from opportunity.services.json_utils import extract_json_object, model_content_to_text
from opportunity.services.prompts import MATCH_PROMPT_VERSION, MATCH_SYSTEM_PROMPT
from opportunity.services.scoring import (
    RULE_VERSION,
    apply_ranking,
    calculate_evidence_completeness,
    calculate_requirement_score,
    calculate_total_score,
    hard_constraint_failed,
    recommendation_level,
)

logger = logging.getLogger('maxkb')

ALLOWED_STATUS = {'FULL', 'PARTIAL', 'NO', 'INSUFFICIENT'}


class MatchSuggestionItemSerializer(serializers.Serializer):
    requirement_id = serializers.CharField(required=True)
    status = serializers.ChoiceField(choices=list(ALLOWED_STATUS))
    reason = serializers.CharField(required=False, allow_blank=True, default='')
    evidence_paragraph_ids = serializers.ListField(child=serializers.CharField(), required=False, default=list)


class MatchSuggestionSerializer(serializers.Serializer):
    items = MatchSuggestionItemSerializer(many=True, required=True)


def _dedupe_evidence(evidence_list):
    seen = set()
    result = []
    for item in evidence_list:
        paragraph_id = str(item.get('paragraph_id'))
        if paragraph_id in seen:
            continue
        seen.add(paragraph_id)
        result.append(item)
    return result


def _to_evidence_view(hit: dict) -> dict:
    return {
        'knowledge_id': hit.get('knowledge_id'),
        'document_id': hit.get('document_id'),
        'paragraph_id': hit.get('paragraph_id'),
        'document_name': hit.get('document_name'),
        'title': hit.get('title'),
        'content_excerpt': hit.get('content_excerpt'),
        'similarity': hit.get('similarity'),
        'document_version': hit.get('document_version'),
    }


def fallback_match_items(requirements, evidence_hits):
    items = []
    for requirement in requirements:
        evidence = _dedupe_evidence(evidence_hits)[:5]
        status = 'PARTIAL' if evidence else 'INSUFFICIENT'
        items.append({
            'requirement_id': requirement.get('id'),
            'status': status,
            'reason': '已召回相关产品资料，待结合证据确认' if evidence else '当前产品资料不足以支持判断',
            'evidence': [_to_evidence_view(item) for item in evidence],
        })
    return items


def match_product(workspace_id, llm_model_id, product, requirements, evidence_hits):
    evidence_map = {str(item.get('paragraph_id')): item for item in evidence_hits}
    if not llm_model_id:
        raise AppApiException(500, '未配置分析模型')
    model = get_model_instance_by_model_workspace_id(str(llm_model_id), workspace_id)
    payload = {
        'product_code': product.code,
        'product_name': product.name,
        'requirements': requirements,
        'evidence': [_to_evidence_view(item) for item in evidence_hits],
    }
    messages = [
        SystemMessage(content=MATCH_SYSTEM_PROMPT),
        HumanMessage(content=json.dumps(payload, ensure_ascii=False)),
    ]
    try:
        text = model_content_to_text(getattr(model.invoke(messages), 'content', ''))
        data = extract_json_object(text)
        serializer = MatchSuggestionSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        suggestions = serializer.validated_data.get('items') or []
    except Exception:
        logger.warning('match suggestion fallback product=%s', product.code)
        return fallback_match_items(requirements, evidence_hits)

    suggestion_map = {item.get('requirement_id'): item for item in suggestions}
    result = []
    for requirement in requirements:
        suggestion = suggestion_map.get(requirement.get('id')) or {}
        status = suggestion.get('status') if suggestion.get('status') in ALLOWED_STATUS else 'INSUFFICIENT'
        paragraph_ids = []
        for paragraph_id in suggestion.get('evidence_paragraph_ids') or []:
            if str(paragraph_id) in evidence_map and str(paragraph_id) not in paragraph_ids:
                paragraph_ids.append(str(paragraph_id))
        evidence = _dedupe_evidence([evidence_map[pid] for pid in paragraph_ids])
        if status == 'FULL' and not evidence:
            status = 'INSUFFICIENT'
        result.append({
            'requirement_id': requirement.get('id'),
            'status': status,
            'reason': suggestion.get('reason') or '',
            'evidence': [_to_evidence_view(item) for item in evidence],
        })
    return result


def build_candidate_result(product, requirements, match_items, department, max_candidates=5):
    failed = hard_constraint_failed(requirements, match_items)
    requirement_score = calculate_requirement_score(requirements, match_items)
    completeness = calculate_evidence_completeness(match_items)
    score = calculate_total_score(requirement_score, completeness)
    risks = []
    missing_information = []
    for item in match_items:
        if item.get('status') == 'NO':
            risks.append(item.get('reason') or f"{item.get('requirement_id')} 不满足")
        if item.get('status') == 'INSUFFICIENT':
            missing_information.append(item.get('requirement_id'))
    return {
        'product_code': product.code,
        'product_name': product.name,
        'product_version': str((product.meta or {}).get('version') or '1.0'),
        'rank': None,
        'score': score,
        'recommendation_level': recommendation_level(requirements, match_items, failed),
        'hard_constraint_failed': failed,
        'score_detail': {
            'requirement_score': requirement_score,
            'evidence_completeness': completeness,
            'case_score': 0,
        },
        'match_items': match_items,
        'risks': risks,
        'missing_information': missing_information,
        'department': department,
        'case_references': [],
        'rule_version': RULE_VERSION,
        'prompt_version': MATCH_PROMPT_VERSION,
        'max_candidates': max_candidates,
    }


def rank_candidates(candidates, max_candidates=5):
    return apply_ranking(candidates, max_candidates=max_candidates)
