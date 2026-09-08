# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： apps.py
    @date：2026/9/3
    @desc: 商机智能分析应用
"""
from django.apps import AppConfig


class OpportunityConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'opportunity'
    verbose_name = 'Opportunity Analysis'
