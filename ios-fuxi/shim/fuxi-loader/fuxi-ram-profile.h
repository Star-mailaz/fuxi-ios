#ifndef FUXI_RAM_PROFILE_H
#define FUXI_RAM_PROFILE_H

#include <stddef.h>
#include <stdint.h>

#define FUXI_RAM_FDT_MAX_BYTES UINT32_C(0x1000000)
#define FUXI_RAM_FDT_MAX_DEPTH 64u
#define FUXI_RAM_FDT_MAX_RANGES 128u
#define FUXI_RAM_FDT_MAX_TOKENS 262144u
#define FUXI_RAM_PROFILE_BASE UINT64_C(0x8c0000000)
#define FUXI_RAM_PROFILE_5G UINT64_C(0x140000000)
#define FUXI_RAM_PROFILE_9G UINT64_C(0x240000000)

enum FuxiRamProfileResult {
    FuxiRamProfileStaticOk12G = 0,
    FuxiRamProfileArgument = 1,
    FuxiRamProfileBounds,
    FuxiRamProfileHeader,
    FuxiRamProfileStructure,
    FuxiRamProfileName,
    FuxiRamProfileModel,
    FuxiRamProfileSkuMissing,
    FuxiRamProfileSkuUnsupported,
    FuxiRamProfileConflict,
    FuxiRamProfileCells,
    FuxiRamProfileMemory,
    FuxiRamProfileReserved,
    FuxiRamProfileOverflow,
    FuxiRamProfileWindow,
    FuxiRamProfileLimit
};

typedef struct {
    uint64_t start, end;
} FuxiRamProfileRange;

typedef struct {
    unsigned kind, seen, children;
} FuxiRamProfileNode;

static inline uint32_t fuxi_ram_profile_be32(const uint8_t *bytes)
{
    return (uint32_t)bytes[0] << 24 | (uint32_t)bytes[1] << 16 |
        (uint32_t)bytes[2] << 8 | (uint32_t)bytes[3];
}

static inline uint64_t fuxi_ram_profile_be64(const uint8_t *bytes)
{
    return (uint64_t)fuxi_ram_profile_be32(bytes) << 32 | fuxi_ram_profile_be32(bytes + 4);
}

static inline int fuxi_ram_profile_text(const uint8_t *bytes, size_t size,
    const char *expected)
{
    size_t index = 0;
    while (expected[index]) {
        if (index >= size || bytes[index] != (uint8_t)expected[index]) return 0;
        index++;
    }
    return index + 1 == size && bytes[index] == 0;
}

static inline int fuxi_ram_profile_unit_node(const uint8_t *bytes, size_t length,
    const char *expected)
{
    size_t index = 0;
    while (expected[index]) {
        if (index >= length || bytes[index] != (uint8_t)expected[index]) return 0;
        index++;
    }
    return index < length && bytes[index] == '@';
}

static inline int fuxi_ram_profile_name(const uint8_t *bytes, size_t available,
    size_t *length)
{
    for (size_t index = 0; index < available && index <= 255; index++) {
        if (!bytes[index]) { *length = index; return 1; }
        if (bytes[index] < 0x21 || bytes[index] > 0x7e || bytes[index] == '/') return 0;
    }
    return 0;
}

static inline int fuxi_ram_profile_word(uint8_t character)
{
    return (character >= 'a' && character <= 'z') ||
        (character >= 'A' && character <= 'Z') ||
        (character >= '0' && character <= '9') || character == '_' || character == '-';
}

static inline int fuxi_ram_profile_model(const uint8_t *bytes, size_t size)
{
    static const uint8_t wanted[] = {'f', 'u', 'x', 'i'};
    int found = 0;
    if (size < 5 || size > 256 || bytes[size - 1]) return 0;
    for (size_t index = 0; index + 1 < size; index++) {
        if (bytes[index] < 0x20 || bytes[index] > 0x7e) return 0;
        if (index + 4 > size - 1 || (index && fuxi_ram_profile_word(bytes[index - 1]))) continue;
        unsigned matched = 0;
        for (unsigned letter = 0; letter < 4; letter++) {
            uint8_t character = bytes[index + letter];
            if (character >= 'A' && character <= 'Z') character = (uint8_t)(character + ('a' - 'A'));
            if (character == wanted[letter]) matched++;
        }
        if (matched == 4 && !fuxi_ram_profile_word(bytes[index + 4])) found = 1;
    }
    return found;
}

static inline int fuxi_ram_profile_intersects(uint64_t start, uint64_t end,
    uint64_t other_start, uint64_t other_end)
{
    return start < other_end && other_start < end;
}

