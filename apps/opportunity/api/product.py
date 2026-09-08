# coding=utf-8
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter

from common.mixins.api_mixin import APIMixin
from common.result import DefaultResultSerializer
from opportunity.serializers.product import DocumentBindingSerializer, ProductWriteSerializer


class ProductAPI(APIMixin):
    @staticmethod
    def get_parameters():
        return [
            OpenApiParameter(name='workspace_id', description='工作空间id', type=OpenApiTypes.STR,
                             location='path', required=True),
        ]

    @staticmethod
    def get_request():
        return ProductWriteSerializer

    @staticmethod
    def get_response():
        return DefaultResultSerializer


class ProductBindingAPI(APIMixin):
    @staticmethod
    def get_parameters():
        return [
            OpenApiParameter(name='workspace_id', description='工作空间id', type=OpenApiTypes.STR,
                             location='path', required=True),
            OpenApiParameter(name='product_id', description='产品id', type=OpenApiTypes.STR,
                             location='path', required=True),
            OpenApiParameter(name='document_id', description='文档id', type=OpenApiTypes.STR,
                             location='path', required=True),
        ]

    @staticmethod
    def get_request():
        return DocumentBindingSerializer

    @staticmethod
    def get_response():
        return DefaultResultSerializer
