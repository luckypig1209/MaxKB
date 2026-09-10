# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： analysis.py
    @date：2026/9/3
    @desc: 商机分析编排
"""
import logging
import time

from common.exception.app_exception import AppApiException
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from opportunity.models import (
    AnalysisStatus,
    DecisionAction,
    OpportunityAnalysis,
    OpportunitySetting,
    RequirementProfileSource,
)
from opportunity.services.candidate_aggregation import aggregate_by_product, build_search_queries
from opportunity.services.case_enhancement import run_case_enhancement
from opportunity.services.department import resolve_department
from opportunity.services.knowledge_retrieval import retrieve_product_paragraphs
from opportunity.services.matching import build_candidate_result, match_product, rank_candidates
from opportunity.services.opportunity_record import sync_opportunity_record
from opportunity.services.prompts import MATCH_PROMPT_VERSION, REQUIREMENT_PROMPT_VERSION
from opportunity.services.report import create_report_snapshot, record_audit, record_feedback
from opportunity.services.requirement_extraction import extract_requirement_profile, merge_clarification
from opportunity.services.requirement_history import save_requirement_profile_version
from opportunity.services.scoring import RULE_VERSION
from opportunity.services.state_machine import assert_transit

logger = logging.getLogger('maxkb')


def get_setting(workspace_id) -> OpportunitySetting:
    setting = QuerySet(OpportunitySetting).filter(workspace_id=workspace_id).first()
    if setting is None:
        setting = OpportunitySetting(workspace_id=workspace_id)
        setting.save()
    return setting


def _transit(analysis: OpportunityAnalysis, target: str):
    assert_transit(analysis.status, target)
    analysis.status = target


def _sanitize_error(message: str) -> str:
    text = (message or '分析失败')[:500]
    for token in ('sk-', 'api_key', 'apikey', 'token', 'password', 'secret'):
        if token in text.lower():
            return '分析失败'
    return text


PROGRESS_STEPS = (
    ('PARSE', '解析客户需求'),
    ('RETRIEVE', '检索产品知识库'),
    ('MATCH', '对照产品资料匹配'),
    ('CASE', '检索相似案例'),
    ('RANK', '评分排序并生成结论'),
)


def _progress_payload(current_key: str, detail: str = '', done: bool = False) -> dict:
    keys = [item[0] for item in PROGRESS_STEPS]
    current_index = keys.index(current_key) if current_key in keys else 0
    steps = []
    for index, (key, label) in enumerate(PROGRESS_STEPS):
        if done or index < current_index:
            status = 'done'
        elif index == current_index:
            status = 'active'
        else:
            status = 'pending'
        steps.append({'key': key, 'label': label, 'status': status})
    return {
        'current': 'DONE' if done else current_key,
        'detail': detail,
        'index': len(PROGRESS_STEPS) if done else current_index + 1,
        'total': len(PROGRESS_STEPS),
        'steps': steps,
    }


def set_progress(analysis: OpportunityAnalysis, current_key: str, detail: str = '', done: bool = False):
    snapshot = dict(analysis.result_snapshot or {})
    snapshot['progress'] = _progress_payload(current_key, detail, done=done)
    analysis.result_snapshot = snapshot
    analysis.save(update_fields=['result_snapshot', 'update_time'])


def run_analysis(analysis_id):
    started = time.time()
    with transaction.atomic():
        analysis = QuerySet(OpportunityAnalysis).select_for_update(skip_locked=True).filter(id=analysis_id).first()
        if analysis is None:
            return
        if analysis.status not in (AnalysisStatus.DRAFT, AnalysisStatus.ANALYZING, AnalysisStatus.NEED_CLARIFICATION,
                                   AnalysisStatus.FAILED):
            return
        if analysis.status != AnalysisStatus.ANALYZING:
            _transit(analysis, AnalysisStatus.ANALYZING)
            analysis.save(update_fields=['status', 'update_time'])
    try:
        _execute(QuerySet(OpportunityAnalysis).get(id=analysis_id))
        finished = QuerySet(OpportunityAnalysis).filter(id=analysis_id).first()
        if finished:
            finished.runtime_ms = int((time.time() - started) * 1000)
            finished.save(update_fields=['runtime_ms', 'update_time'])
    except AppApiException as exc:
        analysis.refresh_from_db(fields=['status'])
        if analysis.status == AnalysisStatus.CLOSED:
            return
        analysis.error_code = str(exc.code)
        analysis.error_message = _sanitize_error(exc.message)
        analysis.status = AnalysisStatus.FAILED
        analysis.runtime_ms = int((time.time() - started) * 1000)
        analysis.save()
        logger.warning('analysis failed id=%s code=%s', analysis.id, exc.code)
    except Exception as exc:
        analysis.refresh_from_db(fields=['status'])
        if analysis.status == AnalysisStatus.CLOSED:
            return
        analysis.error_code = 'ANALYSIS_FAILED'
        analysis.error_message = _sanitize_error(str(exc))
        analysis.status = AnalysisStatus.FAILED
        analysis.runtime_ms = int((time.time() - started) * 1000)
        analysis.save()
        logger.exception('analysis unexpected error id=%s', analysis.id)


def _execute(analysis: OpportunityAnalysis):
    setting = get_setting(analysis.workspace_id)
    if not setting.llm_model_id or not setting.product_knowledge_id:
        raise AppApiException(500, '请先配置分析模型和产品知识库')
    set_progress(analysis, 'PARSE', '正在把客户需求拆成可匹配的能力项')
    extra_context = {'clarification_history': analysis.clarification_history or []}
    if analysis.requirement_profile and analysis.clarification_history:
        profile = merge_clarification(
            analysis.requirement_profile,
            analysis.clarification_history[-1],
            analysis.original_requirement,
        )
    else:
        profile = extract_requirement_profile(
            analysis.workspace_id,
            setting.llm_model_id,
            analysis.original_requirement,
            extra_context=extra_context,
        )
    profile_version, version_created = save_requirement_profile_version(
        analysis,
        profile,
        RequirementProfileSource.CLARIFICATION if analysis.clarification_history else RequirementProfileSource.INITIAL,
        analysis.user_id,
    )
    if version_created:
        record_audit(analysis, 'REQUIREMENT_PROFILE_VERSIONED', analysis.user_id, {
            'version': profile_version.version,
            'source': profile_version.source,
            'clarification_round': profile_version.clarification_round,
        })
    analysis.clarification_questions = profile.get('clarification_questions') or []
    analysis.requirement_profile = profile
    analysis.model_snapshot = {
        'llm_model_id': str(setting.llm_model_id),
        'rerank_model_id': str(setting.rerank_model_id) if setting.rerank_model_id else None,
        'prompt_version': {
            'requirement': REQUIREMENT_PROMPT_VERSION,
            'match': MATCH_PROMPT_VERSION,
        },
    }
    analysis.knowledge_snapshot = {
        'product_knowledge_id': str(setting.product_knowledge_id),
        'case_knowledge_id': str(setting.case_knowledge_id) if setting.case_knowledge_id else None,
        'search_mode': setting.search_mode,
        'top_n': setting.top_n,
        'similarity': setting.similarity,
        'captured_at': timezone.now().isoformat(),
    }
    analysis.rule_version = RULE_VERSION
    should_clarify = bool(analysis.clarification_questions) and not analysis.clarification_history
    if should_clarify:
        analysis.refresh_from_db(fields=['status'])
        if analysis.status == AnalysisStatus.CLOSED:
            return
        _transit(analysis, AnalysisStatus.NEED_CLARIFICATION)
        analysis.result_snapshot = {
            'candidates': [],
            'excluded': [],
            'summary': '需要补充关键参数后再进行产品匹配',
            'progress': _progress_payload('PARSE', '需求已拆解，等待补充关键参数', done=False),
        }
        analysis.result_snapshot['progress']['steps'][0]['status'] = 'done'
        analysis.result_snapshot['progress']['current'] = 'PARSE'
        analysis.result_snapshot['progress']['detail'] = '需求已拆解，请补充下面的关键参数后再继续匹配产品'
        analysis.save()
        record_audit(analysis, 'CLARIFICATION_REQUIRED', analysis.user_id, {
            'question_count': len(analysis.clarification_questions),
        })
        return

    set_progress(analysis, 'RETRIEVE', '正在产品知识库中检索相关资料')
    queries = build_search_queries(profile)
    if analysis.original_requirement not in queries:
        queries.insert(0, analysis.original_requirement)
    hits = []
    for query in queries:
        hits.extend(retrieve_product_paragraphs(
            workspace_id=analysis.workspace_id,
            knowledge_id=setting.product_knowledge_id,
            question=query,
            search_mode=setting.search_mode,
            top_n=setting.top_n,
            similarity=setting.similarity,
        ))
    grouped = aggregate_by_product(analysis.workspace_id, hits)
    candidates = []
    products = list(grouped.values())
    for index, item in enumerate(products, start=1):
        set_progress(
            analysis,
            'MATCH',
            f'正在对照「{item["product"].name}」的产品资料（{index}/{len(products)}）',
        )
        match_items = match_product(
            analysis.workspace_id,
            setting.llm_model_id,
            item['product'],
            profile.get('requirements') or [],
            item['evidence'],
        )
        department = resolve_department(item['product'])
        candidates.append(build_candidate_result(
            item['product'],
            profile.get('requirements') or [],
            match_items,
            department,
            max_candidates=setting.max_candidates,
        ))
    top, excluded = rank_candidates(candidates, max_candidates=min(3, setting.max_candidates or 5))
    set_progress(analysis, 'CASE', '正在检索相似落地案例')
    top, case_enhancement = run_case_enhancement(
        workspace_id=analysis.workspace_id,
        knowledge_id=setting.case_knowledge_id,
        profile=profile,
        candidates=top,
        requirements=profile.get('requirements') or [],
        original_requirement=analysis.original_requirement,
        search_mode=setting.search_mode,
        top_n=setting.top_n,
        similarity=setting.similarity,
        user_id=analysis.user_id,
    )
    set_progress(analysis, 'RANK', '正在评分排序并生成结论')
    top, _ = rank_candidates(top, max_candidates=min(3, setting.max_candidates or 5))
    case_references = [
        {**reference, 'product_code': candidate.get('product_code')}
        for candidate in top
        for reference in candidate.get('case_references') or []
    ]
    analysis.knowledge_snapshot = {
        **analysis.knowledge_snapshot,
        'case_enhancement': case_enhancement,
    }
    summary = '已完成产品事实匹配' if top else '没有合适的候选产品'
    if case_enhancement.get('status') == 'APPLIED':
        summary += '，并补充了相似案例参考'
    elif case_enhancement.get('status') == 'DEGRADED':
        summary += '；案例参考暂不可用'
    analysis.result_snapshot = {
        'candidates': top,
        'excluded': excluded,
        'summary': summary,
        'case_references': case_references,
        'case_enhancement': case_enhancement,
        'progress': _progress_payload('RANK', '分析完成', done=True),
    }
    analysis.error_code = None
    analysis.error_message = None
    analysis.refresh_from_db(fields=['status'])
    if analysis.status == AnalysisStatus.CLOSED:
        return
    _transit(analysis, AnalysisStatus.WAITING_CONFIRMATION)
    analysis.save()
    create_report_snapshot(analysis, analysis.user_id)


def create_analysis(workspace_id, user_id, idempotency_key, requirement):
    if not (requirement or '').strip():
        raise AppApiException(500, '需求不能为空')
    analysis, created = OpportunityAnalysis.objects.get_or_create(
        workspace_id=workspace_id,
        user_id=str(user_id),
        idempotency_key=idempotency_key,
        defaults={
            'status': AnalysisStatus.ANALYZING,
            'original_requirement': requirement.strip(),
        },
    )
    if not created:
        return analysis
    record_audit(analysis, 'ANALYSIS_CREATED', user_id, {
        'idempotency_key': idempotency_key,
    })
    from opportunity.tasks import analyze_opportunity
    analyze_opportunity.delay(str(analysis.id))
    return analysis


def submit_clarification(analysis: OpportunityAnalysis, answer: str):
    assert_transit(analysis.status, AnalysisStatus.ANALYZING)
    history = list(analysis.clarification_history or [])
    history.append({
        'answer': answer,
        'questions': analysis.clarification_questions or [],
        'submitted_at': timezone.now().isoformat(),
    })
    analysis.clarification_history = history
    analysis.status = AnalysisStatus.ANALYZING
    analysis.error_code = None
    analysis.error_message = None
    analysis.save()
    record_audit(analysis, 'CLARIFICATION_SUBMITTED', analysis.user_id, {
        'answer_length': len(answer or ''),
    })
    from opportunity.tasks import analyze_opportunity
    analyze_opportunity.delay(str(analysis.id))
    return analysis


def retry_analysis(analysis: OpportunityAnalysis):
    assert_transit(analysis.status, AnalysisStatus.ANALYZING)
    analysis.status = AnalysisStatus.ANALYZING
    analysis.error_code = None
    analysis.error_message = None
    analysis.save(update_fields=['status', 'error_code', 'error_message', 'update_time'])
    record_audit(analysis, 'ANALYSIS_RETRIED', analysis.user_id)
    from opportunity.tasks import analyze_opportunity
    analyze_opportunity.delay(str(analysis.id))
    return analysis


def _apply_decision(analysis: OpportunityAnalysis, action: str, product_code=None, reason=None, user_id=None):
    normalized = {'CONFIRM': DecisionAction.ACCEPT, 'CLOSE': DecisionAction.CANCEL}.get(action, action)
    if normalized not in DecisionAction.values:
        raise AppApiException(500, '不支持的商机决策操作')
    if normalized in (DecisionAction.REJECT, DecisionAction.NO_MATCH) and analysis.status != AnalysisStatus.WAITING_CONFIRMATION:
        raise AppApiException(500, '仅待确认商机可以驳回或标记无匹配')
    if normalized in (DecisionAction.REJECT, DecisionAction.NO_MATCH, DecisionAction.CANCEL):
        assert_transit(analysis.status, AnalysisStatus.CLOSED)
        analysis.status = AnalysisStatus.CLOSED
        analysis.result_snapshot = {
            **(analysis.result_snapshot or {}),
            'decision': {'action': normalized, 'reason': reason or '', 'product_code': None},
        }
        analysis.save()
        record_feedback(analysis, normalized, user_id, reason=reason)
        create_report_snapshot(analysis, user_id)
        return analysis
    assert_transit(analysis.status, AnalysisStatus.CONFIRMED)
    snapshot = analysis.result_snapshot or {}
    codes = {item.get('product_code') for item in snapshot.get('candidates') or []}
    if product_code not in codes:
        raise AppApiException(500, '只能确认当前候选产品')
    analysis.confirmed_product_code = product_code
    analysis.status = AnalysisStatus.CONFIRMED
    analysis.result_snapshot = {
        **snapshot,
        'confirm_reason': reason or '',
        'confirmed_at': timezone.now().isoformat(),
        'decision': {'action': normalized, 'reason': reason or '', 'product_code': product_code},
    }
    analysis.save()
    record_feedback(analysis, normalized, user_id, product_code=product_code, reason=reason)
    report = create_report_snapshot(analysis, user_id)
    sync_opportunity_record(analysis, normalized, report=report)
    return analysis


def confirm_analysis(analysis: OpportunityAnalysis, action: str, product_code=None, reason=None, user_id=None):
    with transaction.atomic():
        locked = QuerySet(OpportunityAnalysis).select_for_update().get(id=analysis.id)
        return _apply_decision(
            locked, action, product_code=product_code, reason=reason, user_id=user_id,
        )
