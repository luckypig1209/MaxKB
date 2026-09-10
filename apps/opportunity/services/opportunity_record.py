# coding=utf-8
"""商机台账的快照、同步和跟进状态服务。"""
from copy import deepcopy

from common.exception.app_exception import AppApiException
from django.db import transaction
from django.utils import timezone
from opportunity.models import (
    DecisionAction,
    OpportunityAnalysis,
    OpportunityFollowUpStatus,
    OpportunityRecord,
    OpportunityReport,
)
from opportunity.services.report import record_audit

FOLLOW_UP_TRANSITIONS = {
    OpportunityFollowUpStatus.PENDING: {
        OpportunityFollowUpStatus.FOLLOWING,
        OpportunityFollowUpStatus.TRANSFERRED,
        OpportunityFollowUpStatus.CLOSED,
    },
    OpportunityFollowUpStatus.FOLLOWING: {
        OpportunityFollowUpStatus.TRANSFERRED,
        OpportunityFollowUpStatus.CLOSED,
    },
    OpportunityFollowUpStatus.TRANSFERRED: {
        OpportunityFollowUpStatus.FOLLOWING,
        OpportunityFollowUpStatus.CLOSED,
    },
    OpportunityFollowUpStatus.CLOSED: set(),
}


def _candidate_for_analysis(analysis: OpportunityAnalysis):
    snapshot = analysis.result_snapshot or {}
    candidates = snapshot.get('candidates') or []
    confirmed_code = analysis.confirmed_product_code
    if confirmed_code:
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get('product_code') == confirmed_code:
                return candidate
    return None


def _report_reference(report):
    if report is None:
        return None
    return {
        'id': str(report.id),
        'report_no': report.report_no,
        'version': report.version,
        'create_time': report.create_time.isoformat() if report.create_time else None,
    }


def build_decision_snapshot(analysis: OpportunityAnalysis, report=None):
    """Build an immutable, self-contained view of the accepted analysis result."""
    if report is None:
        report = OpportunityReport.objects.filter(analysis=analysis, is_current=True).first()
    candidate = _candidate_for_analysis(analysis)
    candidate_copy = deepcopy(candidate or {})
    cases = deepcopy(candidate_copy.get('case_references') or [])
    evidence = []
    for match in candidate_copy.get('match_items') or []:
        if isinstance(match, dict):
            evidence.extend(deepcopy(match.get('evidence') or []))
    return {
        'schema_version': '1.0',
        'analysis_id': str(analysis.id),
        'original_requirement': analysis.original_requirement,
        'requirement_profile': deepcopy(analysis.requirement_profile or {}),
        'confirmed_product_code': analysis.confirmed_product_code,
        # Keep both names explicit: ``candidate`` is convenient for clients while
        # ``selected_candidate`` documents that this is the accepted product.
        'candidate': candidate_copy,
        'selected_candidate': deepcopy(candidate_copy),
        'cases': cases,
        'evidence': evidence,
        'report': _report_reference(report),
        'report_no': report.report_no if report else None,
        'report_version': report.version if report else None,
        'result': deepcopy(analysis.result_snapshot or {}),
    }


def _record_fields(analysis, action, snapshot, accepted_at):
    candidate = snapshot.get('candidate') or {}
    department = candidate.get('department') if isinstance(candidate.get('department'), dict) else {}
    return {
        'workspace_id': analysis.workspace_id,
        'owner_user_id': str(analysis.user_id),
        'decision_action': action,
        'product_code': str(candidate.get('product_code') or analysis.confirmed_product_code or ''),
        'product_name': str(candidate.get('product_name') or ''),
        'department_code': str(department.get('owner_department_code') or ''),
        'department_name': str(department.get('owner_department_name') or ''),
        'accepted_at': accepted_at,
        'decision_snapshot': snapshot,
    }


def sync_opportunity_record(analysis: OpportunityAnalysis, action, report=None):
    """Create or refresh the record for an accepted analysis, idempotently.

    Existing follow-up state and notes are deliberately omitted from ``defaults``
    so a later synchronization cannot erase user-maintained follow-up data.
    """
    action = str(action)
    if action not in (DecisionAction.ACCEPT, DecisionAction.RESELECT):
        raise AppApiException(500, '只有接受或改选产品后才能生成商机记录')
    if report is None:
        report = OpportunityReport.objects.filter(analysis=analysis, is_current=True).first()
    snapshot = build_decision_snapshot(analysis, report=report)
    existing = OpportunityRecord.objects.filter(analysis=analysis).first()
    accepted_at = existing.accepted_at if existing and existing.accepted_at else timezone.now()
    defaults = _record_fields(analysis, action, snapshot, accepted_at)
    if existing is None:
        defaults.update({
            'status': OpportunityFollowUpStatus.PENDING,
            'latest_note': '',
        })
    record, _ = OpportunityRecord.objects.update_or_create(analysis=analysis, defaults=defaults)
    return record


def change_follow_up_status(record: OpportunityRecord, target, note='', operator_user_id=None):
    """Apply the small follow-up state machine and emit an audit event."""
    target = str(target)
    valid_statuses = {value for value, _ in OpportunityFollowUpStatus.choices}
    if target not in valid_statuses:
        raise AppApiException(500, '不支持的商机跟进状态')
    if note is not None and len(note) > 1024:
        raise AppApiException(500, '跟进说明不能超过 1024 个字符')
    with transaction.atomic():
        locked = OpportunityRecord.objects.select_for_update().select_related('analysis').get(id=record.id)
        before = locked.status
        same_status = target == before
        if not same_status and target not in FOLLOW_UP_TRANSITIONS.get(before, set()):
            raise AppApiException(500, f'非法商机跟进状态迁移: {before} -> {target}')
        note_changed = note is not None and note != locked.latest_note
        if same_status and not note_changed:
            return locked
        locked.status = target
        if note is not None:
            locked.latest_note = note
        locked.save(update_fields=['status', 'latest_note', 'update_time'])
        audit_action = 'OPPORTUNITY_NOTE_UPDATED' if same_status else 'OPPORTUNITY_STATUS_CHANGED'
        record_audit(locked.analysis, audit_action, operator_user_id, {
            'before': before,
            'after': target,
            'note': note if note is not None else locked.latest_note,
        })
        return locked
