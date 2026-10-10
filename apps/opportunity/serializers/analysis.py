# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： analysis.py
    @date：2026/9/3
    @desc: 分析任务接口序列化
"""
from django.db.models import QuerySet
from rest_framework import serializers

from common.db.search import page_search
from common.exception.app_exception import AppApiException
from opportunity.models import AnalysisStatus, OpportunityAnalysis, OpportunityReport, RequirementProfileVersion
from opportunity.serializers.common import model_time
from opportunity.services.analysis import (
    confirm_analysis,
    create_analysis,
    retry_analysis,
    submit_clarification,
)
from opportunity.services.progress import normalize_progress
from opportunity.services.requirement_history import requirement_version_to_dict


class AnalysisCreateSerializer(serializers.Serializer):
    idempotency_key = serializers.CharField(required=True, max_length=128)
    requirement = serializers.CharField(required=True, max_length=20000)


class ClarificationSerializer(serializers.Serializer):
    answer = serializers.CharField(required=True, max_length=10000)


class ConfirmSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=(
        'CONFIRM', 'CLOSE', 'ACCEPT', 'RESELECT', 'REJECT', 'NO_MATCH', 'CANCEL',
    ))
    product_code = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=64)
    reason = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=1024)


class AnalysisQuerySerializer(serializers.Serializer):
    current_page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=100, default=20)
    status = serializers.ChoiceField(choices=AnalysisStatus.choices, required=False)
    create_user = serializers.CharField(required=False, allow_blank=False)
    department_code = serializers.CharField(required=False, allow_blank=False)
    start_time = serializers.DateTimeField(required=False)
    end_time = serializers.DateTimeField(required=False)

    def validate(self, attrs):
        if attrs.get('start_time') and attrs.get('end_time') and attrs['start_time'] > attrs['end_time']:
            raise serializers.ValidationError('开始时间不能晚于结束时间')
        return attrs


def analysis_to_dict(analysis: OpportunityAnalysis, detail=True):
    data = {
        'id': str(analysis.id),
        'workspace_id': analysis.workspace_id,
        'user_id': analysis.user_id,
        'status': analysis.status,
        'original_requirement': analysis.original_requirement,
        'confirmed_product_code': analysis.confirmed_product_code,
        'error_code': analysis.error_code,
        'error_message': analysis.error_message,
        'runtime_ms': analysis.runtime_ms,
        'create_time': model_time(analysis.create_time),
        'update_time': model_time(analysis.update_time),
    }
    if detail:
        report = QuerySet(OpportunityReport).filter(analysis=analysis, is_current=True).first()
        latest_profile = QuerySet(RequirementProfileVersion).filter(analysis=analysis).order_by('-version').first()
        snapshot = dict(analysis.result_snapshot or {})
        if snapshot.get('progress'):
            snapshot = {**snapshot, 'progress': normalize_progress(snapshot.get('progress'))}
        data.update({
            'requirement_profile': analysis.requirement_profile or {},
            'clarification_history': analysis.clarification_history or [],
            'clarification_questions': analysis.clarification_questions or [],
            'result_snapshot': snapshot,
            'model_snapshot': analysis.model_snapshot or {},
            'knowledge_snapshot': analysis.knowledge_snapshot or {},
            'rule_version': analysis.rule_version,
            'requirement_profile_version': latest_profile.version if latest_profile else None,
            'report': {
                'id': str(report.id),
                'report_no': report.report_no,
                'version': report.version,
                'create_time': model_time(report.create_time),
            } if report else None,
            'feedback': [
                {
                    'id': str(item.id),
                    'action': item.action,
                    'product_code': item.product_code,
                    'reason': item.reason,
                    'operator_user_id': item.operator_user_id,
                    'create_time': model_time(item.create_time),
                }
                for item in analysis.feedback_records.all().order_by('create_time')
            ],
            'audit_logs': [
                {
                    'id': str(item.id),
                    'action': item.action,
                    'operator_user_id': item.operator_user_id,
                    'detail': item.detail or {},
                    'create_time': model_time(item.create_time),
                }
                for item in analysis.audit_logs.all().order_by('create_time')
            ],
        })
    return data


class AnalysisSerializer(serializers.Serializer):
    workspace_id = serializers.CharField(required=True)
    user_id = serializers.CharField(required=True)
    is_manager = serializers.BooleanField(required=False, default=False)

    def insert(self, instance: dict):
        self.is_valid(raise_exception=True)
        serializer = AnalysisCreateSerializer(data=instance)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        analysis = create_analysis(
            self.validated_data['workspace_id'],
            self.validated_data['user_id'],
            data['idempotency_key'],
            data['requirement'],
        )
        return {'id': str(analysis.id), 'status': analysis.status}

    def list(self, query: dict, current_page=1, page_size=20):
        self.is_valid(raise_exception=True)
        filter_serializer = AnalysisQuerySerializer(data={
            **query,
            'current_page': query.get('current_page', current_page),
            'page_size': query.get('page_size', page_size),
        })
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data
        workspace_id = self.validated_data['workspace_id']
        queryset = QuerySet(OpportunityAnalysis).filter(workspace_id=workspace_id).order_by('-create_time')
        if not self.validated_data.get('is_manager'):
            queryset = queryset.filter(user_id=self.validated_data['user_id'])
        status = filters.get('status')
        if status:
            queryset = queryset.filter(status=status)
        create_user = filters.get('create_user')
        if create_user:
            queryset = queryset.filter(user_id=create_user)
        department_code = filters.get('department_code')
        if department_code:
            queryset = queryset.filter(result_snapshot__candidates__contains=[{
                'department': {'owner_department_code': department_code},
            }])
        if filters.get('start_time'):
            queryset = queryset.filter(create_time__gte=filters['start_time'])
        if filters.get('end_time'):
            queryset = queryset.filter(create_time__lte=filters['end_time'])
        return page_search(
            filters['current_page'], filters['page_size'], queryset,
            lambda item: analysis_to_dict(item, detail=False),
        )


class AnalysisOperateSerializer(serializers.Serializer):
    workspace_id = serializers.CharField(required=True)
    analysis_id = serializers.UUIDField(required=True)
    user_id = serializers.CharField(required=False)
    is_manager = serializers.BooleanField(required=False, default=False)

    def _get(self) -> OpportunityAnalysis:
        self.is_valid(raise_exception=True)
        queryset = QuerySet(OpportunityAnalysis).filter(
            workspace_id=self.validated_data['workspace_id'],
            id=self.validated_data['analysis_id'],
        )
        if not self.validated_data.get('is_manager'):
            queryset = queryset.filter(user_id=self.validated_data.get('user_id'))
        analysis = queryset.first()
        if analysis is None:
            raise AppApiException(403, '无权访问该分析任务或任务不存在')
        return analysis

    def one(self):
        return analysis_to_dict(self._get())

    def requirement_versions(self):
        analysis = self._get()
        return [
            requirement_version_to_dict(item)
            for item in QuerySet(RequirementProfileVersion).filter(analysis=analysis).order_by('-version')
        ]

    def clarify(self, instance: dict):
        serializer = ClarificationSerializer(data=instance)
        serializer.is_valid(raise_exception=True)
        analysis = self._get()
        if analysis.status != AnalysisStatus.NEED_CLARIFICATION:
            raise AppApiException(500, '当前状态不允许提交补充信息')
        return analysis_to_dict(submit_clarification(analysis, serializer.validated_data['answer']))

    def retry(self):
        analysis = self._get()
        if analysis.status != AnalysisStatus.FAILED:
            raise AppApiException(500, '仅失败任务可以重试')
        return analysis_to_dict(retry_analysis(analysis))

    def confirm(self, instance: dict):
        serializer = ConfirmSerializer(data=instance)
        serializer.is_valid(raise_exception=True)
        analysis = self._get()
        data = serializer.validated_data
        return analysis_to_dict(confirm_analysis(
            analysis,
            data['action'],
            product_code=data.get('product_code'),
            reason=data.get('reason'),
            user_id=self.validated_data.get('user_id'),
        ))
