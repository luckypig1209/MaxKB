# coding=utf-8
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter

from common.mixins.api_mixin import APIMixin
from common.result import DefaultResultSerializer
from opportunity.serializers.case import CaseActionSerializer, CaseDocumentBindingRequest, CaseWriteSerializer


class CaseAPI(APIMixin):
    @staticmethod
    def get_parameters():
        return [
            OpenApiParameter(name='workspace_id', description='工作空间id', type=OpenApiTypes.STR,
                             location='path', required=True),
        ]

    @staticmethod
    def get_request():
        return CaseWriteSerializer

    @staticmethod
    def get_response():
        return DefaultResultSerializer


class CaseActionAPI(CaseAPI):
    @staticmethod
    def get_request():
        return CaseActionSerializer


class CaseBindingAPI(CaseAPI):
    @staticmethod
    def get_request():
        return CaseDocumentBindingRequest
