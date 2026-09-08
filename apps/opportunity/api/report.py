# coding=utf-8
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter

from common.mixins.api_mixin import APIMixin
from common.result import DefaultResultSerializer


class ReportAPI(APIMixin):
    @staticmethod
    def get_parameters():
        return [
            OpenApiParameter(name='workspace_id', type=OpenApiTypes.STR, location='path', required=True),
            OpenApiParameter(name='analysis_id', type=OpenApiTypes.STR, location='path', required=True),
        ]

    @staticmethod
    def get_response():
        return DefaultResultSerializer
