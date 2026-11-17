import argparse
import json
from pathlib import Path
import re
import sys


AUDIT_MARKER = 'fuxi: SpringBoard: battery-audit '
PAUSE_MARKER = 'FUXI BATTERY: poll-pause '
SWEET_MARKER = 'SWEET BATTERY: published #'
CLOCK = 'mach_absolute_time_ms'
UINT32_MAX = (1 << 32) - 1
UINT64_MAX = (1 << 64) - 1
REASONS = ('none', 'config', 'argument', 'clock', 'channel', 'generation', 'ttl',
           'overflow', 'missed-window', 'baseline')
FIELDS = {
    'soc': ('FuxiBatterySOCValid', 'FuxiBatterySOCAgeMs'),
    'external': ('FuxiBatteryExternalKnown', 'FuxiBatteryExternalAgeMs'),
    'status': ('FuxiBatteryStatusKnown', 'FuxiBatteryStatusAgeMs'),
}
AUDIT_FIELDS = (
    'CurrentCapacity', 'MaxCapacity', 'AppleRawCurrentCapacity', 'AppleRawMaxCapacity',
    'ExternalConnected', 'AppleRawExternalConnected', 'IsCharging', 'Voltage', 'Amperage',
    'AdapterDetails', 'AdapterDetails.FamilyCode', 'AdapterDetails.AdapterVoltage',
    'AdapterDetails.Current', 'AdapterDetails.Watts', 'LegacyBatteryInfo',
    'LegacyBatteryInfo.Current', 'LegacyBatteryInfo.Capacity', 'LegacyBatteryInfo.Voltage',
    'LegacyBatteryInfo.Amperage', 'LegacyBatteryInfo.CycleCount', 'LegacyBatteryInfo.Flags',
    'FuxiBatterySOCValid', 'FuxiBatteryExternalKnown', 'FuxiBatteryStatusKnown',
    'FuxiBatteryAdapterValid', 'FuxiBatteryFreshFields', 'FuxiBatteryMaxAgeMs',
    'FuxiBatterySOCAgeMs', 'FuxiBatteryExternalAgeMs', 'FuxiBatteryStatusAgeMs',
    'FuxiBatteryGeneration', 'FuxiBatteryChannelUp',
)
BOOLEAN_FIELDS = {'ExternalConnected', 'AppleRawExternalConnected', 'IsCharging', 'FuxiBatterySOCValid',
                  'FuxiBatteryExternalKnown', 'FuxiBatteryStatusKnown', 'FuxiBatteryAdapterValid', 'FuxiBatteryChannelUp'}
DICTIONARY_FIELDS = {'AdapterDetails', 'LegacyBatteryInfo'}
SWEET_PATTERN = re.compile(
    r'SWEET BATTERY: published #(?P<publication>\d+) (?P<percent>-?\d+)% '
    r'external=(?P<external>[01])(?P<external_unknown>\(unknown\))? '
    r'charging=(?P<charging>[01])(?P<status_unknown>\(unknown\))? '
    r'full=(?P<full>[01]) (?P<current>-?\d+)mA(?:\s|$)')


def integer(value, maximum=UINT64_MAX):
    if type(value) is int:
        return value if 0 <= value <= maximum else None
    if isinstance(value, str) and re.fullmatch(r'(?:\d+|0x[0-9a-fA-F]+)', value):
        number = int(value, 16 if value.startswith('0x') else 10)
        return number if number <= maximum else None
    return None


def scalar(value):
    if value == 'true':
        return True
    if value == 'false':
        return False
    if isinstance(value, str) and re.fullmatch(r'-?\d+', value):
        return int(value)
    return value


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: ' + key)
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError('non-finite JSON constant: ' + value)


def key_values(text):
    result = {}
    for match in re.finditer(r'\b([A-Za-z_][A-Za-z0-9_.]*)=([^\s]+)', text):
        key, value = match.groups()
        if key in result:
            raise ValueError('duplicate log key: ' + key)
        result[key] = scalar(value)
    return result


