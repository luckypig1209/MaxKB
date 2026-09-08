# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： json_utils.py
    @date：2026/9/3
    @desc: 模型 JSON 清理
"""
import json
import re
from typing import Any


def extract_json_object(text: str) -> dict:
    if not text or not isinstance(text, str):
        raise ValueError('empty model response')
    cleaned = text.strip()
    strategies = [
        lambda: json.loads(cleaned),
        lambda: json.loads(re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL).group(1)),
        lambda: json.loads(re.search(r'(\{.*\})', cleaned, flags=re.DOTALL).group(1)),
    ]
    last_error = None
    for strategy in strategies:
        try:
            result = strategy()
            if isinstance(result, dict):
                return result
        except Exception as exc:
            last_error = exc
            continue
    raise ValueError(f'invalid json: {last_error}')


def model_content_to_text(content: Any) -> str:
    if content is None:
        return ''
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get('text'):
                parts.append(str(item.get('text')))
            else:
                parts.append(str(item))
        return ''.join(parts)
    return str(content)
