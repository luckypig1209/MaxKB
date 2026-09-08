# coding=utf-8
from django.db.models import QuerySet
from rest_framework import serializers

from common.exception.app_exception import AppApiException
from opportunity.models import OpportunityAnalysis, OpportunityReport
from opportunity.services.report import report_to_dict


class ReportSerializer(serializers.Serializer):
    workspace_id = serializers.CharField(required=True)
    analysis_id = serializers.UUIDField(required=True)
    user_id = serializers.CharField(required=True)
    is_manager = serializers.BooleanField(required=False, default=False)

    def _analysis(self):
        self.is_valid(raise_exception=True)
        queryset = QuerySet(OpportunityAnalysis).filter(
            workspace_id=self.validated_data['workspace_id'],
            id=self.validated_data['analysis_id'],
        )
        if not self.validated_data.get('is_manager'):
            queryset = queryset.filter(user_id=self.validated_data['user_id'])
        analysis = queryset.first()
        if analysis is None:
            raise AppApiException(403, '无权访问该商机报告或报告不存在')
        return analysis

    def latest(self):
        analysis = self._analysis()
        report = QuerySet(OpportunityReport).filter(analysis=analysis, is_current=True).first()
        if report is None:
            raise AppApiException(500, '报告尚未生成')
        return report

    def one(self):
        return report_to_dict(self.latest())

    def list(self):
        analysis = self._analysis()
        return [
            report_to_dict(item, include_snapshot=False)
            for item in QuerySet(OpportunityReport).filter(analysis=analysis).order_by('-version')
        ]
