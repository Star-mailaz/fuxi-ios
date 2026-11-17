"""Extract production RTC reads for host fault tests; no ARM, SPMI or MMIO access."""

import hashlib
import os
from pathlib import Path
import re
import runpy
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'xnu/fuxi-h1/fuxi_keys.c'

HARNESS = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define FK_RTC_READ @READ_OFFSET@
static unsigned assertions;
#define CHECK(condition) do { assertions++; if (!(condition)) { fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); exit(1); } } while (0)
struct rtc_case {
    const char *name;
    uint8_t values[10];
    unsigned samples, fault_read, expected_reads;
    bool expected_ok;
    uint32_t seconds;
};
@CASES@
static const struct rtc_case *active_case;
static unsigned read_count;
static bool fk_read(uint16_t apid, uint8_t reg, uint8_t *out)
{
    const unsigned ordinal = read_count++;
    CHECK(apid == UINT16_C(0x1234));
    CHECK(ordinal < active_case->samples);
    const unsigned byte = ordinal % 5;
    CHECK(reg == (uint8_t)(FK_RTC_READ + (byte == 4 ? 0 : byte)));
    if (read_count == active_case->fault_read) {
        *out = 0xe7;
        return false;
    }
    *out = active_case->values[ordinal];
    return true;
}
@FUNCTION@
int main(void)
{
    const uint8_t sentinel_raw[4] = {0xa1, 0xb2, 0xc3, 0xd4};
    const unsigned count = (unsigned)(sizeof(cases) / sizeof(cases[0]));
    for (unsigned index = 0; index < count; index++) {
        active_case = &cases[index];
        read_count = 0;
        uint32_t seconds = UINT32_C(0xc0dec0de);
        uint8_t raw[4];
        memcpy(raw, sentinel_raw, sizeof(raw));
        const bool result = fk_rtc_read_raw(UINT16_C(0x1234), &seconds, raw);
        if (result != active_case->expected_ok) {
            fprintf(stderr, "FAIL %s: expected success=%u, got=%u\n", active_case->name,
                (unsigned)active_case->expected_ok, (unsigned)result);
            return 1;
        }
        CHECK(result == active_case->expected_ok);
        CHECK(read_count == active_case->expected_reads);
        if (result) {
            CHECK(seconds == active_case->seconds);
            for (unsigned byte_index = 0; byte_index < 4; byte_index++)
                CHECK(raw[byte_index] == (uint8_t)(active_case->seconds >> (byte_index * 8)));
        } else {
            CHECK(seconds == UINT32_C(0xc0dec0de));
            CHECK(memcmp(raw, sentinel_raw, sizeof(raw)) == 0);
        }
    }
    printf("PASS fk_rtc_read_raw host: %u cases, %u assertions; ARM/MMIO untested\n", count, assertions);
    return 0;
}
'''


def main():
    original = SOURCE.read_bytes()
    source = original.decode('utf-8')
    function = re.search(r'^static bool\s+fk_rtc_read_raw\([^)]*\)\s*\{.*?^\}',
                         source, re.MULTILINE | re.DOTALL)
    register = re.search(r'^#define\s+FK_RTC_READ\s+(\S+)', source, re.MULTILINE)
    if function is None or register is None:
        raise SystemExit('Production RTC function/register extraction refused.')
    stable = [0x78, 0x56, 0x34, 0x12, 0x78]
    rollover = [0xfe, 0xff, 0xff, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00]
    cases = [('stable', stable, 0, 5, True, 0x12345678),
             ('lsb-advances', stable[:4] + [0x79], 0, 5, True, 0x12345678),
             ('zero', [0] * 5, 0, 5, True, 0),
             ('maximum', [0xff] * 5, 0, 5, True, 0xffffffff)]
    cases += [('initial-byte-fault-' + str(read), stable, read, read, False, 0) for read in range(1, 5)]
    cases.append(('final-lsb-fault', stable, 5, 5, False, 0))
    cases.append(('rollover-retry-stable', rollover, 0, 10, True, 0x01000000))
    cases += [('rollover-retry-byte-fault-' + str(read), rollover, read, read, False, 0)
              for read in range(6, 10)]
    cases.append(('rollover-retry-final-lsb-fault', rollover, 10, 10, False, 0))
    cases.append(('rollover-twice-rejects', rollover[:5] + [0xfe, 0x00, 0x00, 0x01, 0x00], 0, 10, False, 0))
    rows = []
    for name, values, fault_read, expected_reads, expected_ok, seconds in cases:
        samples = '{' + ','.join(str(value) for value in values) + '}'
        rows.append('{' + f'"{name}", {samples}, {len(values)}, {fault_read}, {expected_reads}, '
                    f'{str(expected_ok).lower()}, UINT32_C({seconds})' + '}')
    table = 'static const struct rtc_case cases[] = {' + ',\n'.join(rows) + '};'
    harness = HARNESS.replace('@FUNCTION@', function.group()).replace('@READ_OFFSET@', register.group(1))
    harness = harness.replace('@CASES@', table)
    tools = runpy.run_path(str(ROOT / 'tools/test-fuxi-audio-prep.py'))
    compiler, environment = tools['compiler_environment']()
    msvc = Path(compiler[0].strip('"')).name.lower() in ('cl', 'cl.exe')
    with tempfile.TemporaryDirectory(prefix='fuxi-rtc-read-host-') as directory:
        temporary = Path(directory)
        test_source = temporary / 'rtc_read_host.c'
        test_source.write_text(harness, encoding='utf-8', newline='\n')
        executable = temporary / ('rtc-read.exe' if os.name == 'nt' else 'rtc-read')
        if msvc:
            command = compiler + ['/nologo', '/TC', '/std:c11', '/W4', '/WX', '/Od', '/MD',
                                  str(test_source), '/Fe:' + str(executable)]
        else:
            command = compiler + ['-std=c11', '-Wall', '-Wextra', '-Werror', '-O1',
                                  str(test_source), '-o', str(executable)]
        subprocess.run(command, cwd=directory, env=environment, check=True, timeout=60)
        result = subprocess.run([str(executable)], cwd=directory, env=environment,
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise SystemExit(result.stdout + result.stderr)
        print(result.stdout.strip())
    if SOURCE.read_bytes() != original:
        raise SystemExit('Production source changed during host tests.')
    print('sha256 ' + hashlib.sha256(original).hexdigest() + '  ' + str(SOURCE))
    print('Only extracted read logic executes; set_clock, bootargs, drivers and device entry do not run.')


if __name__ == '__main__':
    main()
