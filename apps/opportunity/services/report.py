# coding=utf-8
"""商机报告快照、反馈和审计。"""
from copy import deepcopy
from html import escape

from django.db import transaction
from django.db.models import Max, QuerySet
from django.utils import timezone

from opportunity.models import OpportunityAuditLog, OpportunityFeedback, OpportunityReport


def record_audit(analysis, action, operator_user_id, detail=None):
    return OpportunityAuditLog.objects.create(
        workspace_id=analysis.workspace_id,
        analysis=analysis,
        action=action,
        operator_user_id=str(operator_user_id or analysis.user_id),
        detail=detail or {},
    )


def create_report_snapshot(analysis, generated_by=None):
    """每次生成新版本，历史版本不覆盖。"""
    with transaction.atomic():
        current = QuerySet(OpportunityReport).select_for_update().filter(analysis=analysis)
        version = (current.aggregate(value=Max('version')).get('value') or 0) + 1
        current.filter(is_current=True).update(is_current=False)
        # UUIDv7 的前缀主要是时间戳；同一毫秒创建的分析可能拥有相同前 8 位。
        # 使用完整 UUID hex，确保工作空间内的报告编号与分析任务一一对应。
        analysis_key = str(analysis.id).replace('-', '')
        report_no = f'BIA-{analysis.create_time:%Y%m%d}-{analysis_key}-V{version}'
        snapshot = {
            'schema_version': '1.0',
            'analysis_id': str(analysis.id),
            'report_no': report_no,
            'report_version': version,
            'status': analysis.status,
            'original_requirement': analysis.original_requirement,
            'requirement_profile': deepcopy(analysis.requirement_profile or {}),
            'result': deepcopy(analysis.result_snapshot or {}),
            'confirmed_product_code': analysis.confirmed_product_code,
            'model_snapshot': deepcopy(analysis.model_snapshot or {}),
            'knowledge_snapshot': deepcopy(analysis.knowledge_snapshot or {}),
            'rule_version': analysis.rule_version,
            'generated_at': timezone.now().isoformat(),
        }
        report = OpportunityReport.objects.create(
            workspace_id=analysis.workspace_id,
            analysis=analysis,
            report_no=report_no,
            version=version,
            snapshot=snapshot,
            generated_by=str(generated_by or analysis.user_id),
            is_current=True,
        )
        record_audit(analysis, 'REPORT_GENERATED', generated_by, {
            'report_no': report_no,
            'version': version,
        })
        return report


def record_feedback(analysis, action, operator_user_id, product_code=None, reason=''):
    feedback = OpportunityFeedback.objects.create(
        workspace_id=analysis.workspace_id,
        analysis=analysis,
        action=action,
        product_code=product_code or None,
        reason=reason or '',
        operator_user_id=str(operator_user_id or analysis.user_id),
        result_snapshot=deepcopy(analysis.result_snapshot or {}),
    )
    record_audit(analysis, f'DECISION_{action}', operator_user_id, {
        'product_code': product_code or None,
        'reason': reason or '',
    })
    return feedback


def report_to_dict(report, include_snapshot=True):
    result = {
        'id': str(report.id),
        'analysis_id': str(report.analysis_id),
        'report_no': report.report_no,
        'version': report.version,
        'is_current': report.is_current,
        'generated_by': report.generated_by,
        'create_time': report.create_time.isoformat() if report.create_time else None,
    }
    if include_snapshot:
        result['snapshot'] = report.snapshot or {}
    return result


