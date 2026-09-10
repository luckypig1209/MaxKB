# coding=utf-8
"""商机台账查询、详情与跟进状态序列化。"""
from common.db.search import page_search
from common.exception.app_exception import AppApiException
from django.db.models import Q, QuerySet
from opportunity.models import OpportunityFollowUpStatus, OpportunityRecord
from opportunity.serializers.common import model_time
from opportunity.services.opportunity_record import change_follow_up_status
from rest_framework import serializers


class OpportunityRecordQuerySerializer(serializers.Serializer):
    current_page = serializers.IntegerField(required=False, min_value=1, default=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=100, default=20)
    status = serializers.ChoiceField(choices=OpportunityFollowUpStatus.choices, required=False)
    product_code = serializers.CharField(required=False, allow_blank=False)
    department_code = serializers.CharField(required=False, allow_blank=False)
    start_time = serializers.DateTimeField(required=False)
    end_time = serializers.DateTimeField(required=False)

    def validate(self, attrs):
        if attrs.get('start_time') and attrs.get('end_time') and attrs['start_time'] > attrs['end_time']:
            raise serializers.ValidationError('开始时间不能晚于结束时间')
        return attrs


class OpportunityRecordStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=OpportunityFollowUpStatus.choices, required=True)
    note = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=1024)


def _report_from_snapshot(snapshot):
    report = snapshot.get('report') if isinstance(snapshot, dict) else None
    return report if isinstance(report, dict) else None


def record_to_dict(record: OpportunityRecord, detail=True):
    snapshot = record.decision_snapshot if isinstance(record.decision_snapshot, dict) else {}
    data = {
        'id': str(record.id),
        'workspace_id': record.workspace_id,
        'analysis_id': str(record.analysis_id),
        'owner_user_id': record.owner_user_id,
        'decision_action': record.decision_action,
        'product_code': record.product_code,
        'product_name': record.product_name,
        'department_code': record.department_code,
        'department_name': record.department_name,
        'status': record.status,
        'accepted_at': model_time(record.accepted_at),
        'latest_note': record.latest_note,
        'original_requirement': snapshot.get('original_requirement') or '',
        'create_time': model_time(record.create_time),
        'update_time': model_time(record.update_time),
    }
    if detail:
        data.update({
            'decision_snapshot': snapshot,
            'requirement_profile': snapshot.get('requirement_profile') or {},
            'candidate': snapshot.get('candidate') or snapshot.get('selected_candidate') or {},
            'cases': snapshot.get('cases') or [],
            'evidence': snapshot.get('evidence') or [],
            'report': _report_from_snapshot(snapshot),
        })
    return data


class OpportunityRecordSerializer(serializers.Serializer):
    workspace_id = serializers.CharField(required=True)
    record_id = serializers.UUIDField(required=False)
    user_id = serializers.CharField(required=True)
    is_manager = serializers.BooleanField(required=False, default=False)

    def _base_queryset(self):
        self.is_valid(raise_exception=True)
        queryset = QuerySet(OpportunityRecord).filter(workspace_id=self.validated_data['workspace_id'])
        if not self.validated_data.get('is_manager'):
            # The owner boundary is always supplied by the authenticated request context,
            # never by a query parameter.
            queryset = queryset.filter(owner_user_id=self.validated_data['user_id'])
        return queryset

    def _get(self):
        queryset = self._base_queryset()
        record_id = self.validated_data.get('record_id')
        queryset = queryset.filter(id=record_id)
        record = queryset.first()
        if record is None:
            raise AppApiException(403, '无权访问该商机或商机不存在')
        return record

    def list(self, query=None, current_page=1, page_size=20):
        queryset = self._base_queryset().order_by('-accepted_at', '-create_time')
        query = query or {}
        filter_serializer = OpportunityRecordQuerySerializer(data={
            **query,
            'current_page': query.get('current_page', current_page),
            'page_size': query.get('page_size', page_size),
        })
        filter_serializer.is_valid(raise_exception=True)
        filters = filter_serializer.validated_data
        if filters.get('status'):
            queryset = queryset.filter(status=filters['status'])
        if filters.get('product_code'):
            term = filters['product_code']
            queryset = queryset.filter(Q(product_code__icontains=term) | Q(product_name__icontains=term))
        if filters.get('department_code'):
            term = filters['department_code']
            queryset = queryset.filter(Q(department_code__icontains=term) | Q(department_name__icontains=term))
        if filters.get('start_time'):
            queryset = queryset.filter(accepted_at__gte=filters['start_time'])
        if filters.get('end_time'):
            queryset = queryset.filter(accepted_at__lte=filters['end_time'])
        return page_search(
            filters['current_page'], filters['page_size'], queryset,
            lambda item: record_to_dict(item, detail=False),
        )

    def one(self):
        return record_to_dict(self._get(), detail=True)

    def update_status(self, instance: dict):
        serializer = OpportunityRecordStatusSerializer(data=instance)
        serializer.is_valid(raise_exception=True)
        record = self._get()
        updated = change_follow_up_status(
            record,
            serializer.validated_data['status'],
            note=serializer.validated_data.get('note'),
            operator_user_id=self.validated_data.get('user_id'),
        )
        return record_to_dict(updated, detail=True)
