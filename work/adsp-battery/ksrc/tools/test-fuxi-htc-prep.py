#!/usr/bin/env python3
"""Compile and exercise the independent production HTC parser, without device IO."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'xnu/fuxi-htc-prep/fuxi_htc_prep.c'
INCLUDE = SOURCE.parent
TESTS = r'''
#include "fuxi_htc_prep.h"
#include <stdio.h>
#include <string.h>

static unsigned checks;
#define CHECK(condition) do { checks++; if (!(condition)) return __LINE__; } while (0)

static void write16(uint8_t *bytes, unsigned value) {
    bytes[0] = (uint8_t)value;
    bytes[1] = (uint8_t)(value >> 8);
}

static size_t wire_frame(uint8_t *bytes, unsigned endpoint, unsigned flags,
    unsigned trailer, const uint8_t *payload, size_t length) {
    memset(bytes, 0, 8);
    bytes[0] = (uint8_t)endpoint;
    bytes[1] = (uint8_t)flags;
    write16(bytes + 2, (unsigned)length);
    bytes[4] = (uint8_t)trailer;
    bytes[5] = 0x7b;
    if (length) memcpy(bytes + 8, payload, length);
    return 8 + length;
}

static size_t wire_ready(uint8_t *bytes, unsigned extended) {
    const uint8_t payload[] = {1,0,32,0,0,2,9,0,1,8,0,0};
    return wire_frame(bytes, 0, 0, 0, payload, extended ? 12 : 8);
}

static int test_ready_and_control(void) {
    uint8_t storage[FUXI_HTC_MAX_FRAME + 1];
    uint8_t *bytes = storage + 1;
    struct fuxi_htc_frame output;
    size_t length = wire_ready(bytes, 0);
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_OK);
    CHECK(output.control_kind == FUXI_HTC_CONTROL_READY);
    CHECK(output.message_id == 1 && output.ready_credit_count == 32);
    CHECK(output.ready_credit_size == 512 && output.ready_max_endpoints == 9);
    CHECK(!output.ready_extended && output.control_bytes == 8);
    CHECK(output.control_byte1 == 0x7b && !output.credit_mask);
    for (size_t prefix = 0; prefix < length; prefix++) {
        uint8_t before[sizeof(output)];
        memset(&output, 0xa5, sizeof(output));
        memcpy(before, &output, sizeof(output));
        CHECK(fuxi_htc_parse_frame(bytes, prefix, &output) < 0);
        CHECK(!memcmp(before, &output, sizeof(output)));
    }
    length = wire_ready(bytes, 1);
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_OK);
    CHECK(output.ready_extended && output.ready_version == 1 && output.ready_max_bundle == 8);
    const unsigned offsets[] = {10,12,14,15,16,18};
    const uint8_t invalid[] = {0,0,10,1,2,1};
    for (size_t index = 0; index < sizeof(offsets) / sizeof(offsets[0]); index++) {
        wire_ready(bytes, 1);
        bytes[offsets[index]] = invalid[index];
        if (offsets[index] == 12) bytes[13] = 0;
        CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_INVALID_CONTROL);
    }
    wire_ready(bytes, 1);
    CHECK(fuxi_htc_parse_frame(bytes, length - 1, &output) < 0);
    bytes[0] = 1;
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_OK);
    CHECK(output.control_kind == FUXI_HTC_CONTROL_NONE && !output.control_bytes);
    uint8_t payload[257] = {99,0,0,0};
    payload[255] = 0xee;
    length = wire_frame(bytes, 0, 0, 0, payload, 256);
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_OK);
    CHECK(output.control_kind == FUXI_HTC_CONTROL_OTHER && output.message_id == 99);
    CHECK(output.control[255] == 0xee && output.control_bytes == 256);
    length = wire_frame(bytes, 0, 0, 0, payload, 257);
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_INVALID_CONTROL);
    for (size_t payload_length = 1; payload_length <= 3; payload_length++) {
        length = wire_frame(bytes, 0, 0, 0, payload, payload_length);
        CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_INVALID_CONTROL);
    }
    return 0;
}

static int test_connect_response(void) {
    uint8_t bytes[512];
    uint8_t payload[] = {3,0,0,1,0,2,0,4,2,0,0,0,0xaa,0xbb};
    struct fuxi_htc_frame output;
    size_t length = wire_frame(bytes, 0, 0, 0, payload, sizeof(payload));
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_OK);
    CHECK(output.control_kind == FUXI_HTC_CONTROL_CONNECT_RESPONSE);
    CHECK(output.connect_service_id == 0x100 && output.connect_endpoint == 2);
    CHECK(output.connect_max_message == 1024 && output.connect_metadata_bytes == 2);
    CHECK(!output.connect_status && output.control[13] == 0xbb);
    const unsigned offsets[] = {12,13,14,16,17};
    const uint8_t values[] = {5,9,0,3,1};
    for (size_t index = 0; index < sizeof(offsets) / sizeof(offsets[0]); index++) {
        wire_frame(bytes, 0, 0, 0, payload, sizeof(payload));
        bytes[offsets[index]] = values[index];
        if (offsets[index] == 14) bytes[15] = 0;
        CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_INVALID_CONTROL);
    }
    wire_frame(bytes, 0, 0, 0, payload, sizeof(payload));
    bytes[13] = 0;
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_INVALID_CONTROL);
    write16(bytes + 10, 0);
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_INVALID_CONTROL);
    payload[4] = 2; payload[5] = 255; payload[6] = payload[7] = 0;
    length = wire_frame(bytes, 0, 0, 0, payload, sizeof(payload));
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_OK);
    CHECK(output.connect_status == 2 && output.connect_endpoint == 255);
    return 0;
}

static int test_trailer_and_credit_endpoints(void) {
    uint8_t bytes[512];
    const uint8_t payload[] = {0xca,0xfe,0,0,0,0,1,12,0,0,2,7,0,0,8,255,0,0,2,9,0,0};
    struct fuxi_htc_frame output;
    size_t length = wire_frame(bytes, 3, 2, 20, payload, sizeof(payload));
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_OK);
    CHECK(output.endpoint == 3 && output.payload_bytes == 2 && output.trailer_bytes == 20);
    CHECK(output.trailer_records == 2 && output.credit_reports == 3);
    CHECK(output.credit_mask == ((1u << 2) | (1u << 8)));
    CHECK(output.credit_delta[2] == 16 && output.credit_delta[8] == 255);
    CHECK(!output.credit_delta[3] && !output.control_bytes);
    for (size_t prefix = 0; prefix < length; prefix++) {
        CHECK(fuxi_htc_parse_frame(bytes, prefix, &output) < 0);
    }
    uint8_t before[sizeof(output)];
    memset(&output, 0x7c, sizeof(output));
    memcpy(before, &output, sizeof(output));
    bytes[26] = 9;
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_INVALID_ENDPOINT);
    CHECK(!memcmp(before, &output, sizeof(output)));
    wire_frame(bytes, 3, 2, 20, payload, sizeof(payload));
    bytes[15] = 250;
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_INVALID_LENGTH);
    wire_frame(bytes, 3, 2, 20, payload, sizeof(payload));
    bytes[16] = 1;
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_INVALID_PROTOCOL);
    wire_frame(bytes, 3, 2, 20, payload, sizeof(payload));
    bytes[28] = 1;
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_INVALID_CREDIT);
    uint8_t malformed[] = {1,5,0,0,2,1,0,0,0};
    length = wire_frame(bytes, 1, 2, sizeof(malformed), malformed, sizeof(malformed));
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_INVALID_CREDIT);
    malformed[0] = 7;
    length = wire_frame(bytes, 1, 2, sizeof(malformed), malformed, sizeof(malformed));
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_INVALID_PROTOCOL);
    const uint8_t trailer_only[] = {1,4,0,0,0,3,0,0};
    length = wire_frame(bytes, 0, 2, sizeof(trailer_only), trailer_only, sizeof(trailer_only));
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_OK);
    CHECK(!output.payload_bytes && !output.control_bytes && output.credit_delta[0] == 3);
    return 0;
}

static int test_frame_and_count_bounds(void) {
    uint8_t bytes[FUXI_HTC_MAX_FRAME + 1];
    uint8_t payload[FUXI_HTC_MAX_FRAME - 8] = {0};
    struct fuxi_htc_frame output;
    size_t length = wire_frame(bytes, 8, 0, 0, payload, sizeof(payload));
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_OK);
    CHECK(output.payload_bytes == 4088);
    CHECK(fuxi_htc_parse_frame(bytes, length + 1, &output) == FUXI_HTC_INVALID_LENGTH);
    CHECK(fuxi_htc_parse_frame(NULL, 8, &output) == FUXI_HTC_INVALID_INPUT);
    CHECK(fuxi_htc_parse_frame(bytes, length, NULL) == FUXI_HTC_INVALID_INPUT);
    write16(bytes + 2, 65535);
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_INVALID_LENGTH);
    length = wire_ready(bytes, 0);
    const unsigned offsets[] = {0,1,4,6,7};
    const uint8_t invalid[] = {9,0x10,1,1,1};
    for (size_t index = 0; index < sizeof(offsets) / sizeof(offsets[0]); index++) {
        wire_ready(bytes, 0); bytes[offsets[index]] = invalid[index];
        CHECK(fuxi_htc_parse_frame(bytes, length, &output) < 0);
    }
    for (unsigned trailer = 0; trailer < 4; trailer++) {
        wire_ready(bytes, 0); bytes[1] = 2; bytes[4] = (uint8_t)trailer;
        CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_INVALID_LENGTH);
    }
    wire_ready(bytes, 0); bytes[1] = 2; bytes[4] = 9;
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_INVALID_LENGTH);
    memset(payload, 0, sizeof(payload));
    payload[0] = 1; payload[1] = 248;
    for (unsigned index = 0; index < 62; index++) {
        payload[4 + index * 4] = (uint8_t)(index % 9);
        payload[5 + index * 4] = 255;
    }
    length = wire_frame(bytes, 8, 2, 252, payload, 252);
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_OK);
    CHECK(output.credit_reports == 62 && output.credit_delta[0] == 1785);
    for (unsigned index = 0; index < 62; index++) payload[4 + index * 4] = 8;
    length = wire_frame(bytes, 1, 2, 252, payload, 252);
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_OK);
    CHECK(output.credit_delta[8] == 15810 && output.credit_mask == (1u << 8));
    memset(payload, 0, 255);
    length = wire_frame(bytes, 8, 2, 252, payload, 252);
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_OK);
    CHECK(output.trailer_records == 63 && !output.credit_reports);
    length = wire_frame(bytes, 8, 2, 255, payload, 255);
    CHECK(fuxi_htc_parse_frame(bytes, length, &output) == FUXI_HTC_INVALID_LENGTH);
    return 0;
}

struct callback_state {
    unsigned calls;
    struct fuxi_htc_frame last;
    struct fuxi_htc_observer *observer;
    const uint8_t *wire;
    size_t length;
    int recursive_result;
};

static void receive_observation(void *context, const struct fuxi_htc_frame *frame) {
    struct callback_state *state = context;
    state->calls++;
    state->last = *frame;
    state->recursive_result = fuxi_htc_observe(state->observer, state->wire, state->length);
}

static int test_default_off_and_bounded_callback(void) {
    uint8_t bytes[64];
    size_t length = wire_ready(bytes, 0);
    struct fuxi_htc_observer observer;
    struct callback_state state = {0};
    state.observer = &observer; state.wire = bytes; state.length = length;
    CHECK(fuxi_htc_observer_init(&observer, receive_observation, &state) == FUXI_HTC_OK);
    CHECK(FUXI_HTC_DEFAULT_ACTIVE == 0 && !observer.active);
    CHECK(fuxi_htc_observe(&observer, NULL, SIZE_MAX) == FUXI_HTC_INACTIVE);
    CHECK(!state.calls && observer.callbacks_remaining == 16);
    observer.active = 2;
    CHECK(fuxi_htc_observe(&observer, bytes, length) == FUXI_HTC_INVALID_INPUT);
    observer.active = 1;
    uint8_t before[sizeof(observer)];
    memcpy(before, &observer, sizeof(observer));
    CHECK(fuxi_htc_observe(&observer, bytes, length - 1) < 0);
    CHECK(!memcmp(before, &observer, sizeof(observer)) && !state.calls);
    const uint8_t bad_credit_tail[] = {1,8,0,0,2,7,0,0,9,8,0,0};
    size_t bad_length = wire_frame(bytes, 3, 2, sizeof(bad_credit_tail), bad_credit_tail, sizeof(bad_credit_tail));
    CHECK(fuxi_htc_observe(&observer, bytes, bad_length) == FUXI_HTC_INVALID_ENDPOINT);
    CHECK(!memcmp(before, &observer, sizeof(observer)) && !state.calls);
    length = wire_ready(bytes, 0);
    for (unsigned count = 0; count < 16; count++) {
        CHECK(fuxi_htc_observe(&observer, bytes, length) == FUXI_HTC_OK);
        CHECK(state.calls == count + 1 && observer.callbacks_delivered == count + 1);
        CHECK(observer.callbacks_remaining == 15 - count && !observer.in_callback);
        CHECK(state.recursive_result == FUXI_HTC_CALLBACK_BUSY);
        CHECK(state.last.control_kind == FUXI_HTC_CONTROL_READY);
    }
    CHECK(fuxi_htc_observe(&observer, bytes, length) == FUXI_HTC_CALLBACK_LIMIT);
    CHECK(state.calls == 16 && !observer.callbacks_remaining);
    CHECK(fuxi_htc_observer_init(NULL, receive_observation, &state) == FUXI_HTC_INVALID_INPUT);
    CHECK(fuxi_htc_observe(NULL, bytes, length) == FUXI_HTC_INVALID_INPUT);
    CHECK(fuxi_htc_observer_init(&observer, NULL, &state) == FUXI_HTC_OK);
    observer.active = 1;
    CHECK(fuxi_htc_observe(&observer, bytes, length) == FUXI_HTC_INVALID_INPUT);
    CHECK(!observer.callbacks_delivered && observer.callbacks_remaining == 16);
    return 0;
}

static int test_bounded_malformed_corpus(void) {
    uint8_t bytes[272];
    uint32_t random_state = 0x20261116;
    struct guarded_output {
        uint32_t before;
        struct fuxi_htc_frame frame;
        uint32_t after;
    } output;
    for (unsigned iteration = 0; iteration < 512; iteration++) {
        for (size_t index = 0; index < sizeof(bytes); index++) {
            random_state ^= random_state << 13;
            random_state ^= random_state >> 17;
            random_state ^= random_state << 5;
            bytes[index] = (uint8_t)random_state;
        }
        size_t length = 8 + iteration % 264;
        bytes[0] = (uint8_t)(iteration % 10);
        bytes[1] = (uint8_t)(iteration % 3);
        write16(bytes + 2, (unsigned)(length - 8));
        bytes[6] = bytes[7] = 0;
        uint8_t original[sizeof(output.frame)];
        memset(&output, 0xc3, sizeof(output));
        memcpy(original, &output.frame, sizeof(original));
        int result = fuxi_htc_parse_frame(bytes, length, &output.frame);
        CHECK(output.before == 0xc3c3c3c3u && output.after == 0xc3c3c3c3u);
        if (result) {
            CHECK(!memcmp(original, &output.frame, sizeof(original)));
        } else {
            CHECK(output.frame.endpoint < 9 && output.frame.control_bytes <= 256);
            CHECK(output.frame.credit_reports <= 62 && output.frame.trailer_records <= 63);
        }
    }
    return 0;
}

int main(void) {
    int (*cases[])(void) = {test_ready_and_control, test_connect_response,
        test_trailer_and_credit_endpoints, test_frame_and_count_bounds,
        test_default_off_and_bounded_callback, test_bounded_malformed_corpus};
    for (size_t index = 0; index < sizeof(cases) / sizeof(cases[0]); index++) {
        int result = cases[index]();
        if (result) {
            fprintf(stderr, "HTC case %zu failed at peer line %d\n", index + 1, result);
            return 1;
        }
    }
    printf("HTC production parser: 6 cases, %u checks; default-off, READY/control, credit EIDs, bounds, atomic rejection and callback budget passed\n", checks);
    return 0;
}
'''


def msvc_environment():
    installer = Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Microsoft Visual Studio/Installer/vswhere.exe'
    if not installer.is_file():
        raise SystemExit('Installed MSVC or a POSIX host compiler is required; no tools are installed by this test')
    location = subprocess.run([str(installer), '-latest', '-products', '*', '-property', 'installationPath'],
                              check=True, capture_output=True, text=True, timeout=30).stdout.strip()
    developer = Path(location) / 'Common7/Tools/VsDevCmd.bat'
    if not location or not developer.is_file():
        raise SystemExit('No installed Visual Studio C compiler environment found')
    command = f'cmd.exe /d /s /c "call "{developer}" -no_logo -arch=x64 -host_arch=x64 >nul && set"'
    result = subprocess.run(command,
                            check=True, capture_output=True, text=True, timeout=60)
    environment = os.environ.copy()
    for line in result.stdout.splitlines():
        if '=' in line and not line.startswith('='):
            name, value = line.split('=', 1)
            environment[name.upper()] = value
    return environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arm64-compiler', type=Path, help='Explicit clang path for an additional freestanding iOS compile-only check')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='fuxi-htc-prep-test-') as temporary:
        directory = Path(temporary).resolve()
        if directory.parent != Path(tempfile.gettempdir()).resolve():
            raise SystemExit('Unexpected temporary output directory')
        peer = directory / 'htc-peer.c'
        peer.write_text(TESTS, encoding='utf-8')
        environment = os.environ.copy()
        if os.name == 'nt':
            environment = msvc_environment()
            compiler = shutil.which('cl.exe', path=environment['PATH'])
            if not compiler:
                raise SystemExit('The selected Visual Studio installation has no host C compiler')
            binary = directory / 'htc-tests.exe'
            command = [compiler, '/nologo', '/std:c11', '/W4', '/WX', '/Od', '/Zi', '/MD', '/fsanitize=address',
                       '/I' + str(INCLUDE), str(SOURCE), str(peer), '/Fe' + str(binary),
                       '/Fo' + str(directory) + os.sep, '/Fd' + str(directory / 'htc-tests.pdb')]
            print('Host validation: MSVC C11 /W4 /WX + AddressSanitizer (no UBSan on this host)', flush=True)
        else:
            compiler = os.environ.get('CC') or shutil.which('cc')
            if not compiler:
                raise SystemExit('CC/cc is required; no compiler is installed by this test')
            binary = directory / 'htc-tests'
            command = [compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-Wconversion', '-O1', '-g',
                       '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-fno-omit-frame-pointer',
                       '-I', str(INCLUDE), str(SOURCE), str(peer), '-o', str(binary)]
            print('Host validation: C11 strict warnings + ASan/UBSan', flush=True)
        subprocess.run(command, cwd=directory, env=environment, check=True, timeout=120)
        subprocess.run([str(binary)], cwd=directory, env=environment, check=True, timeout=30)
        if args.arm64_compiler:
            subprocess.run([str(args.arm64_compiler.resolve()), '-target', 'arm64-apple-ios16.0',
                            '-std=c11', '-Wall', '-Wextra', '-Werror', '-Wconversion', '-ffreestanding', '-fno-builtin',
                            '-I', str(INCLUDE), '-c', str(SOURCE), '-o', str(directory / 'htc-arm64.o')],
                           cwd=directory, check=True, timeout=60)
            print('Freestanding arm64 iOS compile-only: PASS', flush=True)


if __name__ == '__main__':
    main()
