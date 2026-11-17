#!/usr/bin/env python3
"""Host-only tests of the actual admission helpers and pending-owner decisions."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('fuxi_ram_admission', Path(__file__).with_name('fuxi-ram-admission.py'))
admission = importlib.util.module_from_spec(spec)
spec.loader.exec_module(admission)
PAGE = admission.PAGE_SIZE


def fixture_inventory():
    ranges = [(0x10000, 0x18000), (0x20000, 0x2c000)]
    return {'source': {'dtb_sha256': 'synthetic-host-fixture'},
            'advertised_memory': {'union': [admission.inventory.range_record(region) for region in ranges]},
            'known_reservation_union': [admission.inventory.range_record((0x24008, 0x24009))],
            'configured_exclusions': {'gpu_scratch_32mib': admission.inventory.range_record((0x2c000, 0x30000))},
            'reserved_memory': {'nodes': []}, 'live_overlaps_unverified': ['synthetic loader placement'],
            'unresolved': []}


class BoundaryTests(unittest.TestCase):
    def test_requested_alignment_and_zero(self):
        self.assertEqual(admission.checked_range((0x10000, 0x18000), aligned=True), (0x10000, 0x18000))
        for region in ((0x10001, 0x18000), (0x10000, 0x18001), (0x10000, 0x10000)):
            with self.subTest(region=region), self.assertRaises(ValueError):
                admission.checked_range(region, aligned=True)

    def test_inward_alignment(self):
        self.assertEqual(admission.align_inside((0x10001, 0x20001)), (0x14000, 0x20000))
        self.assertIsNone(admission.align_inside((0x10001, 0x10002)))
        self.assertIsNone(admission.align_inside((0x10001, 0x10001)))

    def test_exclusion_outward_alignment_and_adjacency(self):
        self.assertEqual(admission.align_exclusion((0x10001, 0x10002)), (0x10000, 0x14000))
        self.assertIsNone(admission.align_exclusion((0x10001, 0x10001)))
        self.assertEqual(admission.aligned_ranges([(0x10001, 0x10002), (0x14001, 0x14002)], outward=True),
                         [(0x10000, 0x18000)])

    def test_uint64_end_and_overflow(self):
        limit = admission.UINT64_LIMIT
        self.assertEqual(admission.checked_range((limit - PAGE, limit), aligned=True), (limit - PAGE, limit))
        self.assertEqual(admission.align_exclusion((limit - 1, limit)), (limit - PAGE, limit))
        for region in ((limit, limit), (0, limit + 1), (0x18000, 0x10000), (-1, 0)):
            with self.subTest(region=region), self.assertRaises(ValueError):
                admission.checked_range(region)

    def test_null_bool_and_float_geometry_rejected(self):
        for value in (None, False, True, 0.0, 'unknown'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                admission.integer(value, 'geometry')
        self.assertEqual(admission.integer('0x10000', 'geometry'), 0x10000)

    def test_pfn_width_and_shift(self):
        last_pfn = admission.UINT32_LIMIT - 1
        physical = admission.pfn_to_pa(last_pfn)
        self.assertEqual(admission.pa_to_pfn(physical), last_pfn)
        self.assertEqual(physical, 0xffffffff << 14)
        for pfn in (-1, admission.UINT32_LIMIT, None):
            with self.subTest(pfn=pfn), self.assertRaises(ValueError):
                admission.pfn_to_pa(pfn)
        with self.assertRaises(ValueError):
            admission.pa_to_pfn(0x10001)
        with self.assertRaises(ValueError):
            admission.pa_to_pfn(admission.UINT64_LIMIT - PAGE)

    def test_scalar_metadata_index(self):
        span = (0x10000, 0x30000)
        self.assertEqual(admission.span_index(0x10000, span), 0)
        self.assertEqual(admission.span_index(0x2c000, span), 7)
        for address in (0xc000, 0x30000, 0x10001):
            with self.subTest(address=address), self.assertRaises(ValueError):
                admission.span_index(address, span)

    def test_scalar_metadata_span_alignment_and_bounds(self):
        for span in ((0x10001, 0x30000), (0x10000, 0x30001), (0x10000, 0x10000),
                     (None, 0x30000), (0x30000, 0x10000), (0x10000, admission.UINT64_LIMIT + 1)):
            with self.subTest(span=span), self.assertRaises(ValueError):
                admission.span_index(0x14000, span)


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.span = (0x10000, 0x30000)
        self.allowed = [(0x10000, 0x18000), (0x24000, 0x30000)]
        self.virtual_base = 0xfffffe0000000000

    def test_roundtrip_every_page_and_last_byte(self):
        for start, end in self.allowed:
            for physical in range(start, end, PAGE):
                for offset in (0, PAGE - 1):
                    address = physical + offset
                    virtual = admission.pa_to_va(address, self.span, self.virtual_base, self.allowed)
                    self.assertEqual(admission.va_to_pa(virtual, self.span, self.virtual_base, self.allowed), address)

    def test_holes_and_exclusive_end_rejected_both_directions(self):
        for physical in (0xffff, 0x18000, 0x23fff, 0x30000):
            with self.subTest(physical=physical), self.assertRaises(ValueError):
                admission.pa_to_va(physical, self.span, self.virtual_base, self.allowed)
        for virtual in (self.virtual_base - 1, self.virtual_base + 0x8000,
                        self.virtual_base + 0x13fff, self.virtual_base + 0x20000):
            with self.subTest(virtual=virtual), self.assertRaises(ValueError):
                admission.va_to_pa(virtual, self.span, self.virtual_base, self.allowed)

    def test_va_uint64_boundary_overflow_and_alignment(self):
        virtual_base = admission.UINT64_LIMIT - 0x20000
        virtual = admission.pa_to_va(0x2ffff, self.span, virtual_base, self.allowed)
        self.assertEqual(virtual, admission.UINT64_LIMIT - 1)
        self.assertEqual(admission.va_to_pa(virtual, self.span, virtual_base, self.allowed), 0x2ffff)
        for base in (virtual_base + PAGE, virtual_base + 1, None):
            with self.subTest(base=base), self.assertRaises(ValueError):
                admission.pa_to_va(0x10000, self.span, base, self.allowed)
            with self.assertRaises(ValueError):
                admission.va_to_pa(virtual, self.span, base, self.allowed)

    def test_dense_vm_pages_counterexample(self):
        physical_pfns = [10, 11, 15]
        inferred = [admission.array_pfn(index, physical_pfns[0]) for index in range(3)]
        self.assertEqual(inferred, [10, 11, 12])
        self.assertNotEqual(inferred[-1], physical_pfns[-1])
        self.assertEqual(admission.array_pfn(5, 10), 15)
        with self.assertRaises(ValueError):
            admission.array_pfn(1, admission.UINT32_LIMIT - 1)


class OwnerTests(unittest.TestCase):
    def effect(self, owners, region=(0x10000, 0x14000)):
        return admission.owner_effect(region, admission.prepare_owners(owners))

    def test_null_owner_manifest_deferred(self):
        excluded, pending = self.effect(None)
        self.assertEqual(excluded, [])
        self.assertEqual(pending, ['owner-manifest-missing'])

    def test_empty_owner_manifest_deferred(self):
        self.assertEqual(self.effect([]), ([], ['owner-manifest-missing']))

    def test_resolved_null_placement_stays_pending(self):
        excluded, pending = self.effect([{'id': 'loader', 'state': 'resolved', 'ranges': None,
                                         'coverage_complete': True, 'evidence': 'synthetic evidence'}])
        self.assertEqual(excluded, [])
        self.assertEqual(pending, ['loader'])

    def test_evidence_and_complete_coverage_required(self):
        for patch_values in ({'evidence': None}, {'evidence': ''}, {'coverage_complete': False},
                             {'coverage_complete': None}, {'state': 'pending'}):
            owner = {'id': 'dynamic', 'state': 'resolved', 'ranges': [],
                     'coverage_complete': True, 'evidence': 'synthetic complete absence'}
            owner.update(patch_values)
            with self.subTest(patch_values=patch_values):
                self.assertEqual(self.effect([owner])[1], ['dynamic'])

    def test_explicit_complete_absence_has_host_evidence(self):
        owner = {'id': 'dynamic', 'state': 'resolved', 'ranges': [],
                 'coverage_complete': True, 'evidence': 'synthetic complete absence'}
        self.assertEqual(self.effect([owner]), ([], []))

    def test_pending_scope_and_null_size(self):
        owner = {'id': 'dynamic', 'state': 'pending', 'ranges': None, 'requested_bytes': None,
                 'scope': [admission.inventory.range_record((0x10000, 0x20000))]}
        self.assertEqual(self.effect([owner])[1], ['dynamic'])
        self.assertEqual(self.effect([owner], (0x20000, 0x24000))[1], [])
        self.assertIsNone(admission.prepare_owners([owner])[0]['requested_bytes'])

    def test_observed_partial_page_excluded_even_while_pending(self):
        owner = {'id': 'monitor', 'state': 'pending',
                 'ranges': [admission.inventory.range_record((0x10008, 0x10009))]}
        excluded, pending = self.effect([owner])
        self.assertEqual(excluded, ['monitor'])
        self.assertEqual(pending, ['monitor'])

    def test_zero_range_stays_pending(self):
        owner = {'id': 'zero', 'state': 'resolved', 'coverage_complete': True,
                 'evidence': 'synthetic zero entry',
                 'ranges': [admission.inventory.range_record((0x10000, 0x10000))]}
        self.assertEqual(self.effect([owner]), ([], ['zero']))

    def test_mixed_zero_range_preserves_pending_evidence(self):
        owner = {'id': 'mixed-zero', 'state': 'resolved', 'coverage_complete': True,
                 'evidence': 'synthetic incomplete placement',
                 'ranges': [admission.inventory.range_record((0x10000, 0x14000)),
                            admission.inventory.range_record((0x20000, 0x20000))]}
        self.assertEqual(self.effect([owner]), (['mixed-zero'], ['mixed-zero']))

    def test_mixed_zero_scope_does_not_shrink_unknown_coverage(self):
        owner = {'id': 'dynamic', 'state': 'pending', 'ranges': None,
                 'scope': [admission.inventory.range_record((0x10000, 0x14000)),
                           admission.inventory.range_record((0x20000, 0x20000))]}
        self.assertEqual(self.effect([owner], (0x24000, 0x28000)), ([], ['dynamic']))

    def test_owner_description_and_unresolved_reasons_retained(self):
        owner = {'id': 'live-owner-0', 'state': 'pending', 'ranges': None,
                 'description': 'synthetic monitor USB/DMA buffers',
                 'unresolved_reasons': ['physical placement unknown']}
        prepared = admission.prepare_owners([owner])[0]
        self.assertEqual(prepared['description'], owner['description'])
        self.assertEqual(prepared['unresolved_reasons'], owner['unresolved_reasons'])

    def test_empty_or_zero_scope_preserves_pending_owner(self):
        for scope in ([], [admission.inventory.range_record((0x10000, 0x10000))]):
            owner = {'id': 'dynamic', 'state': 'pending', 'ranges': None, 'scope': scope}
            with self.subTest(scope=scope):
                self.assertEqual(self.effect([owner]), ([], ['dynamic']))

    def test_invalid_owner_shapes_rejected(self):
        for owners in ([{'id': 'bad', 'ranges': 0}], [{'id': 'bad', 'state': 'admit'}],
                       [{'id': ''}], [{'id': 'repeat'}, {'id': 'repeat'}], [None], 'owners', {}):
            with self.subTest(owners=owners), self.assertRaises(ValueError):
                admission.prepare_owners(owners)


class TraceTests(unittest.TestCase):
    def trace(self, **kwargs):
        return admission.build_trace(fixture_inventory(), requested=[(0x10000, 0x18000), (0x20000, 0x2c000)],
                                     source_evidence={'status': 'verified'}, **kwargs)

    def test_all_pfns_and_scalar_vs_geometric_bytes(self):
        trace = self.trace()
        self.assertEqual(trace['totals_bytes']['scalar_span_bytes'], 7 * PAGE)
        self.assertEqual(trace['totals_bytes']['requested_union_bytes'], 5 * PAGE)
        self.assertEqual(trace['totals_bytes']['holes_inside_scalar_span_bytes'], 2 * PAGE)
        self.assertEqual(trace['totals_bytes']['geometry_after_known_exclusions_bytes'], 4 * PAGE)
        self.assertEqual(trace['pfn_trace']['all_audited_pfns_checked'], 8)
        self.assertEqual(trace['pfn_trace']['scalar_metadata_page_indices_checked'], 7)
        self.assertEqual(trace['pfn_trace']['host_roundtrip_pages_checked'], 4)
        self.assertEqual(sum(row['page_count'] for row in trace['pfn_trace']['runs']), 8)
        self.assertEqual(trace['board_admission'], 'defer')
        self.assertEqual(trace['totals_bytes']['newly_admitted_bytes'], 0)
        self.assertIsNone(trace['totals_bytes']['allocatable_after_all_owners_bytes'])
        self.assertFalse(trace['translation_model']['production_pmap_verified'])

    def test_hole_static_and_gpu_pages_rejected(self):
        trace = self.trace()
        rejected = {reason for row in trace['pfn_trace']['runs'] if row['decision'] == 'reject'
                    for reason in row['reasons']}
        self.assertIn('advertised full-page coverage absent', rejected)
        self.assertIn('static reservation', rejected)
        self.assertIn('GPU scratch', rejected)
        for row in trace['pfn_trace']['runs']:
            if row['geometry_eligible']:
                self.assertEqual(row['decision'], 'defer')
                self.assertIn('actual-pmap-and-board-integration', row['pending_owner_ids'])

    def test_observed_live_owner_removed_from_geometry(self):
        owner = {'id': 'monitor', 'state': 'resolved', 'coverage_complete': True,
                 'evidence': 'synthetic full placement',
                 'ranges': [admission.inventory.range_record((0x10008, 0x10009))]}
        trace = self.trace(owners=[owner])
        self.assertEqual(trace['totals_bytes']['geometry_after_known_exclusions_bytes'], 3 * PAGE)
        self.assertEqual(trace['pfn_trace']['host_roundtrip_pages_checked'], 3)
        self.assertEqual(trace['pfn_trace']['runs'][0]['decision'], 'reject')

    def test_static_exclusion_outside_scalar_span_is_audited(self):
        report = fixture_inventory()
        report['known_reservation_union'].append(admission.inventory.range_record((0x40000, 0x44000)))
        trace = admission.build_trace(report, requested=[(0x10000, 0x18000), (0x20000, 0x2c000)])
        self.assertEqual(trace['pfn_trace']['all_audited_pfns_checked'], 9)
        self.assertEqual(trace['pfn_trace']['runs'][-1]['decision'], 'reject')
        self.assertIn('static reservation', trace['pfn_trace']['runs'][-1]['reasons'])

    def test_compacted_array_counterexample_is_in_trace(self):
        example = self.trace()['vm_pages_contiguity_model']['cross_bank_compaction_example']
        self.assertFalse(example['implicit_rule_matches'])
        self.assertNotEqual(example['enumerated_pfns'], example['compacted_array_inferred_pfns'])

    def test_complete_host_owner_fixture_keeps_board_integration_pending(self):
        trace = self.trace(owners=[{'id': 'complete-fixture', 'state': 'resolved', 'ranges': [],
                                   'coverage_complete': True, 'evidence': 'synthetic complete absence'}])
        self.assertEqual(trace['board_admission'], 'defer')
        self.assertTrue(all(row['decision'] != 'eligible-in-host-model' for row in trace['pfn_trace']['runs']))

    def test_empty_owner_override_keeps_manifest_missing(self):
        trace = self.trace(owners=[])
        self.assertIn('owner-manifest-missing', [owner['id'] for owner in trace['owners']])
        self.assertEqual(trace['board_admission'], 'defer')

    def test_unresolved_memory_or_reserve_map_is_not_dropped(self):
        report = fixture_inventory()
        report['unresolved'] = [{'path': '/memory', 'kind': 'memory', 'reasons': ['zero-size reg']},
                                {'path': 'reserve-map[0]', 'kind': 'reserve-map', 'reasons': ['unknown lifetime']}]
        trace = admission.build_trace(report, requested=[(0x10000, 0x18000)])
        owner_ids = [owner['id'] for owner in trace['owners']]
        self.assertIn('inventory-unresolved:/memory', owner_ids)
        self.assertIn('inventory-unresolved:reserve-map[0]', owner_ids)
        for row in trace['pfn_trace']['runs']:
            if row['geometry_eligible']:
                self.assertIn('inventory-unresolved:/memory', row['pending_owner_ids'])
                self.assertEqual(row['decision'], 'defer')

    def test_nulls_survive_json_roundtrip(self):
        trace = json.loads(json.dumps(self.trace()))
        self.assertIsNone(trace['metadata_model']['first_avail_actual'])
        self.assertIsNone(trace['translation_model']['actual_gVirtBase'])
        self.assertIsNone(trace['totals_bytes']['pending_owner_union_bytes'])

    def test_source_missing_and_hash_mismatch(self):
        with patch.object(Path, 'read_bytes', side_effect=FileNotFoundError('synthetic missing source')):
            evidence = admission.verify_sources(Path('synthetic-source-root'))
        self.assertEqual(evidence['status'], 'pending')
        self.assertTrue(all(record['status'] == 'missing' for record in evidence['files']))
        with patch.object(Path, 'read_bytes', return_value=b'synthetic tampered source'):
            evidence = admission.verify_sources(Path('synthetic-source-root'))
        self.assertEqual(evidence['status'], 'pending')
        self.assertTrue(all(record['status'] == 'hash-mismatch' for record in evidence['files']))

    def test_source_pending_deferred_in_trace(self):
        trace = admission.build_trace(fixture_inventory(), requested=[(0x10000, 0x18000)],
                                      source_evidence=None)
        for row in trace['pfn_trace']['runs']:
            if row['geometry_eligible']:
                self.assertIn('official-source-provenance', row['pending_owner_ids'])


if __name__ == '__main__':
    unittest.main()
