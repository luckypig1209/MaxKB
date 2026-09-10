# coding=utf-8
from datetime import timedelta

from common.exception.app_exception import AppApiException
from django.test import TestCase
from django.utils import timezone
from opportunity.models import (
    AnalysisStatus,
    OpportunityAnalysis,
    OpportunityAuditLog,
    OpportunityFollowUpStatus,
    OpportunityRecord,
)
from opportunity.serializers.record import OpportunityRecordSerializer
from opportunity.services.analysis import confirm_analysis
from opportunity.services.opportunity_record import change_follow_up_status, sync_opportunity_record


def create_confirmable_analysis(user_id='u1', workspace_id='ws-a'):
    return OpportunityAnalysis.objects.create(
        workspace_id=workspace_id,
        user_id=user_id,
        idempotency_key=f'record-{workspace_id}-{user_id}',
        original_requirement='需要统一监控',
        status=AnalysisStatus.WAITING_CONFIRMATION,
        requirement_profile={'business_scenarios': ['监控'], 'requirements': []},
        result_snapshot={
            'summary': '已完成产品事实匹配',
            'candidates': [{
                'product_code': 'P1',
                'product_name': '翼观',
                'score': 88,
                'department': {'owner_department_code': 'D1', 'owner_department_name': '云网运营部'},
                'case_references': [{'case_name': '监控案例'}],
                'match_items': [{'evidence': [{'document_name': '产品手册'}]}],
            }, {
                'product_code': 'P2',
                'product_name': '翼聚',
                'score': 70,
                'department': {},
            }],
        },
    )


class OpportunityRecordServiceTests(TestCase):
    def test_accept_creates_snapshot_and_reselect_keeps_single_record(self):
        analysis = create_confirmable_analysis()
        confirm_analysis(analysis, 'ACCEPT', product_code='P1', user_id='u1')
        record = OpportunityRecord.objects.get(analysis=analysis)
        self.assertEqual(record.product_name, '翼观')
        self.assertEqual(record.department_code, 'D1')
        self.assertEqual(record.decision_snapshot['candidate']['product_code'], 'P1')
        self.assertEqual(record.decision_snapshot['cases'][0]['case_name'], '监控案例')
        record.status = OpportunityFollowUpStatus.FOLLOWING
        record.latest_note = '已联系客户'
        record.save(update_fields=['status', 'latest_note', 'update_time'])
        sync_opportunity_record(analysis, 'ACCEPT')
        record.refresh_from_db()
        self.assertEqual(OpportunityRecord.objects.filter(analysis=analysis).count(), 1)
        self.assertEqual(record.status, OpportunityFollowUpStatus.FOLLOWING)
        self.assertEqual(record.latest_note, '已联系客户')

    def test_reselect_creates_record_for_selected_candidate(self):
        analysis = create_confirmable_analysis(user_id='reselect-user')
        confirm_analysis(analysis, 'RESELECT', product_code='P2', user_id='reselect-user')
        record = OpportunityRecord.objects.get(analysis=analysis)
        self.assertEqual(record.decision_action, 'RESELECT')
        self.assertEqual(record.product_code, 'P2')
        self.assertEqual(record.product_name, '翼聚')

    def test_reject_no_match_and_cancel_do_not_create_record(self):
        for action in ('REJECT', 'NO_MATCH'):
            analysis = create_confirmable_analysis(user_id=f'{action}-user')
            confirm_analysis(analysis, action, user_id=analysis.user_id)
            self.assertFalse(OpportunityRecord.objects.filter(analysis=analysis).exists())
        running = create_confirmable_analysis(user_id='cancel-user')
        running.status = AnalysisStatus.ANALYZING
        running.save(update_fields=['status', 'update_time'])
        confirm_analysis(running, 'CANCEL', user_id='cancel-user')
        self.assertFalse(OpportunityRecord.objects.filter(analysis=running).exists())

    def test_missing_candidate_details_still_creates_readable_record(self):
        analysis = create_confirmable_analysis(user_id='missing-candidate')
        analysis.result_snapshot = {'candidates': []}
        analysis.save(update_fields=['result_snapshot', 'update_time'])
        analysis.confirmed_product_code = 'MISSING'
        analysis.status = AnalysisStatus.CONFIRMED
        analysis.save(update_fields=['confirmed_product_code', 'status', 'update_time'])
        record = sync_opportunity_record(analysis, 'RESELECT')
        self.assertEqual(record.product_code, 'MISSING')
        self.assertEqual(record.product_name, '')
        self.assertEqual(record.department_name, '')

    def test_status_state_machine_and_audit(self):
        analysis = create_confirmable_analysis(user_id='state-user')
        confirm_analysis(analysis, 'ACCEPT', product_code='P1', user_id='state-user')
        record = OpportunityRecord.objects.get(analysis=analysis)
        change_follow_up_status(record, 'FOLLOWING', '开始跟进', 'state-user')
        change_follow_up_status(record, 'CLOSED', '已关闭', 'state-user')
        with self.assertRaises(AppApiException):
            change_follow_up_status(record, 'FOLLOWING', '不得重开', 'state-user')
        self.assertEqual(
            OpportunityAuditLog.objects.filter(analysis=analysis, action='OPPORTUNITY_STATUS_CHANGED').count(), 2,
        )

    def test_same_status_can_update_note_without_fake_status_change(self):
        analysis = create_confirmable_analysis(user_id='note-user')
        confirm_analysis(analysis, 'ACCEPT', product_code='P1', user_id='note-user')
        record = OpportunityRecord.objects.get(analysis=analysis)
        updated = change_follow_up_status(record, 'PENDING', '等待客户反馈', 'note-user')
        self.assertEqual(updated.status, OpportunityFollowUpStatus.PENDING)
        self.assertEqual(updated.latest_note, '等待客户反馈')
        self.assertTrue(
            OpportunityAuditLog.objects.filter(analysis=analysis, action='OPPORTUNITY_NOTE_UPDATED').exists(),
        )
        self.assertFalse(
            OpportunityAuditLog.objects.filter(analysis=analysis, action='OPPORTUNITY_STATUS_CHANGED').exists(),
        )


