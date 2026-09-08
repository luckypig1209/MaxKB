# coding=utf-8
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter

from common.mixins.api_mixin import APIMixin
from common.result import DefaultResultSerializer
from opportunity.serializers.analysis import AnalysisCreateSerializer, ClarificationSerializer, ConfirmSerializer


class AnalysisAPI(APIMixin):
    @staticmethod
    def get_parameters():
        return [
            OpenApiParameter(name='workspace_id', description='工作空间id', type=OpenApiTypes.STR,
                             location='path', required=True),
            OpenApiParameter(name='status', description='状态', type=OpenApiTypes.STR, required=False),
            OpenApiParameter(name='create_user', description='创建人', type=OpenApiTypes.STR, required=False),
            OpenApiParameter(name='current_page', description='页码，最小为 1',
                             type=OpenApiTypes.INT, required=False),
            OpenApiParameter(name='page_size', description='每页条数，最大为 100',
                             type=OpenApiTypes.INT, required=False),
            OpenApiParameter(name='department_code', description='候选产品主责部门编码',
                             type=OpenApiTypes.STR, required=False),
            OpenApiParameter(name='start_time', description='创建时间起点（ISO 8601）',
                             type=OpenApiTypes.DATETIME, required=False),
            OpenApiParameter(name='end_time', description='创建时间终点（ISO 8601）',
                             type=OpenApiTypes.DATETIME, required=False),
        ]

    @staticmethod
    def get_request():
        return AnalysisCreateSerializer

    @staticmethod
    def get_response():
        return DefaultResultSerializer


class AnalysisOperateAPI(APIMixin):
    @staticmethod
    def get_parameters():
        return [
            OpenApiParameter(name='workspace_id', description='工作空间id', type=OpenApiTypes.STR,
                             location='path', required=True),
            OpenApiParameter(name='analysis_id', description='分析id', type=OpenApiTypes.STR,
                             location='path', required=True),
        ]

    @staticmethod
    def get_request():
        return ConfirmSerializer

    @staticmethod
    def get_response():
        return DefaultResultSerializer


class ClarificationAPI(APIMixin):
    @staticmethod
    def get_request():
        return ClarificationSerializer

    @staticmethod
    def get_response():
        return DefaultResultSerializer


class RequirementVersionAPI(APIMixin):
    @staticmethod
    def get_parameters():
        return AnalysisOperateAPI.get_parameters()

    @staticmethod
    def get_response():
        return DefaultResultSerializer
