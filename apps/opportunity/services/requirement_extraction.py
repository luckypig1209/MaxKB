# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： requirement_extraction.py
    @date：2026/9/3
    @desc: 需求解析与澄清合并
"""
import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage
from rest_framework import serializers

from common.exception.app_exception import AppApiException
from models_provider.tools import get_model_instance_by_model_workspace_id
from opportunity.serializers.requirement import normalize_requirement_profile
from opportunity.services.json_utils import extract_json_object, model_content_to_text
from opportunity.services.prompts import REQUIREMENT_PROMPT_VERSION, REQUIREMENT_SYSTEM_PROMPT

logger = logging.getLogger('maxkb')


def _invoke_model(model, messages) -> str:
    try:
        response = model.invoke(messages)
        return model_content_to_text(getattr(response, 'content', response))
    except Exception as exc:
        message = str(exc)
        lowered = message.lower()
        if 'timeout' in lowered or 'timed out' in lowered:
            raise AppApiException(500, '模型调用超时') from exc
        if 'rate' in lowered or '429' in lowered:
            raise AppApiException(500, '模型调用限流') from exc
        raise AppApiException(500, '模型调用失败') from exc


def extract_requirement_profile(workspace_id, llm_model_id, requirement_text, extra_context=None):
    if not llm_model_id:
        raise AppApiException(500, '未配置分析模型')
    model = get_model_instance_by_model_workspace_id(str(llm_model_id), workspace_id)
    payload = {
        'requirement': requirement_text,
        'extra_context': extra_context or {},
    }
    user_content = json.dumps(payload, ensure_ascii=False)
    messages = [
        SystemMessage(content=REQUIREMENT_SYSTEM_PROMPT),
        HumanMessage(content=user_content),
    ]
    last_error = None
    for _ in range(2):
        try:
            text = _invoke_model(model, messages)
            data = extract_json_object(text)
            return normalize_requirement_profile(data)
        except (ValueError, serializers.ValidationError, AppApiException) as exc:
            last_error = exc
            messages.append(HumanMessage(content='上一次输出不是合法 JSON Schema，请只返回修正后的 JSON。'))
            continue
    logger.warning('requirement extraction failed workspace=%s', workspace_id)
    raise AppApiException(500, '需求解析失败，请重试') from last_error


def merge_clarification(profile: dict, answers: dict, original_requirement: str) -> dict:
    merged = dict(profile or {})
    merged.setdefault('requirements', [])
    merged.setdefault('missing_information', [])
    merged.setdefault('clarification_questions', [])
    merged.setdefault('constraints', [])
    answer_text = answers.get('answer') if isinstance(answers, dict) else str(answers or '')
    if answer_text:
        merged['constraints'] = list(merged.get('constraints') or [])
        merged['constraints'].append(f'用户补充: {answer_text}')
        for requirement in merged['requirements']:
            if not requirement.get('source_text'):
                requirement['source_text'] = original_requirement
    remaining_missing = []
    for item in merged.get('missing_information') or []:
        if answer_text and item and item in answer_text:
            continue
        remaining_missing.append(item)
    merged['missing_information'] = remaining_missing
    merged['clarification_questions'] = []
    return normalize_requirement_profile(merged)


def prompt_versions():
    return {
        'requirement': REQUIREMENT_PROMPT_VERSION,
    }
