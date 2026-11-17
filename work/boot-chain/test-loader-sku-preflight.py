"""Host-only production AST regressions; no device or build-script entry is invoked."""

import argparse
import ast
import copy
import io
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock


WORKSPACE = Path(__file__).resolve().parents[2]
SCRIPTS = {
    'profile': WORKSPACE / 'work/adsp-battery/ksrc/tools/mkadt-fuxi.py',
    'ram': WORKSPACE / 'work/adsp-battery/prepare-ram9g-loader.py',
    'w18': WORKSPACE / 'work/adsp-battery/prepare-wlan-w18-loader.py',
    'chain': WORKSPACE / 'work/boot-chain/build-chain.py',
    'verify': WORKSPACE / 'work/Codex-Xiaomi13-GPU-20261109/verify-loader-safety.py',
}
TREES = {name: ast.parse(path.read_text(encoding='utf-8')) for name, path in SCRIPTS.items()}
BASE = 0x8c0000000
GPU_BYTES = 0x2000000
BANKS = {'full': 0x140000000, '9g': 0x240000000}
SKU12 = struct.pack('>I', 12)
SKU8 = struct.pack('>I', 8)
ADT12 = struct.pack('<I', 12)
ADT8 = struct.pack('<I', 8)


def execute(name, statements, namespace, optimize=0):
    compiled = compile(ast.Module(body=statements, type_ignores=[]), str(SCRIPTS[name]),
                       'exec', optimize=optimize)
    exec(compiled, namespace)


def load_functions(name, names, namespace):
    execute(name, [statement for statement in TREES[name].body
                  if isinstance(statement, ast.FunctionDef) and statement.name in names], namespace)
    return namespace


def calls(statement, owner, attribute):
    return any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and
               isinstance(node.func.value, ast.Name) and node.func.value.id == owner and
               node.func.attr == attribute for node in ast.walk(statement))


def assigned(statement, name):
    return isinstance(statement, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == name for target in statement.targets)


def mock_import(module):
    loader = SimpleNamespace(exec_module=mock.Mock())
    return SimpleNamespace(util=SimpleNamespace(
        spec_from_file_location=mock.Mock(return_value=SimpleNamespace(loader=loader)),
        module_from_spec=mock.Mock(return_value=module)))


def profile(raw=SKU12, memory_bytes=BANKS['9g'], reservations=()):
    module = ModuleType('host_mock_ram_profile')
    nodes = {
        '/': {'model': b'Qualcomm Technologies, Inc. fuxi\0'},
        '/memory': {'reg': struct.pack('>QQ', BASE, memory_bytes)},
        '/soc/interrupt-controller@17100000': {
            'reg': struct.pack('>4I', 0x17100000, 0x10000, 0x17180000, 0x200000)},
        '/soc/ufshc@1d84000': {'reg': struct.pack('>II', 0x1d84000, 0x3000)},
        '/reserved-memory/splash_region': {'reg': struct.pack('>QQ', 0xb8000000, 0x2b00000)},
    }
    if raw is not None:
        nodes['/memory']['ddr_size'] = raw
    parser = SimpleNamespace(
        parse=mock.Mock(side_effect=lambda data: (copy.deepcopy(nodes), list(reservations), None)),
        describe=mock.Mock(return_value={'nodes': {}}))
    module.__dict__.update(__file__=str(SCRIPTS['profile']), struct=struct, Path=Path,
                           importlib=mock_import(parser))
    constants = [statement for statement in TREES['profile'].body if isinstance(statement, ast.Assign)
                 and all(isinstance(node, ast.Name) and node.id.isupper()
                         for target in statement.targets for node in ast.walk(target)
                         if isinstance(node, ast.Name))]
    execute('profile', constants, module.__dict__)
    load_functions('profile', {'configure_ram', 'validate_ram_sku', 'memory_contains', 'setprop',
                              'validate_live', 'reserve_gpu'}, module.__dict__)
    return module


