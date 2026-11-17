#!/usr/bin/env python3
"""Host-only interval arithmetic and synthetic-FDT tests for the RAM inventory."""
import hashlib
import importlib.util
from pathlib import Path
import random
import struct
import sys
import unittest


sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('fuxi_ram_inventory', Path(__file__).with_name('fuxi-ram-inventory.py'))
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)


def cells(*values):
    return struct.pack(f'>{len(values)}I', *values)


def regs(*regions):
    return b''.join(struct.pack('>QQ', address, size) for address, size in regions)


def fixture_nodes(memory=((0x1000, 0x1000),)):
    return {'/': {'#address-cells': cells(2), '#size-cells': cells(2)},
            '/memory': {'device_type': b'memory\0', 'reg': regs(*memory)},
            '/reserved-memory': {'#address-cells': cells(2), '#size-cells': cells(2), 'ranges': b''}}


def fdt_blob(nodes, reserves=()):
    strings, offsets = bytearray(), {}
    for props in nodes.values():
        for name in props:
            if name not in offsets:
                offsets[name] = len(strings)
                strings.extend(name.encode('ascii') + b'\0')
    structure = bytearray()

    def emit_node(path):
        name = '' if path == '/' else path.rsplit('/', 1)[1]
        structure.extend(cells(1))
        raw_name = name.encode('ascii') + b'\0'
        structure.extend(raw_name + b'\0' * (-len(raw_name) % 4))
        for name, raw in nodes[path].items():
            structure.extend(cells(3, len(raw), offsets[name]))
            structure.extend(raw + b'\0' * (-len(raw) % 4))
        for child in nodes:
            if child != '/' and (child.rsplit('/', 1)[0] or '/') == path:
                emit_node(child)
        structure.extend(cells(2))

    emit_node('/')
    structure.extend(cells(9))
    reserve_data = regs(*reserves) + regs((0, 0))
    structure_offset = 40 + len(reserve_data)
    strings_offset = structure_offset + len(structure)
    total = strings_offset + len(strings)
    header = cells(0xd00dfeed, total, structure_offset, strings_offset, 40,
                   17, 16, 0, len(strings), len(structure))
    return header + reserve_data + structure + strings


class RangeTests(unittest.TestCase):
    def test_union_overlap_adjacency_and_duplicates(self):
        self.assertEqual(inventory.union_ranges([(30, 40), (10, 20), (20, 30), (12, 18), (10, 20)]),
                         [(10, 40)])

    def test_subtraction_preserves_holes(self):
        self.assertEqual(inventory.subtract_ranges([(0, 10), (20, 40)],
                                                   [(5, 25), (30, 32), (32, 35), (80, 90)]),
                         [(0, 5), (25, 30), (35, 40)])

    def test_subtraction_full_cover_and_boundaries(self):
        self.assertEqual(inventory.subtract_ranges([(10, 20)], [(0, 10), (20, 30)]), [(10, 20)])
        self.assertEqual(inventory.subtract_ranges([(10, 20)], [(0, 30)]), [])
        self.assertEqual(inventory.subtract_ranges([], [(0, 30)]), [])

    def test_zero_size(self):
        self.assertEqual(inventory.checked_interval(42, 0), (42, 42))
        self.assertEqual(inventory.union_ranges([(0, 0), (42, 42)]), [])
        self.assertEqual(inventory.subtract_ranges([(0, 10)], [(5, 5)]), [(0, 10)])

    def test_unsigned_64bit_boundaries_and_overflow(self):
        limit = inventory.UINT64_LIMIT
        self.assertEqual(inventory.checked_interval(limit - 1, 1), (limit - 1, limit))
        self.assertEqual(inventory.union_ranges([(limit - 1, limit)]), [(limit - 1, limit)])
        for address, size in ((-1, 1), (0, -1), (limit, 0), (0, limit), (limit - 1, 2)):
            with self.subTest(address=address, size=size), self.assertRaises(ValueError):
                inventory.checked_interval(address, size)
        for regions in ([(10, 9)], [(limit - 1, limit + 1)]):
            with self.assertRaises(ValueError):
                inventory.union_ranges(regions)

    def test_union_can_span_the_full_uint64_address_space(self):
        limit = inventory.UINT64_LIMIT
        merged = inventory.union_ranges([(0, limit - 1), (limit - 1, limit)])
        self.assertEqual(merged, [(0, limit)])
        self.assertEqual(inventory.union_ranges(merged), merged)
        self.assertEqual(inventory.subtract_ranges(merged, [(1, limit - 1)]),
                         [(0, 1), (limit - 1, limit)])

    def test_intersection(self):
        self.assertEqual(inventory.intersect_ranges([(0, 10), (20, 40)], [(5, 25), (30, 35)]),
                         [(5, 10), (20, 25), (30, 35)])

    def test_arithmetic_against_small_address_sets(self):
        generator = random.Random(20261116)
        for iteration in range(200):
            banks = [(start, start + generator.randrange(10)) for start in
                     (generator.randrange(32) for index in range(6))]
            exclusions = [(start, start + generator.randrange(10)) for start in
                          (generator.randrange(32) for index in range(6))]
            bank_points = {point for start, end in banks for point in range(start, end)}
            excluded_points = {point for start, end in exclusions for point in range(start, end)}
            remaining = inventory.subtract_ranges(banks, exclusions)
            remaining_points = {point for start, end in remaining for point in range(start, end)}
            with self.subTest(iteration=iteration):
                self.assertEqual(remaining_points, bank_points - excluded_points)
                self.assertEqual(inventory.range_bytes(remaining), len(remaining_points))


