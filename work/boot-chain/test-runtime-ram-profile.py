import argparse
import hashlib
import os
from pathlib import Path
import runpy
import struct
import subprocess
import sys
import tempfile


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
HEADER = ROOT / "ios-fuxi/shim/fuxi-loader/fuxi-ram-profile.h"
BASE = 0x8C0000000
BANK5 = 0x140000000
BANK9 = 0x240000000
MAX_BYTES = 16 << 20
OK, ARGUMENT, BOUNDS, HEADER_ERROR, STRUCTURE, NAME, MODEL, SKU_MISSING, SKU_UNSUPPORTED, CONFLICT, CELLS, MEMORY, RESERVED, OVERFLOW, WINDOW, LIMIT = range(16)
REPLAY = (1 << 32) - 1
RESULT_NAMES = ("static-ok-12g", "argument", "bounds", "header", "structure", "name", "model",
    "sku-missing", "sku-unsupported", "conflict", "cells", "memory", "reserved", "overflow", "window", "limit")


def be32(value):
    return struct.pack(">I", value)


def regions(values):
    return b"".join(struct.pack(">QQ", start, size) for start, size in values)


def memory_node(sku=12, banks=None, extra=()):
    return ("memory", [("ddr_size", be32(sku)), ("device_type", b"memory\0"),
        ("reg", regions(banks if banks is not None else [(BASE, BANK9)]))] + list(extra), [])


def reserved_node(children=(), extra=()):
    return ("reserved-memory", [("#address-cells", be32(2)), ("#size-cells", be32(2)),
        ("ranges", b"")] + list(extra), list(children))


def make_fdt(children=None, root_extra=(), reserves=(), model=b"Qualcomm Technologies, Inc. fuxi\0"):
    strings = bytearray()
    offsets = {}
    locations = {}
    body = bytearray()

    def node(name, properties, descendants, parent=""):
        path = parent + "/" + name if parent else "/" + name
        encoded = name.encode("ascii") + b"\0"
        body.extend(be32(1) + encoded + bytes((-len(encoded)) % 4))
        for index, (key, value) in enumerate(properties):
            if key not in offsets:
                offsets[key] = len(strings)
                strings.extend(key.encode("ascii") + b"\0")
            locations[(path, key, index)] = len(body)
            body.extend(be32(3) + be32(len(value)) + be32(offsets[key]))
            body.extend(value + bytes((-len(value)) % 4))
        for child in descendants:
            node(*child, parent=path.rstrip("/"))
        body.extend(be32(2))

    properties = [("#address-cells", be32(2)), ("#size-cells", be32(2)), ("model", model)] + list(root_extra)
    node("", properties, [memory_node()] if children is None else children)
    body.extend(be32(9))
    strings.extend(bytes((-len(strings)) % 4))
    reserve_map = regions(reserves) + bytes(16)
    structure_offset = 40 + len(reserve_map)
    strings_offset = structure_offset + len(body)
    total = strings_offset + len(strings)
    header = struct.pack(">10I", 0xD00DFEED, total, structure_offset, strings_offset, 40,
        17, 16, 0, len(strings), len(body))
    absolute = {key: structure_offset + value for key, value in locations.items()}
    return header + reserve_map + body + strings, absolute


def changed_word(data, offset, value):
    result = bytearray(data)
    struct.pack_into(">I", result, offset, value)
    return bytes(result)


def replaced_structure(data, body):
    structure, strings, reserve = struct.unpack_from(">III", data, 8)
    strings_size = struct.unpack_from(">I", data, 32)[0]
    reserve_map = data[reserve:structure]
    names = data[strings:strings + strings_size]
    names_offset = 40 + len(reserve_map)
    body_offset = (names_offset + len(names) + 3) & ~3
    header = struct.pack(">10I", 0xD00DFEED, body_offset + len(body), body_offset,
        names_offset, 40, 17, 16, 0, len(names), len(body))
    return header + reserve_map + names + bytes(body_offset - names_offset - len(names)) + body


