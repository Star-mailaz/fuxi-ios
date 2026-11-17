"""Host smoke of extracted loader_check_ram; virtual addresses and RD32 are mocked."""

import hashlib
import os
from pathlib import Path
import re
import runpy
import subprocess
import tempfile


WORKSPACE = Path(__file__).resolve().parents[2]
LOADER = WORKSPACE / 'ios-fuxi/shim/fuxi-loader/loader.c'
PROFILE = LOADER.with_name('fuxi-ram-profile.h')
GPU = WORKSPACE / 'ios-fuxi/shim/fuxi-probe/gpu-handoff.h'

HARNESS = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "fuxi-ram-profile.h"
#if defined(_MSC_VER) && !defined(__clang__)
#define __builtin_bswap32(value) ((uint32_t)_byteswap_ulong((unsigned long)(value)))
#endif
@GPU_CONSTANTS@
static unsigned assertions;
#define CHECK(condition) do { assertions++; if (!(condition)) { fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); exit(1); } } while (0)
static uint8_t *host_data;
static size_t host_bytes;
static uint64_t host_address, host_fault_call, host_reads, host_deep_checks;
static uintptr_t host_head = UINT64_C(0x200000000), host_end = UINT64_C(0x200010000);
@PIN_DECLARATION@
uint32_t probe_safe_rd32(uint64_t address, uint32_t *faulted)
{
    const uint64_t ordinal = host_reads++;
    *faulted = 0;
    if (ordinal == host_fault_call || address < host_address || host_bytes < 4 ||
        address - host_address > host_bytes - 4) {
        *faulted = 1;
        return 0;
    }
    uint32_t value;
    memcpy(&value, host_data + (size_t)(address - host_address), sizeof(value));
    return value;
}
static enum FuxiRamProfileResult host_profile_check(const void *fdt, size_t available,
    uint64_t base, uint64_t bank)
{
    host_deep_checks++;
    CHECK((uintptr_t)fdt == host_address);
    CHECK(available == host_bytes);
    CHECK(base == FG_RAM_BASE && bank == FG_BANK_SIZE);
    return fuxi_ram_profile_check(host_data, available, base, bank);
}
#define fuxi_ram_profile_check host_profile_check
@CHECK_FUNCTION@
#undef fuxi_ram_profile_check
@CASE_DATA@
int main(void)
{
    CHECK(sizeof(uintptr_t) == 8);
    const unsigned count = (unsigned)(sizeof(cases) / sizeof(cases[0]));
    for (unsigned index = 0; index < count; index++) {
        host_bytes = cases[index].length;
        host_data = malloc(host_bytes);
        CHECK(host_data != NULL);
        memcpy(host_data, cases[index].data, host_bytes);
        host_address = cases[index].overlap == 1 ? host_head :
            cases[index].overlap == 2 ? FG_RAM_BASE + FG_RAM_SIZE : UINT64_C(0x100000000);
        host_fault_call = cases[index].fault_call;
        host_reads = host_deep_checks = 0;
        loader_fdt_bytes = 0;
        const enum FuxiRamProfileResult result = loader_check_ram((uintptr_t)host_address);
        if ((unsigned)result != cases[index].expected) {
            fprintf(stderr, "FAIL %s: expected %u, got %u\n", cases[index].name,
                cases[index].expected, (unsigned)result);
            return 1;
        }
        CHECK((unsigned)result == cases[index].expected);
        const unsigned deep = cases[index].expected == FuxiRamProfileStaticOk12G ||
            cases[index].expected == FuxiRamProfileSkuMissing || cases[index].expected == FuxiRamProfileSkuUnsupported;
        CHECK(host_deep_checks == deep);
        CHECK(host_reads == (deep ? 2 + (host_bytes + 3) / 4 : cases[index].overlap ? 2 : 3));
        CHECK(loader_fdt_bytes == (result == FuxiRamProfileStaticOk12G ? host_bytes : 0));
        CHECK(memcmp(host_data, cases[index].data, host_bytes) == 0);
        free(host_data);
    }
    printf("PASS loader entry RAM smoke: %s, %u cases, %u assertions\n",
        FG_BANK_SIZE == FUXI_RAM_PROFILE_9G ? "9g" : "5g", count, assertions);
    return 0;
}
'''


def main():
    paths = (LOADER, PROFILE, GPU)
    inputs = {path: path.read_bytes() for path in paths}
    source = inputs[LOADER].decode('utf-8')
    matched = re.search(r'^static enum FuxiRamProfileResult loader_check_ram\(uintptr_t fdt\)\s*\{.*?^\}',
                        source, re.MULTILINE | re.DOTALL)
    if matched is None:
        raise SystemExit('Cannot extract the bounded loader_check_ram function.')
    function, count = re.subn(r'\s*extern const unsigned char _head\[\], _end\[\];', '', matched.group())
    if count != 1:
        raise SystemExit('Unexpected loader image-symbol declaration; extraction refused.')
    function = re.sub(r'\b_head\b', 'host_head', function)
    function = re.sub(r'\b_end\b', 'host_end', function)
    pin = re.search(r'^static uint32_t loader_fdt_bytes;', source, re.MULTILINE)
    if pin is None:
        raise SystemExit('Missing production FDT bytecount pin.')
    gpu = inputs[GPU].decode('utf-8')
    constants = gpu[gpu.index('#define FG_RAM_BASE'):gpu.index('#define FG_HANDOFF')]
    fixtures = runpy.run_path(str(WORKSPACE / 'work/boot-chain/test-runtime-ram-profile.py'))
    normal, unused = fixtures['make_fdt']()
    sku8, unused = fixtures['make_fdt']([fixtures['memory_node'](sku=8)])
    memory = fixtures['memory_node']()
    missing, unused = fixtures['make_fdt']([(memory[0], [row for row in memory[1] if row[0] != 'ddr_size'], memory[2])])
    cases = [('normal', normal, 0, 'UINT64_MAX', 0), ('8g', sku8, 8, 'UINT64_MAX', 0),
             ('missing', missing, 7, 'UINT64_MAX', 0), ('fault', normal, 2, '2', 0),
             ('own-overlap', normal, 9, 'UINT64_MAX', 1),
             ('full-bank-overlap', normal, 9, 'UINT64_MAX', 2)]
    arrays = []
    rows = []
    for index, (name, data, expected, fault_call, overlap) in enumerate(cases):
        identifier = 'case_data_' + str(index)
        arrays.append('static const uint8_t ' + identifier + '[] = {' +
                      ','.join('0x' + format(value, '02x') for value in data) + '};')
        rows.append(f'{{"{name}", {identifier}, sizeof({identifier}), {expected}, {fault_call}, {overlap}}}')
    arrays.append('static const struct { const char *name; const uint8_t *data; size_t length; '
                  'unsigned expected; uint64_t fault_call; unsigned overlap; } cases[] = {' + ','.join(rows) + '};')
    harness = HARNESS.replace('@GPU_CONSTANTS@', constants).replace('@PIN_DECLARATION@', pin.group())
    harness = harness.replace('@CHECK_FUNCTION@', function).replace('@CASE_DATA@', '\n'.join(arrays))
    tools = runpy.run_path(str(WORKSPACE / 'work/adsp-battery/ksrc/tools/test-fuxi-audio-prep.py'))
    compiler, environment = tools['compiler_environment']()
    msvc = Path(compiler[0].strip('"')).name.lower() in ('cl', 'cl.exe')
    with tempfile.TemporaryDirectory(prefix='fuxi-entry-ram-smoke-') as directory:
        temporary = Path(directory)
        (temporary / PROFILE.name).write_bytes(inputs[PROFILE])
        test_source = temporary / 'entry_ram_smoke.c'
        test_source.write_text(harness, encoding='utf-8', newline='\n')
        for layout in ('5g', '9g'):
            executable = temporary / (layout + ('.exe' if os.name == 'nt' else ''))
            if msvc:
                flags = ['/nologo', '/TC', '/std:c11', '/W4', '/WX', '/Od', '/MD']
                if layout == '9g':
                    flags.append('/DFUXI_RAM_9G=1')
                command = compiler + flags + [str(test_source), '/Fe:' + str(executable)]
            else:
                flags = ['-std=c11', '-Wall', '-Wextra', '-Werror', '-O1']
                if layout == '9g':
                    flags.append('-DFUXI_RAM_9G=1')
                command = compiler + flags + [str(test_source), '-o', str(executable)]
            subprocess.run(command, cwd=directory, env=environment, check=True, timeout=60)
            result = subprocess.run([str(executable)], cwd=directory, env=environment, check=True,
                                    capture_output=True, text=True, timeout=30)
            print(result.stdout.strip())
    for path, data in inputs.items():
        if path.read_bytes() != data:
            raise SystemExit('Production input changed during smoke: ' + str(path))
        print('sha256 ' + hashlib.sha256(data).hexdigest() + '  ' + str(path))
    print('Host extraction only; no ARM abort/reset, private capture, device access or writes tested.')


if __name__ == '__main__':
    main()
