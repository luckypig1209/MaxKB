# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： urls.py
    @date：2026/9/3
    @desc:
"""
from django.urls import path

from . import views

app_name = 'opportunity'

urlpatterns = [
    path('opportunity/embed/tokens', views.EmbedTokenExchangeView.as_view(),
         name='opportunity_embed_token_exchange'),
    path('opportunity/embed/session', views.EmbedSessionView.as_view(),
         name='opportunity_embed_session'),
    path('opportunity/embed/analyses', views.EmbedAnalysisView.as_view(),
         name='opportunity_embed_analyses'),
    path('opportunity/embed/analyses/<str:analysis_id>', views.EmbedAnalysisView.Operate.as_view(),
         name='opportunity_embed_analysis_operate'),
    path('opportunity/embed/analyses/<str:analysis_id>/clarifications',
         views.EmbedAnalysisView.Clarification.as_view(), name='opportunity_embed_analysis_clarification'),
    path('opportunity/embed/analyses/<str:analysis_id>/retry', views.EmbedAnalysisView.Retry.as_view(),
         name='opportunity_embed_analysis_retry'),
    path('opportunity/embed/analyses/<str:analysis_id>/confirm', views.EmbedAnalysisView.Confirm.as_view(),
         name='opportunity_embed_analysis_confirm'),
    path('opportunity/embed/analyses/<str:analysis_id>/report/export',
         views.EmbedAnalysisView.ExportReport.as_view(), name='opportunity_embed_analysis_report_export'),
    path('workspace/<str:workspace_id>/opportunity/setting', views.OpportunitySettingView.as_view(),
         name='opportunity_setting'),
    path('workspace/<str:workspace_id>/opportunity/departments', views.DepartmentView.as_view(),
         name='opportunity_departments'),
    path('workspace/<str:workspace_id>/opportunity/departments/<str:department_id>',
         views.DepartmentView.Operate.as_view(), name='opportunity_department_operate'),
    path('workspace/<str:workspace_id>/opportunity/products', views.ProductView.as_view(),
         name='opportunity_products'),
    path('workspace/<str:workspace_id>/opportunity/products/<str:product_id>',
         views.ProductView.Operate.as_view(), name='opportunity_product_operate'),
    path('workspace/<str:workspace_id>/opportunity/products/<str:product_id>/documents/<str:document_id>/binding',
         views.ProductView.Binding.as_view(), name='opportunity_product_binding'),
    path('workspace/<str:workspace_id>/opportunity/cases', views.CaseView.as_view(),
         name='opportunity_cases'),
    path('workspace/<str:workspace_id>/opportunity/cases/<str:case_id>', views.CaseView.Operate.as_view(),
         name='opportunity_case_operate'),
    path('workspace/<str:workspace_id>/opportunity/cases/<str:case_id>/action', views.CaseView.Action.as_view(),
         name='opportunity_case_action'),
    path('workspace/<str:workspace_id>/opportunity/cases/<str:case_id>/documents/<str:document_id>/binding',
         views.CaseView.Binding.as_view(), name='opportunity_case_binding'),
    path('workspace/<str:workspace_id>/opportunity/records', views.OpportunityRecordView.as_view(),
         name='opportunity_records'),
    path('workspace/<str:workspace_id>/opportunity/records/<str:record_id>',
         views.OpportunityRecordView.Operate.as_view(), name='opportunity_record_operate'),
    path('workspace/<str:workspace_id>/opportunity/records/<str:record_id>/status',
         views.OpportunityRecordView.Status.as_view(), name='opportunity_record_status'),
    path('workspace/<str:workspace_id>/opportunity/analyses', views.AnalysisView.as_view(),
         name='opportunity_analyses'),
    path('workspace/<str:workspace_id>/opportunity/analyses/<str:analysis_id>',
         views.AnalysisView.Operate.as_view(), name='opportunity_analysis_operate'),
    path('workspace/<str:workspace_id>/opportunity/analyses/<str:analysis_id>/clarifications',
         views.AnalysisView.Clarification.as_view(), name='opportunity_analysis_clarification'),
    path('workspace/<str:workspace_id>/opportunity/analyses/<str:analysis_id>/requirements/versions',
         views.AnalysisView.RequirementVersions.as_view(), name='opportunity_requirement_versions'),
    path('workspace/<str:workspace_id>/opportunity/analyses/<str:analysis_id>/retry',
         views.AnalysisView.Retry.as_view(), name='opportunity_analysis_retry'),
    path('workspace/<str:workspace_id>/opportunity/analyses/<str:analysis_id>/confirm',
         views.AnalysisView.Confirm.as_view(), name='opportunity_analysis_confirm'),
    path('workspace/<str:workspace_id>/opportunity/analyses/<str:analysis_id>/report',
         views.ReportView.as_view(), name='opportunity_analysis_report'),
    path('workspace/<str:workspace_id>/opportunity/analyses/<str:analysis_id>/report/versions',
         views.ReportView.Versions.as_view(), name='opportunity_analysis_report_versions'),
    path('workspace/<str:workspace_id>/opportunity/analyses/<str:analysis_id>/report/export',
         views.ReportView.Export.as_view(), name='opportunity_analysis_report_export'),
    path('workspace/<str:workspace_id>/opportunity/embed/clients', views.EmbedClientView.as_view(),
         name='opportunity_embed_clients'),
    path('workspace/<str:workspace_id>/opportunity/embed/clients/<str:client_id>',
         views.EmbedClientView.Operate.as_view(), name='opportunity_embed_client_operate'),
    path('workspace/<str:workspace_id>/opportunity/embed/clients/<str:client_id>/rotate-secret',
         views.EmbedClientView.RotateSecret.as_view(), name='opportunity_embed_client_rotate_secret'),
    path('workspace/<str:workspace_id>/opportunity/embed/sessions/<str:session_id>/revoke',
         views.EmbedClientView.RevokeSession.as_view(), name='opportunity_embed_session_revoke'),
]