static inline enum FuxiRamProfileResult fuxi_ram_profile_reg(const uint8_t *bytes,
    uint32_t size, uint64_t target_start, uint64_t target_end, int reserved,
    FuxiRamProfileRange *ranges, unsigned *count)
{
    if (!size || size % 16) return FuxiRamProfileMemory;
    if (!reserved && size / 16 > FUXI_RAM_FDT_MAX_RANGES) return FuxiRamProfileLimit;
    for (uint32_t offset = 0; offset < size; offset += 16) {
        const uint64_t start = fuxi_ram_profile_be64(bytes + offset);
        const uint64_t length = fuxi_ram_profile_be64(bytes + offset + 8);
        if (!length) {
            if (!reserved || (size == 16 && !start)) continue;
            return FuxiRamProfileMemory;
        }
        if (length > UINT64_MAX - start) return FuxiRamProfileOverflow;
        const uint64_t end = start + length;
        if (reserved) {
            if (fuxi_ram_profile_intersects(start, end, target_start, target_end)) return FuxiRamProfileReserved;
        } else {
            if (*count == FUXI_RAM_FDT_MAX_RANGES) return FuxiRamProfileLimit;
            ranges[*count].start = start;
            ranges[*count].end = end;
            (*count)++;
        }
    }
    return FuxiRamProfileStaticOk12G;
}

