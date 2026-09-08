# coding=utf-8
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter

from common.mixins.api_mixin import APIMixin
from common.result import DefaultResultSerializer
from opportunity.serializers.embed import EmbedClientWriteSerializer, EmbedTokenExchangeRequest


class EmbedClientAPI(APIMixin):
    @staticmethod
    def get_parameters():
        return [
            OpenApiParameter(name='workspace_id', type=OpenApiTypes.STR, location='path', required=True),
            OpenApiParameter(name='client_id', type=OpenApiTypes.STR, location='path', required=False),
        ]

    @staticmethod
    def get_request():
        return EmbedClientWriteSerializer

    @staticmethod
    def get_response():
        return DefaultResultSerializer


class EmbedTokenAPI(APIMixin):
    @staticmethod
    def get_request():
        return EmbedTokenExchangeRequest

    @staticmethod
    def get_response():
        return DefaultResultSerializer
