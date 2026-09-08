# coding=utf-8
"""
    @project: MaxKB
    @Author：bia
    @file： department.py
    @date：2026/9/3
    @desc: 部门主数据
"""
from django.db.models import QuerySet
from rest_framework import serializers

from common.exception.app_exception import AppApiException
from opportunity.models import DepartmentProfile, DepartmentStatus, OpportunityAnalysis, ProductDepartmentMapping
from opportunity.serializers.common import model_time, require_department


class DepartmentWriteSerializer(serializers.Serializer):
    code = serializers.CharField(required=True, max_length=64)
    name = serializers.CharField(required=True, max_length=128)
    status = serializers.ChoiceField(choices=DepartmentStatus.choices, required=False)
    meta = serializers.JSONField(required=False)


def department_to_dict(department: DepartmentProfile):
    return {
        'id': str(department.id),
        'workspace_id': department.workspace_id,
        'code': department.code,
        'name': department.name,
        'status': department.status,
        'meta': department.meta or {},
        'create_time': model_time(department.create_time),
        'update_time': model_time(department.update_time),
    }


class DepartmentSerializer(serializers.Serializer):
    workspace_id = serializers.CharField(required=True)

    def list(self):
        self.is_valid(raise_exception=True)
        queryset = QuerySet(DepartmentProfile).filter(
            workspace_id=self.validated_data['workspace_id']
        ).order_by('code')
        return [department_to_dict(item) for item in queryset]

    def insert(self, instance: dict):
        self.is_valid(raise_exception=True)
        serializer = DepartmentWriteSerializer(data=instance)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        workspace_id = self.validated_data['workspace_id']
        if QuerySet(DepartmentProfile).filter(workspace_id=workspace_id, code=data['code']).exists():
            raise AppApiException(500, '部门编码已存在')
        department = DepartmentProfile(
            workspace_id=workspace_id,
            code=data['code'],
            name=data['name'],
            status=data.get('status') or DepartmentStatus.ACTIVE,
            meta=data.get('meta') or {},
        )
        department.save()
        return department_to_dict(department)


class DepartmentOperateSerializer(serializers.Serializer):
    workspace_id = serializers.CharField(required=True)
    department_id = serializers.UUIDField(required=True)

    def one(self):
        self.is_valid(raise_exception=True)
        department = require_department(
            self.validated_data['workspace_id'],
            department_id=self.validated_data['department_id'],
            allow_inactive=True,
        )
        return department_to_dict(department)

    def update(self, instance: dict):
        self.is_valid(raise_exception=True)
        serializer = DepartmentWriteSerializer(data=instance)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        workspace_id = self.validated_data['workspace_id']
        department = require_department(workspace_id, department_id=self.validated_data['department_id'],
                                        allow_inactive=True)
        exists = QuerySet(DepartmentProfile).filter(workspace_id=workspace_id, code=data['code']).exclude(
            id=department.id).exists()
        if exists:
            raise AppApiException(500, '部门编码已存在')
        department.code = data['code']
        department.name = data['name']
        department.status = data.get('status') or department.status
        department.meta = data.get('meta') if data.get('meta') is not None else department.meta
        department.save()
        return department_to_dict(department)

    def delete(self):
        self.is_valid(raise_exception=True)
        workspace_id = self.validated_data['workspace_id']
        department = require_department(workspace_id, department_id=self.validated_data['department_id'],
                                        allow_inactive=True)
        referenced = QuerySet(ProductDepartmentMapping).filter(department=department).exists()
        snapshot_referenced = QuerySet(OpportunityAnalysis).filter(
            workspace_id=workspace_id,
            result_snapshot__isnull=False,
        ).exists()
        if referenced or snapshot_referenced:
            department.status = DepartmentStatus.INACTIVE
            department.save(update_fields=['status', 'update_time'])
            return True
        department.delete()
        return True
