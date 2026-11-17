#!/usr/bin/env python3
"""Inspect manifest-verified ARM64 Mach-O Bluetooth binaries without modifying them."""

import argparse
import bisect
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT.parents[1] / "statusbar-fix" / "inspect-radio-assets-20261116-1436" / "assets.json"
STRING_SECTIONS = {"__cstring", "__objc_methname", "__objc_classname", "__oslogstring"}
DEFAULT_PATTERN = r"(?i)uart|skywalk|bluetooth|transport|capabilit|controller|BlueTool|hci|ioctl"
DEFAULT_CALLS = r"^_(ioctl|access|open|close|fcntl|socket|connect|setsockopt|getsockopt|tcgetattr|tcsetattr|cfmakeraw|cfsetspeed|IOConnectCallMethod|IOConnectCallScalarMethod|IOServiceOpen|os_channel_create|sysctlbyname|xpc_connection_create_mach_service)(?:\$[A-Z_]+)?$"
MAX_BYTES = 128 * 1024 * 1024


def checked(data, offset, size):
    if offset < 0 or size < 0 or offset + size > len(data):
        raise ValueError(f"out-of-file range {offset:#x}+{size:#x}")
    return data[offset:offset + size]


def cstring(data, offset, end):
    if not 0 <= offset < end <= len(data):
        raise ValueError("invalid string-table range")
    terminator = data.find(b"\0", offset, end)
    if terminator < 0:
        raise ValueError("unterminated string")
    return data[offset:terminator].decode("utf-8", errors="replace")


def uleb_values(data):
    value = shift = 0
    for byte in data:
        if shift >= 64 or (shift == 63 and byte & 0x7e):
            raise ValueError("oversized ULEB128")
        value |= (byte & 0x7f) << shift
        if byte & 0x80:
            shift += 7
        else:
            yield value
            value = shift = 0
    if shift:
        raise ValueError("truncated ULEB128")


def version_word(value):
    return f"{value >> 16}.{(value >> 8) & 255}.{value & 255}"


def pointer64_offset(raw, base):
    stride = ((raw >> 51) & 0xfff) * 4
    if raw >> 63:
        return None, stride
    if (raw >> 44) & 0x7f:
        raise ValueError("nonzero reserved DYLD_CHAINED_PTR_64_OFFSET bits")
    target = ((raw & ((1 << 36) - 1)) | (((raw >> 36) & 255) << 56)) + base
    return target, stride


