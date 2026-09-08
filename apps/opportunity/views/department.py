# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： department.py
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
from opportunity.api.department import DepartmentAPI
from opportunity.serializers.department import DepartmentOperateSerializer, DepartmentSerializer
from opportunity.views.setting import READ_ROLES, WRITE_ROLES


class DepartmentView(APIView):
    authentication_classes = [TokenAuth]

    @extend_schema(
        methods=['GET'],
        description=_('List departments'),
        summary=_('List departments'),
        operation_id=_('List departments'),
        parameters=DepartmentAPI.get_parameters(),
        responses=DepartmentAPI.get_response(),
        tags=[_('Opportunity')],
    )
    @has_permissions(*READ_ROLES)
    def get(self, request: Request, workspace_id: str):
        return result.success(DepartmentSerializer(data={'workspace_id': workspace_id}).list())

    @extend_schema(
        methods=['POST'],
        description=_('Create department'),
        summary=_('Create department'),
        operation_id=_('Create department'),
        parameters=DepartmentAPI.get_parameters(),
        request=DepartmentAPI.get_request(),
        responses=DepartmentAPI.get_response(),
        tags=[_('Opportunity')],
    )
    @has_permissions(*WRITE_ROLES)
    def post(self, request: Request, workspace_id: str):
        return result.success(DepartmentSerializer(data={'workspace_id': workspace_id}).insert(request.data))

    class Operate(APIView):
        authentication_classes = [TokenAuth]

        @extend_schema(
            methods=['GET'],
            description=_('Get department'),
            summary=_('Get department'),
            operation_id=_('Get department'),
            parameters=DepartmentAPI.get_parameters(),
            responses=DepartmentAPI.get_response(),
            tags=[_('Opportunity')],
        )
        @has_permissions(*READ_ROLES)
        def get(self, request: Request, workspace_id: str, department_id: str):
            return result.success(DepartmentOperateSerializer(
                data={'workspace_id': workspace_id, 'department_id': department_id}).one())

        @extend_schema(
            methods=['PUT'],
            description=_('Update department'),
            summary=_('Update department'),
            operation_id=_('Update department'),
            parameters=DepartmentAPI.get_parameters(),
            request=DepartmentAPI.get_request(),
            responses=DepartmentAPI.get_response(),
            tags=[_('Opportunity')],
        )
        @has_permissions(*WRITE_ROLES)
        def put(self, request: Request, workspace_id: str, department_id: str):
            return result.success(DepartmentOperateSerializer(
                data={'workspace_id': workspace_id, 'department_id': department_id}).update(request.data))

        @extend_schema(
            methods=['DELETE'],
            description=_('Delete department'),
            summary=_('Delete department'),
            operation_id=_('Delete department'),
            parameters=DepartmentAPI.get_parameters(),
            responses=DepartmentAPI.get_response(),
            tags=[_('Opportunity')],
        )
        @has_permissions(*WRITE_ROLES)
        def delete(self, request: Request, workspace_id: str, department_id: str):
            return result.success(DepartmentOperateSerializer(
                data={'workspace_id': workspace_id, 'department_id': department_id}).delete())