def published_u32(value):
    if type(value) is int and -(1 << 31) <= value <= UINT32_MAX:
        return value & UINT32_MAX
    return None


def audit_record(values, line):
    normalized = dict(values)
    missing = [key for key in AUDIT_FIELDS if key not in values]
    invalid = {}
    for key in AUDIT_FIELDS:
        value = values.get(key)
        unknown = value is None or isinstance(value, str) and re.fullmatch(
            r'unknown(?:\((?:type|non-integer|number-conversion|parent-type)\))?', value)
        valid = type(value) is bool if key in BOOLEAN_FIELDS else (
            isinstance(value, str) and re.fullmatch(r'dictionary\(\d+\)', value) if key in DICTIONARY_FIELDS
            else type(value) is int)
        if not unknown and not valid:
            invalid[key] = value
        if unknown or not valid:
            normalized[key] = 'unknown'
    return {'kind': 'audit', 'line': line, 'values': normalized,
            'missing_fields': missing, 'invalid_fields': invalid,
            'snapshot_fields_complete': not missing and not invalid}


def parse_record(text, line):
    stripped = text.strip()
    if stripped.startswith(('{', '"')):
        payload = json.loads(stripped, object_pairs_hook=unique_object, parse_constant=reject_constant)
        if isinstance(payload, str):
            text = payload
        elif isinstance(payload, dict) and isinstance(payload.get('message'), str):
            text = payload['message']
        elif isinstance(payload, dict) and payload.get('event') == 'battery-audit':
            values = dict(payload)
            properties = values.pop('properties', {})
            if not isinstance(properties, dict) or values.keys() & properties.keys():
                raise ValueError('invalid or overlapping battery-audit properties')
            values.update(properties)
            return audit_record(values, line)
        else:
            return None
    if PAUSE_MARKER in text:
        tail = text.split(PAUSE_MARKER, 1)[1]
        event = tail.split(maxsplit=1)[0] if tail else ''
        if event not in ('start', 'end', 'cancel'):
            raise ValueError('unrecognized poll-pause event')
        values = key_values(tail)
        required = ('generation', 'channel_generation', 'channel_up', 'now_ms', 'ttl_ms',
                    'duration_ms', 'soc_age_ms', 'external_age_ms', 'status_age_ms', 'reason')
        numbers = {key: integer(values.get(key)) for key in required}
        if any(value is None for value in numbers.values()) or numbers['channel_up'] not in (0, 1):
            raise ValueError('incomplete or invalid production poll-pause record')
        numbers['reason_name'] = REASONS[numbers['reason']] if numbers['reason'] < len(REASONS) else 'unrecognized'
        return {'kind': 'pause', 'event': event, 'line': line, 'values': numbers}
    if AUDIT_MARKER in text:
        tail = text.split(AUDIT_MARKER, 1)[1]
        values = key_values(tail)
        if tail.startswith('sample='):
            if 'field' in values:
                if not integer(values.get('sample'), 120) or integer(values.get('now_ms')) is None:
                    raise ValueError('invalid audit field identity')
                if values['field'] not in AUDIT_FIELDS or 'value' not in values:
                    raise ValueError('unrecognized or missing audit field/value')
                return {'kind': 'audit-field', 'line': line, 'values': values}
            if values.get('fmt') == 2:
                return {'kind': 'audit-header', 'line': line, 'values': values}
            return audit_record(values, line)
        return {'kind': 'audit-lifecycle', 'event': tail.split(maxsplit=1)[0] if tail else '',
                'line': line, 'values': values}
    if SWEET_MARKER in text:
        match = SWEET_PATTERN.search(text)
        if match is None:
            raise ValueError('incomplete SweetBattery publication')
        values = match.groupdict()
        for key in ('publication', 'percent', 'external', 'charging', 'full', 'current'):
            values[key] = int(values[key])
        values['external_known'] = values.pop('external_unknown') is None
        values['status_known'] = values.pop('status_unknown') is None
        return {'kind': 'sweet', 'line': line, 'values': values}
    return None


