# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： requirement.py
    @date：2026/9/3
    @desc: 需求画像 Schema
"""
from rest_framework import serializers

PRIORITY_CHOICES = ('must', 'should', 'nice_to_have')
CATEGORY_CHOICES = (
    'business_scenario', 'core_function', 'technical', 'deployment',
    'integration', 'security', 'delivery', 'commercial',
)


class CustomerContextSerializer(serializers.Serializer):
    industry = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    customer_type = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    region = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)


class RequirementItemSerializer(serializers.Serializer):
    id = serializers.CharField(required=True, max_length=64)
    description = serializers.CharField(required=True)
    priority = serializers.ChoiceField(required=True, choices=PRIORITY_CHOICES)
    category = serializers.ChoiceField(required=True, choices=CATEGORY_CHOICES)
    source_text = serializers.CharField(required=True)


class RequirementProfileSerializer(serializers.Serializer):
    schema_version = serializers.CharField(required=False, default='1.0')
    customer_context = CustomerContextSerializer(required=False)
    business_scenarios = serializers.ListField(
        child=serializers.CharField(), required=False, allow_null=True, default=list
    )
    pain_points = serializers.ListField(child=serializers.CharField(), required=False, allow_null=True, default=list)
    requirements = RequirementItemSerializer(many=True, required=True)
    constraints = serializers.ListField(child=serializers.CharField(), required=False, allow_null=True, default=list)
    excluded_conditions = serializers.ListField(
        child=serializers.CharField(), required=False, allow_null=True, default=list
    )
    missing_information = serializers.ListField(
        child=serializers.CharField(), required=False, allow_null=True, default=list
    )
    clarification_questions = serializers.ListField(
        child=serializers.CharField(), required=False, allow_null=True, default=list
    )

    def validate(self, attrs):
        attrs.setdefault('schema_version', '1.0')
        attrs.setdefault('customer_context', {'industry': None, 'customer_type': None, 'region': None})
        for field in ('business_scenarios', 'pain_points', 'constraints', 'excluded_conditions',
                      'missing_information', 'clarification_questions'):
            if attrs.get(field) is None:
                attrs[field] = []
        attrs['clarification_questions'] = (attrs.get('clarification_questions') or [])[:7]
        if not attrs.get('requirements'):
            raise serializers.ValidationError('requirements cannot be empty')
        return attrs


def normalize_requirement_profile(data: dict) -> dict:
    serializer = RequirementProfileSerializer(data=data or {})
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data
