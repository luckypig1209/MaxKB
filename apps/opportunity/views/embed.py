# coding=utf-8
from django.utils.translation import gettext_lazy as _
from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from common import result
from common.auth import AnonymousAuthentication, TokenAuth
from common.auth.authentication import has_permissions
from opportunity.api.embed import EmbedClientAPI, EmbedTokenAPI
from opportunity.auth import OpportunityEmbedTokenAuth
from opportunity.serializers.embed import (
    EmbedClientOperateSerializer,
    EmbedClientSerializer,
    EmbedSessionOperateSerializer,
    EmbedTokenExchangeSerializer,
)
from opportunity.serializers.analysis import AnalysisOperateSerializer, AnalysisSerializer
from opportunity.serializers.report import ReportSerializer
from opportunity.services.report import render_report_html
from opportunity.services.embed_security import ensure_opportunity_embed_enabled
from opportunity.views.setting import WRITE_ROLES


class EmbedTokenExchangeThrottle(SimpleRateThrottle):
    rate = '30/min'

    def get_cache_key(self, request, view):
        client_id = str(request.data.get('client_id') or '')[:64]
        return self.cache_format % {
            'scope': 'opportunity_embed_exchange',
            'ident': f'{self.get_ident(request)}:{client_id}',
        }


def _require_scope(request, scope):
    if not request.auth.has_scope(scope):
        from common.exception.app_exception import AppAuthenticationFailed
        raise AppAuthenticationFailed(1002, '嵌入令牌权限不足')


def _analysis_context(request, analysis_id=None):
    data = {
        'workspace_id': request.auth.workspace_id,
        'user_id': request.auth.user_id,
        'is_manager': False,
    }
    if analysis_id:
        data['analysis_id'] = analysis_id
    return data


def _client_context(request, workspace_id, client_id=None):
    data = {'workspace_id': workspace_id, 'user_id': str(request.user.id)}
    if client_id:
        data['client_id'] = client_id
    return data


class OpportunityEmbedAPIView(APIView):
    """Base view that gates all opportunity embed endpoints before auth.

    The feature flag intentionally runs before DRF authentication and
    permission checks.  A disabled integration therefore returns the same
    not-found response for anonymous callers and authenticated callers,
    without exposing client existence or any stored secrets.
    """

    def initial(self, request, *args, **kwargs):
        ensure_opportunity_embed_enabled()
        return super().initial(request, *args, **kwargs)


class EmbedClientView(OpportunityEmbedAPIView):
    authentication_classes = [TokenAuth]

    @extend_schema(
        methods=['GET'], summary=_('List opportunity embed clients'),
        parameters=EmbedClientAPI.get_parameters(), responses=EmbedClientAPI.get_response(), tags=[_('Opportunity')],
    )
    @has_permissions(*WRITE_ROLES)
    def get(self, request: Request, workspace_id: str):
        return result.success(EmbedClientSerializer(data=_client_context(request, workspace_id)).list())

    @extend_schema(
        methods=['POST'], summary=_('Create opportunity embed client'),
        parameters=EmbedClientAPI.get_parameters(), request=EmbedClientAPI.get_request(),
        responses=EmbedClientAPI.get_response(), tags=[_('Opportunity')],
    )
    @has_permissions(*WRITE_ROLES)
    def post(self, request: Request, workspace_id: str):
        return result.success(EmbedClientSerializer(data=_client_context(request, workspace_id)).insert(request.data))

    class Operate(OpportunityEmbedAPIView):
        authentication_classes = [TokenAuth]

        @has_permissions(*WRITE_ROLES)
        def put(self, request: Request, workspace_id: str, client_id: str):
            return result.success(EmbedClientOperateSerializer(
                data=_client_context(request, workspace_id, client_id),
            ).update(request.data))

        @has_permissions(*WRITE_ROLES)
        def delete(self, request: Request, workspace_id: str, client_id: str):
            return result.success(EmbedClientOperateSerializer(
                data=_client_context(request, workspace_id, client_id),
            ).disable())

    class RotateSecret(OpportunityEmbedAPIView):
        authentication_classes = [TokenAuth]

        @has_permissions(*WRITE_ROLES)
        def post(self, request: Request, workspace_id: str, client_id: str):
            return result.success(EmbedClientOperateSerializer(
                data=_client_context(request, workspace_id, client_id),
            ).rotate_secret())

    class RevokeSession(OpportunityEmbedAPIView):
        authentication_classes = [TokenAuth]

        @has_permissions(*WRITE_ROLES)
        def post(self, request: Request, workspace_id: str, session_id: str):
            return result.success(EmbedSessionOperateSerializer(data={
                'workspace_id': workspace_id,
                'session_id': session_id,
            }).revoke())