def audit_interval(record):
    values = record['values']
    sample = integer(values.get('sample'), 120)
    begin = integer(values.get('begin_ms'))
    end = integer(values.get('now_ms'))
    if not sample or values.get('clock') != CLOCK or begin is None or end is None or begin > end:
        return None
    return begin, end


def field_state(record, field):
    values = record['values']
    if values.get('result') != 'ok' or type(values.get('rc')) is not int or values['rc'] != 0:
        return 'unavailable'
    valid_key, age_key = FIELDS[field]
    flag = values.get(valid_key)
    if flag is False:
        return 'unknown-published'
    age = published_u32(values.get(age_key))
    if age == UINT32_MAX:
        age = None
    ttl = published_u32(values.get('FuxiBatteryMaxAgeMs'))
    mask = published_u32(values.get('FuxiBatteryFreshFields'))
    if flag is True and values.get('FuxiBatteryChannelUp') is True and ttl and age is not None and age <= ttl and mask:
        return 'fresh-flags-and-age'
    return 'unavailable'


def evidence(record):
    values = record['values']
    return {'line': record['line'], 'sample': values.get('sample'),
            'begin_ms': values.get('begin_ms'), 'now_ms': values.get('now_ms'),
            'generation': values.get('FuxiBatteryGeneration', 'unknown'),
            'fresh_fields': values.get('FuxiBatteryFreshFields', 'unknown'),
            'fresh_fields_u32': published_u32(values.get('FuxiBatteryFreshFields')),
            'snapshot_fields_complete': record['snapshot_fields_complete'],
            'missing_fields': record['missing_fields'], 'invalid_fields': record['invalid_fields'],
            'max_age_ms': values.get('FuxiBatteryMaxAgeMs', 'unknown'),
            'ages_ms': {field: values.get(keys[1], 'unknown') for field, keys in FIELDS.items()}}


def episodes(records, clock_errors):
    pauses = [record for record in records if record['kind'] == 'pause']
    audits = [record for record in records if record['kind'] == 'audit']
    result = []
    active = None
    for record in pauses:
        if record['event'] == 'start':
            active = {'start': record, 'terminal': None}
            result.append(active)
        elif active is not None and active['terminal'] is None:
            active['terminal'] = record
        else:
            result.append({'start': None, 'terminal': record})
    for index, episode in enumerate(result):
        start, terminal = episode['start'], episode['terminal']
        episode['fields'] = {}
        episode['generation_binding'] = 'not-seen'
        if start is None:
            episode['status'] = 'clock-incomparable' if terminal['event'] == 'cancel' and terminal['values']['reason'] == 3 else (
                'cancelled-before-start' if terminal['event'] == 'cancel' else 'pause-start-not-seen')
            continue
        if terminal is None:
            episode['status'] = 'pause-end-not-seen'
            continue
        if terminal['event'] == 'cancel':
            episode['status'] = 'clock-incomparable' if terminal['values']['reason'] == 3 else 'cancelled'
            continue
        first, last = start['values'], terminal['values']
        if clock_errors or last['now_ms'] < first['now_ms']:
            episode['status'] = 'clock-incomparable'
            continue
        generation = first['generation']
        if not generation or any(record['values']['generation'] != generation or
                                 record['values']['channel_generation'] != generation or
                                 record['values']['channel_up'] != 1 for record in (start, terminal)):
            episode['status'] = 'generation-unverified'
            continue
        next_start = next((item['start']['values']['now_ms'] for item in result[index + 1:]
                           if item['start'] is not None), UINT64_MAX)
        usable = []
        mismatches = []
        fork_ms = None
        for record in audits:
            interval = audit_interval(record)
            if interval is None or interval[0] < first['now_ms'] or interval[1] >= next_start:
                continue
            audit_generation = integer(record['values'].get('FuxiBatteryGeneration'))
            if audit_generation is not None and audit_generation != generation:
                mismatches.append(record['line'])
                fork_ms = interval[0] if fork_ms is None else min(fork_ms, interval[0])
            else:
                usable.append(record)
        episode['excluded_generation_lines'] = mismatches
        if fork_ms is not None:
            usable = [record for record in usable if audit_interval(record)[1] < fork_ms]
        observed = 0
        for field in FIELDS:
            unknown = next((record for record in usable if audit_interval(record)[1] <= last['now_ms'] and
                            field_state(record, field) == 'unknown-published'), None)
            recovery = next((record for record in usable if audit_interval(record)[0] >= last['now_ms'] and
                             (unknown is None or audit_interval(record)[0] >= audit_interval(unknown)[1]) and
                             field_state(record, field) == 'fresh-flags-and-age'), None)
            status = 'unknown-to-recovery-observed' if unknown and recovery else (
                'recovery-not-seen' if unknown else 'unknown-not-seen' if recovery else 'not-seen')
            episode['fields'][field] = {'status': status,
                                        'unknown': evidence(unknown) if unknown else None,
                                        'recovery': evidence(recovery) if recovery else None}
            observed += bool(unknown and recovery)
        episode['status'] = 'unknown-to-recovery-observed' if observed == len(FIELDS) else (
            'partial-unknown-to-recovery-observed' if observed else 'generation-unverified' if mismatches else 'not-seen')
        selected = [entry[name] for entry in episode['fields'].values() for name in ('unknown', 'recovery')
                    if entry[name] is not None]
        episode['generation_binding'] = 'same-generation' if selected and all(
            integer(entry['generation']) == generation for entry in selected) else 'timing-only-registry-generation-unavailable'
        if not observed and mismatches:
            episode['generation_binding'] = 'mismatch-observed'
    return result


