# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： analysis.py
    @date：2026/9/3
    @desc:
"""
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.views import APIView

from common import result
from common.auth import TokenAuth
from common.auth.authentication import has_permissions
from opportunity.api.analysis import AnalysisAPI, AnalysisOperateAPI, ClarificationAPI, RequirementVersionAPI
from opportunity.serializers.analysis import AnalysisOperateSerializer, AnalysisSerializer
from opportunity.views.setting import READ_ROLES
from users.serializers.user import is_workspace_manage


def _context(request, workspace_id, analysis_id=None):
    data = {
        'workspace_id': workspace_id,
        'user_id': str(request.user.id),
        'is_manager': is_workspace_manage(str(request.user.id), workspace_id),
    }
    if analysis_id:
        data['analysis_id'] = analysis_id
    return data


class AnalysisView(APIView):
    authentication_classes = [TokenAuth]

    @extend_schema(
        methods=['GET'],
        description=_('List opportunity analyses'),
        summary=_('List opportunity analyses'),
        operation_id=_('List opportunity analyses'),
        parameters=AnalysisAPI.get_parameters(),
        responses=AnalysisAPI.get_response(),
        tags=[_('Opportunity')],
    )
    @has_permissions(*READ_ROLES)
    def get(self, request: Request, workspace_id: str):
        return result.success(AnalysisSerializer(data=_context(request, workspace_id)).list(
                request.query_params, request.query_params.get('current_page', 1),
                request.query_params.get('page_size', 20)))

    @extend_schema(
        methods=['POST'],
        description=_('Create opportunity analysis'),
        summary=_('Create opportunity analysis'),
        operation_id=_('Create opportunity analysis'),
        parameters=AnalysisAPI.get_parameters(),
        request=AnalysisAPI.get_request(),
        responses=AnalysisAPI.get_response(),
        tags=[_('Opportunity')],
    )
    @has_permissions(*READ_ROLES)
    def post(self, request: Request, workspace_id: str):
        return result.success(AnalysisSerializer(data=_context(request, workspace_id)).insert(request.data))

    class Operate(APIView):
        authentication_classes = [TokenAuth]

        @extend_schema(
            methods=['GET'],
            description=_('Get opportunity analysis'),
            summary=_('Get opportunity analysis'),
            operation_id=_('Get opportunity analysis'),
            parameters=AnalysisOperateAPI.get_parameters(),
            responses=AnalysisOperateAPI.get_response(),
            tags=[_('Opportunity')],
        )
        @has_permissions(*READ_ROLES)
        def get(self, request: Request, workspace_id: str, analysis_id: str):
            return result.success(AnalysisOperateSerializer(
                data=_context(request, workspace_id, analysis_id),
            ).one())

    class Clarification(APIView):
        authentication_classes = [TokenAuth]

        @extend_schema(
            methods=['POST'],
            description=_('Submit clarification'),
            summary=_('Submit clarification'),
            operation_id=_('Submit clarification'),
            parameters=AnalysisOperateAPI.get_parameters(),
            request=ClarificationAPI.get_request(),
            responses=ClarificationAPI.get_response(),
            tags=[_('Opportunity')],
        )
        @has_permissions(*READ_ROLES)
        def post(self, request: Request, workspace_id: str, analysis_id: str):
            return result.success(AnalysisOperateSerializer(
                data=_context(request, workspace_id, analysis_id),
            ).clarify(request.data))

    class Retry(APIView):
        authentication_classes = [TokenAuth]

        @extend_schema(
            methods=['POST'],
            description=_('Retry opportunity analysis'),
            summary=_('Retry opportunity analysis'),
            operation_id=_('Retry opportunity analysis'),
            parameters=AnalysisOperateAPI.get_parameters(),
            responses=AnalysisOperateAPI.get_response(),
            tags=[_('Opportunity')],
        )
        @has_permissions(*READ_ROLES)
        def post(self, request: Request, workspace_id: str, analysis_id: str):
            return result.success(AnalysisOperateSerializer(
                data=_context(request, workspace_id, analysis_id),
            ).retry())

    class RequirementVersions(APIView):
        authentication_classes = [TokenAuth]

        @extend_schema(
            methods=['GET'],
            description=_('List requirement profile versions'),
            summary=_('List requirement profile versions'),
            operation_id=_('List requirement profile versions'),
            parameters=RequirementVersionAPI.get_parameters(),
            responses=RequirementVersionAPI.get_response(),
            tags=[_('Opportunity')],
        )
        @has_permissions(*READ_ROLES)
        def get(self, request: Request, workspace_id: str, analysis_id: str):
            return result.success(AnalysisOperateSerializer(
                data=_context(request, workspace_id, analysis_id),
            ).requirement_versions())

    class Confirm(APIView):
        authentication_classes = [TokenAuth]

        @extend_schema(
            methods=['POST'],
            description=_('Confirm opportunity analysis'),
            summary=_('Confirm opportunity analysis'),
            operation_id=_('Confirm opportunity analysis'),
            parameters=AnalysisOperateAPI.get_parameters(),
            request=AnalysisOperateAPI.get_request(),
            responses=AnalysisOperateAPI.get_response(),
            tags=[_('Opportunity')],
        )
        @has_permissions(*READ_ROLES)
        def post(self, request: Request, workspace_id: str, analysis_id: str):
            return result.success(AnalysisOperateSerializer(
                data=_context(request, workspace_id, analysis_id),
            ).confirm(request.data))