class EmbedTokenExchangeView(OpportunityEmbedAPIView):
    authentication_classes = [AnonymousAuthentication]
    throttle_classes = [EmbedTokenExchangeThrottle]

    @extend_schema(
        methods=['POST'], summary=_('Exchange opportunity embed short token'),
        request=EmbedTokenAPI.get_request(), responses=EmbedTokenAPI.get_response(), tags=[_('Opportunity')],
    )
    def post(self, request: Request):
        return result.success(EmbedTokenExchangeSerializer().exchange(request.data))


class EmbedSessionView(OpportunityEmbedAPIView):
    authentication_classes = [OpportunityEmbedTokenAuth]

    def get(self, request: Request):
        context = request.auth
        return result.success({
            'workspace_id': context.workspace_id,
            'client_id': context.client_id,
            'session_id': context.session_id,
            'user_id': context.user_id,
            'origin': context.origin,
            'department_ids': list(context.department_ids),
            'scopes': list(context.scopes),
            'expires_at': context.expires_at,
            'user': {
                'id': str(request.user.id),
                'username': request.user.username,
                'nick_name': request.user.nick_name,
            },
        })


class EmbedAnalysisView(OpportunityEmbedAPIView):
    """仅使用服务端令牌上下文，不接受浏览器传入的用户或工作空间。"""
    authentication_classes = [OpportunityEmbedTokenAuth]

    def get(self, request: Request):
        _require_scope(request, 'analysis:read')
        return result.success(AnalysisSerializer(data=_analysis_context(request)).list(
            request.query_params,
            request.query_params.get('current_page', 1),
            request.query_params.get('page_size', 20),
        ))

    def post(self, request: Request):
        _require_scope(request, 'analysis:create')
        return result.success(AnalysisSerializer(data=_analysis_context(request)).insert(request.data))

    class Operate(OpportunityEmbedAPIView):
        authentication_classes = [OpportunityEmbedTokenAuth]

        def get(self, request: Request, analysis_id: str):
            _require_scope(request, 'analysis:read')
            return result.success(AnalysisOperateSerializer(
                data=_analysis_context(request, analysis_id),
            ).one())

    class Clarification(OpportunityEmbedAPIView):
        authentication_classes = [OpportunityEmbedTokenAuth]

        def post(self, request: Request, analysis_id: str):
            _require_scope(request, 'analysis:create')
            return result.success(AnalysisOperateSerializer(
                data=_analysis_context(request, analysis_id),
            ).clarify(request.data))

    class Retry(OpportunityEmbedAPIView):
        authentication_classes = [OpportunityEmbedTokenAuth]

        def post(self, request: Request, analysis_id: str):
            _require_scope(request, 'analysis:create')
            return result.success(AnalysisOperateSerializer(
                data=_analysis_context(request, analysis_id),
            ).retry())

    class Confirm(OpportunityEmbedAPIView):
        authentication_classes = [OpportunityEmbedTokenAuth]

        def post(self, request: Request, analysis_id: str):
            _require_scope(request, 'analysis:decision')
            return result.success(AnalysisOperateSerializer(
                data=_analysis_context(request, analysis_id),
            ).confirm(request.data))

    class ExportReport(OpportunityEmbedAPIView):
        authentication_classes = [OpportunityEmbedTokenAuth]

        def get(self, request: Request, analysis_id: str):
            _require_scope(request, 'report:export')
            report = ReportSerializer(data=_analysis_context(request, analysis_id)).latest()
            response = HttpResponse(render_report_html(report), content_type='text/html; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="{report.report_no}.html"'
            response['Cache-Control'] = 'no-store'
            return response
