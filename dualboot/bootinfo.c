/* SPDX-License-Identifier: MIT
 * Adapted from the workspace's ios-fuxi/shim/fuxi-loader/chain.c.
 * FDT and bootconfig bounds are validated before any string/data access.
 */
#include "bootinfo.h"
static uint32_t be(const unsigned char *p)
{ return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3]; }
static uint32_t le(const unsigned char *p)
{ return (uint32_t)p[3] << 24 | (uint32_t)p[2] << 16 | (uint32_t)p[1] << 8 | p[0]; }
static int equal(const unsigned char *p, size_t n, const char *s)
{
    size_t i = 0;
    for (; i < n && s[i]; ++i) if (p[i] != (unsigned char)s[i]) return 0;
    return i < n && p[i] == 0 && s[i] == 0;
}

int menu_fdt_initrd(const void *data, size_t bytes, struct menu_bootinfo *out)
{
    if (!data || !out || bytes < 40) return 0;
    const unsigned char *b = data;
    uint32_t total = be(b + 4), st = be(b + 8), strings = be(b + 12);
    uint32_t ns = be(b + 32), nt = be(b + 36);
    if (be(b) != 0xd00dfeedu || total < 40 || total > bytes || total > (2u << 20) ||
        st < 40 || (st & 3) || st > total || nt > total - st ||
        strings < 40 || strings > total || ns > total - strings ||
        (st < strings + ns && strings < st + nt)) return 0;
    size_t pos = st, end = st + nt;
    unsigned depth = 0, found = 0, chosen = 0, seen_chosen = 0, seen_root = 0;
    struct menu_bootinfo result = {0};
    while (end - pos >= 4) {
        uint32_t token = be(b + pos); pos += 4;
        if (token == 1) {
            size_t name = pos;
            while (pos < end && b[pos]) ++pos;
            if (pos == end || pos + 4 > end || depth >= 64) return 0;
            if (!depth) {
                if (seen_root || pos != name) return 0;
                seen_root = 1;
            }
            if (depth == 1 && equal(b + name, pos - name + 1, "chosen")) {
                if (seen_chosen) return 0;
                seen_chosen = 1;
                chosen = depth + 1;
            }
            pos = (pos + 4) & ~(size_t)3;
            ++depth;
        } else if (token == 2) {
            if (!depth) return 0;
            if (depth == chosen) chosen = 0;
            --depth;
        } else if (token == 3) {
            if (!depth || end - pos < 8) return 0;
            uint32_t len = be(b + pos), no = be(b + pos + 4); pos += 8;
            if (len > end - pos || no >= ns) return 0;
            size_t namelen = 0;
            while (namelen < ns - no && b[strings + no + namelen]) ++namelen;
            if (namelen == ns - no) return 0;
            if (chosen && depth == chosen) {
                unsigned flag = equal(b + strings + no, namelen + 1, "linux,initrd-start") ? 1u :
                                equal(b + strings + no, namelen + 1, "linux,initrd-end") ? 2u : 0u;
                if (flag) {
                    if ((len != 4 && len != 8) || (found & flag)) return 0;
                    uint64_t value = be(b + pos);
                    if (len == 8) value = (value << 32) | be(b + pos + 4);
                    if (flag == 1) result.initrd_start = value;
                    else result.initrd_end = value;
                    found |= flag;
                }
            }
            pos = (pos + len + 3) & ~(size_t)3;
            if (pos > end) return 0;
        } else if (token == 4) continue;
        else if (token == 9) {
            if (depth || found != 3 || result.initrd_end <= result.initrd_start) return 0;
            *out = result;
            return 1;
        } else return 0;
    }
    return 0;
}

int menu_bootconfig_normal(const void *initrd, size_t bytes)
{
    static const char magic[] = "#BOOTCONFIG\n", key[] = "androidboot.force_normal_boot";
    if (!initrd || bytes < 20) return -1;
    const unsigned char *b = initrd, *trailer = b + bytes - 20;
    for (unsigned i = 0; i < 12; ++i) if (trailer[8 + i] != (unsigned char)magic[i]) return -1;
    uint32_t size = le(trailer), checksum = le(trailer + 4), sum = 0;
    if (!size || size > (1u << 20) || size > bytes - 20) return -1;
    const unsigned char *text = trailer - size;
    for (unsigned i = 0; i < size; ++i) sum += text[i];
    if (sum != checksum) return -1;
    /* A full key at the start of a line; comments, quoted values and prefix
     * lookalikes cannot accidentally turn Recovery into an iOS boot. */
    unsigned at_line_start = 1;
    for (unsigned i = 0; i < size; ++i) {
        if (text[i] == '\n') { at_line_start = 1; continue; }
        if (at_line_start && (text[i] == ' ' || text[i] == '\t')) continue;
        if (at_line_start && size - i >= sizeof(key)) {
            unsigned j = 0;
            while (j < sizeof(key) - 1 && text[i + j] == (unsigned char)key[j]) ++j;
            unsigned k = i + j;
            while (k < size && (text[k] == ' ' || text[k] == '\t')) ++k;
            if (j == sizeof(key) - 1 && k < size && text[k] == '=') return 1;
        }
        at_line_start = 0;
    }
    return 0;
}
