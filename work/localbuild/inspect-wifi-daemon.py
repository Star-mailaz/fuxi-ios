import argparse
import bisect
import hashlib
import re
import struct
from pathlib import Path

import capstone


class Image:
    def __init__(self, path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        if self.data[:4] != bytes.fromhex("cffaedfe"):
            raise ValueError("Expected a little-endian 64-bit Mach-O")
        self.sections = {}
        self.segments = []
        self.symbols = []
        self.stubs = {}
        function_info = None
        symbol_info = None
        indirect_info = None
        pointer_formats = set()
        offset = 32
        for _ in range(struct.unpack_from("<I", self.data, 16)[0]):
            kind, size = struct.unpack_from("<II", self.data, offset)
            if kind == 0x19:
                name = self.data[offset + 8:offset + 24].rstrip(b"\0").decode()
                address, length, file_offset, file_length = struct.unpack_from(
                    "<QQQQ", self.data, offset + 24)
                self.segments.append((name, address, length, file_offset, file_length))
                for index in range(struct.unpack_from("<I", self.data, offset + 64)[0]):
                    section_offset = offset + 72 + 80 * index
                    section_name = self.data[section_offset:section_offset + 16].rstrip(b"\0").decode()
                    section_address, section_length = struct.unpack_from(
                        "<QQ", self.data, section_offset + 32)
                    section_file = struct.unpack_from("<I", self.data, section_offset + 48)[0]
                    reserved = struct.unpack_from("<II", self.data, section_offset + 68)
                    self.sections[(name, section_name)] = (
                        section_address, section_length, section_file, reserved)
            elif kind == 2:
                symbol_info = struct.unpack_from("<IIII", self.data, offset + 8)
            elif kind == 0xB:
                indirect_info = struct.unpack_from("<II", self.data, offset + 56)
            elif kind == 0x26:
                function_info = struct.unpack_from("<II", self.data, offset + 8)
            elif kind == 0x80000034:
                payload, _ = struct.unpack_from("<II", self.data, offset + 8)
                starts = payload + struct.unpack_from("<I", self.data, payload + 4)[0]
                for index in range(struct.unpack_from("<I", self.data, starts)[0]):
                    relative = struct.unpack_from("<I", self.data, starts + 4 + 4 * index)[0]
                    if relative:
                        pointer_formats.add(struct.unpack_from("<H", self.data, starts + relative + 6)[0])
            offset += size
        if symbol_info:
            symbol_offset, symbol_count, string_offset, _ = symbol_info
            for index in range(symbol_count):
                name_offset, _, _, _, address = struct.unpack_from(
                    "<IBBHQ", self.data, symbol_offset + 16 * index)
                start = string_offset + name_offset
                end = self.data.find(b"\0", start)
                self.symbols.append((address, self.data[start:end].decode("utf-8", "replace")))
        if indirect_info and ("__TEXT", "__stubs") in self.sections:
            address, length, _, (first_index, stub_size) = self.sections[("__TEXT", "__stubs")]
            indirect_offset, indirect_count = indirect_info
            for index in range(length // stub_size):
                if first_index + index >= indirect_count:
                    break
                symbol_index = struct.unpack_from(
                    "<I", self.data, indirect_offset + 4 * (first_index + index))[0]
                if symbol_index < len(self.symbols):
                    self.stubs[address + stub_size * index] = self.symbols[symbol_index][1]
        self.text_address, self.text_length, self.text_offset, _ = self.sections[("__TEXT", "__text")]
        self.starts = []
        if function_info:
            cursor, length = function_info
            limit = cursor + length
            address = next(segment[1] for segment in self.segments if segment[0] == "__TEXT")
            while cursor < limit:
                delta = 0
                shift = 0
                while cursor < limit:
                    value = self.data[cursor]
                    cursor += 1
                    delta |= (value & 0x7F) << shift
                    shift += 7
                    if value < 0x80:
                        break
                if not delta:
                    break
                address += delta
                if self.text_address <= address < self.text_address + self.text_length:
                    self.starts.append(address)
        self.starts.append(self.text_address + self.text_length)
        self.decoder = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
        self.literals = {}
        if pointer_formats == {6}:
            base = next(segment[1] for segment in self.segments if segment[0] == "__TEXT")
            for (_, name), (address, length, file_offset, _) in self.sections.items():
                if name != "__cfstring":
                    continue
                for offset in range(0, length, 32):
                    pointer = struct.unpack_from("<Q", self.data, file_offset + offset + 16)[0]
                    if not pointer & (1 << 63):
                        self.literals[address + offset] = self.string(base + (pointer & 0xFFFFFFFFF))
            for (_, name), (address, length, file_offset, _) in self.sections.items():
                if name not in ("__got", "__objc_selrefs"):
                    continue
                for offset in range(0, length, 8):
                    pointer = struct.unpack_from("<Q", self.data, file_offset + offset)[0]
                    if not pointer & (1 << 63):
                        target = base + (pointer & 0xFFFFFFFFF)
                        self.literals[address + offset] = self.literals.get(target) or self.string(target)
        if ("__TEXT", "__objc_stubs") in self.sections:
            address, length, file_offset, _ = self.sections[("__TEXT", "__objc_stubs")]
            for offset in range(0, length - 19, 32):
                page, load = struct.unpack_from("<II", self.data, file_offset + offset)
                branch = struct.unpack_from("<I", self.data, file_offset + offset + 16)[0]
                if (page & 0x9F00001F != 0x90000001 or load & 0xFFC003FF != 0xF9400021
                        or branch != 0xD61F0200):
                    continue
                immediate = ((page >> 29) & 3) | (((page >> 5) & 0x7FFFF) << 2)
                if immediate & (1 << 20):
                    immediate -= 1 << 21
                reference = ((address + offset) & ~0xFFF) + (immediate << 12) + 8 * ((load >> 10) & 0xFFF)
                selector = self.literals.get(reference)
                if selector:
                    self.stubs[address + offset] = "_objc_msgSend [" + selector + "]"

    def read(self, address, length):
        for _, segment_address, _, file_offset, file_length in self.segments:
            relative = address - segment_address
            if 0 <= relative and relative + length <= file_length:
                return self.data[file_offset + relative:file_offset + relative + length]
        return b""

    def string(self, address):
        content = self.read(address, 1)
        if not content:
            return ""
        result = bytearray()
        while len(result) < 300:
            content = self.read(address + len(result), 1)
            if not content or content == b"\0":
                break
            result.extend(content)
        return result.decode("utf-8", "replace")

    def extent(self, address):
        index = bisect.bisect_right(self.starts, address) - 1
        if index < 0 or index + 1 >= len(self.starts):
            raise ValueError("Address is outside known function extents")
        return self.starts[index], self.starts[index + 1]

    def matches(self, pattern):
        expression = re.compile(pattern)
        for (_, name), (address, length, file_offset, _) in self.sections.items():
            if name not in ("__cstring", "__objc_methname"):
                continue
            content = self.data[file_offset:file_offset + length]
            for match in re.finditer(rb"[^\0]+", content):
                text = match.group().decode("utf-8", "replace")
                if expression.search(text):
                    yield address + match.start(), text

    def references(self, targets):
        content = self.read(self.text_address, self.text_length)
        for offset in range(0, len(content) - 4, 4):
            instruction = struct.unpack_from("<I", content, offset)[0]
            kind = instruction & 0x9F000000
            if kind not in (0x90000000, 0x10000000):
                continue
            register = instruction & 31
            immediate = ((instruction >> 29) & 3) | (((instruction >> 5) & 0x7FFFF) << 2)
            if immediate & (1 << 20):
                immediate -= 1 << 21
            address = self.text_address + offset
            if kind == 0x10000000:
                target = address + immediate
                if target in targets:
                    yield address, target
                continue
            page = (address & ~0xFFF) + (immediate << 12)
            for distance in range(4, min(28, len(content) - offset), 4):
                following = struct.unpack_from("<I", content, offset + distance)[0]
                following_kind = following & 0xFFC00000
                if following_kind in (0x91000000, 0xF9400000) and (following >> 5) & 31 == register:
                    scale = 8 if following_kind == 0xF9400000 else 1
                    target = page + scale * ((following >> 10) & 0xFFF)
                    if target in targets:
                        yield address + distance, target
                    if following & 31 == register:
                        break

    def disassemble(self, address, limit):
        start, end = self.extent(address)
        print("FUNCTION", hex(start), hex(end), "extent from LC_FUNCTION_STARTS")
        for index, instruction in enumerate(self.decoder.disasm(self.read(start, end - start), start)):
            if index >= limit:
                print("TRUNCATED")
                break
            note = ""
            if instruction.mnemonic in ("bl", "b") and instruction.op_str.startswith("#"):
                target = int(instruction.op_str[1:], 16)
                if target in self.stubs:
                    note = " ; " + self.stubs[target]
            print(f"{instruction.address:#x} {instruction.mnemonic:8} {instruction.op_str}{note}")


def main():
    parser = argparse.ArgumentParser(description="Read-only inspection of a local standalone Wi-Fi daemon")
    parser.add_argument("image", type=Path)
    parser.add_argument("mode", choices=("strings", "xref", "function", "symbols"))
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=180)
    arguments = parser.parse_args()
    image = Image(arguments.image)
    print("SHA256", hashlib.sha256(image.data).hexdigest())
    if arguments.mode == "function":
        image.disassemble(int(arguments.query, 0), arguments.limit)
    elif arguments.mode == "symbols":
        for address, name in image.symbols:
            if re.search(arguments.query, name):
                print(hex(address), name)
    else:
        matches = dict(image.matches(arguments.query))
        if arguments.mode == "xref":
            matches.update({address: text for address, text in image.literals.items()
                            if re.search(arguments.query, text)})
        for address, text in matches.items():
            print("STRING", hex(address), text)
        if arguments.mode == "xref":
            for address, target in image.references(matches):
                start, end = image.extent(address)
                print("REFERENCE_CANDIDATE", hex(address), hex(target), "function", hex(start), hex(end))


if __name__ == "__main__":
    main()