def fixtures():
    cases = []

    def add(name, data, expected=OK, bank=BANK9, available=None, offset=0, base=BASE, flags=0):
        cases.append((name, data, len(data) if available is None else available, offset, base, bank, expected, flags))

    valid, locations = make_fdt()
    add("12g-full-9g", valid)
    add("12g-full-5g", valid, bank=BANK5)
    adjacent = [(BASE, 0x40000000), (BASE + 0x40000000, 0x200000000)]
    add("adjacent-unsorted-9g", make_fdt([memory_node(banks=list(reversed(adjacent)))])[0])
    add("exact-5g-includes-gpu", make_fdt([memory_node(banks=[(BASE, BANK5)])])[0], bank=BANK5)
    add("5g-cannot-cover-9g", make_fdt([memory_node(banks=[(BASE, BANK5)])])[0], MEMORY)
    add("5g-gpu-tail-missing", make_fdt([memory_node(banks=[(BASE, BANK5 - 0x2000000)])])[0], MEMORY, bank=BANK5)
    add("9g-gpu-tail-missing", make_fdt([memory_node(banks=[(BASE, BANK9 - 0x2000000)])])[0], MEMORY)
    add("8g-fake-declared-9g", make_fdt([memory_node(sku=8)])[0], SKU_UNSUPPORTED)
    add("unknown-sku", make_fdt([memory_node(sku=16)])[0], SKU_UNSUPPORTED)
    add("zero-sku", make_fdt([memory_node(sku=0)])[0], SKU_UNSUPPORTED)
    memory = memory_node()
    add("missing-sku", make_fdt([(memory[0], memory[1][1:], [])])[0], SKU_MISSING)
    add("little-endian-12-is-not-sku", make_fdt([("memory", [("ddr_size", struct.pack("<I", 12))] + memory[1][1:], [])])[0], SKU_UNSUPPORTED)
    add("wrong-sku-size", make_fdt([("memory", [("ddr_size", b"\0\x0c")] + memory[1][1:], [])])[0], SKU_UNSUPPORTED)
    add("duplicate-sku-same", make_fdt([memory_node(extra=[("ddr_size", be32(12))])])[0], CONFLICT)
    add("duplicate-sku-conflict", make_fdt([memory_node(extra=[("ddr_size", be32(8))])])[0], CONFLICT)
    add("duplicate-memory-node", make_fdt([memory_node(), memory_node(sku=8)])[0], CONFLICT)
    add("ambiguous-memory-unit-node", make_fdt([memory_node(), ("memory@8c0000000", memory[1], [])])[0], CONFLICT)
    add("duplicate-model", make_fdt(root_extra=[("model", b"fuxi\0")])[0], CONFLICT)
    add("wrong-model", make_fdt(model=b"other\0")[0], MODEL)
    add("substring-is-not-model", make_fdt(model=b"notfuxi\0")[0], MODEL)
    add("different-fuxi-variant", make_fdt(model=b"fuxi-pro\0")[0], MODEL)
    add("exact-model", make_fdt(model=b"fuxi\0")[0])
    add("casefold-model", make_fdt(model=b"Qualcomm Technologies, Inc. FUXI\0")[0])
    add("unterminated-model", make_fdt(model=b"fuxi")[0], MODEL)
    add("string-list-model", make_fdt(model=b"other\0fuxi\0")[0], MODEL)
    add("model-non-ascii", make_fdt(model=b"fuxi\xff\0")[0], MODEL)
    add("zero-reg", make_fdt([memory_node(banks=[(BASE, 0)])])[0], MEMORY)
    add("complete-9g-plus-zero-slot-no-contribution", make_fdt([memory_node(banks=[(BASE, BANK9), (0, 0)])])[0])
    add("complete-5g-plus-zero-slot-no-contribution", make_fdt([memory_node(banks=[(BASE, BANK5), (0, 0)])])[0], bank=BANK5)
    add("nonzero-address-zero-memory-slot", make_fdt([memory_node(banks=[(0x90000000, 0)] + adjacent)])[0])
    add("all-zero-memory-no-coverage", make_fdt([memory_node(banks=[(0, 0), (BASE, 0)])])[0], MEMORY)
    add("zero-memory-cannot-fill-hole", make_fdt([memory_node(banks=[adjacent[0],
        (adjacent[1][0], 0), (adjacent[1][0] + 1, adjacent[1][1] - 1)])])[0], MEMORY)
    add("zero-memory-cannot-hide-overlap", make_fdt([memory_node(banks=[(BASE, 0)] + adjacent + [(BASE + 1, 1)])])[0], CONFLICT)
    add("zero-memory-cannot-hide-overflow", make_fdt([memory_node(banks=[(0, 0), (BASE, BANK9), ((1 << 64) - 1, 2)])])[0], OVERFLOW)
    add("zero-memory-cannot-admit-8g", make_fdt([memory_node(sku=8, banks=[(BASE, BANK9), (0, 0)])])[0], SKU_UNSUPPORTED)
    add("memory-zero-slots-at-limit", make_fdt([memory_node(banks=[(0, 0)] * 127 + [(BASE, BANK9)])])[0])
    add("memory-zero-slots-over-limit", make_fdt([memory_node(banks=[(0, 0)] * 128 + [(BASE, BANK9)])])[0], LIMIT)
    add("empty-reg", make_fdt([memory_node(banks=[])])[0], MEMORY)
    add("overflow-reg", make_fdt([memory_node(banks=[((1 << 64) - 16, 32)])])[0], OVERFLOW)
    add("overlapping-memory", make_fdt([memory_node(banks=adjacent + [(BASE + 1, 2)])])[0], CONFLICT)
    add("hole-in-9g", make_fdt([memory_node(banks=[adjacent[0], (adjacent[1][0] + 1, adjacent[1][1] - 1)])])[0], MEMORY)
    add("wrong-cell-layout", make_fdt(root_extra=[("#address-cells", be32(1))])[0], CELLS)
    add("duplicate-cells", make_fdt(root_extra=[("#address-cells", be32(2))])[0], CONFLICT)
    add("disabled-memory", make_fdt([memory_node(extra=[("status", b"disabled\0")])])[0], MEMORY)
    add("duplicate-reg", make_fdt([memory_node(extra=[("reg", regions([(BASE, BANK9)]))])])[0], CONFLICT)
    add("reserve-map-inside-gpu", make_fdt(reserves=[(BASE + BANK9 - 0x1000, 0x1000)])[0], RESERVED)
    add("reserve-map-inside-xnu", make_fdt(reserves=[(BASE, 0x1000)])[0], RESERVED)
    add("reserve-map-before-bank", make_fdt(reserves=[(BASE - 0x1000, 0x1000)])[0])
    add("reserve-map-after-bank", make_fdt(reserves=[(BASE + BANK9, 30 << 20)])[0])
    add("reserve-map-zero", make_fdt(reserves=[(BASE, 0)])[0], MEMORY)
    add("reserve-map-overflow", make_fdt(reserves=[((1 << 64) - 1, 2)])[0], OVERFLOW)
    child = ("owner@afe000000", [("reg", regions([(BASE + BANK9 - 0x2000000, 0x2000000)]))], [])
    add("reserved-memory-gpu-overlap", make_fdt([memory_node(), reserved_node([child])])[0], RESERVED)
    add("reserved-memory-xnu-overlap", make_fdt([memory_node(), reserved_node([("owner", [("reg", regions([(BASE, 1)]))], [])])])[0], RESERVED)
    add("reserved-memory-zero", make_fdt([memory_node(), reserved_node([("owner", [("reg", regions([(1, 0)]))], [])])])[0], MEMORY)
    empty_owners = [("empty-owner0", [("reg", regions([(0, 0)]))], []),
        ("empty-owner1", [("reg", regions([(0, 0)]))], [])]
    shape = [memory_node(banks=[(0x90000000, 0)] + list(reversed(adjacent))), reserved_node(empty_owners)]
    shape[0] = (shape[0][0], shape[0][1], [("ebuff", [], [])])
    add("capture-shaped-zero-placeholders-9g-static-only", make_fdt(shape)[0])
    add("capture-shaped-zero-placeholders-5g-static-only", make_fdt(shape)[0], bank=BANK5)
    memory = memory_node()
    add("memory-ebuff-properties-rejected", make_fdt([(memory[0], memory[1], [
        ("ebuff", [("reg", regions([(BASE, BANK9)]))], [])])])[0], STRUCTURE)
    add("memory-ebuff-children-rejected", make_fdt([(memory[0], memory[1], [
        ("ebuff", [], [("nested", [], [])])])])[0], STRUCTURE)
    add("memory-ebuff-duplicate-rejected", make_fdt([(memory[0], memory[1], [
        ("ebuff", [], []), ("ebuff", [], [])])])[0], CONFLICT)
    add("memory-other-empty-child-rejected", make_fdt([(memory[0], memory[1], [
        ("other", [], [])])])[0], STRUCTURE)
    add("reserved-zero-placeholder-cannot-hide-gpu-overlap", make_fdt([memory_node(), reserved_node(empty_owners + [child])])[0], RESERVED)
    add("reserved-zero-placeholder-cannot-hide-xnu-overlap", make_fdt([memory_node(), reserved_node(empty_owners + [
        ("owner", [("reg", regions([(BASE, 1)]))], [])])])[0], RESERVED)
    add("reserved-zero-nonzero-address-rejected", make_fdt([memory_node(), reserved_node([
        ("owner", [("reg", regions([(BASE, 0)]))], [])])])[0], MEMORY)
    add("reserved-zero-mixed-reg-rejected", make_fdt([memory_node(), reserved_node([
        ("owner", [("reg", regions([(0, 0), (1, 1)]))], [])])])[0], MEMORY)
    add("reserved-zero-multiple-tuples-rejected", make_fdt([memory_node(), reserved_node([
        ("owner", [("reg", regions([(0, 0), (0, 0)]))], [])])])[0], MEMORY)
    add("reserved-memory-overflow", make_fdt([memory_node(), reserved_node([("owner", [("reg", regions([((1 << 64) - 1, 2)]))], [])])])[0], OVERFLOW)
    add("reserved-memory-outside", make_fdt([memory_node(), reserved_node([("owner", [("reg", regions([(0x80000000, 0x1000)]))], [])])])[0])
    add("reserved-child-reg-malformed", make_fdt([memory_node(), reserved_node([("owner", [("reg", bytes(12))], [])])])[0], MEMORY)
    add("reserved-child-duplicate-reg", make_fdt([memory_node(), reserved_node([("owner", [("reg", regions([(1, 1)])), ("reg", regions([(2, 1)]))], [])])])[0], CONFLICT)
    for attribute, value in (("no-map", b""), ("reusable", b""), ("status", b"disabled\0")):
        add(f"reserved-{attribute}-still-overlap", make_fdt([memory_node(), reserved_node([
            (child[0], child[1] + [(attribute, value)], [])])])[0], RESERVED)
    add("dynamic-owner-not-clearance", make_fdt([memory_node(), reserved_node([("dynamic", [("size", struct.pack(">Q", 0x1000))], [])])])[0])
    add("dynamic-zero-size-still-rejected", make_fdt([memory_node(), reserved_node([
        ("dynamic", [("size", bytes(8))], [])])])[0], MEMORY)
    add("dynamic-wrong-size-cells-still-rejected", make_fdt([memory_node(), reserved_node([
        ("dynamic", [("size", bytes(4))], [])])])[0], MEMORY)
    add("reserved-translation-unsupported", make_fdt([memory_node(), reserved_node(extra=[("ranges", bytes(16))])])[0], RESERVED)
    add("duplicate-reserved-root", make_fdt([memory_node(), reserved_node(), reserved_node()])[0], CONFLICT)
    reserved = reserved_node([child])
    add("ambiguous-reserved-unit-node", make_fdt([memory_node(), ("reserved-memory@0", reserved[1], reserved[2])])[0], CONFLICT)
    add("reserve-map-not-terminated", changed_word(changed_word(valid, 40, 1), 52, 1), HEADER_ERROR)
    add("reserve-map-max-entries", make_fdt(reserves=[(1, 1)] * 1023)[0])
    add("reserve-map-entry-limit", make_fdt(reserves=[(1, 1)] * 1024)[0], HEADER_ERROR)
    add("wrong-window-base", valid, WINDOW, base=BASE + 0x1000)
    add("usable-length-not-full-bank", valid, WINDOW, bank=BANK9 - 0x2000000)
    add("new-30mib-window-not-admitted", valid, WINDOW, bank=BANK9 + (30 << 20))
    add("zero-bank", valid, OVERFLOW, bank=0)
    add("overflow-bank", valid, OVERFLOW, base=(1 << 64) - 1, bank=BANK9)
    add("null-pointer", valid, ARGUMENT, flags=1)
    add("misaligned-pointer", valid, ARGUMENT, offset=1)
    add("pointer-wrap", b"", OVERFLOW, available=40, flags=2)
    add("available-too-large", valid, BOUNDS, available=MAX_BYTES + 1)
    for length in range(len(valid)):
        add(f"physical-truncation-{length}", valid[:length], BOUNDS)
    for offset, value in ((0, 0), (20, 16), (20, 18), (24, 15), (24, 18),
                          (8, 0), (8, 41), (8, 0xFFFFFFFC), (12, 0), (12, 0xFFFFFFFF),
                          (16, 0), (16, 41), (16, 0xFFFFFFF8), (32, 0), (32, 0xFFFFFFFF),
                          (36, 0), (36, 15), (36, 0xFFFFFFFC)):
        add(f"header-field-{offset}-{value}", changed_word(valid, offset, value), HEADER_ERROR)
    add("declared-too-large", changed_word(valid, 4, MAX_BYTES + 1), BOUNDS)
    add("declared-too-small", changed_word(valid, 4, 39), BOUNDS)
    add("structure-strings-overlap", changed_word(valid, 12, struct.unpack_from(">I", valid, 8)[0]), HEADER_ERROR)
    prop = next(value for (path, key, index), value in locations.items() if path == "/memory" and key == "reg")
    add("property-length-overflow", changed_word(valid, prop + 4, 0xFFFFFFFF), STRUCTURE)
    add("property-name-offset-overflow", changed_word(valid, prop + 8, 0xFFFFFFFF), NAME)
    strings_size = struct.unpack_from(">I", valid, 32)[0]
    malformed = bytearray(changed_word(valid, prop + 8, strings_size - 1))
    malformed[-1] = ord("x")
    add("property-name-unterminated-at-bound", bytes(malformed), NAME)
    add("node-name-unterminated-bound", make_fdt([memory_node(), ("a" * 256, [], [])])[0], NAME)
    add("node-name-max-bound", make_fdt([memory_node(), ("a" * 255, [], [])])[0])
    add("node-name-unterminated-physical-end", replaced_structure(valid, be32(1) + b"x" * 12), NAME)
    add("node-empty-child-name", make_fdt([memory_node(), ("", [], [])])[0], NAME)
    structure_offset = struct.unpack_from(">I", valid, 8)[0]
    structure_size = struct.unpack_from(">I", valid, 36)[0]
    body = valid[structure_offset:structure_offset + structure_size]
    add("property-value-truncated-physical-end", replaced_structure(valid, body[:20]), STRUCTURE)
    add("property-header-truncated-physical-end", replaced_structure(valid, body[:16]), STRUCTURE)
    add("structure-end-trailing-token", replaced_structure(valid, body + be32(4)), STRUCTURE)
    add("nop-prefix-valid", replaced_structure(valid, be32(4) * 8 + body))
    add("token-count-limit", replaced_structure(valid, be32(4) * 262145 + body), LIMIT)
    add("bad-token", changed_word(valid, structure_offset, 5), STRUCTURE)
    add("missing-end", changed_word(valid, struct.unpack_from(">I", valid, 12)[0] - 4, 4), STRUCTURE)
    add("unbalanced-end", changed_word(valid, structure_offset, 2), STRUCTURE)
    nested = ("leaf", [], [])
    for depth in range(65):
        nested = (f"node{depth}", [], [nested])
    add("depth-limit", make_fdt([memory_node(), nested])[0], LIMIT)
    many = [(BASE + index * 0x1000, 0x1000) for index in range(129)]
    add("range-count-limit", make_fdt([memory_node(banks=many)])[0], LIMIT)
    empty_padding, unused = make_fdt(root_extra=[("bounded-padding", b"")])
    large, unused = make_fdt(root_extra=[("bounded-padding", bytes(MAX_BYTES - len(empty_padding)))])
    assert len(large) == MAX_BYTES
    add("exact-16mib-bound", large)
    return cases


