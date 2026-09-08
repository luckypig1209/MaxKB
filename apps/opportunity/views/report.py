# coding=utf-8
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.request import Request
from rest_framework.views import APIView

from common import result
from common.auth import TokenAuth
from common.auth.authentication import has_permissions
from opportunity.api.report import ReportAPI
from opportunity.serializers.report import ReportSerializer
from opportunity.services.report import render_report_html
from opportunity.views.setting import READ_ROLES
from users.serializers.user import is_workspace_manage


def _serializer(request, workspace_id, analysis_id):
    return ReportSerializer(data={
        'workspace_id': workspace_id,
        'analysis_id': analysis_id,
        'user_id': str(request.user.id),
        'is_manager': is_workspace_manage(str(request.user.id), workspace_id),
    })


class ReportView(APIView):
    authentication_classes = [TokenAuth]

    @extend_schema(
        methods=['GET'], summary=_('Get latest opportunity report'), parameters=ReportAPI.get_parameters(),
        responses=ReportAPI.get_response(), tags=[_('Opportunity')],
    )
    @has_permissions(*READ_ROLES)
    def get(self, request: Request, workspace_id: str, analysis_id: str):
        return result.success(_serializer(request, workspace_id, analysis_id).one())

    class Versions(APIView):
        authentication_classes = [TokenAuth]

        @extend_schema(
            methods=['GET'], summary=_('List opportunity report versions'), parameters=ReportAPI.get_parameters(),
            responses=ReportAPI.get_response(), tags=[_('Opportunity')],
        )
        @has_permissions(*READ_ROLES)
        def get(self, request: Request, workspace_id: str, analysis_id: str):
            return result.success(_serializer(request, workspace_id, analysis_id).list())

    class Export(APIView):
        authentication_classes = [TokenAuth]

        @extend_schema(
            methods=['GET'], summary=_('Export opportunity report'), parameters=ReportAPI.get_parameters(),
            responses={(200, 'text/html'): OpenApiTypes.BINARY}, tags=[_('Opportunity')],
        )
        @has_permissions(*READ_ROLES)
        def get(self, request: Request, workspace_id: str, analysis_id: str):
            report = _serializer(request, workspace_id, analysis_id).latest()
            response = HttpResponse(render_report_html(report), content_type='text/html; charset=utf-8')
            response['Content-Disposition'] = f'attachment; filename="{report.report_no}.html"'
            return response
