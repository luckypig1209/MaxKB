# coding=utf-8
from common.mixins.api_mixin import APIMixin
from common.result import DefaultResultSerializer
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from opportunity.serializers.record import OpportunityRecordStatusSerializer


class OpportunityRecordAPI(APIMixin):
    @staticmethod
    def get_parameters():
        return [
            OpenApiParameter(name='workspace_id', type=OpenApiTypes.STR, location='path', required=True),
            OpenApiParameter(name='record_id', type=OpenApiTypes.STR, location='path', required=False),
            OpenApiParameter(name='status', type=OpenApiTypes.STR, required=False),
            OpenApiParameter(name='product_code', description='产品编码或名称关键字', type=OpenApiTypes.STR,
                             required=False),
            OpenApiParameter(name='department_code', type=OpenApiTypes.STR, required=False),
            OpenApiParameter(name='start_time', type=OpenApiTypes.DATETIME, required=False),
            OpenApiParameter(name='end_time', type=OpenApiTypes.DATETIME, required=False),
            OpenApiParameter(name='current_page', type=OpenApiTypes.INT, required=False),
            OpenApiParameter(name='page_size', type=OpenApiTypes.INT, required=False),
        ]

    @staticmethod
    def get_request():
        return OpportunityRecordStatusSerializer

    @staticmethod
    def get_response():
        return DefaultResultSerializer