class OpportunityRecordAccessTests(TestCase):
    def setUp(self):
        own_analysis = create_confirmable_analysis('u1')
        confirm_analysis(own_analysis, 'ACCEPT', product_code='P1', user_id='u1')
        self.own = OpportunityRecord.objects.get(analysis=own_analysis)
        other_analysis = create_confirmable_analysis('u2')
        confirm_analysis(other_analysis, 'ACCEPT', product_code='P1', user_id='u2')
        self.other = OpportunityRecord.objects.get(analysis=other_analysis)

    def test_regular_user_list_and_detail_are_owner_scoped(self):
        serializer = OpportunityRecordSerializer(data={'workspace_id': 'ws-a', 'user_id': 'u1', 'is_manager': False})
        page = serializer.list({}, 1, 20)
        self.assertEqual(page['total'], 1)
        self.assertEqual(page['records'][0]['id'], str(self.own.id))
        denied = OpportunityRecordSerializer(data={
            'workspace_id': 'ws-a', 'record_id': str(self.other.id), 'user_id': 'u1', 'is_manager': False,
        })
        with self.assertRaises(AppApiException):
            denied.one()

    def test_manager_is_scoped_to_workspace_and_filters(self):
        result = OpportunityRecordSerializer(data={'workspace_id': 'ws-a', 'user_id': 'manager', 'is_manager': True}).list({
            'product_code': 'P1',
            'start_time': (timezone.now() - timedelta(minutes=1)).isoformat(),
            'end_time': (timezone.now() + timedelta(minutes=1)).isoformat(),
        }, 1, 20)
        self.assertEqual(result['total'], 2)
        cross = OpportunityRecordSerializer(data={
            'workspace_id': 'ws-b', 'record_id': str(self.own.id), 'user_id': 'manager', 'is_manager': True,
        })
        with self.assertRaises(AppApiException):
            cross.one()

    def test_department_filter_accepts_department_name(self):
        result = OpportunityRecordSerializer(
            data={'workspace_id': 'ws-a', 'user_id': 'manager', 'is_manager': True},
        ).list({'department_code': '云网运营'}, 1, 20)
        self.assertEqual(result['total'], 2)