class Options(SimpleNamespace):
    """模擬 argparse 結果：沒列出的選項一律當成沒給（None），產生器新增的開關不必逐一補進測試。"""
    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return None


class Chosen:
    def __init__(self, layout='full', sku=ADT12):
        self.name = 'chosen'
        self.props = [
            ('dram-base', 0, struct.pack('<Q', BASE)),
            ('dram-size', 0, struct.pack('<Q', BANKS[layout] - GPU_BYTES)),
            ('fuxi-gpu-memory', 0, struct.pack('<2Q', BASE + BANKS[layout] - GPU_BYTES, GPU_BYTES)),
            ('fuxi-root-extents', 7, b'host-only-root-mapping'),
            ('fuxi-root-blocks', 0, struct.pack('<Q', 20 * 1024**3 // 4096)),
            ('fuxi,sbshape', 0, struct.pack('<I', 300127)),
            ('fuxi,inject', 0, struct.pack('<I', 2)),
            ('identity', 3, b'host-only-identity'),
        ]
        if sku is not None:
            self.props.append(('fuxi,ram-sku', 0, sku))

    def prop(self, name):
        return next((value for key, flags, value in self.props if key == name), None)


def payload(layout):
    data = bytearray(696)
    data[:8] = b'SWEETXNU'
    struct.pack_into('<I', data, 8, 1)
    struct.pack_into('<2Q', data, 32, 680, 16)
    struct.pack_into('<2Q', data, 56, BASE, BANKS[layout] - GPU_BYTES)
    return bytes(data)


class LoaderSkuTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='fuxi-loader-sku-host-')
        self.addCleanup(temporary.cleanup)
        self.temporary = Path(temporary.name)
        self.capture = mock.Mock(read_bytes=mock.Mock(return_value=b'host-only-mock-fdt'))
        self.sequence = 0
        self.events = []

    def parse_ram_options(self, arguments=(), optimize=0):
        statements = TREES['ram'].body
        start = next(index for index, statement in enumerate(statements) if assigned(statement, 'parser'))
        parsed = next(index for index, statement in enumerate(statements) if assigned(statement, 'args'))
        end = next(index for index in range(parsed + 1, len(statements))
                   if isinstance(statements[index], ast.Assert))
        namespace = {'argparse': argparse, 'Path': Path, 'workspace': self.temporary}
        argv = ['host-only-ram-parser', 'native-host-mock-loader', 'native-host-source-loader',
                'kernel-host-mock-artifact', *arguments]
        with mock.patch.object(sys, 'argv', argv), mock.patch.object(sys, 'stderr', io.StringIO()):
            execute('ram', statements[start:end], namespace, optimize)
        return namespace['args']

    def run_pause(self, arguments=(), source_line='host-only=1', marker=b'FUXI BATTERY: poll-pause %s', optimize=0):
        args = self.parse_ram_options(arguments, optimize)
        kernel = mock.Mock(read_bytes=mock.Mock(return_value=marker))
        namespace = {'args': args, 'kernel': kernel, 'command_line': source_line}
        body = TREES['ram'].body
        start = next(index for index, statement in enumerate(body) if assigned(statement, 'command_line'))
        end = next(index for index, statement in enumerate(body) if calls(statement, 'layout', 'configure_ram'))
        statements = [statement for statement in body[start + 1:end]
                      if any((isinstance(node, ast.Attribute) and node.attr.startswith('battery_get_pause')) or
                             (isinstance(node, ast.Constant) and isinstance(node.value, str) and
                              node.value.startswith(('fuxibatpause=', 'fuxibatpausedelay=')))
                             for node in ast.walk(statement))]
        self.assertTrue(statements)
        execute('ram', statements, namespace, optimize)
        return namespace

    def run_ram(self, layout='9g', raw=SKU12, requested='auto', source_sku=ADT12, battery_audit=False, pmic_mode=0):
        self.sequence += 1
        self.output = self.temporary / ('ram-output-' + str(self.sequence))
        artifact = self.temporary / ('artifact-' + str(self.sequence))
        artifact.mkdir()
        (artifact / 'fuxi.adt').write_bytes(b'host-only-mock-adt')
        module = profile(raw)
        original = Chosen(sku=source_sku)
        arguments = ['--ram-layout', layout, '--ram-sku', requested]
        if battery_audit:
            arguments.append('--battery-audit')
        if pmic_mode:
            arguments.append({1: '--pmic-survey', 2: '--pmic-torch-pulse', 3: '--pmic-torch-runtime'}[pmic_mode])
        args = self.parse_ram_options(arguments)
        args.live_fdt = self.capture
        namespace = {
            'layout': module, 'tree': SimpleNamespace(children=[original]), 'struct': struct,
            'original_props': {name: value for name, flags, value in original.props},
            'original_rows': copy.deepcopy(original.props),
            'args': args, 'rtc_record': None,   # 沒給 --rtc-calibration 時產生器的預設
            'artifact': artifact, 'output': self.output,
            'adt': SimpleNamespace(parse=lambda data: (SimpleNamespace(children=[Chosen(layout)]), len(data))),
        }
        statements = TREES['ram'].body
        execute('ram', [next(statement for statement in statements if assigned(statement, 'pmic_mode'))], namespace)
        self.assertEqual(namespace['pmic_mode'], pmic_mode)
        start = next(index for index, statement in enumerate(statements)
                     if calls(statement, 'layout', 'configure_ram'))
        end = next(index for index, statement in enumerate(statements) if calls(statement, 'output', 'mkdir'))
        execute('ram', statements[start:end + 1], namespace)
        return namespace

    def run_chain(self, layout='9g', raw=SKU12, requested='auto'):
        module = profile(raw)
        validator = module.validate_live
        self.events = []

        def validate(*arguments):
            self.events.append('sku_guard')
            return validator(*arguments)

        def read_bytes(path):
            if path.name == 'payload.bin':
                return payload(layout)
            if path.name == 'fuxi-live-20261116.dtb':
                return b'host-only-mock-fdt'
            raise AssertionError('unexpected host read: ' + str(path))

        module.validate_live = validate
        namespace = {
            # os：fuxi-ios 公開倉庫把 NDK 路徑改成讀 LOCALAPPDATA，同一份測試兩邊都要能跑
            '__file__': str(SCRIPTS['chain']), 'Path': Path, 're': re, 'struct': struct, 'json': json, 'os': os,
            'sys': SimpleNamespace(argv=['build-chain.py', 'chain-host-mock', '--ram-sku', requested],
                                   path=SimpleNamespace(insert=mock.Mock())),
            'importlib': mock_import(module),
        }
        end = next(index for index, statement in enumerate(TREES['chain'].body) if assigned(statement, 'boot_a'))
        statements = [statement for statement in TREES['chain'].body[:end]
                      if not isinstance(statement, (ast.Import, ast.ImportFrom))]
        metadata = json.dumps({'layout': '9g', 'usable': BANKS['9g'] - GPU_BYTES,
                               'scratch': BASE + BANKS['9g'] - GPU_BYTES, 'scratch_size': GPU_BYTES})
        with mock.patch.object(Path, 'read_bytes', autospec=True, side_effect=read_bytes), \
                mock.patch.object(Path, 'read_text', return_value=metadata), \
                mock.patch.object(Path, 'mkdir', autospec=True,
                                  side_effect=lambda path, **options: self.events.append('mkdir')):
            execute('chain', statements, namespace)
        return namespace, module

    def run_w18(self, raw=SKU12, requested='auto', source_sku=ADT12):
        module = profile(raw)
        tree = SimpleNamespace(children=[Chosen('9g', source_sku)])
        namespace = {
            'STORAGE': self.temporary, 'WORKSPACE': self.temporary, 'TOOLS': self.temporary,
            'RAM_BASE': BASE, 'RAM_SIZE': BANKS['9g'] - GPU_BYTES,
            'GPU_BASE': BASE + BANKS['9g'] - GPU_BYTES, 'GPU_SIZE': GPU_BYTES,
            'struct': struct, 'json': json, 'importlib': mock_import(module), 'GPU_INPUTS': (),
            'OFF_PROPS': (),
            'sums': mock.Mock(return_value={'payload.bin': 'mock-payload-pin', 'boot.img': 'mock-boot-pin'}),
            'checked_file': mock.Mock(), 'parse_tree': mock.Mock(return_value=tree),
            'digest': mock.Mock(return_value='mock-fdt-pin'), 'verify_map': mock.Mock(return_value={}),
            'arguments': mock.Mock(return_value=('host-only-mock-arguments', [])),
            'asset_report': mock.Mock(return_value={'gaps': [], 'bdf_recorded': False, 'provenance': None}),
        }
        load_functions('w18', {'require', 'chosen_node', 'inspect'}, namespace)
        args = Options(source='native-host-mock-loader', artifact='kernel-host-mock-artifact',
                               live_fdt=self.temporary / 'mock.dtb', ram_sku=requested,
                               map_record=self.temporary / 'map.json', bdf=None, mlo=0,
                               host_cap_secondary=False, omit_nm_modem=False,
                               shim_reference=None, assets_manifest=None)
        metadata = {'layout': '9g', 'usable': BANKS['9g'] - GPU_BYTES,
                    'scratch': BASE + BANKS['9g'] - GPU_BYTES, 'live_fdt_sha256': 'mock-fdt-pin'}
        with mock.patch.object(Path, 'read_bytes', autospec=True,
                               side_effect=lambda path: payload('9g') if path.name == 'payload.bin' else b'mock-fdt'), \
                mock.patch.object(Path, 'read_text', return_value=json.dumps(metadata)), \
                mock.patch.object(Path, 'is_dir', return_value=False):
            return namespace['inspect'](args)[0]

    def run_verify(self, layout='9g', raw=SKU12, source_sku=ADT12, optimize=0, error=None):
        check_output = mock.Mock(return_value=raw, side_effect=error)
        # os：公開倉庫的 adb 序號改讀 FUXI_ANDROID_SERIAL
        namespace = {'chosen': Chosen(layout, source_sku), 'subprocess': SimpleNamespace(check_output=check_output),
                     'struct': struct, 'payload': payload(layout), 'os': os}
        statements = TREES['verify'].body
        start = next(index for index, statement in enumerate(statements) if assigned(statement, 'physical_sku'))
        end = next(index for index, statement in enumerate(statements)
                   if isinstance(statement, ast.If) and 'memory_size' in ast.unparse(statement.test))
        execute('verify', statements[start:end], namespace, optimize)
        check_output.assert_called_once()
        return namespace

    def test_physical_12g_full_is_not_full_capacity_admission(self):
        module = profile()
        module.configure_ram('full')
        evidence = module.validate_live(self.capture, True)
        self.assertEqual(evidence['ram_sku'], '12g')
        self.assertEqual(evidence['xnu_usable_bytes'], 0x13e000000)
        self.assertEqual(evidence['gpu_scratch_base'], 0x9fe000000)
        self.assertFalse(evidence['runtime_sku_verified'])

    def test_physical_12g_9g_admission_is_separate(self):
        module = profile()
        module.configure_ram('9g')
        evidence = module.validate_live(self.capture, True, '12g')
        self.assertEqual(evidence['ram_sku'], '12g')
        self.assertEqual(evidence['xnu_usable_bytes'], 0x23e000000)
        self.assertEqual(evidence['gpu_scratch_base'], 0xafe000000)
        self.assertTrue(evidence['source_sku_verified'])
        self.assertFalse(evidence['runtime_sku_verified'])

    def test_profile_rejects_8g_despite_advertised_9g_bank(self):
        for layout in BANKS:
            with self.subTest(layout=layout), self.assertRaisesRegex(ValueError, 'own measured'):
                module = profile(SKU8)
                module.configure_ram(layout)
                module.validate_live(self.capture, True)

    def test_profile_rejects_missing_malformed_and_wrong_endian(self):
        for raw in (None, b'', b'\x0c', struct.pack('>Q', 12), struct.pack('<I', 12), bytearray(SKU12)):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                profile(raw).validate_live(self.capture, True)

    def test_profile_rejects_unknown_capacity(self):
        for capacity in (0, 4, 6, 16):
            with self.subTest(capacity=capacity), self.assertRaisesRegex(ValueError, 'unsupported'):
                profile(struct.pack('>I', capacity)).validate_live(self.capture, True)

    def test_profile_rejects_requested_sku_mismatch(self):
        for raw, requested in ((SKU12, '8g'), (SKU8, '12g')):
            with self.subTest(requested=requested), self.assertRaisesRegex(ValueError, 'differs'):
                profile(raw).validate_live(self.capture, True, requested)

    def test_profile_never_uses_admission_names_as_physical_sku(self):
        for requested in ('full', '9g', '', None):
            with self.subTest(requested=requested), self.assertRaisesRegex(ValueError, 'unsupported'):
                profile().validate_live(self.capture, True, requested)

    def test_9g_requires_full_bank_including_gpu_tail(self):
        for memory_bytes in (BANKS['full'], BANKS['9g'] - GPU_BYTES):
            module = profile(memory_bytes=memory_bytes)
            module.configure_ram('9g')
            with self.subTest(memory_bytes=memory_bytes), self.assertRaisesRegex(ValueError, 'outside advertised'):
                module.validate_live(self.capture, True)

    def test_gpu_reservation_still_rejects_valid_sku(self):
        module = profile(reservations=({'address': hex(0xafe000000), 'size': hex(4096)},))
        module.configure_ram('9g')
        with self.assertRaisesRegex(ValueError, 'reserve map'):
            module.validate_live(self.capture, True)

    def test_reserve_gpu_adds_sku_without_changing_identity_or_root(self):
        for layout in BANKS:
            with self.subTest(layout=layout):
                module = profile()
                module.configure_ram(layout)
                chosen = Chosen(sku=None)
                original = {name: (flags, value) for name, flags, value in chosen.props}
                tree = SimpleNamespace(children=[chosen])
                module.reserve_gpu(tree)
                self.assertEqual(chosen.prop('fuxi,ram-sku'), ADT12)
                self.assertEqual({name: (flags, value) for name, flags, value in chosen.props
                                  if name not in ('dram-size', 'fuxi-gpu-memory', 'fuxi,ram-sku')},
                                 {name: value for name, value in original.items()
                                  if name not in ('dram-size', 'fuxi-gpu-memory', 'fuxi,ram-sku')})
                count = len(chosen.props)
                module.reserve_gpu(tree)
                self.assertEqual(len(chosen.props), count)

    def test_reserve_gpu_rejects_explicit_foreign_adt_sku(self):
        for sku in (ADT8, b'', SKU12):
            with self.subTest(sku=sku), self.assertRaisesRegex(ValueError, 'physical RAM SKU'):
                profile().reserve_gpu(SimpleNamespace(children=[Chosen(sku=sku)]))

    def test_ram_full_12g_reaches_first_output_creation(self):
        result = self.run_ram('full')
        self.assertEqual(result['sku_metadata']['ram_sku'], '12g')
        self.assertTrue(self.output.is_dir())

    def test_ram_9g_12g_reaches_first_output_creation(self):
        result = self.run_ram('9g')
        self.assertEqual(result['sku_metadata']['xnu_usable_bytes'], 0x23e000000)
        self.assertTrue(self.output.is_dir())

    def test_ram_rejects_missing_8g_before_output_creation(self):
        for layout in BANKS:
            for raw in (None, b'', SKU8, struct.pack('<I', 12)):
                with self.subTest(layout=layout, raw=raw), self.assertRaises(ValueError):
                    self.run_ram(layout, raw)
                self.assertFalse(self.output.exists())

    def test_ram_rejects_explicit_8g_request_before_output_creation(self):
        with self.assertRaisesRegex(ValueError, 'differs'):
            self.run_ram(requested='8g')
        self.assertFalse(self.output.exists())

    def test_ram_full_legacy_adt_accepts_new_verified_sku(self):
        result = self.run_ram('full', source_sku=None)
        self.assertEqual(result['chosen'].prop('fuxi,ram-sku'), ADT12)
        self.assertTrue(self.output.is_dir())

    def test_ram_9g_legacy_adt_accepts_new_verified_sku(self):
        result = self.run_ram('9g', source_sku=None)
        self.assertEqual(result['chosen'].prop('fuxi,ram-sku'), ADT12)
        self.assertTrue(self.output.is_dir())

    def test_ram_legacy_adt_sku_addition_also_survives_pmic_guard(self):
        for layout in BANKS:
            with self.subTest(layout=layout):
                result = self.run_ram(layout, source_sku=None, pmic_mode=1)
                self.assertEqual(result['chosen'].prop('fuxi,ram-sku'), ADT12)
                self.assertEqual(result['chosen'].prop('fuxi,pmic'), struct.pack('<I', 1))
                self.assertTrue(result['args'].pmic_survey)
                roots = {'fuxi-root-extents', 'fuxi-root-blocks'}
                self.assertEqual([row for row in result['chosen'].props if row[0] in roots],
                                 [row for row in result['original_rows'] if row[0] in roots])
                self.assertTrue(self.output.is_dir())

    def test_ram_first_sku_tag_with_pmic1_and_audit_keeps_root_pins(self):
        result = self.run_ram('9g', source_sku=None, pmic_mode=1, battery_audit=True)
        self.assertEqual(result['chosen'].prop('fuxi,ram-sku'), ADT12)
        self.assertEqual(result['chosen'].prop('fuxi,pmic'), struct.pack('<I', 1))
        self.assertEqual(result['chosen'].prop('fuxi,batteryaudit'), struct.pack('<I', 1))
        roots = {'fuxi-root-extents', 'fuxi-root-blocks'}
        self.assertEqual([row for row in result['chosen'].props if row[0] in roots],
                         [row for row in result['original_rows'] if row[0] in roots])
        self.assertEqual(result['chosen'].prop('identity'), result['original_props']['identity'])

    def test_chain_profiles_come_from_admission_not_physical_sku(self):
        for layout in BANKS:
            with self.subTest(layout=layout):
                result, module = self.run_chain(layout)
                self.assertEqual(result['sku_evidence']['ram_sku'], '12g')
                self.assertEqual(module.MEM_SIZE, BANKS[layout] - GPU_BYTES)
                self.assertEqual(result['ram9g'], layout == '9g')
                self.assertEqual(self.events, ['sku_guard', 'mkdir'])

    def test_chain_rejects_missing_8g_or_wrong_endian(self):
        for layout in BANKS:
            for raw in (None, b'', SKU8, struct.pack('<I', 12)):
                with self.subTest(layout=layout, raw=raw), self.assertRaises(ValueError):
                    self.run_chain(layout, raw)
                self.assertEqual(self.events, ['sku_guard'])

    def test_chain_rejects_explicit_8g_request(self):
        with self.assertRaisesRegex(ValueError, 'differs'):
            self.run_chain(requested='8g')

    def test_chain_missing_sku_does_not_create_output(self):
        with self.assertRaises(ValueError):
            self.run_chain(raw=None)
        self.assertEqual(self.events, ['sku_guard'])

    def test_builders_guard_before_file_write_or_compiler(self):
        for name, owner in (('ram', 'layout'), ('chain', 'profile')):
            statements = TREES[name].body
            guard = next(index for index, statement in enumerate(statements) if calls(statement, owner, 'validate_live'))
            writes = [index for index, statement in enumerate(statements)
                      if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and
                             node.func.attr in ('write_bytes', 'write_text', 'run', 'check_output')
                             for node in ast.walk(statement)) and not isinstance(statement, ast.FunctionDef)]
            with self.subTest(name=name):
                self.assertTrue(writes)
                self.assertTrue(all(guard < index for index in writes))

    def test_w18_valid_12g_evidence_stays_nonruntime(self):
        result = self.run_w18()
        self.assertEqual(result['ram_sku_evidence']['ram_sku'], '12g')
        self.assertEqual(result['ram_sku_evidence']['xnu_usable_bytes'], 0x23e000000)
        self.assertFalse(result['ram_sku_evidence']['runtime_sku_verified'])
        self.assertFalse(result['ready_to_build'])

    def test_w18_rejects_missing_8g_and_wrong_endian(self):
        for raw in (None, b'', SKU8, struct.pack('>Q', 12), struct.pack('<I', 12)):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.run_w18(raw)

    def test_w18_rejects_explicit_8g_request(self):
        with self.assertRaisesRegex(ValueError, 'differs'):
            self.run_w18(requested='8g')

    def test_w18_rejects_explicit_foreign_source_adt_sku(self):
        with self.assertRaises(ValueError):
            self.run_w18(source_sku=ADT8)

    def test_w18_inspect_failure_never_calls_build(self):
        namespace = {'argparse': argparse, '__doc__': None, 'Path': Path, 'WORKSPACE': self.temporary,
                     'SOURCE': 'native-host-mock-loader', 'ARTIFACT': 'kernel-host-mock-artifact',
                     'COMPILER': self.temporary, 're': re, 'struct': struct, 'subprocess': subprocess,
                     'inspect': mock.Mock(side_effect=ValueError('mock SKU refused')),
                     'build': mock.Mock(), 'json': json}
        load_functions('w18', {'require', 'main'}, namespace)
        with mock.patch.object(sys, 'argv', ['prepare-wlan-w18-loader.py', 'build']), \
                self.assertRaisesRegex(SystemExit, 'mock SKU refused'):
            namespace['main']()
        namespace['build'].assert_not_called()

    def test_verifier_12g_accepts_full_and_9g_admission(self):
        for layout in BANKS:
            with self.subTest(layout=layout):
                result = self.run_verify(layout)
                self.assertEqual(result['physical_sku'], ADT12)
                self.assertEqual(result['live_sku'], SKU12)
                self.assertEqual(result['memory_size'], BANKS[layout] - GPU_BYTES)

    def test_verifier_rejects_missing_8g_or_malformed_measurement(self):
        for raw in (None, b'', SKU8, b'\x0c', struct.pack('>Q', 12), struct.pack('<I', 12)):
            with self.subTest(raw=raw), self.assertRaises(AssertionError):
                self.run_verify(raw=raw)

    def test_verifier_rejects_explicit_foreign_adt_sku(self):
        with self.assertRaisesRegex(AssertionError, 'loader needs'):
            self.run_verify(source_sku=ADT8)

    def test_verifier_allows_legacy_adt_only_with_measured_12g(self):
        self.run_verify(source_sku=None)
        with self.assertRaisesRegex(AssertionError, 'connected device'):
            self.run_verify(raw=None, source_sku=None)

    def test_verifier_failed_measurement_does_not_succeed(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_verify(error=subprocess.CalledProcessError(1, ['mock-only']))

    def test_battery_defaults_are_off_and_do_not_read_kernel(self):
        result = self.run_pause()
        self.assertFalse(result['args'].battery_audit)
        self.assertEqual(result['args'].battery_get_pause_ms, 0)
        self.assertEqual(result['args'].battery_get_pause_delay_ms, 0)
        self.assertEqual(result['command_line'], 'host-only=1')
        result['kernel'].read_bytes.assert_not_called()
        prepared = self.run_ram('full')
        self.assertIsNone(prepared['chosen'].prop('fuxi,batteryaudit'))

    def test_battery_audit_optin_only_adds_audit_property(self):
        result = self.run_ram('full', battery_audit=True)
        self.assertEqual(result['chosen'].prop('fuxi,batteryaudit'), struct.pack('<I', 1))
        self.assertEqual({name: value for name, flags, value in result['chosen'].props
                          if name != 'fuxi,batteryaudit'}, result['original_props'])

    def test_battery_duration_is_exactly_zero_or_130000(self):
        for duration in (0, 130000):
            with self.subTest(duration=duration):
                self.assertEqual(self.parse_ram_options(['--battery-get-pause-ms', str(duration)])
                                 .battery_get_pause_ms, duration)
        for duration in (-1, 1, 129999, 130001):
            with self.subTest(duration=duration), self.assertRaises(SystemExit):
                self.parse_ram_options(['--battery-get-pause-ms', str(duration)])

    def test_battery_delay_is_bounded_even_in_optimized_bytecode(self):
        for optimize in (0, 1):
            for delay in (0, 1, 60000):
                with self.subTest(optimize=optimize, delay=delay):
                    args = self.parse_ram_options(['--battery-get-pause-ms', '130000',
                                                   '--battery-get-pause-delay-ms', str(delay)], optimize)
                    self.assertEqual(args.battery_get_pause_delay_ms, delay)
            for delay in (-1, 60001):
                with self.subTest(optimize=optimize, delay=delay), self.assertRaisesRegex(ValueError, 'between'):
                    self.parse_ram_options(['--battery-get-pause-ms', '130000',
                                            '--battery-get-pause-delay-ms', str(delay)], optimize)

    def test_battery_nonzero_delay_requires_duration(self):
        for delay in (1, 60000):
            with self.subTest(delay=delay), self.assertRaisesRegex(ValueError, 'explicit pause duration'):
                self.parse_ram_options(['--battery-get-pause-delay-ms', str(delay)])

    def test_battery_exact_production_marker_is_required(self):
        for marker in (b'', b'FUXI BATTERY: poll-pause', b'FUXI BATTERY: poll-pause %u'):
            with self.subTest(marker=marker), self.assertRaisesRegex(ValueError, 'production battery'):
                self.run_pause(['--battery-get-pause-ms', '130000'], marker=marker)
        result = self.run_pause(['--battery-get-pause-ms', '130000'])
        result['kernel'].read_bytes.assert_called_once()

    def test_battery_pause_and_delay_tokens_are_bounded_optin(self):
        result = self.run_pause(['--battery-get-pause-ms', '130000', '--battery-get-pause-delay-ms', '60000'])
        self.assertEqual(result['command_line'].split(),
                         ['host-only=1', 'fuxibatpause=130000', 'fuxibatpausedelay=60000'])
        result = self.run_pause(['--battery-get-pause-ms', '130000'])
        self.assertNotIn('fuxibatpausedelay=', result['command_line'])

    def test_battery_pause_rejects_existing_source_tokens_when_enabled(self):
        for token in ('fuxibatpause=130000', 'fuxibatpausedelay=0'):
            with self.subTest(token=token), self.assertRaisesRegex(ValueError, 'already carries'):
                self.run_pause(['--battery-get-pause-ms', '130000'], source_line='host-only=1 ' + token)

    def test_battery_pause_obeys_v1_command_line_limit(self):
        suffix = ' fuxibatpause=130000'
        result = self.run_pause(['--battery-get-pause-ms', '130000'], source_line='x' * (607 - len(suffix)))
        self.assertEqual(len(result['command_line'].encode('ascii')), 607)
        with self.assertRaisesRegex(ValueError, 'exceeds the v1 command line'):
            self.run_pause(['--battery-get-pause-ms', '130000'], source_line='x' * (608 - len(suffix)))

    def test_battery_default_off_rejects_inherited_source_pause(self):
        with self.assertRaisesRegex(ValueError, 'already carries'):
            self.run_pause(source_line='host-only=1 fuxibatpause=130000')

    def test_verifier_optimized_bytecode_still_rejects_8g(self):
        with self.assertRaises(AssertionError):
            self.run_verify(raw=SKU8, source_sku=ADT8, optimize=1)


if __name__ == '__main__':
    unittest.main()