HARNESS = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "fuxi-ram-profile.h"
static unsigned checks;
#define CHECK(condition) do { checks++; if (!(condition)) { fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); exit(1); } } while (0)
static uint32_t suite32(const uint8_t *bytes) {
    return (uint32_t)bytes[0] | (uint32_t)bytes[1] << 8 | (uint32_t)bytes[2] << 16 | (uint32_t)bytes[3] << 24;
}
static uint64_t suite64(const uint8_t *bytes) { return (uint64_t)suite32(bytes) | (uint64_t)suite32(bytes + 4) << 32; }
int main(int argc, char **argv) {
    CHECK(argc == 2);
    FILE *input = fopen(argv[1], "rb"); CHECK(input != NULL);
    uint8_t header[40]; CHECK(fread(header, 1, 4, input) == 4);
    const uint32_t cases = suite32(header);
    for (uint32_t index = 0; index < cases; index++) {
        CHECK(fread(header, 1, 40, input) == 40);
        const uint32_t length = suite32(header), offset = suite32(header + 4);
        const uint64_t available = suite64(header + 8), base = suite64(header + 16), bank = suite64(header + 24);
        const uint32_t expected = suite32(header + 32), flags = suite32(header + 36);
        CHECK(length <= FUXI_RAM_FDT_MAX_BYTES && offset <= 7 && available <= SIZE_MAX);
        uint8_t *allocation = malloc(length + offset ? length + offset : 1);
        uint8_t *before = malloc(length ? length : 1);
        CHECK(allocation != NULL && before != NULL);
        uint8_t *data = allocation + offset;
        CHECK(fread(data, 1, length, input) == length); memcpy(before, data, length);
        const void *fdt = flags == 1 ? NULL : flags == 2 ? (const void *)(UINTPTR_MAX & ~(uintptr_t)7) : data;
        const enum FuxiRamProfileResult result = fuxi_ram_profile_check(fdt, (size_t)available, base, bank);
        if (expected == UINT32_MAX) {
            printf("REPLAY case %u result %u\n", index, (unsigned)result);
        } else {
            CHECK((unsigned)result <= FuxiRamProfileLimit);
            if ((unsigned)result != expected) { fprintf(stderr, "FAIL case %u: expected %u got %u\n", index, expected, (unsigned)result); return 1; }
            CHECK((unsigned)result == expected);
        }
        CHECK(memcmp(before, data, length) == 0);
        free(before); free(allocation);
    }
    CHECK(fgetc(input) == EOF); CHECK(fclose(input) == 0);
    printf("PASS runtime RAM profile: %u cases, %u assertions; static-only, no writes\n", cases, checks);
    return 0;
}
'''


def run_suite(compiler, environment, sanitize, cases):
    msvc = Path(compiler[0].strip('"')).name.lower() in ("cl", "cl.exe")
    with tempfile.TemporaryDirectory(prefix="fuxi-runtime-ram-") as directory:
        temporary = Path(directory)
        harness = temporary / "test_ram_profile.c"
        harness.write_text(HARNESS, encoding="utf-8", newline="\n")
        suite = temporary / "synthetic_cases.bin"
        with suite.open("wb") as output:
            output.write(struct.pack("<I", len(cases)))
            for name, data, available, offset, base, bank, expected, flags in cases:
                output.write(struct.pack("<IIQQQII", len(data), offset, available, base, bank, expected, flags))
                output.write(data)
        executable = temporary / ("ram-profile.exe" if os.name == "nt" else "ram-profile")
        if msvc:
            flags = ["/nologo", "/TC", "/std:c11", "/W4", "/WX", "/Od", "/Zi", "/MD"]
            if sanitize:
                flags += ["/fsanitize=address"]
            command = compiler + flags + [f"/I{HEADER.parent}", str(harness), f"/Fe:{executable}"]
        else:
            flags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1", "-g"]
            if sanitize:
                flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
            command = compiler + flags + ["-I", str(HEADER.parent), str(harness), "-o", str(executable)]
        subprocess.run(command, cwd=directory, env=environment, check=True, timeout=120)
        result = subprocess.run([str(executable), str(suite)], cwd=directory, env=environment,
            capture_output=True, text=True, timeout=90)
        if result.returncode:
            failure = result.stdout + result.stderr
            for line in failure.splitlines():
                if line.startswith("FAIL case "):
                    index = int(line.split()[2].rstrip(":"))
                    failure += f"\nfixture={cases[index][0]}"
            raise SystemExit(failure)
        for line in result.stdout.splitlines():
            if line.startswith("REPLAY case "):
                fields = line.split()
                index, verdict = int(fields[2]), int(fields[4])
                print(f"{cases[index][0]}: result={verdict} ({RESULT_NAMES[verdict]})")
            else:
                print(line)
        print(f"compiler={Path(compiler[0]).name}, sanitize={sanitize}")


def main():
    parser = argparse.ArgumentParser(description="Synthetic host replay of the unwired incoming-FDT RAM guard; no device access.")
    parser.add_argument("--sanitize", action="store_true")
    parser.add_argument("--live-fdt", type=Path, help="Optional local capture, read-only; never downloaded or published.")
    parser.add_argument("--live-expect", type=int, choices=range(len(RESULT_NAMES)),
        help="Optional asserted return code for both local-capture windows; not runtime proof.")
    arguments = parser.parse_args()
    if arguments.live_expect is not None and arguments.live_fdt is None:
        parser.error("--live-expect requires --live-fdt")
    digest = hashlib.sha256(HEADER.read_bytes()).hexdigest()
    host_tools = runpy.run_path(str(ROOT / "work/adsp-battery/ksrc/tools/test-fuxi-audio-prep.py"))
    compiler, environment = host_tools["compiler_environment"]()
    cases = fixtures()
    if arguments.live_fdt is not None:
        with arguments.live_fdt.open("rb") as capture:
            data = capture.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise SystemExit("Local capture exceeds 16 MiB; not replayed.")
        expected = REPLAY if arguments.live_expect is None else arguments.live_expect
        cases += [("local-capture-5g", data, len(data), 0, BASE, BANK5, expected, 0),
                  ("local-capture-9g", data, len(data), 0, BASE, BANK9, expected, 0)]
        if arguments.live_expect is not None:
            print(f"Both local-capture windows must return {expected} ({RESULT_NAMES[expected]}).")
        print("Optional local capture replay only: not runtime phone proof or dynamic-owner clearance.")
    run_suite(compiler, environment, arguments.sanitize, cases)
    if hashlib.sha256(HEADER.read_bytes()).hexdigest() != digest:
        raise SystemExit("Guard header changed during tests.")
    print(f"sha256 header {digest}")
    print("Default fixtures are synthetic only; no private DTB is needed or published.")


if __name__ == "__main__":
    main()
