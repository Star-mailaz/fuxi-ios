#!/usr/bin/env python3
"""Bounded synthetic tests against the production read-only BDF inventory helper."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import struct
import subprocess
import sys
import tempfile
import unittest


sys.dont_write_bytecode = True
SCRIPT = Path(__file__).with_name('fuxi-wlan-bdf-inventory.py')
spec = importlib.util.spec_from_file_location('fuxi_wlan_bdf_inventory', SCRIPT)
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)
NAME = b'bus=pci,qmi-chip-id=2,qmi-board-id=255'
PCI_NAME = b'bus=pci,vendor=17cb,device=1107,subsystem-vendor=17cb,subsystem-device=3378,qmi-chip-id=2,qmi-board-id=255,variant=fixture'


def tlv(identifier, value):
    return struct.pack('<II', identifier, len(value)) + value + b'\0' * (-len(value) % 4)


def board(names=(NAME,), data=b'fixture-board-data', kind=0):
    return tlv(kind, b''.join(tlv(0, name) for name in names) + tlv(1, data))


def container(*entries):
    return inventory.MAGIC + b''.join(entries or (board(),))


def elf32():
    identifier = b'\x7fELF\x01\x01\x01' + b'\0' * 9
    header = struct.pack('<HHIIIIIHHHHHH', 2, 40, 1, 0, 52, 0, 0, 52, 32, 1, 0, 0, 0)
    program = struct.pack('<IIIIIIII', 1, 84, 0, 0, 4, 4, 4, 4)
    return identifier + header + program + b'BDF!'


class BoardNameTests(unittest.TestCase):
    def test_pci_attributes_decoded_without_selection(self):
        result = inventory.parse_board_name(PCI_NAME)
        self.assertEqual(result['attributes']['device'], 0x1107)
        self.assertEqual(result['attributes']['qmi-board-id'], 255)
        self.assertEqual(result['attributes']['variant'], 'fixture')
        self.assertEqual(result['ids_source'], 'container_name_not_live_hardware')

    def test_bus_only_regdb(self):
        self.assertEqual(inventory.parse_board_name(b'bus=pci', 'regdb')['attributes'], {'bus': 'pci'})
        with self.assertRaises(ValueError):
            inventory.parse_board_name(b'bus=pci')

    def test_missing_required_attributes(self):
        for name in (b'qmi-chip-id=2,qmi-board-id=255', b'bus=pci,qmi-chip-id=2',
                     b'bus=pci,qmi-board-id=255', NAME + b',vendor=17cb', b'bus=pci,variant=test'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                inventory.parse_board_name(name)

    def test_duplicates_unknown_empty_and_non_ascii(self):
        for name in (NAME + b',bus=pci', NAME + b',variant=one,variant=two', NAME + b',unknown=1',
                     NAME + b',variant=', NAME + b'\0', NAME + b'\xff', NAME + b'\n', NAME + b',variant=a=b'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                inventory.parse_board_name(name)

    def test_ids_decimal_hex_and_overflow(self):
        for value in (b'0xff', b'-1', b'4294967296', b'0255', b'1' * 30):
            with self.subTest(value=value), self.assertRaises(ValueError):
                inventory.parse_board_name(b'bus=pci,qmi-chip-id=2,qmi-board-id=' + value)
        self.assertEqual(inventory.parse_board_name(b'bus=pci,qmi-chip-id=0,qmi-board-id=4294967295')['attributes']['qmi-board-id'], 0xffffffff)
        with self.assertRaises(ValueError):
            inventory.parse_board_name(PCI_NAME.replace(b'vendor=17cb', b'vendor=17c', 1))
        with self.assertRaises(ValueError):
            inventory.parse_board_name(PCI_NAME.replace(b'bus=pci', b'bus=ahb'))

    def test_name_bound(self):
        with self.assertRaises(ValueError):
            inventory.parse_board_name(NAME + b',variant=' + b'x' * inventory.MAX_NAME_BYTES)


class ContainerTests(unittest.TestCase):
    def test_valid_aliases_hashes_offsets_and_regdb(self):
        blob = container(board((NAME, PCI_NAME)), board((b'bus=pci',), b'regdb', 1))
        result = inventory.parse_board2(blob)
        self.assertEqual(len(result['records']), 2)
        self.assertEqual(len(result['records'][0]['names']), 2)
        for record in result['records']:
            data = blob[record['data_offset']:record['data_offset'] + record['bytes']]
            self.assertEqual(record['sha256'], hashlib.sha256(data).hexdigest())

    def test_magic_and_empty_container(self):
        for blob in (b'ATH12K-BOARD\0', inventory.MAGIC, b'X' + container()[1:], container()[1:]):
            with self.subTest(blob=blob[:16]), self.assertRaises(ValueError):
                inventory.parse_board2(blob)

    def test_every_truncated_prefix_rejected(self):
        blob = container()
        for length in range(len(blob)):
            with self.subTest(length=length), self.assertRaises(ValueError):
                inventory.parse_board2(blob[:length])

    def test_alignment_u32_overflow_and_declared_size(self):
        for size in (0xffffffff, 0xfffffffd, 0xfffffffc, 4096):
            with self.subTest(size=size), self.assertRaises(ValueError):
                inventory.parse_board2(inventory.MAGIC + struct.pack('<II', 0, size) + b'x' * 12)
        with self.assertRaises(ValueError):
            inventory.checked_range(0xfffffff0, 32, 1 << 32, 32)

    def test_nested_truncation_unknown_and_padding(self):
        payloads = (b'x', struct.pack('<II', 0, 100), tlv(7, b'x'),
                    struct.pack('<II', 0, 1) + b'x\0\0\x01')
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                inventory.parse_board2(container(tlv(0, payload)))
        with self.assertRaises(ValueError):
            inventory.parse_board2(container(tlv(2, b'unknown')))

    def test_duplicate_names_data_and_cross_records(self):
        invalid = (board((NAME, NAME)), board() + board(),
                   tlv(0, tlv(0, NAME) + tlv(1, b'a') + tlv(1, b'b')),
                   tlv(0, tlv(0, NAME) + tlv(1, b'a') + tlv(0, PCI_NAME)))
        for entry in invalid:
            with self.subTest(entry=entry[:16]), self.assertRaises(ValueError):
                inventory.parse_board2(container(entry))

    def test_missing_name_data_empty_data_and_regdb_only(self):
        for entry in (tlv(0, b''), tlv(0, tlv(0, NAME)), tlv(0, tlv(1, b'data')),
                      board(data=b''), board((b'bus=pci',), b'regdb', 1)):
            with self.subTest(entry=entry[:16]), self.assertRaises(ValueError):
                inventory.parse_board2(container(entry))

    def test_bounds_for_files_records_aliases_and_tlvs(self):
        with self.assertRaises(ValueError):
            inventory.parse_board2(inventory.MAGIC + b'x' * inventory.MAX_FILE_BYTES)
        aliases = tuple(b'bus=pci,qmi-chip-id=2,qmi-board-id=' + str(index).encode() for index in range(inventory.MAX_ALIASES + 1))
        with self.assertRaises(ValueError):
            inventory.parse_board2(container(board(aliases)))
        entries = tuple(board((b'bus=pci,qmi-chip-id=2,qmi-board-id=' + str(index).encode(),)) for index in range(inventory.MAX_RECORDS + 1))
        with self.assertRaises(ValueError):
            inventory.parse_board2(container(*entries))
        with self.assertRaises(ValueError):
            list(inventory.parse_tlvs(tlv(1, b'a'), 0, [inventory.MAX_TLVS]))

    def test_bounded_malformed_fuzz_uses_production_parser(self):
        generator = random.Random(18)
        for _ in range(256):
            blob = inventory.MAGIC + generator.randbytes(generator.randrange(1, 128))
            try:
                inventory.parse_board2(blob)
            except ValueError:
                continue
            self.fail('random malformed container unexpectedly accepted')


class RawInventoryTests(unittest.TestCase):
    def test_elf64_both_endian_wrappers(self):
        for endian, encoding in (('<', 1), ('>', 2)):
            identifier = b'\x7fELF' + bytes((2, encoding, 1)) + b'\0' * 9
            header = struct.pack(endian + 'HHIQQQIHHHHHH', 2, 183, 1, 0, 64, 0, 0, 64, 56, 1, 0, 0, 0)
            program = struct.pack(endian + 'IIQQQQQQ', 1, 4, 120, 0, 0, 4, 4, 4)
            result = inventory.parse_elf(identifier + header + program + b'BDF!')
            self.assertEqual(result['elf']['class_bits'], 64)
            self.assertEqual(result['elf']['endian'], 'little' if encoding == 1 else 'big')

    def test_elf_wrapper_and_segment_hash_not_calibration_id(self):
        result = inventory.inventory_bytes(elf32(), 'bd_m3gl.elf', 'synthetic fixture')
        self.assertEqual(result['elf']['class_bits'], 32)
        self.assertEqual(result['elf']['segments'][0]['sha256'], hashlib.sha256(b'BDF!').hexdigest())
        self.assertIsNone(result['embedded_calibration_ids'])
        self.assertFalse(result['selected'])
        self.assertFalse(result['filename_hint']['is_live_id'])

    def test_elf_truncation_table_overflow_and_segment_bounds(self):
        blob = elf32()
        for length in (4, 16, 51, 60, len(blob) - 1):
            with self.subTest(length=length), self.assertRaises(ValueError):
                inventory.parse_elf(blob[:length])
        for offset, value, field in ((28, 0xfffffff0, '<I'), (44, 65535, '<H'),
                                     (56, 0xfffffff0, '<I'), (72, 1, '<I'), (80, 3, '<I')):
            altered = bytearray(blob)
            struct.pack_into(field, altered, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                inventory.parse_elf(bytes(altered))

    def test_opaque_raw_and_suffix_hints_do_not_select(self):
        result = inventory.inventory_bytes(b'not-schema-known', 'bdwlan01.e23', 'synthetic fixture')
        self.assertEqual(result['format'], 'opaque-raw-not-schema-verified')
        self.assertEqual(result['filename_hint']['board_id_hint'], 0x123)
        self.assertFalse(result['selected'])
        self.assertEqual(inventory.filename_hint('bdwlang.e02')['board_id_hint'], 2)
        self.assertIsNone(inventory.filename_hint('unknown.bin'))

    def test_no_format_fallback_on_malformed_known_file(self):
        for data, name in ((b'bad', 'board-2.bin'), (b'bad', 'bd_m3.elf'), (b'QCA-ATHbroken', 'renamed.bin')):
            with self.subTest(name=name), self.assertRaises(ValueError):
                inventory.inventory_bytes(data, name, 'fixture')
        with self.assertRaises(ValueError):
            inventory.inventory_bytes(b'a', 'a.bin', '')

    def test_read_and_cli_are_read_only_and_require_provenance(self):
        with tempfile.TemporaryDirectory(prefix='fuxi-bdf-inventory-test-') as temporary:
            path = Path(temporary) / 'board-2.bin'
            path.write_bytes(container())
            before = (path.read_bytes(), path.stat().st_mtime_ns)
            result = subprocess.run([sys.executable, '-B', str(SCRIPT), '--provenance', 'synthetic fixture', str(path)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"automatic_selection": false', result.stdout)
            self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
            self.assertEqual(list(Path(temporary).iterdir()), [path])
            self.assertEqual(inventory.read_regular(path), before[0])
            duplicate = subprocess.run([sys.executable, '-B', str(SCRIPT), '--provenance', 'fixture', str(path), str(path)],
                                       capture_output=True, text=True, timeout=10)
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertIn('duplicate input path', duplicate.stderr)
            missing = subprocess.run([sys.executable, '-B', str(SCRIPT), str(path)], capture_output=True, timeout=10)
            self.assertNotEqual(missing.returncode, 0)
            with self.assertRaises(ValueError):
                inventory.read_regular(Path(temporary))
            path.write_bytes(b'')
            with self.assertRaises(ValueError):
                inventory.read_regular(path)

    def test_regular_file_size_bound_and_symlink_rejection(self):
        with tempfile.TemporaryDirectory(prefix='fuxi-bdf-bound-test-') as temporary:
            path = Path(temporary) / 'raw.bin'
            with path.open('wb') as stream:
                stream.truncate(inventory.MAX_FILE_BYTES + 1)
            with self.assertRaises(ValueError):
                inventory.read_regular(path)
            path.write_bytes(b'fixture')
            link = Path(temporary) / 'link.bin'
            try:
                os.symlink(path, link)
            except OSError:
                self.skipTest('host does not permit creating a synthetic symlink')
            with self.assertRaises(ValueError):
                inventory.read_regular(link)


class CaptureReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='fuxi-root-receipt-test-')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.manifest = self.directory / 'assets.json'
        self.log = self.directory / 'guest.log'
        self.record = {'provenance': {'method': 'synthetic read-only fixture', 'captured_at': 'fixture-time',
                                     'guest_log': self.log.name},
                       'root_path': '/fixture/root.img', 'root_bytes': 4096, 'version': {'ProductBuildVersion': 'fixture'},
                       'files': {'/usr/sbin/BlueTool': {'runtime_path': '/usr/sbin/BlueTool', 'bytes': 123,
                                                     'sha256': 'a' * 64, 'host_path': 'intentionally-absent'}}}
        self.lines = ['ROOT_ASSETS_MOUNT_OK', 'ROOT_VERSION ' + json.dumps(self.record['version']),
                      'ROOT_DIRECTORY ' + json.dumps({'path': inventory.WLAN_DIRECTORY, 'exists': False}),
                      'ROOT_FILE_SENT /usr/sbin/BlueTool 123', 'ROOT_FILE_COUNT 1',
                      'ROOT_ASSETS_INSPECT_SUCCESS', 'GUEST_OK']
        self.write_fixture()

    def write_fixture(self):
        self.manifest.write_text(json.dumps(self.record), encoding='utf-8')
        self.log.write_text('\n'.join(self.lines), encoding='utf-8')

    def test_observed_absence_is_not_missing_host_filename(self):
        result = inventory.read_root_capture(self.manifest)
        self.assertFalse(result['wlan_directory']['exists'])
        self.assertEqual(result['wlan_directory']['evidence'], 'successful_guest_ROOT_DIRECTORY_receipt')
        self.assertEqual(result['wlan_files_recorded'], 0)
        self.assertEqual(result['payload_files_opened'], 0)
        self.assertFalse(result['bdf_selected'])
        self.assertEqual(result['manifest_sha256'], hashlib.sha256(self.manifest.read_bytes()).hexdigest())

    def test_missing_required_receipt_and_manifest_attributes(self):
        for marker in ('ROOT_DIRECTORY ', 'ROOT_ASSETS_INSPECT_SUCCESS', 'ROOT_VERSION ', 'ROOT_FILE_COUNT '):
            original = self.lines
            self.lines = [line for line in original if not line.startswith(marker)]
            self.write_fixture()
            with self.subTest(marker=marker), self.assertRaises(ValueError):
                inventory.read_root_capture(self.manifest)
            self.lines = original
        del self.record['provenance']['captured_at']
        self.write_fixture()
        with self.assertRaises(ValueError):
            inventory.read_root_capture(self.manifest)

    def test_duplicate_directory_success_and_json_attributes(self):
        for line in (self.lines[2], 'GUEST_OK', self.lines[3]):
            self.lines.append(line)
            self.write_fixture()
            with self.subTest(line=line), self.assertRaises(ValueError):
                inventory.read_root_capture(self.manifest)
            self.lines.pop()
        self.manifest.write_text('{"files":{},"files":{}}', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'duplicate JSON'):
            inventory.read_root_capture(self.manifest)

    def test_directory_boolean_and_file_size_mismatch(self):
        for invalid in ('false', 0, None):
            self.lines[2] = 'ROOT_DIRECTORY ' + json.dumps({'path': inventory.WLAN_DIRECTORY, 'exists': invalid})
            self.write_fixture()
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                inventory.read_root_capture(self.manifest)
        self.lines[2] = 'ROOT_DIRECTORY ' + json.dumps({'path': inventory.WLAN_DIRECTORY, 'exists': False})
        self.record['files']['/usr/sbin/BlueTool']['bytes'] = 124
        self.write_fixture()
        with self.assertRaises(ValueError):
            inventory.read_root_capture(self.manifest)

    def test_absent_directory_cannot_contain_manifest_wlan_file(self):
        runtime_path = inventory.WLAN_DIRECTORY + '/fixture.bin'
        self.record['files'] = {runtime_path: {'runtime_path': runtime_path, 'bytes': 123, 'sha256': 'a' * 64}}
        self.lines[3] = 'ROOT_FILE_SENT ' + runtime_path + ' 123'
        self.write_fixture()
        with self.assertRaisesRegex(ValueError, 'contradicts'):
            inventory.read_root_capture(self.manifest)

    def test_capture_log_escape_and_size_bound(self):
        self.record['provenance']['guest_log'] = '../outside.log'
        self.write_fixture()
        with self.assertRaisesRegex(ValueError, 'inside capture'):
            inventory.read_root_capture(self.manifest)
        with self.manifest.open('wb') as stream:
            stream.truncate(inventory.MAX_MANIFEST_BYTES + 1)
        with self.assertRaises(ValueError):
            inventory.read_root_capture(self.manifest)

    def test_receipt_only_cli_does_not_parse_bluetooth_as_bdf(self):
        result = subprocess.run([sys.executable, '-B', str(SCRIPT), '--provenance', 'synthetic fixture',
                                 '--capture-manifest', str(self.manifest)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report['files'], [])
        self.assertEqual(report['root_capture']['payload_files_opened'], 0)
        self.assertFalse(report['automatic_selection'])


def android_receipt():
    sysfs = '/devices/platform/soc/1c00000.qcom,pcie/pci0000:00/0000:00:00.0/0000:01:00.0/firmware/'
    messages = [
        'cnss: FW name is kiwi/amss20.bin, FW fallback name is kiwi/amss20.bin',
        "ueventd: firmware: loading 'kiwi/amss20.bin' for '" + sysfs + "kiwi!amss20.bin'",
        'ueventd: found /vendor/firmware_mnt/image/kiwi/amss20.bin for ' + sysfs + 'kiwi!amss20.bin',
        'cnss: Target capability: chip_id: 0x2, chip_family: 0x4, board_id: 0xff, soc_id: 0x40170200, otp_version: 0x0',
        'cnss: fw_version: 0x1003003a, fw_build_timestamp: fixture-time, fw_build_id: fixture-build, hwid_bitmap:0x0',
        'cnss: Sending BDF download message, state: 0x1, type: 4',
        'cnss: FW name added with prefix: kiwi/regdb_xiaomi.bin',
        "ueventd: firmware: loading 'kiwi/regdb_xiaomi.bin' for '" + sysfs + "kiwi!regdb_xiaomi.bin'",
        'ueventd: found /vendor/firmware_mnt/image/kiwi/regdb_xiaomi.bin for ' + sysfs + 'kiwi!regdb_xiaomi.bin',
        'cnss: Downloading BDF: kiwi/regdb_xiaomi.bin, size: 5',
        'cnss: Sending BDF download message, state: 0x1, type: 1',
        'cnss: FW name added with prefix: kiwi/bd_m3.elf',
        "ueventd: firmware: loading 'kiwi/bd_m3.elf' for '" + sysfs + "kiwi!bd_m3.elf'",
        'ueventd: found /vendor/firmware_mnt/image/kiwi/bd_m3.elf for ' + sysfs + 'kiwi!bd_m3.elf',
        'cnss: Downloading BDF: kiwi/bd_m3.elf, size: 88',
        'cnss: Host BDF config: HW_XPA: 1 CalDB: 0',
        'cnss: Sending M3 information message, state: 0x1',
        'cnss: M3 memory, va: 0x0000000000000000, pa: 0x00000000a2a00000, size: 0x4928c']
    return '\n'.join(f'[{index + 1:5d}.000001] {message}' for index, message in enumerate(messages)).encode()


class AndroidReceiptTests(unittest.TestCase):
    def test_actual_request_not_automatic_selection_or_tlv_validity(self):
        result = inventory.parse_android_capability(android_receipt())
        self.assertEqual(result['cap']['board_id'], 255)
        self.assertFalse(result['cap_validity_flags_observed'])
        self.assertEqual(result['board_request']['request_name'], 'kiwi/bd_m3.elf')
        self.assertEqual(result['board_request']['runtime_path'], '/vendor/firmware_mnt/image/kiwi/bd_m3.elf')
        self.assertFalse(result['board_request']['each_segment_ack_observed'])
        self.assertTrue(result['board_request']['host_progressed_to_m3'])
        self.assertFalse(result['xnu_bdf_selected'])

    def test_m3_printed_zero_is_not_physical_or_null_pointer_proof(self):
        result = inventory.parse_android_capability(android_receipt())
        self.assertEqual(result['m3']['bytes'], 299660)
        self.assertEqual(result['m3']['dma_address'], 0xa2a00000)
        self.assertFalse(result['m3']['cpu_physical_address_verified'])
        self.assertFalse(result['m3']['va_pointer_value_verified'])
        self.assertFalse(result['m3']['runtime_m3_filename_observed'])
        self.assertIsNone(result['m3']['payload_sha256'])
        self.assertEqual(result['m3']['metadata_line_number'], 18)
        self.assertEqual(result['m3']['metadata_time_us'], 18000001)
        self.assertEqual(result['m3']['metadata_log_stage'], 'before_QMI_request_and_reply_in_published_CNSS')
        self.assertFalse(result['m3']['m3_info_reply_observed'])
        candidate = result['published_m3_source_candidate']
        self.assertEqual(candidate['request_name'], 'kiwi/phy_ucode20.elf')
        self.assertFalse(candidate['extract_elf_segments'])
        self.assertFalse(candidate['selector_inputs_verified'])
        self.assertFalse(candidate['installed_cnss_revision_verified'])

    def test_non_v2_firmware_receipt_does_not_create_v2_m3_candidate(self):
        data = android_receipt().replace(b'amss20.bin', b'amss.bin')
        result = inventory.parse_android_capability(data)
        self.assertIsNone(result['published_m3_source_candidate'])
        self.assertEqual(result['m3']['bytes'], 299660)
        self.assertIsNone(result['m3']['payload_sha256'])

    def test_m3_zero_size_address_and_pointer_overflow_are_rejected(self):
        changes = ((b'size: 0x4928c', b'size: 0x0'),
                   (b'size: 0x4928c', b'size: 0x200001'),
                   (b'pa: 0x00000000a2a00000', b'pa: 0x0'),
                   (b'va: 0x0000000000000000', b'va: 0x10000000000000000'))
        for before, after in changes:
            with self.subTest(after=after), self.assertRaises(ValueError):
                inventory.parse_android_capability(android_receipt().replace(before, after))

    def test_wma_board_id_and_unrelated_logs_do_not_replace_cap(self):
        data = android_receipt() + b'\n[   99.000001] kiwi_v2: WMA Board id: 0, Board version: 8'
        self.assertEqual(inventory.parse_android_capability(data)['cap']['board_id'], 255)

    def test_missing_required_cap_fw_host_and_request_fields(self):
        lines = android_receipt().splitlines()
        for token in (b'Target capability:', b'fw_version:', b'Host BDF config:',
                      b'firmware: loading', b'ueventd: found', b'Downloading BDF:'):
            altered = b'\n'.join(line for line in lines if token not in line)
            with self.subTest(token=token), self.assertRaises(ValueError):
                inventory.parse_android_capability(altered)

    def test_duplicate_cap_version_requests_and_downloads(self):
        for token in (b'Target capability:', b'fw_version:', b'firmware: loading', b'Downloading BDF:'):
            lines = android_receipt().splitlines()
            index = next(index for index, line in enumerate(lines) if token in line)
            lines.insert(index, lines[index])
            with self.subTest(token=token), self.assertRaises(ValueError):
                inventory.parse_android_capability(b'\n'.join(lines))

    def test_overflow_type_path_and_receipt_order(self):
        changes = ((b'board_id: 0xff', b'board_id: 0x100000000'),
                   (b'state: 0x1', b'state: 0x10000000000000000'),
                   (b'type: 4', b'type: 7'), (b'size: 88', b'size: 4294967295'),
                   (b'kiwi/bd_m3.elf', b'kiwi/../bd_m3.elf'),
                   (b'[   18.000001]', b'[    1.000001]'),
                   (b'[    8.000001]', b'[    1.000001]'),
                   (b'pa: 0x00000000a2a00000', b'pa: 0xffffffffffffffff'))
        for before, after in changes:
            with self.subTest(after=after), self.assertRaises(ValueError):
                inventory.parse_android_capability(android_receipt().replace(before, after))

    def test_mismatched_prefix_sysfs_and_resolution(self):
        for before, after in ((b'prefix: kiwi/bd_m3.elf', b'prefix: kiwi/other.elf'),
                              (b'kiwi!bd_m3.elf', b'kiwi!other.elf'),
                              (b'found /vendor/', b'found /vendor/../')):
            with self.subTest(after=after), self.assertRaises(ValueError):
                inventory.parse_android_capability(android_receipt().replace(before, after))

    def test_m3_missing_both_is_explicit_and_partial_is_rejected(self):
        data = b'\n'.join(line for line in android_receipt().splitlines() if b'M3 ' not in line)
        self.assertIsNone(inventory.parse_android_capability(data)['m3'])
        partial = b'\n'.join(line for line in android_receipt().splitlines() if b'M3 memory' not in line)
        with self.assertRaises(ValueError):
            inventory.parse_android_capability(partial)


class AndroidManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='fuxi-android-evidence-test-')
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.survey_path = self.directory / 'survey.json'
        records = {}
        for name, data in (('identity', b'fuxi\nfixture-fingerprint\n'), ('capability', android_receipt())):
            path = self.directory / (name + '.txt')
            path.write_bytes(data)
            records[name] = {'host_path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                             'command': 'never execute this fixture field'}
        self.survey = {'method': 'read-only Android shell', 'captured_at': 'fixture-time', 'records': records}
        self.survey_path.write_text(json.dumps(self.survey), encoding='utf-8')
        self.assets_path = self.directory / 'assets.json'
        files = {}
        for name, data in (('amss20.bin', b'fixture-build'), ('regdb_xiaomi.bin', b'regdb'), ('bd_m3.elf', elf32())):
            path = self.directory / name
            path.write_bytes(data)
            files[name] = {'host_path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                           'android_path': '/vendor/firmware_mnt/image/kiwi/' + name}
        self.assets = {'provenance': {'method': 'synthetic fixture', 'captured_at': 'fixture-time',
                                     'selection_evidence': str(self.directory / 'capability.txt')},
                       'root_staging_verified': False, 'files': files}
        self.assets_path.write_text(json.dumps(self.assets), encoding='utf-8')

    def test_survey_assets_chain_and_no_staging_or_m3_promotion(self):
        survey = inventory.read_android_survey(self.survey_path)
        self.assertEqual(survey['firmware_payloads_opened'], 0)
        assets = inventory.read_android_assets(self.assets_path, survey)
        roles = {entry['actual_android_request_role'] for entry in assets['files']}
        self.assertEqual(roles, {'firmware', 'board_request', 'regdb_request'})
        self.assertTrue(assets['files'][0]['receipt_build_id_in_payload'])
        self.assertFalse(assets['root_staging_verified'])
        self.assertFalse(assets['m3_payload_hash_verified'])
        self.assertFalse(assets['xnu_bdf_selected'])

    def test_same_size_candidate_file_is_not_loaded_m3_identity(self):
        survey = inventory.read_android_survey(self.survey_path)
        name = 'phy_ucode20.elf'
        data = elf32().ljust(survey['m3']['bytes'], b'\0')
        path = self.directory / name
        path.write_bytes(data)
        self.assets['files'][name] = {'host_path': str(path), 'bytes': len(data),
                                     'sha256': hashlib.sha256(data).hexdigest(),
                                     'android_path': '/vendor/firmware_mnt/image/kiwi/' + name}
        self.assets_path.write_text(json.dumps(self.assets), encoding='utf-8')
        assets = inventory.read_android_assets(self.assets_path, survey)
        candidate = next(entry for entry in assets['files'] if entry['name'] == name)
        self.assertEqual(candidate['bytes'], survey['m3']['bytes'])
        self.assertEqual(candidate['status'], 'local_payload_hash_verified')
        self.assertNotIn('actual_android_request_role', candidate)
        self.assertFalse(assets['m3_payload_hash_verified'])
        self.assertFalse(assets['root_staging_verified'])

    def test_survey_hash_tamper_and_missing_required_record(self):
        capability = self.directory / 'capability.txt'
        original = capability.read_bytes()
        capability.write_bytes(original + b'changed')
        with self.assertRaisesRegex(ValueError, 'hash/size'):
            inventory.read_android_survey(self.survey_path)
        del self.survey['records']['identity']
        self.survey_path.write_text(json.dumps(self.survey), encoding='utf-8')
        with self.assertRaises(ValueError):
            inventory.read_android_survey(self.survey_path)

    def test_asset_hash_tamper_wrong_receipt_and_unverified_root_declaration(self):
        survey = inventory.read_android_survey(self.survey_path)
        self.assets['root_staging_verified'] = True
        self.assets_path.write_text(json.dumps(self.assets), encoding='utf-8')
        self.assertFalse(inventory.read_android_assets(self.assets_path, survey)['root_staging_verified'])
        self.assets['provenance']['selection_evidence'] = 'different.txt'
        self.assets_path.write_text(json.dumps(self.assets), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'different selection'):
            inventory.read_android_assets(self.assets_path, survey)
        (self.directory / 'bd_m3.elf').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'hash/size'):
            inventory.read_android_assets(self.assets_path)

    def test_bound_paths_and_wire_type_mismatch(self):
        survey = inventory.read_android_survey(self.survey_path)
        self.survey['records']['capability']['host_path'] = '../escape.txt'
        self.survey_path.write_text(json.dumps(self.survey), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'escapes'):
            inventory.read_android_survey(self.survey_path)
        survey['board_request']['type'] = 0
        with self.assertRaisesRegex(ValueError, 'wire type'):
            inventory.read_android_assets(self.assets_path, survey)
        self.assets['files']['amss20.bin']['bytes'] = inventory.MAX_FILE_BYTES + 1
        self.assets_path.write_text(json.dumps(self.assets), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'size bound'):
            inventory.read_android_assets(self.assets_path)

    def test_cli_combined_receipts_and_assets_never_auto_selects(self):
        result = subprocess.run([sys.executable, '-B', str(SCRIPT), '--provenance', 'synthetic fixture',
                                 '--android-survey-manifest', str(self.survey_path),
                                 '--android-assets-manifest', str(self.assets_path)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report['automatic_selection'])
        self.assertFalse(report['android_assets']['m3_payload_hash_verified'])

    def test_asset_manifest_required_provenance_and_boolean(self):
        del self.assets['provenance']['captured_at']
        self.assets_path.write_text(json.dumps(self.assets), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'provenance'):
            inventory.read_android_assets(self.assets_path)
        self.assets['root_staging_verified'] = 'false'
        self.assets_path.write_text(json.dumps(self.assets), encoding='utf-8')
        with self.assertRaises(ValueError):
            inventory.read_android_assets(self.assets_path)


if __name__ == '__main__':
    unittest.main()
