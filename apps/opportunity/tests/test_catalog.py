import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[3]
CATALOG_PATHS = (
    ROOT / 'deploy' / 'bootstrap' / 'phase1' / 'PHASE1_CATALOG.json',
    ROOT.parent / 'docs' / 'knowledge_import' / 'phase1' / 'PHASE1_CATALOG.json',
)

READY_CODES = {'YIJIE', 'YIJU', 'YISHI', 'YIGUAN', 'YITENG', 'YIXIAO', 'YIZHI', 'YIMOU'}
ALL_CODES = {
    'YITU', 'YIJIE', 'YISHU', 'YILIAN_VIDEO', 'YIJU', 'YIXI', 'YIJIE_RPA',
    'YISHI', 'YIGUAN', 'YILING', 'YITENG', 'YIXIAO', 'YIGOU', 'YILIAN_BAAS',
    'YISUAN', 'YIZHI', 'YIMOU', 'YIJING',
}
DEPARTMENT_CODES = {'SHZL', 'YFZX', 'SZFZ', 'SZZF', 'ZHCS', 'ZNQG', 'ZNYW'}


class PhaseOneCatalogTests(TestCase):
    def test_deploy_and_import_catalogs_are_identical(self):
        catalogs = [json.loads(path.read_text(encoding='utf-8')) for path in CATALOG_PATHS]
        self.assertEqual(catalogs[0], catalogs[1])

    def test_authority_counts_codes_and_department_references(self):
        catalog = json.loads(CATALOG_PATHS[0].read_text(encoding='utf-8'))
        departments = catalog['departments']
        products = catalog['products']
        department_codes = [item['code'] for item in departments]
        product_codes = [item['code'] for item in products]
        self.assertEqual(len(departments), 7)
        self.assertEqual(len(products), 18)
        self.assertEqual(set(department_codes), DEPARTMENT_CODES)
        self.assertEqual(set(product_codes), ALL_CODES)
        self.assertEqual(len(department_codes), len(set(department_codes)))
        self.assertEqual(len(product_codes), len(set(product_codes)))
        self.assertTrue(set(item['department_code'] for item in products) <= DEPARTMENT_CODES)

    def test_eight_ready_and_ten_pending_products_are_explicit(self):
        catalog = json.loads(CATALOG_PATHS[0].read_text(encoding='utf-8'))
        ready = {item['code'] for item in catalog['products'] if item.get('document_name')}
        pending = {item['code'] for item in catalog['products'] if not item.get('document_name')}
        self.assertEqual(ready, READY_CODES)
        self.assertEqual(len(pending), 10)
        self.assertEqual(ready | pending, ALL_CODES)

    def test_support_metadata_has_source_and_update_time(self):
        catalog = json.loads(CATALOG_PATHS[0].read_text(encoding='utf-8'))
        self.assertEqual(catalog['source']['file'], '鸿信工具型产品/工具型产品名录及支持团队联系方式.md')
        for item in catalog['products']:
            support = item['support']
            self.assertTrue(support['manager'])
            self.assertTrue(support['phone'])
            self.assertEqual(support['source'], catalog['source']['file'])
            self.assertTrue(support['updated_at'])

    def test_bootstrap_payload_merges_catalog_fields_without_erasing_extensions(self):
        source = (ROOT / 'deploy' / 'bootstrap' / 'bootstrap_phase1.py').read_text(encoding='utf-8')
        module = ast.parse(source)
        functions = [node for node in module.body if isinstance(node, ast.FunctionDef)
                     and node.name in {'department_payload', 'product_payload'}]
        namespace = {
            'DepartmentStatus': SimpleNamespace(ACTIVE='ACTIVE'),
            'ProductStatus': SimpleNamespace(ACTIVE='ACTIVE'),
        }
        exec(compile(ast.Module(body=functions, type_ignores=[]), '<bootstrap-contract>', 'exec'), namespace)
        existing = {'version': 'v9', 'support': {'manager': 'old', 'phone': 'old'}}
        product = namespace['product_payload']({
            'code': 'P1', 'name': '产品', 'aliases': [], 'product_line': '', 'description': '',
            'department_code': 'D1',
            'support': {'manager': 'new', 'phone': 'new'},
        }, SimpleNamespace(id='dept-1'), existing)
        self.assertEqual(product['meta']['version'], 'v9')
        self.assertEqual(product['meta']['support']['manager'], 'new')
        department = namespace['department_payload'](
            {'code': 'D1', 'name': '部门', 'source_name': '原始部门'},
            {'custom': 'kept'},
        )
        self.assertEqual(department['meta']['custom'], 'kept')
        self.assertEqual(department['meta']['source_name'], '原始部门')