def assemble_records(records, errors):
    result = []
    blocks = {}
    run = 0
    active_block = None
    for record in records:
        if record['kind'] == 'audit-lifecycle':
            if record['event'] == 'done' and record['values'].get('reason') == 'log-error' and active_block is not None:
                active_block['conflicts'].append('collector reported log-error')
                errors.append({'line': record['line'], 'error': 'collector reported incomplete audit logging'})
            if record['event'] in ('enabled', 'done', 'rejected'):
                run += 1
                active_block = None
        if record['kind'] not in ('audit-header', 'audit-field'):
            result.append(record)
            continue
        values = record['values']
        key = (run, integer(values.get('sample'), 120), integer(values.get('now_ms')))
        if record['kind'] == 'audit-header':
            if key in blocks:
                blocks[key]['conflicts'].append('duplicate header')
                errors.append({'line': record['line'], 'error': 'duplicate audit header identity'})
                active_block = blocks[key]
            else:
                block = {'line': record['line'], 'values': dict(values), 'fields': {}, 'conflicts': []}
                blocks[key] = block
                result.append(block)
                active_block = block
        elif key not in blocks:
            errors.append({'line': record['line'], 'error': 'orphan audit field; header identity unavailable'})
        else:
            block = blocks[key]
            field = values['field']
            if field in block['fields']:
                block['conflicts'].append('duplicate field: ' + field)
                errors.append({'line': record['line'], 'error': 'duplicate/conflicting audit field: ' + field})
            else:
                block['fields'][field] = record['line']
                block['values'][field] = values['value']
    assembled = []
    for record in result:
        if 'conflicts' not in record:
            assembled.append(record)
            continue
        snapshot = audit_record(record['values'], record['line'])
        snapshot['format'] = 'kv-v2-fields'
        snapshot['field_lines'] = record['fields']
        snapshot['transport_conflicts'] = record['conflicts']
        if record['conflicts']:
            snapshot['values']['result'] = 'transport-conflict'
            snapshot['snapshot_fields_complete'] = False
        assembled.append(snapshot)
    return assembled