static inline enum FuxiRamProfileResult fuxi_ram_profile_check(const void *fdt,
    size_t available, uint64_t phys_base, uint64_t bank_length)
{
    enum { Other = 0, Root = 1, Memory = 2, ReservedRoot = 3, ReservedChild = 4, MemoryEmpty = 5 };
    enum { Model = 1, Sku = 2, Reg = 4, Type = 8, Address = 16,
        Size = 32, Ranges = 64, Status = 128, DynamicSize = 256, EmptyChild = 512 };
    const uint8_t *bytes = (const uint8_t *)fdt;
    const uintptr_t address = (uintptr_t)fdt;
    FuxiRamProfileNode stack[FUXI_RAM_FDT_MAX_DEPTH];
    FuxiRamProfileRange ranges[FUXI_RAM_FDT_MAX_RANGES];
    unsigned depth = 0, root_seen = 0, root_complete = 0, model_seen = 0;
    unsigned sku_seen = 0, memory_seen = 0, reserved_seen = 0, count = 0, tokens = 0;

    if (!fdt || (address & 7u)) return FuxiRamProfileArgument;
    if (available < 40 || available > FUXI_RAM_FDT_MAX_BYTES) return FuxiRamProfileBounds;
    if (available > UINTPTR_MAX - address) return FuxiRamProfileOverflow;
    if (!bank_length || bank_length > UINT64_MAX - phys_base) return FuxiRamProfileOverflow;
    if (phys_base != FUXI_RAM_PROFILE_BASE ||
        (bank_length != FUXI_RAM_PROFILE_5G && bank_length != FUXI_RAM_PROFILE_9G)) return FuxiRamProfileWindow;
    const uint64_t target_end = phys_base + bank_length;
    if (fuxi_ram_profile_be32(bytes) != UINT32_C(0xd00dfeed)) return FuxiRamProfileHeader;
    const uint32_t total = fuxi_ram_profile_be32(bytes + 4);
    const uint32_t structure = fuxi_ram_profile_be32(bytes + 8);
    const uint32_t strings = fuxi_ram_profile_be32(bytes + 12);
    const uint32_t reserve = fuxi_ram_profile_be32(bytes + 16);
    const uint32_t version = fuxi_ram_profile_be32(bytes + 20);
    const uint32_t compatible = fuxi_ram_profile_be32(bytes + 24);
    const uint32_t strings_size = fuxi_ram_profile_be32(bytes + 32);
    const uint32_t structure_size = fuxi_ram_profile_be32(bytes + 36);
    if (total < 40 || total > FUXI_RAM_FDT_MAX_BYTES || total > available) return FuxiRamProfileBounds;
    if (version != 17 || compatible < 16 || compatible > version) return FuxiRamProfileHeader;
    if (structure < 40 || (structure & 3u) || structure_size < 16 || (structure_size & 3u) ||
        structure > total || structure_size > total - structure || strings < 40 ||
        strings > total || !strings_size || strings_size > total - strings ||
        reserve < 40 || (reserve & 7u) || reserve > total || total - reserve < 16) return FuxiRamProfileHeader;
    const uint32_t structure_end = structure + structure_size;
    const uint32_t strings_end = strings + strings_size;
    if (fuxi_ram_profile_intersects(structure, structure_end, strings, strings_end)) return FuxiRamProfileHeader;
    uint32_t reserve_end = reserve;
    int terminated = 0;
    for (unsigned entry = 0; entry < 1024 && total - reserve_end >= 16; entry++) {
        if (fuxi_ram_profile_intersects(reserve_end, (uint64_t)reserve_end + 16, structure, structure_end) ||
            fuxi_ram_profile_intersects(reserve_end, (uint64_t)reserve_end + 16, strings, strings_end)) return FuxiRamProfileHeader;
        const uint64_t start = fuxi_ram_profile_be64(bytes + reserve_end);
        const uint64_t length = fuxi_ram_profile_be64(bytes + reserve_end + 8);
        reserve_end += 16;
        if (!start && !length) { terminated = 1; break; }
        if (!length) return FuxiRamProfileMemory;
        if (length > UINT64_MAX - start) return FuxiRamProfileOverflow;
        if (fuxi_ram_profile_intersects(start, start + length, phys_base, target_end)) return FuxiRamProfileReserved;
    }
    if (!terminated) return FuxiRamProfileHeader;
    uint32_t cursor = structure;
    while (cursor < structure_end) {
        if (++tokens > FUXI_RAM_FDT_MAX_TOKENS) return FuxiRamProfileLimit;
        if (structure_end - cursor < 4) return FuxiRamProfileStructure;
        const uint32_t token = fuxi_ram_profile_be32(bytes + cursor);
        cursor += 4;
        if (token == 1) {
            size_t length = 0;
            if (!fuxi_ram_profile_name(bytes + cursor, structure_end - cursor, &length)) return FuxiRamProfileName;
            const uint32_t padded = ((uint32_t)length + 1u + 3u) & ~UINT32_C(3);
            if (padded > structure_end - cursor) return FuxiRamProfileStructure;
            if (depth == FUXI_RAM_FDT_MAX_DEPTH) return FuxiRamProfileLimit;
            FuxiRamProfileNode node = {Other, 0, 0};
            if (!depth) {
                if (root_seen || length) return FuxiRamProfileStructure;
                root_seen = 1; node.kind = Root;
            } else {
                if (!length) return FuxiRamProfileName;
                FuxiRamProfileNode *parent = &stack[depth - 1];
                parent->children = 1;
                if (parent->kind == Root) {
                    if ((parent->seen & (Address | Size)) != (Address | Size)) return FuxiRamProfileCells;
                    if (fuxi_ram_profile_text(bytes + cursor, length + 1, "memory")) {
                        if (memory_seen++) return FuxiRamProfileConflict;
                        node.kind = Memory;
                    } else if (fuxi_ram_profile_unit_node(bytes + cursor, length, "memory")) {
                        return FuxiRamProfileConflict;
                    } else if (fuxi_ram_profile_text(bytes + cursor, length + 1, "reserved-memory")) {
                        if (reserved_seen++) return FuxiRamProfileConflict;
                        node.kind = ReservedRoot;
                    } else if (fuxi_ram_profile_unit_node(bytes + cursor, length, "reserved-memory")) {
                        return FuxiRamProfileConflict;
                    }
                } else if (parent->kind == ReservedRoot) {
                    if ((parent->seen & (Address | Size | Ranges)) != (Address | Size | Ranges)) return FuxiRamProfileCells;
                    node.kind = ReservedChild;
                } else if (parent->kind == Memory) {
                    if (!fuxi_ram_profile_text(bytes + cursor, length + 1, "ebuff")) return FuxiRamProfileStructure;
                    if (parent->seen & EmptyChild) return FuxiRamProfileConflict;
                    parent->seen |= EmptyChild;
                    node.kind = MemoryEmpty;
                } else if (parent->kind == ReservedChild || parent->kind == MemoryEmpty) {
                    return FuxiRamProfileStructure;
                }
            }
            stack[depth++] = node;
            cursor += padded;
        } else if (token == 2) {
            if (!depth) return FuxiRamProfileStructure;
            const FuxiRamProfileNode node = stack[--depth];
            if (node.kind == Memory && (node.seen & (Sku | Reg | Type)) != (Sku | Reg | Type)) return FuxiRamProfileSkuMissing;
            if (node.kind == Root) {
                if ((node.seen & (Address | Size)) != (Address | Size)) return FuxiRamProfileCells;
                root_complete = 1;
            }
            if (node.kind == ReservedRoot && (node.seen & (Address | Size | Ranges)) != (Address | Size | Ranges)) return FuxiRamProfileCells;
        } else if (token == 3) {
            if (!depth || stack[depth - 1].children || structure_end - cursor < 8) return FuxiRamProfileStructure;
            const uint32_t size = fuxi_ram_profile_be32(bytes + cursor);
            const uint32_t name_offset = fuxi_ram_profile_be32(bytes + cursor + 4);
            cursor += 8;
            if (size > structure_end - cursor) return FuxiRamProfileStructure;
            const uint32_t padded = (size + 3u) & ~UINT32_C(3);
            if (padded > structure_end - cursor) return FuxiRamProfileStructure;
            size_t name_length = 0;
            if (name_offset >= strings_size ||
                !fuxi_ram_profile_name(bytes + strings + name_offset, strings_size - name_offset, &name_length) ||
                !name_length) return FuxiRamProfileName;
            const uint8_t *name = bytes + strings + name_offset;
            const uint8_t *value = bytes + cursor;
            FuxiRamProfileNode *node = &stack[depth - 1];
            if (node->kind == MemoryEmpty) return FuxiRamProfileStructure;
            unsigned field = 0;
            if (node->kind == Root && fuxi_ram_profile_text(name, name_length + 1, "model")) {
                field = Model;
                if (model_seen++) return FuxiRamProfileConflict;
                if (!fuxi_ram_profile_model(value, size)) return FuxiRamProfileModel;
            } else if ((node->kind == Root || node->kind == ReservedRoot) &&
                (fuxi_ram_profile_text(name, name_length + 1, "#address-cells") ||
                 fuxi_ram_profile_text(name, name_length + 1, "#size-cells"))) {
                field = fuxi_ram_profile_text(name, name_length + 1, "#address-cells") ? Address : Size;
                if (size != 4 || fuxi_ram_profile_be32(value) != 2) return FuxiRamProfileCells;
            } else if (node->kind == Memory && fuxi_ram_profile_text(name, name_length + 1, "ddr_size")) {
                field = Sku;
                if (sku_seen++) return FuxiRamProfileConflict;
                if (size != 4 || fuxi_ram_profile_be32(value) != 12) return FuxiRamProfileSkuUnsupported;
            } else if (node->kind == Memory && fuxi_ram_profile_text(name, name_length + 1, "device_type")) {
                field = Type;
                if (!fuxi_ram_profile_text(value, size, "memory")) return FuxiRamProfileMemory;
            } else if ((node->kind == Memory || node->kind == ReservedChild) &&
                fuxi_ram_profile_text(name, name_length + 1, "reg")) {
                field = Reg;
                const enum FuxiRamProfileResult result = fuxi_ram_profile_reg(value, size,
                    phys_base, target_end, node->kind == ReservedChild, ranges, &count);
                if (result) return result;
            } else if (node->kind == ReservedRoot && fuxi_ram_profile_text(name, name_length + 1, "ranges")) {
                field = Ranges;
                if (size) return FuxiRamProfileReserved;
            } else if (node->kind == ReservedRoot && fuxi_ram_profile_text(name, name_length + 1, "reg")) {
                return FuxiRamProfileReserved;
            } else if (node->kind == ReservedChild && fuxi_ram_profile_text(name, name_length + 1, "size")) {
                field = DynamicSize;
                if (size != 8 || !fuxi_ram_profile_be64(value)) return FuxiRamProfileMemory;
            } else if (node->kind == Memory && fuxi_ram_profile_text(name, name_length + 1, "status")) {
                field = Status;
                if (!fuxi_ram_profile_text(value, size, "okay") && !fuxi_ram_profile_text(value, size, "ok")) return FuxiRamProfileMemory;
            }
            if (field && (node->seen & field)) return FuxiRamProfileConflict;
            node->seen |= field;
            cursor += padded;
        } else if (token == 4) {
            continue;
        } else if (token == 9) {
            if (depth || !root_complete || cursor != structure_end) return FuxiRamProfileStructure;
            if (!model_seen) return FuxiRamProfileModel;
            if (!sku_seen || !memory_seen) return FuxiRamProfileSkuMissing;
            for (unsigned index = 1; index < count; index++) {
                const FuxiRamProfileRange item = ranges[index];
                unsigned position = index;
                while (position && ranges[position - 1].start > item.start) {
                    ranges[position] = ranges[position - 1]; position--;
                }
                ranges[position] = item;
            }
            uint64_t covered = phys_base;
            for (unsigned index = 0; index < count; index++) {
                if (index && ranges[index].start < ranges[index - 1].end) return FuxiRamProfileConflict;
                if (ranges[index].end <= covered) continue;
                if (ranges[index].start > covered) return FuxiRamProfileMemory;
                covered = ranges[index].end;
                if (covered >= target_end) {
                    for (unsigned later = index + 1; later < count; later++) {
                        if (ranges[later].start < ranges[later - 1].end) return FuxiRamProfileConflict;
                    }
                    return FuxiRamProfileStaticOk12G;
                }
            }
            return FuxiRamProfileMemory;
        } else {
            return FuxiRamProfileStructure;
        }
    }
    return FuxiRamProfileStructure;
}

#endif
