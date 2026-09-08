# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： setting.py
    @date：2026/9/3
    @desc:
"""
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter

from common.mixins.api_mixin import APIMixin
from common.result import DefaultResultSerializer
from opportunity.serializers.setting import OpportunitySettingSerializer


class SettingAPI(APIMixin):
    @staticmethod
    def get_parameters():
        return [
            OpenApiParameter(name='workspace_id', description='工作空间id', type=OpenApiTypes.STR,
                             location='path', required=True),
        ]

    @staticmethod
    def get_request():
        return OpportunitySettingSerializer

    @staticmethod
    def get_response():
        return DefaultResultSerializer