def summarize_segment(segment):
    raw_records = segment.pop('records')
    segment['wire_counts'] = {kind: sum(record['kind'] == kind for record in raw_records)
                              for kind in ('audit-header', 'audit-field', 'audit')}
    records = assemble_records(raw_records, segment['parse_errors'])
    clock_errors = []
    for kind in ('pause', 'audit'):
        previous = None
        for record in records:
            if record['kind'] != kind:
                continue
            interval = audit_interval(record) if kind == 'audit' else (
                record['values']['now_ms'], record['values']['now_ms'])
            if interval is None or previous is not None and interval[0] < previous:
                clock_errors.append({'line': record['line'], 'kind': kind,
                                     'reason': 'missing/foreign clock, invalid interval or regression'})
            if interval is not None:
                previous = interval[1]
    sweet = [record for record in records if record['kind'] == 'sweet']
    sweet_transitions = {}
    for field in ('external', 'status'):
        unknown = next((record for record in sweet if not record['values'][field + '_known']), None)
        recovery = next((record for record in sweet if unknown and record['line'] > unknown['line'] and
                         record['values'][field + '_known']), None)
        sweet_transitions[field] = {'unknown_line': unknown['line'] if unknown else None,
                                    'recovery_line': recovery['line'] if recovery else None,
                                    'status': 'unknown-to-known-log-order-only' if unknown and recovery else 'not-seen'}
    segment.update({
        'counts': {kind: sum(record['kind'] == kind for record in records)
                   for kind in ('pause', 'audit', 'audit-lifecycle', 'sweet')},
        'clock_errors': clock_errors,
        'episodes': episodes(records, clock_errors),
        'sweet_publications': sweet,
        'sweet_transitions': sweet_transitions,
        'sweet_pause_clock': 'clock-incomparable' if sweet else 'not-seen',
        'audit_lifecycle': [record for record in records if record['kind'] == 'audit-lifecycle'],
        'audit_observations': [{'line': record['line'], 'values': record['values'],
                                'format': record.get('format', 'legacy-kv-or-json'),
                                'field_lines': record.get('field_lines', {}),
                                'transport_conflicts': record.get('transport_conflicts', []),
                                'snapshot_fields_complete': record['snapshot_fields_complete'],
                                'missing_fields': record['missing_fields'], 'invalid_fields': record['invalid_fields'],
                                'fresh_fields_u32': published_u32(record['values'].get('FuxiBatteryFreshFields')),
                                'states': {field: field_state(record, field) for field in FIELDS}}
                               for record in records if record['kind'] == 'audit'],
    })
    if not segment['episodes']:
        segment['status'] = 'poll-pause-not-seen'
    else:
        segment['status'] = 'see-episodes'
    return segment


def analyze_lines(lines, source='<synthetic>'):
    segments = [{'boot_boundary_line': None, 'records': [], 'parse_errors': []}]
    for number, text in enumerate(lines, 1):
        if 'Darwin Kernel Version ' in text:
            if segments[-1]['records'] or segments[-1]['parse_errors']:
                segments.append({'boot_boundary_line': number, 'records': [], 'parse_errors': []})
            else:
                segments[-1]['boot_boundary_line'] = number
        pieces = [text]
        if not text.lstrip().startswith(('{', '"')):
            markers = list(re.finditer('|'.join(re.escape(marker) for marker in
                                              (PAUSE_MARKER, AUDIT_MARKER, SWEET_MARKER)), text))
            if markers:
                pieces = [text[match.start():markers[index + 1].start() if index + 1 < len(markers) else len(text)]
                          for index, match in enumerate(markers)]
        for piece in pieces:
            try:
                record = parse_record(piece, number)
            except (ValueError, TypeError, RecursionError) as error:
                if any(marker in piece for marker in (PAUSE_MARKER, AUDIT_MARKER, SWEET_MARKER, 'battery-audit')):
                    segments[-1]['parse_errors'].append({'line': number, 'error': str(error)})
                continue
            if record is not None:
                segments[-1]['records'].append(record)
    return {'source': source, 'segments': [summarize_segment(segment) for segment in segments],
            'physical_unplug': 'not-established', 'ui_behavior': 'not-established',
            'cross_alias_coherence': 'not-established',
            'limits': ['Inputs are independent boot scopes; no cross-file or wall-clock time joins.',
                       'Collector times are observation intervals, not publication/sample timestamps.',
                       'Absent registry generation or sequence permits timing-only association, not causality.',
                       'FreshFields is preserved numerically; numeric bit positions are not guessed.',
                       'Signed CFNumber FreshFields/ages use confirmed 32-bit putNumber representation; native values remain visible.',
                       'Missing/damaged keys stay unknown; transport field completeness is not alias coherence.',
                       'V2 fields require a preceding unique header in the same boot/collector run; sample+now_ms is not an atomic publication sequence.',
                       'Retained external/full/capacity values are not physical-unplug evidence.',
                       'Change-only bounded logs, missing keys and truncated records cannot prove absence.']}


