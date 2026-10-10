# coding=utf-8
"""嵌入页面的动态 frame-ancestors 安全响应头。"""
import re

from django.db import DatabaseError
from django.db.models import QuerySet
from django.utils.deprecation import MiddlewareMixin

from common.result import Result
from maxkb.const import CONFIG
from opportunity.models import OpportunityEmbedClient
from opportunity.services.embed_security import (
    EMBED_FEATURE_DISABLED_CODE,
    EMBED_FEATURE_DISABLED_HTTP_STATUS,
    EMBED_FEATURE_DISABLED_MESSAGE,
    is_opportunity_embed_enabled,
    normalize_origin,
)


class OpportunityEmbedHeadersMiddleware(MiddlewareMixin):
    def process_response(self, request, response):
        prefix = re.escape(CONFIG.get_admin_path().rstrip('/'))
        path_match = re.match(rf'^{prefix}/opportunity/embed(?:/|$)', request.path)
        if path_match is None:
            return response
        if not is_opportunity_embed_enabled():
            return Result(
                code=EMBED_FEATURE_DISABLED_CODE,
                message=EMBED_FEATURE_DISABLED_MESSAGE,
                response_status=EMBED_FEATURE_DISABLED_HTTP_STATUS,
            )

        match = re.match(rf'^{prefix}/opportunity/embed/([A-Za-z0-9_-]+)(?:/|$)', request.path)
        if match is None:
            return response
        origins = []
        try:
            client = QuerySet(OpportunityEmbedClient).filter(
                client_id=match.group(1), is_active=True,
            ).first()
            if client:
                for origin in client.allowed_origins or []:
                    try:
                        origins.append(normalize_origin(origin))
                    except Exception:
                        continue
        except DatabaseError:
            pass
        frame_ancestors = "'self' " + ' '.join(origins) if origins else "'none'"
        response['Content-Security-Policy'] = f'frame-ancestors {frame_ancestors}'
        response['Referrer-Policy'] = 'no-referrer'
        response['Cache-Control'] = 'no-store'
        response['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        return response
