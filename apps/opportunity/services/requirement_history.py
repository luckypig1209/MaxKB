# coding=utf-8
"""需求画像不可变版本记录。"""
from copy import deepcopy

from django.db import transaction
from django.db.models import QuerySet

from opportunity.models import OpportunityAnalysis, RequirementProfileSource, RequirementProfileVersion
from opportunity.serializers.common import model_time


def save_requirement_profile_version(
    analysis: OpportunityAnalysis,
    profile: dict,
    source: str,
    operator_user_id: str,
) -> tuple[RequirementProfileVersion, bool]:
    """保存变化后的画像；相同画像重试时复用最新版本。"""
    if source not in RequirementProfileSource.values:
        source = RequirementProfileSource.INITIAL
    with transaction.atomic():
        locked = QuerySet(OpportunityAnalysis).select_for_update().get(id=analysis.id)
        latest = QuerySet(RequirementProfileVersion).filter(analysis=locked).order_by('-version').first()
        snapshot = deepcopy(profile or {})
        if latest is not None and latest.profile == snapshot:
            if locked.requirement_profile != snapshot:
                locked.requirement_profile = snapshot
                locked.save(update_fields=['requirement_profile', 'update_time'])
            analysis.requirement_profile = snapshot
            return latest, False
        version = (latest.version if latest else 0) + 1
        locked.requirement_profile = snapshot
        locked.save(update_fields=['requirement_profile', 'update_time'])
        item = RequirementProfileVersion.objects.create(
            workspace_id=locked.workspace_id,
            analysis=locked,
            version=version,
            source=source,
            clarification_round=len(locked.clarification_history or []),
            profile=snapshot,
            operator_user_id=str(operator_user_id),
        )
        analysis.requirement_profile = snapshot
        return item, True


def requirement_version_to_dict(item: RequirementProfileVersion, include_profile=True) -> dict:
    data = {
        'id': str(item.id),
        'version': item.version,
        'source': item.source,
        'clarification_round': item.clarification_round,
        'operator_user_id': item.operator_user_id,
        'create_time': model_time(item.create_time),
    }
    if include_profile:
        data['profile'] = item.profile or {}
    return data
