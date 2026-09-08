# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： setting.py
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
from common.constants.permission_constants import RoleConstants
from opportunity.api.setting import SettingAPI
from opportunity.serializers.setting import SettingOperateSerializer

READ_ROLES = (
    RoleConstants.WORKSPACE_MANAGE.get_workspace_role(),
    RoleConstants.USER.get_workspace_role(),
)
WRITE_ROLES = (
    RoleConstants.WORKSPACE_MANAGE.get_workspace_role(),
)


class OpportunitySettingView(APIView):
    authentication_classes = [TokenAuth]

    @extend_schema(
        methods=['GET'],
        description=_('Get opportunity setting'),
        summary=_('Get opportunity setting'),
        operation_id=_('Get opportunity setting'),
        parameters=SettingAPI.get_parameters(),
        responses=SettingAPI.get_response(),
        tags=[_('Opportunity')],
    )
    @has_permissions(*READ_ROLES)
    def get(self, request: Request, workspace_id: str):
        return result.success(SettingOperateSerializer(data={'workspace_id': workspace_id}).one())

    @extend_schema(
        methods=['PUT'],
        description=_('Update opportunity setting'),
        summary=_('Update opportunity setting'),
        operation_id=_('Update opportunity setting'),
        parameters=SettingAPI.get_parameters(),
        request=SettingAPI.get_request(),
        responses=SettingAPI.get_response(),
        tags=[_('Opportunity')],
    )
    @has_permissions(*WRITE_ROLES)
    def put(self, request: Request, workspace_id: str):
        return result.success(SettingOperateSerializer(data={'workspace_id': workspace_id}).update(request.data))
