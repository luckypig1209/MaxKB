# coding=utf-8
"""案例档案、审核发布和资料绑定接口。"""
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.views import APIView

from common import result
from common.auth import TokenAuth
from common.auth.authentication import has_permissions
from common.exception.app_exception import AppUnauthorizedFailed
from opportunity.api.case import CaseAPI, CaseActionAPI, CaseBindingAPI
from opportunity.serializers.case import (
    CaseDocumentBindingSerializer,
    CaseOperateSerializer,
    CaseSerializer,
    list_available_case_documents,
)
from opportunity.views.setting import READ_ROLES, WRITE_ROLES
from users.serializers.user import is_workspace_manage


def _is_manager(request, workspace_id):
    return is_workspace_manage(str(request.user.id), workspace_id)


class CaseView(APIView):
    authentication_classes = [TokenAuth]

    @extend_schema(
        methods=['GET'], description=_('List opportunity cases'), summary=_('List opportunity cases'),
        operation_id=_('List opportunity cases'), parameters=CaseAPI.get_parameters(),
        responses=CaseAPI.get_response(), tags=[_('Opportunity')],
    )
    @has_permissions(*READ_ROLES)
    def get(self, request: Request, workspace_id: str):
        return result.success(CaseSerializer(data={
            'workspace_id': workspace_id,
            'user_id': str(request.user.id),
            'is_manager': _is_manager(request, workspace_id),
        }).list({
            'status': request.query_params.get('status'),
            'industry': request.query_params.get('industry'),
            'name': request.query_params.get('name'),
        }))

    @extend_schema(
        methods=['POST'], description=_('Create opportunity case'), summary=_('Create opportunity case'),
        operation_id=_('Create opportunity case'), parameters=CaseAPI.get_parameters(), request=CaseAPI.get_request(),
        responses=CaseAPI.get_response(), tags=[_('Opportunity')],
    )
    @has_permissions(*WRITE_ROLES)
    def post(self, request: Request, workspace_id: str):
        return result.success(CaseSerializer(data={
            'workspace_id': workspace_id,
            'user_id': str(request.user.id),
            'is_manager': True,
            'require_document': True,
        }).insert(request.data))

    class Operate(APIView):
        authentication_classes = [TokenAuth]

        @extend_schema(
            methods=['GET'], description=_('Get opportunity case'), summary=_('Get opportunity case'),
            operation_id=_('Get opportunity case'), parameters=CaseAPI.get_parameters(),
            responses=CaseAPI.get_response(), tags=[_('Opportunity')],
        )
        @has_permissions(*READ_ROLES)
        def get(self, request: Request, workspace_id: str, case_id: str):
            return result.success(CaseOperateSerializer(data={
                'workspace_id': workspace_id,
                'case_id': case_id,
                'user_id': str(request.user.id),
                'is_manager': _is_manager(request, workspace_id),
            }).one())

        @extend_schema(
            methods=['PUT'], description=_('Update opportunity case'), summary=_('Update opportunity case'),
            operation_id=_('Update opportunity case'), parameters=CaseAPI.get_parameters(),
            request=CaseAPI.get_request(), responses=CaseAPI.get_response(), tags=[_('Opportunity')],
        )
        @has_permissions(*WRITE_ROLES)
        def put(self, request: Request, workspace_id: str, case_id: str):
            return result.success(CaseOperateSerializer(data={
                'workspace_id': workspace_id,
                'case_id': case_id,
                'user_id': str(request.user.id),
                'is_manager': True,
            }).update(request.data))

    class Action(APIView):
        authentication_classes = [TokenAuth]

        @extend_schema(
            methods=['PUT'], description=_('Review or publish opportunity case'),
            summary=_('Review or publish opportunity case'), operation_id=_('Review or publish opportunity case'),
            parameters=CaseActionAPI.get_parameters(), request=CaseActionAPI.get_request(),
            responses=CaseActionAPI.get_response(), tags=[_('Opportunity')],
        )
        @has_permissions(*WRITE_ROLES)
        def put(self, request: Request, workspace_id: str, case_id: str):
            return result.success(CaseOperateSerializer(data={
                'workspace_id': workspace_id,
                'case_id': case_id,
                'user_id': str(request.user.id),
                'is_manager': True,
            }).action(request.data))

    class Binding(APIView):
        authentication_classes = [TokenAuth]

        @extend_schema(
            methods=['PUT'], description=_('Bind opportunity case document'),
            summary=_('Bind opportunity case document'), operation_id=_('Bind opportunity case document'),
            parameters=CaseBindingAPI.get_parameters(), request=CaseBindingAPI.get_request(),
            responses=CaseBindingAPI.get_response(), tags=[_('Opportunity')],
        )
        @has_permissions(*WRITE_ROLES)
        def put(self, request: Request, workspace_id: str, case_id: str, document_id: str):
            return result.success(CaseDocumentBindingSerializer(data={
                'workspace_id': workspace_id,
                'case_id': case_id,
                'document_id': document_id,
            }).bind(request.data))


class CaseAvailableDocumentView(APIView):
    """Admin-only source picker for new case registration."""

    authentication_classes = [TokenAuth]

    @extend_schema(
        methods=['GET'], description=_('List available case documents'),
        summary=_('List available case documents'), operation_id=_('List available case documents'),
        parameters=CaseAPI.get_parameters(), responses=CaseAPI.get_response(), tags=[_('Opportunity')],
    )
    @has_permissions(*WRITE_ROLES)
    def get(self, request: Request, workspace_id: str):
        if not _is_manager(request, workspace_id):
            raise AppUnauthorizedFailed(403, _('No permission to access'))
        return result.success(list_available_case_documents(
            workspace_id,
            user_id=str(request.user.id),
            case_id=request.query_params.get('case_id') or None,
        ))
