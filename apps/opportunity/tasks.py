# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： tasks.py
    @date：2026/9/3
    @desc: 商机分析异步任务
"""
from celery_once import QueueOnce

from ops import celery_app


@celery_app.task(base=QueueOnce, once={'keys': ['analysis_id']}, name='celery:analyze_opportunity')
def analyze_opportunity(analysis_id):
    from opportunity.services.analysis import run_analysis

    run_analysis(analysis_id)
