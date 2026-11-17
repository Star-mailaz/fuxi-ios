#!/usr/bin/env python3
"""Produce a host-only 16 KiB Fuxi RAM admission trace with pending-owner gates."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('fuxi_admission_inventory', Path(__file__).with_name('fuxi-ram-inventory.py'))
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)

PAGE_SIZE = 0x4000
UINT64_LIMIT = 1 << 64
UINT32_LIMIT = 1 << 32
EXTRA_BANK = (0x8b9f00000, 0x8bbd00000)
CONTEXT_HOLE = (0x8b9d00000, 0x8b9f00000)
MODEL_VIRTUAL_BASE = 0xfffffe0000000000
SOURCE_TAG = 'xnu-8796.141.3'
SOURCE_COMMIT = '1b191cb58250d0705d8a51287127505aa4bc0789'
SOURCE_TAG_OBJECT = 'f625db25f47631424dc62ac1c3414b6e530f7e8a'
SOURCE_REPOSITORY = 'https://github.com/apple-oss-distributions/xnu'
SOURCE_HASHES = {
    'osfmk/arm64/arm_vm_init.c': '3aef6df1e86fea3061ef4b5b83053502e2c50bf2e636d6949c4d55a58181e3f5',
    'osfmk/arm64/start.s': 'bf92967ea96e638f5a9a002cd4e478272f08616531d212caa919944c85e8a023',
    'osfmk/arm/arm_init.c': '5161a3fc8b31b3317e2dd745594ec8a6877590a3976147b52bfd1255d9eec47e',
    'osfmk/arm/pmap/pmap.c': '78cdd8a97fae341dd2b757c8def4799e824f56e79ccb8d1b654f92cd6c78e375',
    'osfmk/arm/pmap/pmap_data.c': '564ee64643bc22d66a36734fa75c3967fca7f592b3dd4f1c1c41160db7742b67',
    'osfmk/arm/pmap/pmap_data.h': '26f464e4dc2dd71da80d1155f7314a8f107d0a8be54965ac03def390a7dadc17',
    'osfmk/arm64/machine_routines.c': '663b25f0d52c811dc09a646ab8a5c904826f4312a1bfd23c2d3a9744cb3eb2a1',
    'osfmk/vm/vm_resident.c': '0c0dd352efef32cb032cd0a84f77cce77ba77a90412420df76d2e0f5e9ea81e1',
    'osfmk/vm/vm_page.h': '527fc93aaf8c5fa8f66c6ca213d8b9fc59dd924f5af0ad45d55424f8051334a3',
    'osfmk/mach/arm/vm_types.h': 'b2deb6cfadc2972a42f698b1822393d240f96c1f91426f4f087e0cffc367225d',
    'osfmk/mach/vm_types.h': 'df52204bad8668284b16da16007a0b88553dd4dc2e6882093fe2f2d335ad2330',
    'pexpert/arm/pe_init.c': '828368f9415c9749f661563a714152d88f70ce639faae867c900dcfdbdf53b79',
    'pexpert/pexpert/arm64/boot.h': 'efdfec46319cb147297682a8faebe02873f845261b57f7511ab8e15c13ef3439'}


def integer(value, name, limit=UINT64_LIMIT):
    if isinstance(value, str):
        try:
            value = int(value, 0)
        except ValueError as error:
            raise ValueError(f'{name} must be an integer') from error
    if type(value) is not int or not 0 <= value < limit:
        raise ValueError(f'{name} outside unsigned integer bounds')
    return value


def checked_range(region, aligned=False):
    start, end = region
    start = integer(start, 'range start')
    end = integer(end, 'range end', UINT64_LIMIT + 1)
    if end < start:
        raise ValueError('range end precedes start')
    if aligned and (start % PAGE_SIZE or end % PAGE_SIZE or start == end):
        raise ValueError('requested ranges must be nonempty and 16 KiB aligned')
    return start, end


def record_range(record):
    return checked_range((record['start'], record['end']))


def align_inside(region):
    start, end = checked_range(region)
    start = (start + PAGE_SIZE - 1) & ~(PAGE_SIZE - 1)
    end &= ~(PAGE_SIZE - 1)
    return (start, end) if start < end else None


def align_exclusion(region):
    start, end = checked_range(region)
    if start == end:
        return None
    return start & ~(PAGE_SIZE - 1), (end + PAGE_SIZE - 1) & ~(PAGE_SIZE - 1)


def aligned_ranges(ranges, outward=False):
    result = []
    align = align_exclusion if outward else align_inside
    for region in ranges:
        aligned = align(region)
        if aligned is not None:
            result.append(aligned)
    return inventory.union_ranges(result)


def covers(ranges, region):
    start, end = region
    return any(range_start <= start and end <= range_end for range_start, range_end in ranges)


def pfn_to_pa(pfn):
    return integer(pfn, 'PFN', UINT32_LIMIT) << 14


def pa_to_pfn(address):
    address = integer(address, 'page PA')
    if address % PAGE_SIZE:
        raise ValueError('page PA must be 16 KiB aligned')
    return integer(address >> 14, 'PFN', UINT32_LIMIT)


def span_index(address, physical_span):
    address = integer(address, 'metadata PA')
    start, end = checked_range(physical_span, aligned=True)
    if address % PAGE_SIZE or not start <= address or address + PAGE_SIZE > end:
        raise ValueError('metadata page outside aligned scalar span')
    return integer((address - start) // PAGE_SIZE, 'PA index', UINT32_LIMIT)


def array_pfn(index, first_pfn):
    index = integer(index, 'vm_pages index', UINT32_LIMIT)
    first_pfn = integer(first_pfn, 'vm_first_phys_ppnum', UINT32_LIMIT)
    return integer(index + first_pfn, 'implicit vm_pages PFN', UINT32_LIMIT)


def pa_to_va(address, physical_span, virtual_base, allowed_ranges):
    address = integer(address, 'PA')
    start, end = checked_range(physical_span, aligned=True)
    virtual_base = integer(virtual_base, 'model VA base')
    if virtual_base % PAGE_SIZE or virtual_base + end - start > UINT64_LIMIT:
        raise ValueError('model VA span is unaligned or overflows uint64')
    if not start <= address < end or not covers(allowed_ranges, (address, address + 1)):
        raise ValueError('PA outside geometrically allowed mapping ranges')
    return virtual_base + address - start


def va_to_pa(address, physical_span, virtual_base, allowed_ranges):
    address = integer(address, 'VA')
    start, end = checked_range(physical_span, aligned=True)
    virtual_base = integer(virtual_base, 'model VA base')
    if virtual_base % PAGE_SIZE or virtual_base + end - start > UINT64_LIMIT:
        raise ValueError('model VA span is unaligned or overflows uint64')
    if not virtual_base <= address < virtual_base + end - start:
        raise ValueError('VA outside synthetic affine span')
    physical = address - virtual_base + start
    if not covers(allowed_ranges, (physical, physical + 1)):
        raise ValueError('VA resolves into an excluded physical range')
    return physical


def prepare_owners(owners):
    if owners is None or owners == []:
        owners = [{'id': 'owner-manifest-missing', 'state': 'pending', 'ranges': None}]
    if not isinstance(owners, list):
        raise ValueError('owners must be a list or null')
    prepared, identifiers = [], set()
    for owner in owners:
        if not isinstance(owner, dict):
            raise ValueError('each owner must be an object')
        identifier = owner.get('id')
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise ValueError('owners require unique nonempty string ids')
        identifiers.add(identifier)
        if owner.get('state', 'pending') not in ('pending', 'resolved'):
            raise ValueError(f'{identifier}: invalid owner state')
        decoded, zero_fields = {}, set()
        for field in ('ranges', 'scope'):
            values = owner.get(field)
            if values is not None and not isinstance(values, list):
                raise ValueError(f'{identifier}: {field} must be a range list or null')
            regions = [record_range(value) for value in values] if values is not None else None
            if regions is not None and any(start == end for start, end in regions):
                zero_fields.add(field)
            decoded[field] = aligned_ranges(regions, outward=True) if regions is not None else None
        decoded['scope'] = None if 'scope' in zero_fields else decoded['scope'] or None
        evidence = owner.get('evidence')
        complete = (owner.get('state') == 'resolved' and owner.get('coverage_complete') is True and
                    isinstance(evidence, str) and bool(evidence.strip()) and decoded['ranges'] is not None)
        if 'ranges' in zero_fields:
            complete = False
        prepared.append({'id': identifier, 'kind': owner.get('kind'), 'ranges': decoded['ranges'],
                         'scope': decoded['scope'], 'pending': not complete,
                         'coverage_complete': owner.get('coverage_complete') is True,
                         'evidence': evidence, 'requested_bytes': owner.get('requested_bytes'),
                         'description': owner.get('description'),
                         'unresolved_reasons': owner.get('unresolved_reasons')})
    return prepared


def owner_effect(region, owners):
    excluded, pending = [], []
    for owner in owners:
        if owner['ranges'] and inventory.intersect_ranges([region], owner['ranges']):
            excluded.append(owner['id'])
        if owner['pending'] and (owner['scope'] is None or inventory.intersect_ranges([region], owner['scope'])):
            pending.append(owner['id'])
    return excluded, pending


def inventory_owners(report):
    owners, reserved_paths = [], set()
    for node in report['reserved_memory']['nodes']:
        reserved_paths.add(node['path'])
        if not node['unresolved']:
            continue
        physical = node['physical_address_translation_resolved']
        ranges = node['decoded_reg'] if physical else None
        windows = node['decoded_alloc_ranges'] if physical else None
        positive = [record for record in ranges or [] if record['size_bytes'] > 0]
        scope = [record for record in windows or [] if record['size_bytes'] > 0] or positive or None
        if node.get('zero_size_reg_indices') or any(record['size_bytes'] == 0 for record in windows or []):
            scope = None
        owners.append({'id': node['path'], 'kind': 'dt-reservation', 'state': 'pending',
                       'ranges': positive or None, 'scope': scope, 'coverage_complete': False,
                       'requested_bytes': node['decoded_size_request_bytes'],
                       'evidence': report['source']['dtb_sha256'], 'unresolved_reasons': node['unresolved']})
    for item in report['unresolved']:
        if item['path'] not in reserved_paths:
            owners.append({'id': f"inventory-unresolved:{item['path']}", 'kind': f"dt-{item['kind']}",
                           'state': 'pending', 'ranges': None, 'scope': None,
                           'evidence': report['source']['dtb_sha256'], 'unresolved_reasons': item['reasons']})
    for index, owner in enumerate(report['live_overlaps_unverified']):
        owners.append({'id': f'live-owner-{index}', 'kind': 'live-runtime', 'state': 'pending',
                       'ranges': None, 'scope': None, 'evidence': None, 'description': owner})
    return owners


def verify_sources(source_root):
    records = []
    for relative, expected_hash in SOURCE_HASHES.items():
        path = source_root / relative
        record = {'path': str(path.resolve()), 'relative_path': relative, 'expected_sha256': expected_hash,
                  'tag_url': f'{SOURCE_REPOSITORY}/blob/{SOURCE_TAG}/{relative}',
                  'commit_url': f'{SOURCE_REPOSITORY}/blob/{SOURCE_COMMIT}/{relative}'}
        try:
            data = path.read_bytes()
            record['actual_sha256'] = hashlib.sha256(data).hexdigest()
            record['size_bytes'] = len(data)
            record['status'] = 'verified' if record['actual_sha256'] == expected_hash else 'hash-mismatch'
        except OSError as error:
            record.update(status='missing', actual_sha256=None, size_bytes=None, error=str(error))
        records.append(record)
    return {'repository': SOURCE_REPOSITORY, 'tag': SOURCE_TAG, 'tag_object': SOURCE_TAG_OBJECT,
            'commit': SOURCE_COMMIT, 'status': 'verified' if all(
                record['status'] == 'verified' for record in records) else 'pending', 'files': records}


def trace_pfns(audit_ranges, requested, advertised, static, gpu, physical_span, allowed, owners, virtual_base):
    boundaries = set()
    for ranges in (audit_ranges, requested, advertised, static, gpu, allowed):
        for start, end in ranges:
            boundaries.update((start, end))
    for owner in owners:
        for field in ('scope', 'ranges'):
            for start, end in owner[field] or []:
                boundaries.update((start, end))
    rows = []
    checked_pages, roundtrip_pages, index_pages = 0, 0, 0
    for audit_start, audit_end in inventory.union_ranges(audit_ranges):
        endpoints = sorted({audit_start, audit_end} | {
            point for point in boundaries if audit_start < point < audit_end})
        for start, end in zip(endpoints, endpoints[1:]):
            region = start, end
            excluded_owners, pending_owners = owner_effect(region, owners)
            eligibility = covers(allowed, region)
            reasons = []
            if not covers(requested, region):
                reasons.append('outside requested ranges')
            if not covers(advertised, region):
                reasons.append('advertised full-page coverage absent')
            if inventory.intersect_ranges([region], static):
                reasons.append('static reservation')
            if inventory.intersect_ranges([region], gpu):
                reasons.append('GPU scratch')
            if excluded_owners:
                reasons.append('observed owner extent')
            decision = 'reject' if reasons else 'defer' if pending_owners else 'eligible-in-host-model'
            first_pfn, end_pfn = start // PAGE_SIZE, end // PAGE_SIZE
            for pfn in range(first_pfn, end_pfn):
                physical = pfn_to_pa(pfn)
                if pa_to_pfn(physical) != pfn:
                    raise ValueError('PFN/PA roundtrip failed')
                checked_pages += 1
                if covers([physical_span], (physical, physical + PAGE_SIZE)):
                    span_index(physical, physical_span)
                    index_pages += 1
                if eligibility:
                    for offset in (0, PAGE_SIZE - 1):
                        address = physical + offset
                        virtual = pa_to_va(address, physical_span, virtual_base, allowed)
                        if va_to_pa(virtual, physical_span, virtual_base, allowed) != address:
                            raise ValueError('synthetic PA/VA roundtrip failed')
                    roundtrip_pages += 1
            row = inventory.range_record(region)
            row.update(first_pfn=hex(first_pfn), end_pfn_exclusive=hex(end_pfn), page_count=end_pfn - first_pfn,
                       decision=decision, reasons=reasons, pending_owner_ids=pending_owners,
                       excluded_owner_ids=excluded_owners,
                       requested=covers(requested, region), advertised_full_pages=covers(advertised, region),
                       scalar_span_covered=covers([physical_span], region), geometry_eligible=eligibility,
                       uint32_pfn_roundtrip_all_pages=True,
                       scalar_metadata_indices_checked=covers([physical_span], region),
                       host_pa_va_roundtrip_all_pages=True if eligibility else None)
            rows.append(row)
    return {'runs': rows, 'all_audited_pfns_checked': checked_pages,
            'scalar_metadata_page_indices_checked': index_pages,
            'host_roundtrip_pages_checked': roundtrip_pages,
            'host_roundtrip_points_checked': roundtrip_pages * 2,
            'point_offsets': [0, PAGE_SIZE - 1]}


def build_trace(report, requested=None, owners=None, source_evidence=None,
                virtual_base=MODEL_VIRTUAL_BASE, context_ranges=()):
    requested = [inventory.CURRENT_XNU, EXTRA_BANK] if requested is None else requested
    requested = inventory.union_ranges([checked_range(region, aligned=True) for region in requested])
    if not requested:
        raise ValueError('requested geometry is empty')
    physical_span = requested[0][0], requested[-1][1]
    slots = (physical_span[1] - physical_span[0]) // PAGE_SIZE
    integer(slots, 'scalar metadata slot count', UINT32_LIMIT)
    advertised = aligned_ranges([record_range(record) for record in report['advertised_memory']['union']])
    static = aligned_ranges([record_range(record) for record in report['known_reservation_union']], outward=True)
    gpu = aligned_ranges([record_range(report['configured_exclusions']['gpu_scratch_32mib'])], outward=True)
    owners = inventory_owners(report) if owners is None else list(owners)
    if not owners:
        owners = [{'id': 'owner-manifest-missing', 'state': 'pending', 'ranges': None}]
    owners.append({'id': 'actual-pmap-and-board-integration', 'kind': 'board-integration',
                   'state': 'pending', 'ranges': None, 'scope': None, 'evidence': None})
    if source_evidence is None or source_evidence.get('status') != 'verified':
        owners.append({'id': 'official-source-provenance', 'kind': 'source-evidence',
                       'state': 'pending', 'ranges': None, 'scope': None, 'evidence': None})
    owners = prepare_owners(owners)
    observed_owner_ranges = inventory.union_ranges([
        region for owner in owners for region in owner['ranges'] or []])
    known_exclusions = inventory.union_ranges(static + gpu + observed_owner_ranges)
    advertised_requested = inventory.intersect_ranges(requested, advertised)
    allowed = inventory.subtract_ranges(advertised_requested, known_exclusions)
    audit_ranges = inventory.union_ranges([physical_span] + gpu + static + [
        checked_range(region, aligned=True) for region in context_ranges])
    trace = trace_pfns(audit_ranges, requested, advertised, static, gpu, physical_span,
                       allowed, owners, virtual_base)
    holes = inventory.subtract_ranges([physical_span], advertised)
    pp_attr_bytes = slots * 2
    pv_head_bytes = (slots * 8 + PAGE_SIZE - 1) & ~(PAGE_SIZE - 1)
    array_example = None
    if len(requested) > 1:
        first_pfn = pa_to_pfn(requested[0][1] - PAGE_SIZE)
        following_pfn = pa_to_pfn(requested[1][0])
        array_example = {'enumerated_pfns': [hex(first_pfn), hex(following_pfn)],
                         'compacted_array_inferred_pfns': [hex(array_pfn(0, first_pfn)), hex(array_pfn(1, first_pfn))],
                         'implicit_rule_matches': array_pfn(1, first_pfn) == following_pfn}
    owners_json = []
    for owner in owners:
        record = dict(owner)
        for field in ('ranges', 'scope'):
            record[field] = [inventory.range_record(region) for region in owner[field]] if owner[field] is not None else None
        owners_json.append(record)
    totals = {'scalar_span_bytes': physical_span[1] - physical_span[0],
              'requested_union_bytes': inventory.range_bytes(requested),
              'holes_inside_scalar_span_bytes': inventory.range_bytes(holes),
              'requested_without_advertised_full_pages_bytes': inventory.range_bytes(requested) - inventory.range_bytes(advertised_requested),
              'known_excluded_advertised_requested_bytes': inventory.range_bytes(advertised_requested) - inventory.range_bytes(allowed),
              'geometry_after_known_exclusions_bytes': inventory.range_bytes(allowed),
              'pending_owner_union_bytes': None, 'allocatable_after_all_owners_bytes': None,
              'newly_admitted_bytes': 0}
    return {'schema_version': 1, 'mode': 'host arithmetic and admission preparation',
            'page_size_bytes': PAGE_SIZE, 'source_inventory': report['source'],
            'official_sources': source_evidence,
            'requested_ranges': [inventory.range_record(region) for region in requested],
            'scalar_span': inventory.range_record(physical_span),
            'holes_inside_scalar_span': [inventory.range_record(region) for region in holes],
            'gpu_exclusion': [inventory.range_record(region) for region in gpu],
            'static_exclusions_page_aligned': [inventory.range_record(region) for region in static],
            'observed_owner_exclusions_page_aligned': [inventory.range_record(region) for region in observed_owner_ranges],
            'audit_ranges': [inventory.range_record(region) for region in audit_ranges],
            'geometry_after_known_exclusions': [inventory.range_record(region) for region in allowed],
            'owners': owners_json, 'pfn_trace': trace,
            'totals_bytes': totals,
            'totals_mib': {name.removesuffix('_bytes') + '_mib': value / inventory.MIB if value is not None else None
                           for name, value in totals.items()},
            'metadata_model': {'scalar_span_slots': slots, 'pp_attr_element_bytes': 2,
                               'pp_attr_table_bytes': pp_attr_bytes, 'arm64_pointer_bytes': 8,
                               'pv_head_table_bytes_page_aligned': pv_head_bytes,
                               'ptd_root_table_bytes': None, 'vm_pages_bytes': None,
                               'first_avail_actual': None, 'pmap_free_pages_actual': None,
                               'pmap_free_pages_span_actual': None,
                               'basis': 'pmap_data.c:634-638; ARM64 LP64, PAGE_SIZE=16KiB, no maxmem/KASAN adjustment'},
            'vm_pages_contiguity_model': {'rule': 'implicit PFN = array index + vm_first_phys_ppnum',
                                         'cross_bank_compaction_example': array_example,
                                         'late_vm_page_create_path': 'vm_resident.c:1694; vm_page.h:413-435',
                                         'startup_first_avail_actual': None},
            'translation_model': {'virtual_base': hex(virtual_base), 'actual_gVirtBase': None,
                                  'formula': 'VA = synthetic_virtual_base + PA - scalar_span.start',
                                  'domain': 'geometry_after_known_exclusions',
                                  'pfn_sampling': 'every audited PFN; first and last byte of every eligible page',
                                  'actual_PTOV_entries': None, 'production_pmap_verified': False},
            'board_admission': 'defer', 'physical_device_test_performed': False,
            'pending_evidence': ['dynamic/unknown reservations and complete live-owner extents',
                                 'board-patched pmap/physmap/VM metadata and boot-argument integration',
                                 'actual bootstrap/first_avail/PA-VA state and additional-bank hardware validation'],
            'inventory_unresolved': report['unresolved']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument('--dtb', type=Path)
    inputs.add_argument('--inventory-json', help='existing inventory JSON file, or - for stdin')
    parser.add_argument('--source-dir', type=Path, default=Path(__file__).resolve().parents[2] /
                        'ram-source-reference' / SOURCE_TAG)
    args = parser.parse_args()
    try:
        if args.inventory_json:
            report = json.load(sys.stdin) if args.inventory_json == '-' else json.loads(
                Path(args.inventory_json).read_text(encoding='utf-8'))
        else:
            path = args.dtb or Path(__file__).resolve().parents[3] / 'hw-survey/fuxi-live-20261116.dtb'
            report = inventory.build_inventory(path.read_bytes(), path)
        trace = build_trace(report, source_evidence=verify_sources(args.source_dir), context_ranges=[CONTEXT_HOLE])
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f'{error}\n')
    print(json.dumps(trace, indent=2))


if __name__ == '__main__':
    main()