class MachO:
    def __init__(self, data):
        self.data = data
        header = checked(data, 0, 32)
        magic, cpu, subtype, kind, count, command_bytes, flags, reserved = struct.unpack("<8I", header)
        if magic != 0xfeedfacf or cpu != 0x100000c or kind != 2:
            raise ValueError("only thin little-endian ARM64 MH_EXECUTE is supported")
        if count > 512 or reserved or subtype & 0xffffff:
            raise ValueError("unsupported ARM64 subtype or header bounds")
        self.header = {"architecture": "arm64", "cpu_subtype": subtype, "flags": hex(flags)}
        self.sections = []
        self.segments = []
        self.commands = {}
        self.dylibs = []
        self.uuid = None
        self.build = None
        command_end = 32 + command_bytes
        checked(data, 32, command_bytes)
        offset = 32
        for index in range(count):
            cmd, size = struct.unpack("<II", checked(data, offset, 8))
            if size < 8 or size % 8 or offset + size > command_end:
                raise ValueError("invalid load-command bounds")
            payload = checked(data, offset, size)
            if cmd in (2, 0xb, 0x26, 0x80000034) and cmd in self.commands:
                raise ValueError("duplicate singleton load command")
            self.commands[cmd] = payload
            if cmd == 0x19:
                checked(payload, 0, 72)
                segname = payload[8:24].rstrip(b"\0").decode("ascii")
                address, vm_size, file_offset, file_size = struct.unpack_from("<4Q", payload, 24)
                sections = struct.unpack_from("<I", payload, 64)[0]
                if sections > 1024 or 72 + 80 * sections != size:
                    raise ValueError("invalid segment section count")
                checked(data, file_offset, file_size)
                self.segments.append({"name": segname, "address": address,
                    "vm_size": vm_size, "file_offset": file_offset, "file_size": file_size})
                for section_index in range(sections):
                    position = 72 + 80 * section_index
                    name = payload[position:position + 16].rstrip(b"\0").decode("ascii")
                    section_segment = payload[position + 16:position + 32].rstrip(b"\0").decode("ascii")
                    section_address, length, section_offset = struct.unpack_from("<QQI", payload, position + 32)
                    section_flags, indirect_index, stride = struct.unpack_from("<III", payload, position + 64)
                    zero_fill = section_flags & 255 in (1, 0xc, 0x12)
                    if section_segment != segname or section_address < address or section_address + length > address + vm_size:
                        raise ValueError("section outside segment VM range")
                    if not zero_fill:
                        checked(data, section_offset, length)
                        if section_offset < file_offset or section_offset + length > file_offset + file_size:
                            raise ValueError("section outside segment file range")
                    self.sections.append({"name": name, "segment": segname, "address": section_address,
                        "size": length, "file_offset": section_offset, "flags": section_flags,
                        "indirect_index": indirect_index, "stride": stride, "zero_fill": zero_fill})
            elif cmd == 0x1b:
                self.uuid = str(uuid.UUID(bytes=checked(payload, 8, 16))).upper()
            elif cmd == 0x32:
                platform, minimum, sdk, tools = struct.unpack("<4I", checked(payload, 8, 16))
                if 24 + tools * 8 != size:
                    raise ValueError("invalid build-version tool count")
                self.build = {"platform": platform, "minimum_os": version_word(minimum), "sdk": version_word(sdk)}
            elif cmd in (0xc, 0x80000018, 0x8000001f, 0x20):
                checked(payload, 0, 24)
                name_offset = struct.unpack_from("<I", payload, 8)[0]
                self.dylibs.append({"name": cstring(payload, name_offset, size), "weak": cmd == 0x80000018})
            offset += size
        if offset != command_end:
            raise ValueError("load-command count/size mismatch")
        text = [segment for segment in self.segments if segment["name"] == "__TEXT"]
        if len(text) != 1:
            raise ValueError("missing or duplicate __TEXT")
        self.base = text[0]["address"]
        self.rebases = {}
        self.fixups = {"formats": [], "rebase_slots": 0, "bind_slots": 0}
        self.parse_fixups()
        self.imports = self.parse_imports()
        self.functions = self.parse_functions()

    def file_offset(self, address, size=1):
        for segment in self.segments:
            delta = address - segment["address"]
            if 0 <= delta and delta + size <= segment["file_size"]:
                return segment["file_offset"] + delta
        raise ValueError(f"VM address not file-backed: {address:#x}")

    def location(self, address):
        return {"address": hex(address), "file_offset": hex(self.file_offset(address))}

    def parse_fixups(self):
        command = self.commands.get(0x80000034)
        if not command:
            return
        offset, size = struct.unpack("<II", checked(command, 8, 8))
        payload = checked(self.data, offset, size)
        revision, starts, imports, symbols, import_count, import_format, symbol_format = struct.unpack("<7I", checked(payload, 0, 28))
        if revision or starts < 28:
            raise ValueError("unsupported chained-fixups header")
        count = struct.unpack("<I", checked(payload, starts, 4))[0]
        if count != len(self.segments):
            raise ValueError("chained-fixups segment count mismatch")
        segment_offsets = struct.unpack(f"<{count}I", checked(payload, starts + 4, count * 4))
        for segment_index, relative in enumerate(segment_offsets):
            if not relative:
                continue
            position = starts + relative
            segment_size, page_size, pointer_format, segment_offset, maximum, pages = struct.unpack("<IHHQIH", checked(payload, position, 22))
            content = checked(payload, position, segment_size)
            if page_size not in (0x1000, 0x4000) or pointer_format != 6 or segment_size < 22 + pages * 2:
                raise ValueError("only bounded DYLD_CHAINED_PTR_64_OFFSET starts are supported")
            if pointer_format not in self.fixups["formats"]:
                self.fixups["formats"].append(pointer_format)
            page_table = struct.unpack(f"<{(segment_size - 22) // 2}H", content[22:segment_size - ((segment_size - 22) % 2)])
            segment = self.segments[segment_index]
            if self.base + segment_offset != segment["address"]:
                raise ValueError("chained-fixups segment offset mismatch")
            for page_index in range(pages):
                start = page_table[page_index]
                if start == 0xffff:
                    continue
                starts_in_page = [start]
                if start & 0x8000:
                    table_index = start & 0x7fff
                    starts_in_page = []
                    while True:
                        if table_index >= len(page_table):
                            raise ValueError("invalid multi-start overflow index")
                        entry = page_table[table_index]
                        starts_in_page.append(entry & 0x7fff)
                        table_index += 1
                        if entry & 0x8000:
                            break
                page_address = segment["address"] + page_index * page_size
                for first in starts_in_page:
                    address = page_address + first
                    for step in range(page_size // 4):
                        if address < page_address or address + 8 > page_address + page_size:
                            raise ValueError("chained pointer leaves page")
                        file_offset = self.file_offset(address, 8)
                        raw = struct.unpack_from("<Q", self.data, file_offset)[0]
                        target, stride = pointer64_offset(raw, self.base)
                        if target is None:
                            self.fixups["bind_slots"] += 1
                        else:
                            if address in self.rebases:
                                raise ValueError("duplicate chained rebase slot")
                            self.rebases[address] = target
                        if not stride:
                            break
                        address += stride
                    else:
                        raise ValueError("chained-pointer step budget exhausted")
        self.fixups["rebase_slots"] = len(self.rebases)

    def pointer(self, address):
        if 0x80000034 in self.commands:
            return self.rebases.get(address)
        return struct.unpack_from("<Q", self.data, self.file_offset(address, 8))[0]

    def parse_imports(self):
        if 2 not in self.commands or 0xb not in self.commands:
            return {}
        symbol_offset, count, string_offset, string_size = struct.unpack("<4I", checked(self.commands[2], 8, 16))
        checked(self.data, symbol_offset, count * 16)
        checked(self.data, string_offset, string_size)
        indirect_offset, indirect_count = struct.unpack("<2I", checked(self.commands[0xb], 56, 8))
        checked(self.data, indirect_offset, indirect_count * 4)
        symbols = []
        for index in range(count):
            name = struct.unpack_from("<I", self.data, symbol_offset + index * 16)[0]
            symbols.append(cstring(self.data, string_offset + name, string_offset + string_size))
        imports = {}
        for section in self.sections:
            if section["flags"] & 255 != 8:
                continue
            stride = section["stride"]
            if not stride or section["size"] % stride:
                raise ValueError("invalid symbol-stub stride")
            slots = section["size"] // stride
            if section["indirect_index"] + slots > indirect_count:
                raise ValueError("stub indirect-symbol range exceeds table")
            for index in range(slots):
                symbol = struct.unpack_from("<I", self.data, indirect_offset + 4 * (section["indirect_index"] + index))[0]
                if symbol & 0xc0000000:
                    continue
                if symbol >= len(symbols):
                    raise ValueError("invalid indirect-symbol index")
                imports[section["address"] + index * stride] = symbols[symbol]
        return imports

    def parse_functions(self):
        command = self.commands.get(0x26)
        if not command:
            return []
        offset, size = struct.unpack("<2I", checked(command, 8, 8))
        address = self.base
        functions = []
        for delta in uleb_values(checked(self.data, offset, size)):
            if not delta:
                break
            address += delta
            self.file_offset(address, 4)
            functions.append(address)
        return functions

    def function_start(self, address):
        index = bisect.bisect_right(self.functions, address) - 1
        return hex(self.functions[index]) if index >= 0 else None


def selected_strings(image, pattern):
    records = {}
    for section in image.sections:
        if section["name"] not in STRING_SECTIONS or section["zero_fill"]:
            continue
        payload = checked(image.data, section["file_offset"], section["size"])
        for match in re.finditer(rb"[\x20-\x7e]{3,}\x00", payload):
            text = match.group()[:-1].decode("ascii")
            if pattern.search(text):
                address = section["address"] + match.start()
                records[address] = {**image.location(address), "section": section["name"], "text": text}
    return records


def reference_slots(image, strings):
    selectors = []
    targets = dict(strings)
    unresolved = 0
    for section in image.sections:
        if section["name"] not in ("__objc_selrefs", "__cfstring"):
            continue
        stride = 8 if section["name"] == "__objc_selrefs" else 32
        if section["size"] % stride:
            raise ValueError("invalid selector/CFString section stride")
        for delta in range(0, section["size"], stride):
            address = section["address"] + delta
            pointer_address = address if stride == 8 else address + 16
            target = image.pointer(pointer_address)
            if target is None:
                unresolved += 1
                continue
            if target in strings:
                record = {**image.location(address), "text": strings[target]["text"],
                    "kind": "selector_slot" if stride == 8 else "cfstring_object", "string_address": hex(target)}
                targets[address] = record
                if stride == 8:
                    selectors.append(record)
    return selectors, targets, unresolved


def ioctl_fields(request):
    return {"request": hex(request & 0xffffffff), "direction_bits": hex(request & 0xe0000000),
        "encoded_size": (request >> 16) & 0x1fff, "group": chr((request >> 8) & 255), "number": request & 255}


def register_key(name):
    if name in ("xzr", "wzr"):
        return "zero"
    if re.fullmatch(r"[xw]\d+", name):
        return "x" + name[1:]
    return name


def constant_arguments(instructions, decoder):
    from capstone.arm64_const import ARM64_OP_IMM, ARM64_OP_REG
    values = {"zero": 0}
    definitions = {}
    for instruction in instructions:
        operands = instruction.operands
        if instruction.mnemonic in ("bl", "blr"):
            for index in range(19):
                values.pop(f"x{index}", None)
                definitions.pop(f"x{index}", None)
            continue
        if instruction.mnemonic in ("b", "br", "ret", "cbz", "cbnz", "tbz", "tbnz") or instruction.mnemonic.startswith("b."):
            values = {"zero": 0}
            definitions = {}
            continue
        known = None
        destination = None
        if operands and operands[0].type == ARM64_OP_REG:
            name = instruction.reg_name(operands[0].reg)
            destination = register_key(name)
            width = 32 if name.startswith("w") else 64
            if len(operands) >= 2:
                source = operands[1]
                source_value = source.imm if source.type == ARM64_OP_IMM else values.get(register_key(instruction.reg_name(source.reg))) if source.type == ARM64_OP_REG else None
                if instruction.mnemonic in ("mov", "movz", "adr", "adrp") and source_value is not None:
                    known = source_value << source.shift.value
                elif instruction.mnemonic == "movn" and source.type == ARM64_OP_IMM:
                    known = ~(source.imm << source.shift.value)
                elif instruction.mnemonic == "movk" and destination in values and source.type == ARM64_OP_IMM:
                    shift = source.shift.value
                    known = (values[destination] & ~(0xffff << shift)) | (source.imm << shift)
                elif instruction.mnemonic in ("add", "sub") and source_value is not None and len(operands) == 3 and operands[2].type == ARM64_OP_IMM:
                    delta = operands[2].imm << operands[2].shift.value
                    known = source_value + (delta if instruction.mnemonic == "add" else -delta)
            if known is not None:
                known &= (1 << width) - 1
        reads, writes = instruction.regs_access()
        for written in writes:
            key = register_key(instruction.reg_name(written))
            if key != "zero":
                values.pop(key, None)
                definitions.pop(key, None)
        if known is not None and destination != "zero":
            values[destination] = known
            definitions[destination] = hex(instruction.address)
    return {key: {"value": hex(values[key]), "last_definition": definitions[key]}
        for key in ("x0", "x1", "x2", "x3", "x4", "x5") if key in definitions}


def inspect_code(image, targets, call_pattern, limit, window):
    import capstone
    decoder = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_LITTLE_ENDIAN)
    decoder.detail = True
    calls = []
    xrefs = []
    total_calls = total_xrefs = 0
    for section in image.sections:
        if section["name"] != "__text":
            continue
        if section["size"] % 4:
            raise ValueError("unaligned ARM64 text size")
        payload = checked(image.data, section["file_offset"], section["size"])
        pages = {}
        for index, (word,) in enumerate(struct.iter_unpack("<I", payload)):
            address = section["address"] + index * 4
            destination = word & 31
            target = None
            kind = None
            if word & 0x9f000000 == 0x90000000:
                immediate = ((word >> 5) & 0x7ffff) << 2 | ((word >> 29) & 3)
                if immediate & (1 << 20):
                    immediate -= 1 << 21
                pages[destination] = (address & ~0xfff) + (immediate << 12)
                continue
            if word & 0xffc00000 == 0x91000000 and ((word >> 5) & 31) in pages:
                target = pages[(word >> 5) & 31] + ((word >> 10) & 0xfff)
                kind = "adjacent_adrp_add_address"
            elif word & 0xffc00000 == 0xf9400000 and ((word >> 5) & 31) in pages:
                target = pages[(word >> 5) & 31] + (((word >> 10) & 0xfff) << 3)
                kind = "adjacent_adrp_ldr_slot"
            if target in targets:
                total_xrefs += 1
                if len(xrefs) < limit:
                    xrefs.append({**image.location(address), "function_start": image.function_start(address),
                        "target": hex(target), "kind": kind, "text": targets[target]["text"]})
            pages = {}
            if word & 0xfc000000 not in (0x94000000, 0x14000000):
                continue
            immediate = word & 0x3ffffff
            if immediate & (1 << 25):
                immediate -= 1 << 26
            callee = address + immediate * 4
            symbol = image.imports.get(callee)
            if not symbol or not call_pattern.search(symbol):
                continue
            total_calls += 1
            if len(calls) >= limit:
                continue
            begin = max(index - window, 0)
            function = image.function_start(address)
            if function is not None:
                begin = max(begin, (int(function, 16) - section["address"]) // 4)
            end = min(index + 4, section["size"] // 4)
            decoded = list(decoder.disasm(payload[begin * 4:end * 4], section["address"] + begin * 4))
            arguments = constant_arguments([instruction for instruction in decoded if instruction.address < address], decoder)
            record = {**image.location(address), "function_start": function,
                "kind": "direct_bl" if word & 0xfc000000 == 0x94000000 else "direct_tail_b",
                "symbol": symbol, "stub": hex(callee), "constant_registers": arguments,
                "window": [{**image.location(instruction.address), "assembly": instruction.mnemonic + " " + instruction.op_str}
                    for instruction in decoded]}
            if symbol == "_ioctl" and "x1" in arguments:
                record["ioctl_encoding"] = ioctl_fields(int(arguments["x1"]["value"], 16))
            if symbol in ("_getsockopt", "_setsockopt") and "x2" in arguments:
                option = int(arguments["x2"]["value"], 16)
                if option & 0xe0000000:
                    record["socket_option_encoding"] = ioctl_fields(option)
            calls.append(record)
    return {"decoder": f"capstone {capstone.__version__}", "calls": calls, "call_count": total_calls,
        "calls_truncated": total_calls > len(calls), "address_references": xrefs,
        "reference_count": total_xrefs, "references_truncated": total_xrefs > len(xrefs),
        "reference_scope": "adjacent ADRP+ADD/LDR only; no indirect calls, reachability or complete dataflow proof"}


def parse_function(value):
    match = re.fullmatch(r"(BlueTool|bluetoothd):(0x[0-9a-fA-F]+|[0-9]+)", value)
    if not match:
        raise ValueError("--function requires BlueTool:VM or bluetoothd:VM (unslid)")
    address = int(match[2], 16 if match[2].startswith("0x") else 10)
    if address >= 1 << 64 or address % 4:
        raise ValueError("--function VM must be aligned ARM64 uint64")
    return "/usr/sbin/" + match[1], address


def inspect_function_windows(image, addresses, limit, instruction_limit):
    import capstone
    if not 1 <= instruction_limit <= 4096 or not 1 <= limit <= 10000 or len(addresses) > 8:
        raise ValueError("invalid function-window budget")
    decoder = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_LITTLE_ENDIAN)
    windows = {}
    for address in addresses:
        sections = [section for section in image.sections if section["name"] == "__text"
            and section["address"] <= address < section["address"] + section["size"]]
        index = bisect.bisect_right(image.functions, address) - 1
        if len(sections) != 1 or address % 4 or index < 0:
            raise ValueError("requested function VM lacks __text/function-start evidence")
        section = sections[0]
        start = image.functions[index]
        end = min(image.functions[index + 1] if index + 1 < len(image.functions)
            else section["address"] + section["size"], section["address"] + section["size"])
        if start < section["address"] or end <= address or (end - start) % 4:
            raise ValueError("invalid function extent")
        if start in windows:
            windows[start]["requested_addresses"].append(hex(address))
            continue
        total = (end - start) // 4
        length = min(total, instruction_limit) * 4
        decoded = list(decoder.disasm(checked(image.data, image.file_offset(start, length), length), start))
        if len(decoded) * 4 != length:
            raise ValueError("undecodable ARM64 instruction in requested window")
        instructions = []
        for instruction in decoded:
            record = {**image.location(instruction.address), "assembly": instruction.mnemonic + " " + instruction.op_str}
            if instruction.mnemonic in ("bl", "b"):
                target = int(instruction.op_str.removeprefix("#"), 16)
                record["direct_target"] = {"address": hex(target), "import": image.imports.get(target),
                    "function_start": image.function_start(target) if any(candidate["name"] == "__text"
                        and candidate["address"] <= target < candidate["address"] + candidate["size"]
                        for candidate in image.sections) else None}
            instructions.append(record)
        windows[start] = {"requested_addresses": [hex(address)], **image.location(start),
            "end_address_exclusive": hex(end), "extent_source": "LC_FUNCTION_STARTS bounded by __text; not reachability proof",
            "instruction_count": total, "instructions_truncated": total > len(instructions),
            "instructions": instructions, "incoming_references": [], "incoming_reference_count": 0}

    def add_reference(target, address, kind):
        if target not in windows:
            return
        record = windows[target]
        record["incoming_reference_count"] += 1
        if len(record["incoming_references"]) < limit:
            record["incoming_references"].append({**image.location(address), "kind": kind})

    for address, target in image.rebases.items():
        add_reference(target, address, "chained_rebase_function_pointer")
    for section in image.sections:
        if section["name"] != "__text":
            continue
        if section["size"] % 4:
            raise ValueError("unaligned ARM64 text size")
        payload = checked(image.data, section["file_offset"], section["size"])
        pages = {}
        for index, (word,) in enumerate(struct.iter_unpack("<I", payload)):
            address = section["address"] + index * 4
            if word & 0x9f000000 in (0x10000000, 0x90000000):
                immediate = ((word >> 5) & 0x7ffff) << 2 | ((word >> 29) & 3)
                if immediate & (1 << 20):
                    immediate -= 1 << 21
                if word & 0x80000000:
                    pages = {word & 31: (address & ~0xfff) + (immediate << 12)}
                else:
                    add_reference(address + immediate, address, "direct_adr_function_address")
                    pages = {}
                continue
            if word & 0xffc00000 == 0x91000000 and ((word >> 5) & 31) in pages:
                add_reference(pages[(word >> 5) & 31] + ((word >> 10) & 0xfff), address,
                    "adjacent_adrp_add_function_address")
            pages = {}
            if word & 0xfc000000 not in (0x94000000, 0x14000000):
                continue
            immediate = word & 0x3ffffff
            if immediate & (1 << 25):
                immediate -= 1 << 26
            add_reference(address + immediate * 4, address,
                "direct_bl_target" if word & 0xfc000000 == 0x94000000 else "direct_b_target")
    for record in windows.values():
        record["incoming_references_truncated"] = record["incoming_reference_count"] > len(record["incoming_references"])
        record["incoming_reference_scope"] = "direct B/BL, ADR, adjacent ADRP+ADD and chained rebase only; no runtime selection or indirect dispatch proof"
    return list(windows.values())


def build_report(manifest_path, pattern, calls, limit, window, no_code=False, objdump=None,
        functions=(), function_limit=256):
    if functions and (no_code or len(functions) > 8):
        raise ValueError("function windows require code analysis and at most eight requests")
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    version = manifest["version"]
    if version.get("ProductBuildVersion") != "20H392" or version.get("ProductVersion") != "16.7.16":
        raise ValueError("manifest is not the requested actual iOS16.7.16 / 20H392 root")
    report = {"schema": "fuxi-bluetooth-abi-v1", "manifest": str(manifest_path.resolve()),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(), "root_version": version,
        "provenance": {key: manifest.get("provenance", {}).get(key) for key in ("method", "captured_at")},
        "static_only": True, "limits": {"records_per_category": limit, "preceding_instructions": window,
            "instructions_per_function": function_limit}, "binaries": []}
    if objdump:
        result = subprocess.run([str(objdump), "--version"], capture_output=True, text=True, check=True, timeout=30)
        report["llvm_version"] = result.stdout.splitlines()[:3]
    for runtime in ("/usr/sbin/BlueTool", "/usr/sbin/bluetoothd"):
        asset = manifest["files"][runtime]
        path = Path(asset["host_path"])
        length = path.stat().st_size
        if length != asset["bytes"] or not 0 < length <= MAX_BYTES:
            raise ValueError(f"size mismatch/budget: {runtime}")
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != asset["sha256"] or len(data) != length:
            raise ValueError(f"hash/read-size mismatch: {runtime}")
        image = MachO(data)
        strings = selected_strings(image, pattern)
        selectors, targets, unresolved = reference_slots(image, strings)
        record = {"runtime_path": runtime, "host_path": str(path.resolve()), "bytes": length,
            "sha256": digest, "verified_against_manifest": True, "header": image.header,
            "uuid": image.uuid, "build_version": image.build, "chained_fixups": image.fixups,
            "dylibs": image.dylibs,
            "sections": [{key: hex(value) if key in ("address", "file_offset", "size") else value
                for key, value in section.items()} for section in image.sections],
            "selected_strings": list(strings.values())[:limit], "selected_string_count": len(strings),
            "strings_truncated": len(strings) > limit, "selector_offsets": selectors[:limit],
            "selector_count": len(selectors), "selectors_truncated": len(selectors) > limit,
            "unresolved_selector_cfstring_slots": unresolved,
            "imports": [{"stub": hex(address), "name": name} for address, name in image.imports.items() if calls.search(name)]}
        if not no_code:
            record["code"] = inspect_code(image, targets, calls, limit, window)
            addresses = [address for requested_runtime, address in functions if requested_runtime == runtime]
            if addresses:
                record["function_windows"] = inspect_function_windows(image, addresses, limit, function_limit)
        if objdump:
            result = subprocess.run([str(objdump), "--macho", "--private-header", str(path)],
                capture_output=True, text=True, check=True, timeout=30)
            record["llvm_header"] = result.stdout.splitlines()
        report["binaries"].append(record)
    return report


def self_test():
    fixture = bytearray(0x300)
    struct.pack_into("<8I", fixture, 0, 0xfeedfacf, 0x100000c, 0, 2, 1, 232, 0, 0)
    struct.pack_into("<II16sQQQQIIII", fixture, 32, 0x19, 232, b"__TEXT", 0x100000000, 0x300, 0, 0x300, 5, 5, 2, 0)
    for index, (name, offset, size) in enumerate(((b"__text", 0x180, 4), (b"__cstring", 0x200, 32))):
        struct.pack_into("<16s16sQQ8I", fixture, 104 + index * 80, name, b"__TEXT",
            0x100000000 + offset, size, offset, 2, 0, 0, 0, 0, 0, 0)
    fixture[0x180:0x184] = struct.pack("<I", 0xd503201f)
    text = b"com.apple.uart.bluetooth\0"
    fixture[0x200:0x200 + len(text)] = text
    image = MachO(bytes(fixture))
    strings = selected_strings(image, re.compile("uart"))
    assert strings[0x100000200]["file_offset"] == "0x200"
    assert pointer64_offset((2 << 51) | 0x1234, 0x100000000) == (0x100001234, 8)
    assert pointer64_offset((0xab << 36) | 0x1234, 0x100000000) == (0xab00000100001234, 0)
    assert pointer64_offset(1 << 63, 0x100000000) == (None, 0)
    assert list(uleb_values(b"\x81\x01\x00")) == [129, 0]
    failures = 0
    for operation in (lambda: MachO(b""), lambda: checked(b"a", 1, 1),
            lambda: cstring(b"abc", 0, 3), lambda: list(uleb_values(b"\x80")),
            lambda: list(uleb_values(b"\x80" * 10 + b"\x01")),
            lambda: pointer64_offset(1 << 44, 0x100000000),
            lambda: MachO(bytes(fixture[:36]) + struct.pack("<I", 0) + bytes(fixture[40:]))):
        try:
            operation()
        except ValueError:
            failures += 1
        else:
            raise AssertionError("malformed fixture accepted")
    assert failures == 7
    import capstone
    decoder = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_LITTLE_ENDIAN)
    decoder.detail = True
    code = struct.pack("<2I", 0x52800001 | (0x4e03 << 5), 0x72a00001 | (0xc064 << 5))
    arguments = constant_arguments(list(decoder.disasm(code, 0x100000100)), decoder)
    assert arguments["x1"]["value"] == "0xc0644e03"
    assert ioctl_fields(0xc0644e03) == {"request": "0xc0644e03", "direction_bits": "0xc0000000", "encoded_size": 100, "group": "N", "number": 3}
    assert constant_arguments(list(decoder.disasm(code + struct.pack("<I", 0x94000000), 0x100000100)), decoder) == {}
    struct.pack_into("<Q", fixture, 104 + 40, 16)
    struct.pack_into("<4I", fixture, 0x180, 0x94000004, 0x10000041, 0xd503201f, 0xd65f03c0)
    image = MachO(bytes(fixture))
    image.functions = [0x100000180, 0x10000018c]
    image.imports = {0x100000190: "_fixture_import"}
    image.rebases = {0x100000200: 0x100000180, 0x100000208: 0x100000180}
    windows = inspect_function_windows(image, [0x100000184, 0x10000018c], 1, 2)
    assert windows[0]["address"] == "0x100000180" and windows[0]["end_address_exclusive"] == "0x10000018c"
    assert windows[0]["instructions_truncated"] and windows[0]["instruction_count"] == 3
    assert windows[0]["instructions"][0]["direct_target"]["import"] == "_fixture_import"
    assert windows[0]["incoming_references"][0]["kind"] == "chained_rebase_function_pointer"
    assert windows[0]["incoming_reference_count"] == 2 and windows[0]["incoming_references_truncated"]
    assert windows[1]["incoming_references"][0]["kind"] == "direct_adr_function_address"
    assert windows[1]["instruction_count"] == 1 and not windows[1]["instructions_truncated"]
    assert parse_function("bluetoothd:0x100067610") == ("/usr/sbin/bluetoothd", 0x100067610)
    for operation in (lambda: parse_function("Other:0x100000180"), lambda: parse_function("BlueTool:0x181"),
            lambda: parse_function("BlueTool:0x10000000000000000"),
            lambda: inspect_function_windows(image, [0x100000200], 1, 2),
            lambda: inspect_function_windows(image, [0x100000181], 1, 2),
            lambda: inspect_function_windows(image, [0x100000180] * 9, 1, 2),
            lambda: inspect_function_windows(image, [0x100000180], 1, 0)):
        try:
            operation()
        except ValueError:
            pass
        else:
            raise AssertionError("invalid function request accepted")
    print("PASS Mach-O/string/chained-pointer/ULEB bounds, ARM64 constants/ioctl, bounded function windows/imports/rebase/ADR references and malformed requests")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--pattern", default=DEFAULT_PATTERN)
    parser.add_argument("--calls", default=DEFAULT_CALLS)
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--window", type=int, default=16)
    parser.add_argument("--format", choices=("json", "strings", "selectors"), default="json")
    parser.add_argument("--no-code", action="store_true")
    parser.add_argument("--objdump", type=Path)
    parser.add_argument("--function", action="append", default=[], metavar="BINARY:VM")
    parser.add_argument("--function-limit", type=int, default=256)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= 10000 or not 2 <= args.window <= 64:
        parser.error("--limit must be 1..10000 and --window 2..64")
    try:
        if args.self_test:
            self_test()
            return
        functions = [parse_function(value) for value in args.function]
        if functions and args.format != "json":
            raise ValueError("--function requires --format json")
        if not 1 <= args.function_limit <= 4096:
            raise ValueError("--function-limit must be 1..4096")
        report = build_report(args.manifest, re.compile(args.pattern), re.compile(args.calls),
            args.limit, args.window, args.no_code, args.objdump, functions, args.function_limit)
        if args.format == "json":
            print(json.dumps(report, ensure_ascii=True, indent=2))
        else:
            for binary in report["binaries"]:
                records = binary["selected_strings"] if args.format == "strings" else binary["selector_offsets"]
                count = binary['selected_string_count'] if args.format == 'strings' else binary['selector_count']
                print(f"# {binary['runtime_path']} SHA256={binary['sha256']} count={count} shown={len(records)} truncated={count > len(records)} static_only=True")
                for record in records:
                    print(f"{record['file_offset']}\t{record['address']}\t{record['text']}")
    except (ValueError, KeyError, OSError, ImportError, re.error, struct.error, subprocess.SubprocessError) as error:
        parser.exit(1, f"inspection refused: {error}\n")


if __name__ == "__main__":
    main()