def self_test():
    checks = 0

    def check(condition):
        nonlocal checks
        if not condition:
            raise AssertionError('synthetic check ' + str(checks + 1))
        checks += 1

    def pause(event, now, generation=7, channel_generation=7, reason=0):
        return (f'{PAUSE_MARKER}{event} generation={generation} channel_generation={channel_generation} '
                f'channel_up=1 now_ms={now} ttl_ms=30000 duration_ms=40000 '
                f'soc_age_ms=100 external_age_ms=100 status_age_ms=100 reason={reason}')

    def audit(sample, now, valid, clock=CLOCK, generation='unknown', age=None):
        age = (100 if valid else 35000) if age is None else age
        flag = 'true' if valid else 'false'
        fields = ' '.join(f'{keys[0]}={flag} {keys[1]}={age}' for keys in FIELDS.values())
        return (f'{AUDIT_MARKER}sample={sample} begin_ms={now} now_ms={now + 1} clock={clock} '
                f'result=ok coherence=unestablished publication_sequence=unknown rc=0 '
                f'ExternalConnected=true IsCharging=false FuxiBatteryChannelUp=true '
                f'FuxiBatteryGeneration={generation} FuxiBatteryFreshFields=261 FuxiBatteryMaxAgeMs=30000 {fields}')

    start, end = pause('start', 100000), pause('end', 140000)
    unknown, recovery = audit(1, 135000, False), audit(2, 145000, True)

    def episode(lines):
        return analyze_lines(lines)['segments'][0]['episodes'][0]

    report = analyze_lines([start, unknown, end, recovery])
    check(report['segments'][0]['episodes'][0]['status'] == 'unknown-to-recovery-observed')
    check(report['segments'][0]['episodes'][0]['generation_binding'] == 'timing-only-registry-generation-unavailable')
    check(report['physical_unplug'] == 'not-established')
    wrapped = [json.dumps({'message': line, 'timestamp': '1970-01-01T00:00:00Z'})
               for line in (start, unknown, end, recovery)]
    check(episode(wrapped)['status'] == 'unknown-to-recovery-observed')
    native = {'event': 'battery-audit', **parse_record(recovery, 1)['values']}
    check(episode([start, unknown, end, json.dumps(native)])['status'] == 'unknown-to-recovery-observed')
    check(episode([start, audit(1, 135000, False, clock='unix_epoch_ms'), end, recovery])['status'] == 'clock-incomparable')
    check(episode([start, end, recovery])['status'] == 'not-seen')
    check(episode([start, unknown, end, audit(2, 145000, True, age=UINT32_MAX)])['status'] == 'not-seen')
    missing = recovery.replace('FuxiBatterySOCValid=true', 'FuxiBatterySOCValid=unknown')
    check(episode([start, unknown, end, missing])['status'] == 'partial-unknown-to-recovery-observed')
    check(episode([start, unknown, recovery])['status'] == 'pause-end-not-seen')
    check(episode([pause('cancel', 100000, reason=4)])['status'] == 'cancelled-before-start')
    check(episode([pause('cancel', 100000, reason=3)])['status'] == 'clock-incomparable')
    check(episode([start, pause('cancel', 140000, reason=5, channel_generation=8), recovery])['status'] == 'cancelled')
    check(episode([start, unknown, end, audit(2, 145000, True, generation=8)])['status'] == 'generation-unverified')
    check(episode([start, audit(1, 135000, False, generation=7), end,
                   audit(2, 145000, True, generation=7)])['generation_binding'] == 'same-generation')
    check(episode([start, unknown, end, audit(2, 142000, True, generation=8),
                   audit(3, 145000, True, generation=7)])['status'] == 'generation-unverified')
    check(episode([start, unknown, end, recovery, audit(3, 150000, True, generation=8)])['status'] == 'unknown-to-recovery-observed')
    check(episode([start, unknown, end, audit(2, 134000, True)])['status'] == 'clock-incomparable')
    check(episode([start, audit(1, 140000, False), end, recovery])['status'] == 'not-seen')
    check(episode([start, unknown, end.replace('channel_generation=7', 'channel_generation=8'), recovery])['status'] == 'generation-unverified')
    merged_boots = analyze_lines([start, unknown, 'Darwin Kernel Version 22.6.0: second boot', end, recovery])
    check(len(merged_boots['segments']) == 2)
    check(merged_boots['segments'][0]['episodes'][0]['status'] == 'pause-end-not-seen')
    check(merged_boots['segments'][1]['episodes'][0]['status'] == 'pause-start-not-seen')
    malformed = analyze_lines([start.replace('ttl_ms=30000 ', ''), end, recovery])
    check(len(malformed['segments'][0]['parse_errors']) == 1)
    check(malformed['segments'][0]['episodes'][0]['status'] == 'pause-start-not-seen')
    duplicate = analyze_lines([start + ' now_ms=0'])
    check(bool(duplicate['segments'][0]['parse_errors']))
    boolean_number = recovery.replace('FuxiBatterySOCValid=true', 'FuxiBatterySOCValid=1')
    check(episode([start, unknown, end, boolean_number])['status'] == 'partial-unknown-to-recovery-observed')
    sweet = ['23:59:59 SWEET BATTERY: published #1 100% external=1(unknown) charging=0(unknown) full=1 0mA',
             '00:00:01 SWEET BATTERY: published #2 100% external=1 charging=0 full=1 -20mA']
    sweet_report = analyze_lines([start, *sweet, end])
    check(sweet_report['segments'][0]['sweet_pause_clock'] == 'clock-incomparable')
    check(sweet_report['segments'][0]['sweet_transitions']['external']['status'] == 'unknown-to-known-log-order-only')
    check(sweet_report['physical_unplug'] == 'not-established')
    check(analyze_lines([])['segments'][0]['status'] == 'poll-pause-not-seen')
    check(parse_record('SWEET BATTERY: read #3 by SpringBoard (published #2: 100% external=1 charging=0)', 1) is None)
    check(episode([start + unknown, end + recovery])['status'] == 'unknown-to-recovery-observed')
    check(episode([start, unknown, end, recovery.replace('sample=2', 'sample=0')])['status'] == 'clock-incomparable')
    invalid_json = analyze_lines(['{"event":"battery-audit","now_ms":NaN}'])
    check(bool(invalid_json['segments'][0]['parse_errors']))
    damaged = parse_record(unknown.replace('FuxiBatteryExternalKnown=false', 'FuxiBatteryExternalKnown=|SpringBoard|'), 1)
    check(damaged['values']['FuxiBatteryExternalKnown'] == 'unknown')
    check('FuxiBatteryExternalKnown' in damaged['invalid_fields'])
    shortened = parse_record(unknown.replace('FuxiBatteryExternalKnown=false', 'rnalKnown=false'), 1)
    check(shortened['values']['FuxiBatteryExternalKnown'] == 'unknown')
    check('FuxiBatteryExternalKnown' in shortened['missing_fields'])
    check(not shortened['snapshot_fields_complete'])
    signed_mask = recovery.replace('FuxiBatteryFreshFields=261', 'FuxiBatteryFreshFields=-4097')
    check(episode([start, unknown, end, signed_mask])['status'] == 'unknown-to-recovery-observed')
    check(published_u32(-4097) == 0xffffefff and published_u32(-1) == UINT32_MAX)
    def short_snapshot(text):
        values = parse_record(text, 1)['values']
        header = (f'{AUDIT_MARKER}sample={values["sample"]} now_ms={values["now_ms"]} '
                  f'begin_ms={values["begin_ms"]} result=ok rc=0 clock={CLOCK} coherence=unestablished fmt=2')
        rows = [f'{AUDIT_MARKER}sample={values["sample"]} now_ms={values["now_ms"]} '
                f'field={key} value={str(values[key]).lower()}' for key in AUDIT_FIELDS]
        return [header, *rows]
    short_unknown, short_recovery = short_snapshot(unknown), short_snapshot(signed_mask)
    short_report = analyze_lines([start, *short_unknown, end, *short_recovery])['segments'][0]
    check(short_report['episodes'][0]['status'] == 'unknown-to-recovery-observed')
    check(all(row['snapshot_fields_complete'] for row in short_report['audit_observations']))
    check(short_report['wire_counts']['audit-header'] == 2 and short_report['wire_counts']['audit-field'] == 64)
    missing_row = [row for row in short_recovery if 'field=FuxiBatteryExternalKnown ' not in row]
    check(episode([start, *short_unknown, end, *missing_row])['status'] == 'partial-unknown-to-recovery-observed')
    mismatch_row = short_recovery[-1].replace(f'now_ms={145001}', 'now_ms=145002')
    incomplete = analyze_lines([short_recovery[0], *short_recovery[1:-1], mismatch_row])['segments'][0]
    check(not incomplete['audit_observations'][0]['snapshot_fields_complete'] and bool(incomplete['parse_errors']))
    duplicate_header = analyze_lines([*short_recovery, short_recovery[0]])['segments'][0]
    check(duplicate_header['audit_observations'][0]['values']['result'] == 'transport-conflict')
    duplicate_field = analyze_lines([*short_recovery, short_recovery[-1]])['segments'][0]
    check(not duplicate_field['audit_observations'][0]['snapshot_fields_complete'])
    wrapped_short = [json.dumps({'message': row}) for row in [start, *short_unknown, end, *short_recovery]]
    check(episode(wrapped_short)['status'] == 'unknown-to-recovery-observed')
    error_done = f'{AUDIT_MARKER}done samples=2 changes=2 change_snapshots=1 reason=log-error coherence=unestablished'
    failed_output = analyze_lines([*short_recovery, error_done])['segments'][0]
    check(not failed_output['audit_observations'][0]['snapshot_fields_complete'])
    check(failed_output['audit_observations'][0]['values']['result'] == 'transport-conflict')
    late_field = analyze_lines([*short_recovery[:-1], error_done, short_recovery[-1]])['segments'][0]
    check(not late_field['audit_observations'][0]['snapshot_fields_complete'] and bool(late_field['parse_errors']))
    print(f'PASS: {checks} synthetic assertions; production KV, JSONL, unknown/recovery, clocks, generations, '
          'boot boundaries, corruption, missing evidence and no physical-unplug/UI inference')


def main():
    parser = argparse.ArgumentParser(description='Read-only battery pause evidence analysis; JSON report to stdout. '
                                     'Accept production console text, JSONL message wrappers or battery-audit event objects. '
                                     'Each input is analyzed independently; host wall-clock prefixes are ignored.')
    parser.add_argument('logs', nargs='*', help='UTF-8 log paths, or - for stdin')
    parser.add_argument('--self-test', action='store_true', help='run purely synthetic assertions without files or devices')
    args = parser.parse_args()
    if args.self_test and args.logs:
        parser.error('--self-test does not accept log paths')
    if args.self_test:
        self_test()
    if not args.logs:
        if args.self_test:
            return
        parser.error('provide a log path or --self-test')
    reports = []
    try:
        for name in args.logs:
            if name == '-':
                reports.append(analyze_lines(sys.stdin, '<stdin>'))
            else:
                path = Path(name).resolve()
                with path.open(encoding='utf-8-sig', errors='replace') as stream:
                    reports.append(analyze_lines(stream, str(path)))
    except OSError as error:
        parser.exit(2, f'input error: {error}\n')
    print(json.dumps({'schema': 'fuxi-battery-pause-evidence-v1', 'inputs': reports}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