def render_report_html(report):
    snapshot = report.snapshot or {}
    result = snapshot.get('result') or {}
    profile = snapshot.get('requirement_profile') or {}
    candidates = [
        item for item in (result.get('candidates') or [])
        if float(item.get('score') or 0) > 0
    ]
    preferred = candidates[0] if candidates else None
    others = candidates[1:]

    def department_name(candidate):
        return escape(str((candidate.get('department') or {}).get('owner_department_name') or '归属待确认'))

    def level_text(level):
        return {
            'RECOMMENDED': '可直接推荐',
            'TECHNICAL_CONFIRMATION': '建议进入技术确认',
            'NOT_RECOMMENDED': '不推荐',
        }.get(level, '待确认')

    def case_names(candidate):
        return '、'.join(
            escape(str(item.get('case_name') or ''))
            for item in candidate.get('case_references') or []
        ) or '暂无案例参考'

    def match_counts(candidate):
        counts = {'FULL': 0, 'PARTIAL': 0, 'NO': 0, 'INSUFFICIENT': 0}
        for item in candidate.get('match_items') or []:
            status = item.get('status') or 'INSUFFICIENT'
            if status in counts:
                counts[status] += 1
        return counts

    def candidate_card(candidate, featured=False):
        counts = match_counts(candidate)
        score = float(candidate.get('score') or 0)
        klass = 'card featured' if featured else 'card'
        badge = '首选推荐' if featured else f'第 {escape(str(candidate.get("rank") or "-"))} 名'
        return (
            f'<div class="{klass}">'
            f'<div class="card-head"><span class="badge">{badge}</span>'
            f'<strong>{escape(str(candidate.get("product_name") or ""))}</strong>'
            f'<span class="score">{score:.1f}</span></div>'
            f'<div class="bar"><span style="width:{min(score, 100)}%"></span></div>'
            f'<p class="meta">{escape(level_text(candidate.get("recommendation_level")))}'
            f' · {department_name(candidate)}</p>'
            f'<p class="counts">完全满足 {counts["FULL"]} · 部分满足 {counts["PARTIAL"]}'
            f' · 不满足 {counts["NO"]} · 资料不足 {counts["INSUFFICIENT"]}</p>'
            f'<p class="cases">案例参考：{case_names(candidate)}</p>'
            '</div>'
        )

    featured_html = candidate_card(preferred, True) if preferred else '<p>暂无达到匹配门槛的候选产品。</p>'
    others_html = ''.join(candidate_card(item) for item in others)
    pain = '、'.join(escape(str(item)) for item in (profile.get('pain_points') or [])[:4])
    scenarios = '、'.join(escape(str(item)) for item in (profile.get('business_scenarios') or [])[:4])
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{escape(report.report_no)}</title>
<style>
body{{font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;max-width:880px;margin:32px auto;color:#1d2129;padding:0 20px}}
h1{{font-size:22px;margin:0 0 8px;color:#0b5cab}} h2{{font-size:16px;margin:28px 0 12px}}
.sub{{color:#86909c;margin-bottom:24px}}
.card{{border:1px solid #e5e6eb;border-radius:10px;padding:16px 18px;margin-bottom:12px;background:#fff}}
.featured{{border-color:#0b5cab;background:#f4f8fc;box-shadow:0 8px 20px rgba(11,92,171,.08)}}
.card-head{{display:flex;align-items:center;gap:10px}}
.badge{{background:#0b5cab;color:#fff;border-radius:999px;font-size:12px;padding:2px 8px}}
.score{{margin-left:auto;font-size:22px;font-weight:700;color:#0b5cab}}
.bar{{height:8px;background:#e8f1fa;border-radius:99px;margin:10px 0 8px;overflow:hidden}}
.bar span{{display:block;height:100%;background:#0b5cab}}
.meta,.counts,.cases{{margin:6px 0 0;color:#4e5969}}
.note{{padding:12px 14px;background:#f7f8fa;border-left:4px solid #0b5cab;color:#4e5969}}
.chips span{{display:inline-block;background:#f2f3f5;border-radius:999px;padding:4px 10px;margin:0 8px 8px 0}}
</style></head>
<body>
<h1>商机智能分析报告</h1>
<p class="sub">报告编号：{escape(report.report_no)}　版本：V{report.version}</p>
<h2>客户需求</h2>
<p>{escape(str(snapshot.get("original_requirement") or ""))}</p>
<p class="chips">{f'<span>场景：{scenarios}</span>' if scenarios else ''}{f'<span>痛点：{pain}</span>' if pain else ''}</p>
<h2>推荐结论</h2>
<p>{escape(str(result.get("summary") or ""))}</p>
{featured_html}
{others_html}
<p class="note">产品事实、案例参考和待确认项应分别理解。0 分或硬约束失败的产品不进入推荐列表；案例仅用于增强场景可信度，不代表标准产品能力。</p>
</body></html>'''
