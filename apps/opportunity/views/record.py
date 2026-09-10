# coding=utf-8
from common import result
from common.auth import TokenAuth
from common.auth.authentication import has_permissions
from django.utils.translation import gettext_lazy as _
from drf_spectacular.utils import extend_schema
from opportunity.api.record import OpportunityRecordAPI
from opportunity.serializers.record import OpportunityRecordSerializer
from opportunity.views.setting import READ_ROLES
from rest_framework.request import Request
from rest_framework.views import APIView
from users.serializers.user import is_workspace_manage


def _serializer(request, workspace_id, record_id=None):
    data = {
        'workspace_id': workspace_id,
        'user_id': str(request.user.id),
        'is_manager': is_workspace_manage(str(request.user.id), workspace_id),
    }
    if record_id:
        data['record_id'] = record_id
    return OpportunityRecordSerializer(data=data)


class OpportunityRecordView(APIView):
    authentication_classes = [TokenAuth]

    @extend_schema(
        methods=['GET'], description=_('List opportunity records'), summary=_('List opportunity records'),
        operation_id=_('List opportunity records'), parameters=OpportunityRecordAPI.get_parameters(),
        responses=OpportunityRecordAPI.get_response(), tags=[_('Opportunity')],
    )
    @has_permissions(*READ_ROLES)
    def get(self, request: Request, workspace_id: str):
        return result.success(_serializer(request, workspace_id).list(
            request.query_params,
            request.query_params.get('current_page', 1),
            request.query_params.get('page_size', 20),
        ))

    class Operate(APIView):
        authentication_classes = [TokenAuth]

        @extend_schema(
            methods=['GET'], description=_('Get opportunity record'), summary=_('Get opportunity record'),
            operation_id=_('Get opportunity record'), parameters=OpportunityRecordAPI.get_parameters(),
            responses=OpportunityRecordAPI.get_response(), tags=[_('Opportunity')],
        )
        @has_permissions(*READ_ROLES)
        def get(self, request: Request, workspace_id: str, record_id: str):
            return result.success(_serializer(request, workspace_id, record_id).one())

    class Status(APIView):
        authentication_classes = [TokenAuth]

        @extend_schema(
            methods=['PUT'], description=_('Update opportunity follow-up status'),
            summary=_('Update opportunity follow-up status'), operation_id=_('Update opportunity follow-up status'),
            parameters=OpportunityRecordAPI.get_parameters(), request=OpportunityRecordAPI.get_request(),
            responses=OpportunityRecordAPI.get_response(), tags=[_('Opportunity')],
        )
        @has_permissions(*READ_ROLES)
        def put(self, request: Request, workspace_id: str, record_id: str):
            return result.success(_serializer(request, workspace_id, record_id).update_status(request.data))
