#!/usr/bin/env python3
"""Compile and execute the actual standalone C preparation helper.

No boot/VM hooks; single-threaded host shadow ledger, not production admission.
ABI v1 is a bounded native C manifest, not an implemented loader wire format.
Select --synthetic-only --sanitize for public CI without private inputs.
Select --actual-trace --sanitize for the independent local DTB/source-cache check.
Synthetic-only requires ASan and disables the C actual-trace entry point.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'xnu/fuxi-ram-prep'


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def synthetic_fixture(directory):
    lines = ['static void load_actual_manifest(struct fuxi_ram_prep_manifest *manifest)', '{',
             '    (void)manifest;',
             '    fputs("Actual trace unavailable in synthetic-only CI mode\\n", stderr);',
             '    exit(EXIT_FAILURE);', '}',
             'struct actual_trace_run { uint64_t first_pfn, pages; int defer; };',
             'static const struct actual_trace_run actual_runs[] = {{0, 0, 0}};',
             '#define ACTUAL_AUDITED UINT64_C(0)', '#define ACTUAL_DENSE UINT64_C(0)',
             '#define ACTUAL_DEFERRED UINT64_C(0)', '#define ACTUAL_REJECTED UINT64_C(0)']
    (directory / 'trace_fixture.h').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def trace_fixture(directory):
    admission = load_module('ram_bank_admission_reference', 'fuxi-ram-admission.py')
    dtb = ROOT.parent.parent / 'hw-survey/fuxi-live-20261116.dtb'
    report = admission.inventory.build_inventory(dtb.read_bytes(), dtb)
    trace = admission.build_trace(report, source_evidence=admission.verify_sources(
        ROOT.parent / 'ram-source-reference' / admission.SOURCE_TAG), context_ranges=[admission.CONTEXT_HOLE])
    if trace['board_admission'] != 'defer' or trace['totals_bytes']['allocatable_after_all_owners_bytes'] is not None:
        raise ValueError('Reference trace must retain pending admission/null owners')
    if len(trace['requested_ranges']) > 16 or len(trace['static_exclusions_page_aligned']) > 32 or len(trace['owners']) > 96:
        raise ValueError('Reference exceeds bounded C manifest capacity; do not truncate evidence')
    lines = ['static void load_actual_manifest(struct fuxi_ram_prep_manifest *manifest)', '{',
             '    memset(manifest, 0, sizeof(*manifest));',
             '    manifest->version = FUXI_RAM_PREP_VERSION;',
             '    manifest->structure_bytes = (uint32_t)sizeof(*manifest);',
             '    manifest->page_size = (uint32_t)FUXI_RAM_PREP_PAGE_SIZE;',
             '    manifest->flags = FUXI_RAM_PREP_EXPERIMENTAL;']
    span = trace['scalar_span']
    lines += [f"    manifest->physical_base = UINT64_C({span['start']});",
              f"    manifest->physical_size = UINT64_C({span['size_bytes']});"]
    for field, records in (('banks', trace['requested_ranges']), ('exclusions', trace['static_exclusions_page_aligned'])):
        count_field = 'bank_count' if field == 'banks' else 'exclusion_count'
        lines.append(f'    manifest->{count_field} = {len(records)};')
        for index, record in enumerate(records):
            lines += [f"    manifest->{field}[{index}].start = UINT64_C({record['start']});",
                      f"    manifest->{field}[{index}].size = UINT64_C({record['size_bytes']});"]
    lines.append(f"    manifest->owner_count = {len(trace['owners'])};")
    for index, owner in enumerate(trace['owners']):
        if not owner['pending']:
            raise ValueError('Actual fixture must not manufacture completed owner evidence')
        ranges = owner['ranges'] or []
        if len(ranges) > 8:
            raise ValueError('Owner extents exceed bounded capacity; do not truncate')
        lines += [f'    manifest->owners[{index}].id = {index + 1};',
                  f'    manifest->owners[{index}].range_count = {len(ranges)};']
        for range_index, record in enumerate(ranges):
            lines += [f"    manifest->owners[{index}].ranges[{range_index}].start = UINT64_C({record['start']});",
                      f"    manifest->owners[{index}].ranges[{range_index}].size = UINT64_C({record['size_bytes']});"]
    lines += ['}', 'struct actual_trace_run { uint64_t first_pfn, pages; int defer; };',
              'static const struct actual_trace_run actual_runs[] = {']
    for run in trace['pfn_trace']['runs']:
        if run['decision'] not in ('defer', 'reject'):
            raise ValueError('Actual trace unexpectedly admits a PFN')
        lines.append(f"    {{UINT64_C({run['first_pfn']}), UINT64_C({run['page_count']}), {int(run['decision'] == 'defer')}}},")
    lines += ['};']
    decisions = {decision: sum(run['page_count'] for run in trace['pfn_trace']['runs'] if run['decision'] == decision)
                 for decision in ('defer', 'reject')}
    for macro, count in (('ACTUAL_AUDITED', trace['pfn_trace']['all_audited_pfns_checked']),
                         ('ACTUAL_DENSE', trace['pfn_trace']['scalar_metadata_page_indices_checked']),
                         ('ACTUAL_DEFERRED', decisions['defer']), ('ACTUAL_REJECTED', decisions['reject'])):
        lines.append(f'#define {macro} UINT64_C({count})')
    (directory / 'trace_fixture.h').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return trace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--synthetic-only', action='store_true',
                       help='public CI: built-in C synthetic cases only, no DTB/source cache; requires --sanitize')
    modes.add_argument('--actual-trace', action='store_true',
                       help='local check: also require the actual DTB and verified cached XNU sources; no fallback')
    parser.add_argument('--sanitize', action='store_true', help='require real ASan instrumentation/runtime, never skip')
    arguments = parser.parse_args()
    if arguments.synthetic_only and not arguments.sanitize:
        parser.error('--synthetic-only CI mode requires --sanitize; sanitizer failures are fatal')
    discovery = load_module('ram_bank_compiler_discovery', 'test-fuxi-audio-prep.py')
    compiler, environment = discovery.compiler_environment()
    environment = dict(environment)
    environment['ASAN_OPTIONS'] = 'halt_on_error=1:detect_leaks=0'
    msvc = Path(compiler[0].strip('"')).name.lower() in ('cl', 'cl.exe')
    sources = [SOURCE / 'fuxi_ram_bank.c', SOURCE / 'test_fuxi_ram_bank.c']
    with tempfile.TemporaryDirectory(prefix='fuxi-ram-bank-') as temporary:
        directory = Path(temporary)
        trace = None
        if arguments.synthetic_only:
            synthetic_fixture(directory)
        else:
            trace = trace_fixture(directory)
        executables = []
        for enabled in (0, 1):
            executable = directory / (f'ram-bank-{enabled}.exe' if os.name == 'nt' else f'ram-bank-{enabled}')
            if msvc:
                flags = ['/nologo', '/TC', '/std:c11', '/W4', '/WX', '/Od', '/Zi', '/MD', f'/I{directory}',
                         f'/Fd:{directory / f"ram-bank-{enabled}.pdb"}']
                if enabled:
                    flags += ['/DFUXI_RAM_PREP_ENABLED=1']
                if arguments.sanitize:
                    flags += ['/fsanitize=address']
                command = compiler + flags + [str(source) for source in sources] + [f'/Fe:{executable}']
            else:
                flags = ['-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', '-O1', '-g', '-I', str(directory)]
                if enabled:
                    flags += ['-DFUXI_RAM_PREP_ENABLED=1']
                if arguments.sanitize:
                    flags += ['-fsanitize=address,undefined', '-fno-omit-frame-pointer']
                command = compiler + flags + [str(source) for source in sources] + ['-o', str(executable)]
            subprocess.run(command, cwd=directory, env=environment, check=True)
            result = subprocess.run([str(executable)], cwd=directory, env=environment,
                                    capture_output=True, text=True, check=True, timeout=60)
            checks = json.loads(result.stdout)
            if checks['compiled_enabled'] != enabled or checks['checks'] < 50:
                raise ValueError('C helper self-test result missing or incomplete')
            print(json.dumps(checks))
            executables.append(executable)
        if arguments.sanitize:
            canary = subprocess.run([str(executables[1]), 'asan-canary'], cwd=directory, env=environment,
                                    capture_output=True, text=True, timeout=30)
            output = canary.stdout + canary.stderr
            if canary.returncode == 0 or 'AddressSanitizer' not in output or 'heap-buffer-overflow' not in output:
                raise ValueError('ASan runtime canary did not detect intentional test-only heap OOB')
            print('PASS ASan runtime canary: intentional host-test heap OOB detected')
        if arguments.synthetic_only:
            guard = subprocess.run([str(executables[1]), 'actual-trace'], cwd=directory, env=environment,
                                   capture_output=True, text=True, timeout=30)
            if guard.returncode != 1 or 'Actual trace unavailable in synthetic-only CI mode' not in guard.stderr:
                raise ValueError('Synthetic-only binary must reject the unavailable actual trace')
            print('PASS synthetic-only guard: actual trace unavailable, not fabricated or silently skipped')
        else:
            actual = subprocess.run([str(executables[1]), 'actual-trace'], cwd=directory, env=environment,
                                    capture_output=True, text=True, check=True, timeout=60)
            checkpoint = json.loads(actual.stdout)
            if checkpoint['audited_pfns'] != trace['pfn_trace']['all_audited_pfns_checked'] or checkpoint['shadow_released_pages'] != 0:
                raise ValueError('Actual C trace mismatch or unexpected release')
            print(json.dumps(checkpoint))
        metadata = {'compiler': compiler[0], 'sanitize': arguments.sanitize,
                    'input_mode': 'synthetic-only' if arguments.synthetic_only else 'actual-trace',
                    'actual_trace_executed': not arguments.synthetic_only,
                    'private_dtb_read': not arguments.synthetic_only,
                    'source_cache_read': not arguments.synthetic_only,
                    'source_lookup_or_download': False, 'production_pmap_verified': False,
                    'physical_device_test_performed': False}
        if trace is not None:
            metadata['dtb_sha256'] = trace['source_inventory']['dtb_sha256']
        print(json.dumps(metadata))


if __name__ == '__main__':
    main()
