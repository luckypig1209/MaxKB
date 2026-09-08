# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： state_machine.py
    @date：2026/9/3
    @desc: 分析任务状态机
"""
from opportunity.models import AnalysisStatus

ALLOWED_TRANSITIONS = {
    AnalysisStatus.DRAFT: {AnalysisStatus.ANALYZING, AnalysisStatus.CLOSED},
    AnalysisStatus.ANALYZING: {
        AnalysisStatus.NEED_CLARIFICATION,
        AnalysisStatus.FAILED,
        AnalysisStatus.WAITING_CONFIRMATION,
        AnalysisStatus.CLOSED,
    },
    AnalysisStatus.NEED_CLARIFICATION: {AnalysisStatus.ANALYZING, AnalysisStatus.CLOSED},
    AnalysisStatus.FAILED: {AnalysisStatus.ANALYZING, AnalysisStatus.CLOSED},
    AnalysisStatus.WAITING_CONFIRMATION: {AnalysisStatus.CONFIRMED, AnalysisStatus.CLOSED},
    AnalysisStatus.CONFIRMED: set(),
    AnalysisStatus.CLOSED: set(),
}


def can_transit(current: str, target: str) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, set())


def assert_transit(current: str, target: str):
    from common.exception.app_exception import AppApiException
    if not can_transit(current, target):
        raise AppApiException(500, f'非法状态迁移: {current} -> {target}')
