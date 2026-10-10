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
from opportunity.services.progress import (
    STATE_CANCELLED,
    ProgressTracker,
    evidence_text_metrics,
    mark_progress_cancelled,
    mark_progress_failed,
    maybe_start_new_attempt,
    persist_snapshot,
    requirement_text_metrics,
    start_new_attempt,
)
from opportunity.services.prompts import MATCH_PROMPT_VERSION, REQUIREMENT_PROMPT_VERSION
from opportunity.services.report import create_report_snapshot, record_audit, record_feedback
from opportunity.services.requirement_history import save_requirement_profile_version
from opportunity.services.retrieval_optimization import AttemptRetrievalCache
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


CASE_PROGRESS_DETAILS = {
    'NOT_CONFIGURED': '案例阶段：未配置案例知识库',
    'SKIPPED': '案例阶段：已跳过',
    'NO_MATCH': '案例阶段：无命中',
    'DEGRADED': '案例阶段：已降级，仅依据产品资料',
}


def _should_stop(tracker: ProgressTracker, analysis: OpportunityAnalysis) -> bool:
    if tracker.cancelled:
        return True
    current = QuerySet(OpportunityAnalysis).filter(id=analysis.id).values_list('status', flat=True).first()
    if current == AnalysisStatus.CLOSED:
        tracker.cancelled = True
        tracker.state = STATE_CANCELLED
        return True
    return False


def _case_progress_detail(enhancement: dict) -> str:
    status = (enhancement or {}).get('status')
    count = (enhancement or {}).get('count') or 0
    if status == 'APPLIED':
        return f'案例阶段：已应用 {count} 条参考'
    return CASE_PROGRESS_DETAILS.get(status, '正在检索相似落地案例')


def _finalize_success(analysis: OpportunityAnalysis, tracker: ProgressTracker, snapshot_fields: dict):
    with transaction.atomic():
        locked = QuerySet(OpportunityAnalysis).select_for_update().filter(id=analysis.id).first()
        if locked is None or locked.status == AnalysisStatus.CLOSED:
            tracker.cancelled = True
            tracker.state = STATE_CANCELLED
            return
        _transit(locked, AnalysisStatus.WAITING_CONFIRMATION)
        done_progress = tracker.complete('分析完成', flush=False)
        snapshot = dict(locked.result_snapshot or {})
        snapshot.update(snapshot_fields)
        snapshot['progress'] = done_progress
        locked.result_snapshot = snapshot
        locked.error_code = None
        locked.error_message = None
        locked.knowledge_snapshot = analysis.knowledge_snapshot
        locked.requirement_profile = analysis.requirement_profile
        locked.model_snapshot = analysis.model_snapshot
        locked.rule_version = analysis.rule_version
        locked.save(update_fields=[
            'status', 'result_snapshot', 'error_code', 'error_message',
            'knowledge_snapshot', 'requirement_profile', 'model_snapshot',
            'rule_version', 'update_time',
        ])
        started = time.perf_counter()
        create_report_snapshot(locked, locked.user_id)
        duration_ms = int((time.perf_counter() - started) * 1000)
        tracker.record_event('RANK', 'create_report_snapshot', duration_ms, outcome='SUCCESS')
        locked.result_snapshot = {
            **locked.result_snapshot,
            'progress': tracker.complete('分析完成', flush=False),
        }
        locked.save(update_fields=['result_snapshot', 'update_time'])
        analysis.status = locked.status
        analysis.result_snapshot = locked.result_snapshot
        analysis.error_code = locked.error_code
        analysis.error_message = locked.error_message


def run_analysis(analysis_id):
    started = time.time()
    with transaction.atomic():
        analysis = QuerySet(OpportunityAnalysis).select_for_update(skip_locked=True).filter(id=analysis_id).first()
        if analysis is None:
            return
        if analysis.status not in (AnalysisStatus.DRAFT, AnalysisStatus.ANALYZING, AnalysisStatus.NEED_CLARIFICATION,
                                   AnalysisStatus.FAILED):
            return
        if analysis.status in (AnalysisStatus.FAILED, AnalysisStatus.NEED_CLARIFICATION):
            maybe_start_new_attempt(analysis)
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
        analysis.refresh_from_db()
        if analysis.status == AnalysisStatus.CLOSED:
            return
        message = _sanitize_error(exc.message)
        persist_snapshot(
            analysis,
            status=AnalysisStatus.FAILED,
            extra_fields={
                'error_code': str(exc.code),
                'error_message': message,
                'runtime_ms': int((time.time() - started) * 1000),
            },
        )
        mark_progress_failed(analysis, message)
        logger.warning('analysis failed id=%s code=%s', analysis.id, exc.code)
    except Exception as exc:
        analysis.refresh_from_db()
        if analysis.status == AnalysisStatus.CLOSED:
            return
        message = _sanitize_error(str(exc))
        persist_snapshot(
            analysis,
            status=AnalysisStatus.FAILED,
            extra_fields={
                'error_code': 'ANALYSIS_FAILED',
                'error_message': message,
                'runtime_ms': int((time.time() - started) * 1000),
            },
        )
        mark_progress_failed(analysis, message)
        logger.exception('analysis unexpected error id=%s', analysis.id)


