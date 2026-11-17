#!/usr/bin/env python3
"""Print a host-only Fuxi RAM inventory from an FDT, with unresolved reservations."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct


UINT64_LIMIT = 1 << 64
MIB = 1 << 20
CURRENT_XNU = (0x8c0000000, 0xafe000000)
GPU_SCRATCH = (0xafe000000, 0xb00000000)
INSPECTOR_PATH = Path(__file__).with_name('fuxi-inspect-dtb.py')
spec = importlib.util.spec_from_file_location('fuxi_inventory_fdt', INSPECTOR_PATH)
fdt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fdt)


def checked_interval(address, size):
    if address < 0 or address >= UINT64_LIMIT or size < 0 or size >= UINT64_LIMIT:
        raise ValueError('address or size outside unsigned 64-bit range')
    end = address + size
    if end > UINT64_LIMIT:
        raise ValueError('unsigned 64-bit address range overflow')
    return address, end


def union_ranges(ranges):
    merged = []
    for start, end in sorted(ranges):
        if start < 0 or start >= UINT64_LIMIT or end < start or end > UINT64_LIMIT:
            raise ValueError('invalid unsigned 64-bit interval endpoints')
        if start == end:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def subtract_ranges(ranges, exclusions):
    remaining = []
    exclusions = union_ranges(exclusions)
    for start, end in union_ranges(ranges):
        cursor = start
        for blocked_start, blocked_end in exclusions:
            if blocked_end <= cursor:
                continue
            if blocked_start >= end:
                break
            if blocked_start > cursor:
                remaining.append((cursor, blocked_start))
            cursor = max(cursor, blocked_end)
            if cursor >= end:
                break
        if cursor < end:
            remaining.append((cursor, end))
    return remaining


def intersect_ranges(ranges, other_ranges):
    intersections = []
    other_ranges = union_ranges(other_ranges)
    for start, end in union_ranges(ranges):
        for other_start, other_end in other_ranges:
            overlap_start = max(start, other_start)
            overlap_end = min(end, other_end)
            if overlap_start < overlap_end:
                intersections.append((overlap_start, overlap_end))
    return union_ranges(intersections)


def range_record(region):
    start, end = region
    return {'start': hex(start), 'end': hex(end), 'size_hex': hex(end - start),
            'size_bytes': end - start, 'size_mib': (end - start) / MIB}


def range_bytes(ranges):
    return sum(end - start for start, end in ranges)


def cell_layout(props):
    layout = {'defaulted_properties': [], 'errors': []}
    for name, default in (('#address-cells', 2), ('#size-cells', 1)):
        raw = props.get(name)
        if raw is None:
            layout[name] = default
            layout['defaulted_properties'].append(name)
        elif len(raw) != 4:
            layout[name] = None
            layout['errors'].append(f'{name} must contain exactly one cell')
        else:
            layout[name] = fdt.cells(raw)[0]
    return layout


def cell_number(values):
    number = 0
    for value in values:
        number = (number << 32) | value
    return number


def decode_ranges(raw, layout):
    address_cells, size_cells = layout['#address-cells'], layout['#size-cells']
    if address_cells not in (1, 2) or size_cells not in (1, 2):
        raise ValueError('unsupported address/size cell counts')
    values = fdt.cells(raw)
    width = address_cells + size_cells
    if not values or len(values) % width:
        raise ValueError('property must contain complete address/size tuples')
    ranges = []
    for offset in range(0, len(values), width):
        address = cell_number(values[offset:offset + address_cells])
        size = cell_number(values[offset + address_cells:offset + width])
        ranges.append(checked_interval(address, size))
    return ranges


def inspect_node(path, nodes, kind, root_layout, reserved_identity):
    props = nodes[path]
    parent = path.rsplit('/', 1)[0] or '/'
    layout = cell_layout(nodes.get(parent, {}))
    reasons = list(layout['errors'])
    expected_parent = '/' if kind == 'memory' else '/reserved-memory'
    physical = parent == expected_parent
    if kind == 'reserved-memory':
        physical = physical and reserved_identity
        if (layout['#address-cells'], layout['#size-cells']) != (
                root_layout['#address-cells'], root_layout['#size-cells']):
            reasons.append('address/size cell layout differs from root')
    if not physical:
        reasons.append('physical address translation unresolved')
    decoded = {}
    for name in ('reg', 'alloc-ranges'):
        if name in props:
            try:
                decoded[name] = decode_ranges(props[name], layout)
            except ValueError as error:
                reasons.append(f'{name}: {error}')
    size_request = None
    for name in ('size', 'alignment'):
        if name in props:
            try:
                values = fdt.cells(props[name])
                if layout['#size-cells'] not in (1, 2) or len(values) != layout['#size-cells']:
                    raise ValueError('property differs from parent size-cell width')
                decoded[name] = cell_number(values)
                if name == 'size':
                    size_request = decoded[name]
            except ValueError as error:
                reasons.append(f'{name}: {error}')
    static_ranges = decoded.get('reg', []) if physical else []
    allocation_windows = decoded.get('alloc-ranges', []) if physical else []
    zero_indices = [index for index, (start, end) in enumerate(decoded.get('reg', []))
                    if start == end]
    if zero_indices:
        reasons.append('zero-size reg entries retain unresolved placement/lifetime')
    if 'reg' not in props:
        reasons.append('reg absent; physical placement unresolved')
    if 'size' in props:
        reasons.append('size allocation placement/activation unresolved')
    if 'alloc-ranges' in props:
        reasons.append('alloc-ranges are allocation windows; actual allocations unresolved')
        if not union_ranges(allocation_windows):
            reasons.append('allocation window physical coverage unresolved')
    for name in ('no-map', 'reusable'):
        if name in props:
            reasons.append(f'{name} mapping/reclaim lifetime unresolved for XNU')
            if props[name]:
                reasons.append(f'{name} boolean property has a payload')
    status = props.get('status', b'okay\0').rstrip(b'\0').decode('ascii', errors='replace')
    if status not in ('okay', 'ok'):
        reasons.append(f'status={status}; reservation or bank lifetime unresolved')
    record = {'path': path, 'parent': parent, 'parent_cells': layout,
              'properties_hex': {name: props[name].hex() for name in (
                  'device_type', 'reg', 'size', 'alloc-ranges', 'alignment',
                  'no-map', 'reusable', 'status') if name in props},
              'no_map': 'no-map' in props, 'reusable': 'reusable' in props,
              'status': status, 'physical_address_translation_resolved': physical,
              'decoded_reg': [range_record(region) for region in decoded.get('reg', [])],
              'decoded_alloc_ranges': [range_record(region) for region in decoded.get('alloc-ranges', [])],
              'decoded_size_request_bytes': size_request,
              'decoded_alignment_bytes': decoded.get('alignment'),
              'zero_size_reg_indices': zero_indices, 'unresolved': list(dict.fromkeys(reasons))}
    return record, union_ranges(static_ranges), union_ranges(allocation_windows)


def build_inventory(data, source_path=None):
    nodes, reserves, total = fdt.parse(data)
    root_layout = cell_layout(nodes['/'])
    reserved_props = nodes.get('/reserved-memory', {})
    reserved_layout = cell_layout(reserved_props)
    reserved_identity = (not root_layout['errors'] and not reserved_layout['errors'] and
                         root_layout['#address-cells'] == reserved_layout['#address-cells'] and
                         root_layout['#size-cells'] == reserved_layout['#size-cells'] and
                         reserved_props.get('ranges') == b'')
    memory_nodes, reserved_nodes, unresolved = [], [], []
    advertised, static_reserved, dynamic_windows = [], [], {}
    unknown_placement, no_map_nodes, reusable_nodes = [], [], []
    raw_memory_bytes, dynamic_size_bytes = 0, 0
    for path, props in nodes.items():
        if path == '/memory' or path.startswith('/memory@') or props.get('device_type') == b'memory\0':
            kind = 'memory'
        elif path.startswith('/reserved-memory/'):
            kind = 'reserved-memory'
        else:
            continue
        record, physical_ranges, windows = inspect_node(path, nodes, kind, root_layout, reserved_identity)
        if kind == 'memory':
            memory_nodes.append(record)
            advertised.extend(physical_ranges)
            raw_memory_bytes += sum(region['size_bytes'] for region in record['decoded_reg'])
        else:
            reserved_nodes.append(record)
            static_reserved.extend(physical_ranges)
            if windows:
                dynamic_windows[path] = windows
            if not physical_ranges and not windows:
                unknown_placement.append(path)
            if 'reg' not in props and record['decoded_size_request_bytes'] is not None:
                dynamic_size_bytes += record['decoded_size_request_bytes']
            if record['no_map']:
                no_map_nodes.append(path)
            if record['reusable']:
                reusable_nodes.append(path)
        if record['unresolved']:
            unresolved.append({'path': path, 'kind': kind, 'reasons': record['unresolved']})
    if not memory_nodes:
        unresolved.append({'path': '/', 'kind': 'memory', 'reasons': ['advertised memory nodes absent']})
    reserve_records, reserve_ranges = [], []
    for index, reserve in enumerate(reserves):
        record = dict(reserve, index=index)
        try:
            region = checked_interval(int(reserve['address'], 16), int(reserve['size'], 16))
            record.update(range_record(region))
            reserve_ranges.append(region)
            if region[0] == region[1]:
                record['unresolved'] = ['zero-size reserve-map entry; lifetime unresolved']
        except ValueError as error:
            record['unresolved'] = [str(error)]
        if record.get('unresolved'):
            unresolved.append({'path': f'reserve-map[{index}]', 'kind': 'reserve-map',
                               'reasons': record['unresolved']})
        reserve_records.append(record)
    advertised = union_ranges(advertised)
    static_reserved = union_ranges(static_reserved)
    reserve_ranges = union_ranges(reserve_ranges)
    known_reserved = union_ranges(static_reserved + reserve_ranges)
    exclusions = union_ranges(known_reserved + [CURRENT_XNU, GPU_SCRATCH])
    candidates = subtract_ranges(advertised, exclusions)
    candidate_records = []
    for region in candidates:
        record = range_record(region)
        record['possible_dynamic_reservations'] = [
            path for path, windows in dynamic_windows.items() if intersect_ranges([region], windows)]
        record['live_overlap_clearance'] = 'unverified'
        record['xnu_multirange_admission'] = 'unverified'
        candidate_records.append(record)
    totals = {
        'advertised_memory_raw_decoded_sum_bytes': raw_memory_bytes,
        'advertised_memory_union_bytes': range_bytes(advertised),
        'reserve_map_union_bytes': range_bytes(reserve_ranges),
        'reserved_memory_static_union_bytes': range_bytes(static_reserved),
        'known_reservation_union_bytes': range_bytes(known_reserved),
        'known_reservations_inside_advertised_bytes': range_bytes(intersect_ranges(known_reserved, advertised)),
        'known_reservations_outside_advertised_bytes': range_bytes(subtract_ranges(known_reserved, advertised)),
        'current_xnu_9g_bytes': CURRENT_XNU[1] - CURRENT_XNU[0],
        'gpu_scratch_bytes': GPU_SCRATCH[1] - GPU_SCRATCH[0],
        'candidate_after_known_exclusions_bytes': range_bytes(candidates),
        'dynamic_size_requests_decoded_sum_bytes': dynamic_size_bytes,
        'unresolved_reservation_union_bytes': None,
        'candidate_after_all_reservations_bytes': None,
        'certified_usable_bytes': None,
        'physical_installed_ram_bytes': None}
    return {
        'schema_version': 1,
        'source': {'dtb_path': str(Path(source_path).resolve()) if source_path else None,
                   'dtb_sha256': hashlib.sha256(data).hexdigest(),
                   'file_size_bytes': len(data), 'fdt_total_size_bytes': total,
                   'trailing_bytes': len(data) - total,
                   'parser_path': str(INSPECTOR_PATH.resolve()),
                   'parser_sha256': hashlib.sha256(INSPECTOR_PATH.read_bytes()).hexdigest()},
        'range_convention': 'half-open unsigned 64-bit physical intervals; end may equal 2**64',
        'root_cells': root_layout,
        'advertised_memory': {'nodes': memory_nodes, 'union': [range_record(region) for region in advertised]},
        'reserve_map': {'entries': reserve_records, 'union': [range_record(region) for region in reserve_ranges]},
        'reserved_memory': {'parent_cells': reserved_layout,
                            'ranges_hex': reserved_props.get('ranges', b'').hex(),
                            'ranges_property_present': 'ranges' in reserved_props,
                            'identity_translation_resolved': reserved_identity,
                            'nodes': reserved_nodes,
                            'static_union': [range_record(region) for region in static_reserved],
                            'no_map_nodes': no_map_nodes, 'reusable_nodes': reusable_nodes,
                            'unbounded_unknown_placement_nodes': unknown_placement},
        'known_reservation_union': [range_record(region) for region in known_reserved],
        'configured_exclusions': {'source': 'xnu/variants/ram9g.patch:6',
                                 'current_xnu_9g': range_record(CURRENT_XNU),
                                 'gpu_scratch_32mib': range_record(GPU_SCRATCH)},
        'current_layout_checks': {
            'xnu_outside_advertised': [range_record(region) for region in subtract_ranges([CURRENT_XNU], advertised)],
            'gpu_outside_advertised': [range_record(region) for region in subtract_ranges([GPU_SCRATCH], advertised)],
            'xnu_known_reservation_overlaps': [range_record(region) for region in intersect_ranges([CURRENT_XNU], known_reserved)],
            'gpu_known_reservation_overlaps': [range_record(region) for region in intersect_ranges([GPU_SCRATCH], known_reserved)],
            'dynamic_allocations_and_live_overlaps': 'unresolved'},
        'exclusion_union': [range_record(region) for region in exclusions],
        'candidate_ranges': candidate_records,
        'totals_bytes': totals,
        'totals_mib': {name.removesuffix('_bytes') + '_mib': value / MIB if value is not None else None
                       for name, value in totals.items()},
        'unresolved': unresolved,
        'physical_device_test_performed': False,
        'live_overlaps_unverified': [
            'loader image, BSS, stacks, page tables and heap',
            'persistent monitor core, USB/DMA buffers and monitor-owned data',
            'original/relocated FDT and payload/initrd staging buffers',
            'kernel segments, RAMDisk/trust cache, ADT, boot_args and topOfKernelData'],
        'uncertainties': [
            'Raw /memory sum describes DT advertisement; installed physical capacity requires independent evidence.',
            'Static reservation unions deduplicate overlap and adjacency, including ranges outside advertised banks.',
            'Dynamic size requests and alloc-ranges leave allocation placement, activation and union size unresolved.',
            'no-map/reusable flags and zero-size/missing reg entries retain unresolved mapping and reclaim lifetimes.',
            'Candidates require all unresolved reservation placements and live-overlap checks before XNU admission.',
            'Single-contiguous boot arguments, physmap and FG_RAM_BASE invariants require a separate multi-range checkpoint.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dtb', type=Path)
    args = parser.parse_args()
    try:
        inventory = build_inventory(args.dtb.read_bytes(), args.dtb)
    except (OSError, ValueError, UnicodeDecodeError, struct.error) as error:
        parser.exit(1, f'{args.dtb}: {error}\n')
    print(json.dumps(inventory, indent=2))


if __name__ == '__main__':
    main()