class InventoryTests(unittest.TestCase):
    def test_static_and_reserve_map_union_deduplication(self):
        nodes = fixture_nodes()
        nodes['/reserved-memory/first'] = {'reg': regs((0x1000, 0x100)), 'no-map': b''}
        nodes['/reserved-memory/second'] = {'reg': regs((0x1080, 0x100)), 'reusable': b''}
        report = inventory.build_inventory(fdt_blob(nodes, ((0x1070, 0x80),)))
        totals = report['totals_bytes']
        self.assertEqual(totals['known_reservation_union_bytes'], 0x180)
        self.assertEqual(totals['known_reservations_inside_advertised_bytes'], 0x180)
        self.assertEqual(totals['candidate_after_known_exclusions_bytes'], 0xe80)
        self.assertEqual(report['candidate_ranges'][0]['start'], '0x1180')
        self.assertEqual(len(report['unresolved']), 2)
        self.assertEqual(report['reserved_memory']['no_map_nodes'], ['/reserved-memory/first'])
        self.assertEqual(report['reserved_memory']['reusable_nodes'], ['/reserved-memory/second'])

    def test_fragmented_banks_current9g_and_gpu_exclusion(self):
        nodes = fixture_nodes(((0x1000, 0x1000), (0x4000, 0x1000),
                               (0x8c0000000, 0xc0000000), (0x980000000, 0x180000000),
                               (0xb10000000, 0x2000000)))
        report = inventory.build_inventory(fdt_blob(nodes))
        self.assertEqual([(record['start'], record['end']) for record in report['candidate_ranges']],
                         [('0x1000', '0x2000'), ('0x4000', '0x5000'), ('0xb10000000', '0xb12000000')])
        self.assertEqual(report['totals_bytes']['current_xnu_9g_bytes'], 9184 * inventory.MIB)
        self.assertEqual(report['totals_bytes']['gpu_scratch_bytes'], 32 * inventory.MIB)
        self.assertEqual(report['current_layout_checks']['xnu_outside_advertised'], [])
        self.assertEqual(report['current_layout_checks']['gpu_outside_advertised'], [])
        self.assertFalse(report['physical_device_test_performed'])

    def test_current9g_gap_is_reported(self):
        nodes = fixture_nodes(((0x8c0000000, 0xc0000000), (0x980004000, 0x17fffc000)))
        report = inventory.build_inventory(fdt_blob(nodes))
        self.assertEqual(report['current_layout_checks']['xnu_outside_advertised'],
                         [inventory.range_record((0x980000000, 0x980004000))])
        self.assertEqual(report['candidate_ranges'], [])

    def test_current9g_and_gpu_known_reservation_overlaps(self):
        nodes = fixture_nodes(((0x8c0000000, 0x240000000),))
        nodes['/reserved-memory/inside-xnu'] = {'reg': regs((0x980000000, 0x4000))}
        nodes['/reserved-memory/inside-gpu'] = {'reg': regs((0xafe004000, 0x4000))}
        report = inventory.build_inventory(fdt_blob(nodes))
        self.assertEqual(len(report['current_layout_checks']['xnu_known_reservation_overlaps']), 1)
        self.assertEqual(len(report['current_layout_checks']['gpu_known_reservation_overlaps']), 1)

    def test_dynamic_unknown_and_zero_size_reservations(self):
        nodes = fixture_nodes()
        nodes['/reserved-memory/dynamic'] = {'size': cells(0, 0x40),
                                             'alloc-ranges': regs((0x1000, 0x1000)), 'reusable': b''}
        nodes['/reserved-memory/unknown'] = {'no-map': b''}
        nodes['/reserved-memory/zero'] = {'reg': regs((0, 0))}
        nodes['/memory']['reg'] += regs((0x5000, 0))
        report = inventory.build_inventory(fdt_blob(nodes))
        self.assertEqual(report['totals_bytes']['dynamic_size_requests_decoded_sum_bytes'], 0x40)
        self.assertIsNone(report['totals_bytes']['unresolved_reservation_union_bytes'])
        self.assertIsNone(report['totals_bytes']['candidate_after_all_reservations_bytes'])
        self.assertIsNone(report['totals_bytes']['physical_installed_ram_bytes'])
        self.assertEqual(report['candidate_ranges'][0]['possible_dynamic_reservations'], ['/reserved-memory/dynamic'])
        self.assertEqual(report['reserved_memory']['unbounded_unknown_placement_nodes'],
                         ['/reserved-memory/unknown', '/reserved-memory/zero'])
        self.assertEqual(report['advertised_memory']['nodes'][0]['zero_size_reg_indices'], [1])
        self.assertEqual(report['reserved_memory']['nodes'][2]['zero_size_reg_indices'], [0])

    def test_different_cell_layout_is_unresolved(self):
        nodes = fixture_nodes()
        nodes['/reserved-memory']['#address-cells'] = cells(1)
        nodes['/reserved-memory']['#size-cells'] = cells(1)
        nodes['/reserved-memory/different'] = {'reg': cells(0x1000, 0x100)}
        report = inventory.build_inventory(fdt_blob(nodes))
        reserved = report['reserved_memory']['nodes'][0]
        self.assertEqual(reserved['decoded_reg'][0]['size_bytes'], 0x100)
        self.assertFalse(reserved['physical_address_translation_resolved'])
        self.assertIn('address/size cell layout differs from root', reserved['unresolved'])
        self.assertEqual(report['reserved_memory']['static_union'], [])

    def test_unsupported_cells_and_bus_translation(self):
        nodes = fixture_nodes()
        nodes['/bus'] = {'#address-cells': cells(1), '#size-cells': cells(1), 'ranges': cells(0, 0, 0x8000, 0x1000)}
        nodes['/bus/memory@100'] = {'device_type': b'memory\0', 'reg': cells(0x100, 0x100)}
        nodes['/reserved-memory']['#address-cells'] = cells(3)
        nodes['/reserved-memory/unsupported'] = {'reg': cells(0, 0, 0x1000, 0, 0x100)}
        report = inventory.build_inventory(fdt_blob(nodes))
        self.assertEqual(report['totals_bytes']['advertised_memory_raw_decoded_sum_bytes'], 0x1100)
        self.assertEqual(report['totals_bytes']['advertised_memory_union_bytes'], 0x1000)
        self.assertFalse(report['advertised_memory']['nodes'][1]['physical_address_translation_resolved'])
        self.assertIn('reg: unsupported address/size cell counts', report['reserved_memory']['nodes'][0]['unresolved'])

    def test_default_cell_widths_and_malformed_size(self):
        nodes = {'/': {}, '/memory': {'device_type': b'memory\0', 'reg': cells(0, 0x1000, 0x1000)},
                 '/reserved-memory': {'#address-cells': cells(2), '#size-cells': cells(1), 'ranges': b''},
                 '/reserved-memory/dynamic': {'size': cells(0, 0x40)}}
        report = inventory.build_inventory(fdt_blob(nodes))
        self.assertEqual(report['root_cells']['defaulted_properties'], ['#address-cells', '#size-cells'])
        self.assertEqual(report['totals_bytes']['advertised_memory_union_bytes'], 0x1000)
        self.assertIn('size: property differs from parent size-cell width',
                      report['reserved_memory']['nodes'][0]['unresolved'])
        self.assertIsNone(report['reserved_memory']['nodes'][0]['decoded_size_request_bytes'])

    def test_malformed_reg_and_reserve_overflow_are_retained(self):
        nodes = fixture_nodes()
        nodes['/reserved-memory/malformed'] = {'reg': b'\0\0\0'}
        report = inventory.build_inventory(fdt_blob(nodes, ((inventory.UINT64_LIMIT - 1, 2),)))
        self.assertEqual(report['reserved_memory']['nodes'][0]['properties_hex']['reg'], '000000')
        self.assertEqual(report['reserve_map']['entries'][0]['size'], '0x2')
        self.assertEqual(report['reserve_map']['union'], [])
        self.assertEqual(len(report['unresolved']), 2)

    def test_missing_ranges_retains_unresolved_address_translation(self):
        nodes = fixture_nodes()
        del nodes['/reserved-memory']['ranges']
        nodes['/reserved-memory/static'] = {'reg': regs((0x1000, 0x100))}
        report = inventory.build_inventory(fdt_blob(nodes))
        self.assertFalse(report['reserved_memory']['ranges_property_present'])
        self.assertFalse(report['reserved_memory']['identity_translation_resolved'])
        self.assertEqual(report['reserved_memory']['static_union'], [])
        self.assertEqual(report['reserved_memory']['unbounded_unknown_placement_nodes'], ['/reserved-memory/static'])

    def test_reserved_ranges_outside_advertised_are_counted_separately(self):
        nodes = fixture_nodes()
        nodes['/reserved-memory/cross-bank'] = {'reg': regs((0x800, 0x1000))}
        report = inventory.build_inventory(fdt_blob(nodes))
        self.assertEqual(report['totals_bytes']['known_reservations_inside_advertised_bytes'], 0x800)
        self.assertEqual(report['totals_bytes']['known_reservations_outside_advertised_bytes'], 0x800)

    def test_source_hash_and_parser_reuse(self):
        data = fdt_blob(fixture_nodes())
        report = inventory.build_inventory(data)
        self.assertEqual(report['source']['dtb_sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(report['source']['fdt_total_size_bytes'], len(data))
        self.assertEqual(report['source']['parser_path'], str(inventory.INSPECTOR_PATH.resolve()))
        with self.assertRaises(ValueError):
            inventory.build_inventory(b'bad fdt')


if __name__ == '__main__':
    unittest.main()