def _execute(analysis: OpportunityAnalysis):
    tracker = ProgressTracker(analysis)
    try:
        _execute_tracked(analysis, tracker)
    except Exception as exc:
        tracker.fail(_sanitize_error(getattr(exc, 'message', None) or str(exc)))
        raise


def _execute_tracked(analysis: OpportunityAnalysis, tracker: ProgressTracker):
    if _should_stop(tracker, analysis):
        return
    setting = get_setting(analysis.workspace_id)
    if not setting.llm_model_id or not setting.product_knowledge_id:
        raise AppApiException(500, '请先配置分析模型和产品知识库')
    from opportunity.services.requirement_extraction import extract_requirement_profile, merge_clarification
    tracker.begin('PARSE', '正在把客户需求拆成可匹配的能力项')
    extra_context = {'clarification_history': analysis.clarification_history or []}
    parse_name = 'merge_clarification' if analysis.requirement_profile and analysis.clarification_history else 'extract_requirement'
    with tracker.timed('PARSE', parse_name):
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
    req_metrics = requirement_text_metrics(profile.get('requirements'))
    tracker.set_totals(**req_metrics)
    tracker.add_completed(1)
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
    persist_snapshot(
        analysis,
        progress=tracker.payload(),
        extra_fields={
            'clarification_questions': analysis.clarification_questions,
            'requirement_profile': analysis.requirement_profile,
            'model_snapshot': analysis.model_snapshot,
            'knowledge_snapshot': analysis.knowledge_snapshot,
            'rule_version': analysis.rule_version,
        },
    )
    if _should_stop(tracker, analysis):
        return
    should_clarify = bool(analysis.clarification_questions) and not analysis.clarification_history
    if should_clarify:
        analysis.refresh_from_db(fields=['status'])
        if analysis.status == AnalysisStatus.CLOSED:
            return
        _transit(analysis, AnalysisStatus.NEED_CLARIFICATION)
        progress = tracker.waiting_user('需求已拆解，请补充下面的关键参数后再继续匹配产品')
        _, cancelled = persist_snapshot(
            analysis,
            progress=progress,
            snapshot_fields={
                'candidates': [],
                'excluded': [],
                'summary': '需要补充关键参数后再进行产品匹配',
            },
            status=AnalysisStatus.NEED_CLARIFICATION,
            extra_fields={
                'clarification_questions': analysis.clarification_questions,
                'requirement_profile': analysis.requirement_profile,
                'model_snapshot': analysis.model_snapshot,
                'knowledge_snapshot': analysis.knowledge_snapshot,
                'rule_version': analysis.rule_version,
            },
        )
        if cancelled:
            return
        record_audit(analysis, 'CLARIFICATION_REQUIRED', analysis.user_id, {
            'question_count': len(analysis.clarification_questions),
        })
        return
    if _should_stop(tracker, analysis):
        return

    tracker.begin('RETRIEVE', '正在产品知识库中检索相关资料')
    queries = build_search_queries(profile)
    if analysis.original_requirement not in queries:
        queries.insert(0, analysis.original_requirement)
    tracker.set_totals(
        queries_total=len(queries),
        total_units=1 + len(queries) + 2,
        **req_metrics,
    )
    retrieval_cache = AttemptRetrievalCache()
    hits = []
    for index, query in enumerate(queries, start=1):
        if _should_stop(tracker, analysis):
            return
        tracker.detail = f'正在执行第 {index}/{len(queries)} 条知识检索'
        tracker.flush(force=True)
        tracker.increment_counter('query_attempts')
        started = time.perf_counter()
        batch = []
        outcome = 'FAILED'
        try:
            batch, _ = retrieval_cache.get_or_retrieve(
                workspace_id=analysis.workspace_id,
                knowledge_id=setting.product_knowledge_id,
                search_mode=setting.search_mode,
                top_n=setting.top_n,
                similarity=setting.similarity,
                query=query,
                user_id=analysis.user_id,
                authorization_scope=analysis.workspace_id,
                knowledge_version=analysis.knowledge_snapshot.get('captured_at'),
                retrieve=lambda: retrieve_product_paragraphs(
                    workspace_id=analysis.workspace_id,
                    knowledge_id=setting.product_knowledge_id,
                    question=query,
                    search_mode=setting.search_mode,
                    top_n=setting.top_n,
                    similarity=setting.similarity,
                ),
            )
            outcome = 'SUCCESS'
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            tracker.record_event(
                'RETRIEVE', 'retrieve_query', duration_ms,
                query_index=index, hit_count=len(batch), outcome=outcome,
            )
        hits.extend(batch)
        tracker.note_retrieval_metrics(retrieval_cache.metrics())
        tracker.note_query(len(batch))
        tracker.flush(force=False)
        if _should_stop(tracker, analysis):
            return
    tracker.note_unique_paragraphs(len({
        str(item.get('paragraph_id')) for item in hits if item.get('paragraph_id')
    }))
    grouped = aggregate_by_product(analysis.workspace_id, hits)
    candidates = []
    products = list(grouped.values())
    tracker.set_totals(
        products_found=len(products),
        total_units=1 + len(queries) + len(products) + 2,
    )
    for index, item in enumerate(products, start=1):
        if _should_stop(tracker, analysis):
            return
        detail = f'正在核验第 {index}/{len(products)} 个候选产品「{item["product"].name}」'
        if index == 1:
            tracker.begin('MATCH', detail, force=True)
        else:
            tracker.detail = detail
            tracker.flush(force=True)
        if _should_stop(tracker, analysis):
            return
        ev_metrics = evidence_text_metrics(item['evidence'])
        prompt_chars = req_metrics['requirement_chars'] + ev_metrics['evidence_chars']
        tracker.increment_counter('match_model_attempts')
        tracker.increment_counter('prompt_chars', prompt_chars)
        with tracker.timed(
            'MATCH', 'match_product',
            product_code=item['product'].code,
            evidence_count=ev_metrics['evidence_count'],
            unique_paragraphs=ev_metrics['unique_paragraphs'],
            evidence_chars=ev_metrics['evidence_chars'],
            requirement_count=req_metrics['requirement_count'],
            requirement_chars=req_metrics['requirement_chars'],
            prompt_chars=prompt_chars,
        ):
            match_items = match_product(
                analysis.workspace_id,
                setting.llm_model_id,
                item['product'],
                profile.get('requirements') or [],
                item['evidence'],
            )
        tracker.note_match(**ev_metrics)
        tracker.flush(force=False)
        if _should_stop(tracker, analysis):
            return
        department = resolve_department(item['product'])
        candidates.append(build_candidate_result(
            item['product'],
            profile.get('requirements') or [],
            match_items,
            department,
            max_candidates=setting.max_candidates,
        ))
    with tracker.timed('MATCH', 'rank_candidates_initial'):
        top, excluded = rank_candidates(candidates, max_candidates=min(3, setting.max_candidates or 5))
    if _should_stop(tracker, analysis):
        return
    tracker.begin('CASE', '正在检索相似落地案例')
    if _should_stop(tracker, analysis):
        return
    with tracker.timed('CASE', 'run_case_enhancement'):
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
    tracker.detail = _case_progress_detail(case_enhancement)
    tracker.add_completed(1)
    tracker.flush(force=True)
    if _should_stop(tracker, analysis):
        return
    tracker.begin('RANK', '正在评分排序并生成结论')
    with tracker.timed('RANK', 'rank_candidates'):
        top, _ = rank_candidates(top, max_candidates=min(3, setting.max_candidates or 5))
    if _should_stop(tracker, analysis):
        return
    tracker.detail = '正在生成分析报告'
    tracker.flush(force=True)
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
    analysis.error_code = None
    analysis.error_message = None
    snapshot_fields = {
        'candidates': top,
        'excluded': excluded,
        'summary': summary,
        'case_references': case_references,
        'case_enhancement': case_enhancement,
    }
    _, cancelled = persist_snapshot(
        analysis,
        progress=tracker.payload(),
        snapshot_fields=snapshot_fields,
        extra_fields={
            'knowledge_snapshot': analysis.knowledge_snapshot,
            'requirement_profile': analysis.requirement_profile,
            'model_snapshot': analysis.model_snapshot,
            'rule_version': analysis.rule_version,
            'error_code': None,
            'error_message': None,
        },
    )
    if cancelled or tracker.cancelled:
        return
    _finalize_success(analysis, tracker, snapshot_fields)


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
    start_new_attempt(analysis)
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
    analysis.save(update_fields=['clarification_history', 'status', 'error_code', 'error_message', 'update_time'])
    start_new_attempt(analysis)
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
    start_new_attempt(analysis)
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
        persist_snapshot(
            analysis,
            snapshot_fields={
                'decision': {'action': normalized, 'reason': reason or '', 'product_code': None},
            },
            status=AnalysisStatus.CLOSED,
        )
        mark_progress_cancelled(analysis, '分析已取消' if normalized == DecisionAction.CANCEL else '分析已关闭')
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
