/* Fuxi chain stage (slot-b dual boot): runs first, before anything touches hardware,
 * and picks between the XNU loader and an embedded Android (Linux) kernel.
 *
 * Measured on the Xiaomi 13 (2026-11-14): in recovery mode ABL boots the boot
 * partition's kernel with the recovery ramdisk (TWRP in recovery_a/_b has no kernel),
 * and the bootconfig ABL appends to the initrd carries androidboot.force_normal_boot
 * on a normal boot but not in recovery mode (initrd 33 MB normal, 107 MB with TWRP).
 * So with this image in boot_b: normal boot -> XNU, recovery boot (Power+Vol-up) ->
 * the embedded Android kernel -> TWRP, which can switch back to slot a.
 *
 * MMU and caches are off (Linux boot ABI), so memory is Device: only byte loads and
 * aligned word loads here (-mstrict-align), no writes outside our own stack. */
#include <stdint.h>

extern char _linux_start[], _linux_end[];

#define FDT_MAGIC	0xd00dfeedu
#define FDT_BEGIN_NODE	1
#define FDT_END_NODE	2
#define FDT_PROP	3
#define FDT_NOP		4
#define FDT_END		9
#define RECOVERY_INITRD_MIN	(64u << 20)	/* fallback only: no bootconfig found */

static uint32_t be32(uintptr_t p)
{
	const volatile uint8_t *b = (const volatile uint8_t *)p;
	return (uint32_t)b[0] << 24 | (uint32_t)b[1] << 16 | (uint32_t)b[2] << 8 | b[3];
}

static uint32_t le32(uintptr_t p)
{
	const volatile uint8_t *b = (const volatile uint8_t *)p;
	return (uint32_t)b[3] << 24 | (uint32_t)b[2] << 16 | (uint32_t)b[1] << 8 | b[0];
}

static int mem_eq(uintptr_t p, const char *s, uint32_t n)
{
	const volatile uint8_t *b = (const volatile uint8_t *)p;
	for (uint32_t i = 0; i < n; i++)
		if (b[i] != (uint8_t)s[i])
			return 0;
	return 1;
}

static uint32_t str_len(const char *s)
{
	uint32_t n = 0;
	while (s[n])
		n++;
	return n;
}

/* /chosen linux,initrd-start/-end (one or two big-endian cells). 1 when both found. */
static int fdt_initrd(uintptr_t fdt, uint64_t *start, uint64_t *end)
{
	if (!fdt || (fdt & 3) || be32(fdt) != FDT_MAGIC)
		return 0;
	uint32_t total = be32(fdt + 4), off_struct = be32(fdt + 8), off_strings = be32(fdt + 12);
	uint32_t size_strings = be32(fdt + 32), size_struct = be32(fdt + 36);
	if (total > (16u << 20) || off_struct > total || size_struct > total - off_struct ||
	    off_strings > total || size_strings > total - off_strings)
		return 0;
	uintptr_t p = fdt + off_struct, lim = p + size_struct;
	int depth = 0, chosen_depth = -1, found = 0;
	while (p + 4 <= lim) {
		uint32_t tok = be32(p);
		p += 4;
		if (tok == FDT_BEGIN_NODE) {
			uintptr_t name = p;
			while (p < lim && *(const volatile uint8_t *)p)
				p++;
			p = (p + 1 + 3) & ~(uintptr_t)3;
			depth++;
			if (depth == 2 && chosen_depth < 0 && mem_eq(name, "chosen", 7))
				chosen_depth = depth;
		} else if (tok == FDT_END_NODE) {
			if (depth == chosen_depth)
				return found == 3;
			depth--;
		} else if (tok == FDT_PROP) {
			if (p + 8 > lim)
				return 0;
			uint32_t len = be32(p), nameoff = be32(p + 4);
			uintptr_t val = p + 8;
			p = (val + len + 3) & ~(uintptr_t)3;
			if (p > lim || nameoff >= size_strings || depth != chosen_depth)
				continue;
			uintptr_t name = fdt + off_strings + nameoff;
			uint64_t v = len == 4 ? be32(val) : len == 8 ? (uint64_t)be32(val) << 32 | be32(val + 4) : 0;
			if (len != 4 && len != 8)
				continue;
			if (mem_eq(name, "linux,initrd-start", 19)) {
				*start = v;
				found |= 1;
			} else if (mem_eq(name, "linux,initrd-end", 17)) {
				*end = v;
				found |= 2;
			}
		} else if (tok == FDT_NOP) {
		} else {
			break;	/* FDT_END or garbage */
		}
	}
	return 0;
}

/* Bootconfig trailer at the initrd end: [text][size le32][checksum le32]["#BOOTCONFIG\n"].
 * 1 = key present, 0 = absent, -1 = no valid bootconfig. */
static int bootconfig_has(uint64_t start, uint64_t end, const char *key)
{
	if (end <= start || end - start < 32)
		return -1;
	uintptr_t e = (uintptr_t)end;
	if (!mem_eq(e - 12, "#BOOTCONFIG\n", 12))
		return -1;
	uint32_t size = le32(e - 20), sum = le32(e - 16), calc = 0;
	if (size == 0 || size > (1u << 20) || size > end - start - 20)
		return -1;
	uintptr_t text = e - 20 - size;
	for (uint32_t i = 0; i < size; i++)
		calc += *(const volatile uint8_t *)(text + i);
	if (calc != sum)
		return -1;
	uint32_t n = str_len(key);
	for (uint32_t i = 0; i + n <= size; i++)
		if (mem_eq(text + i, key, n))
			return 1;
	return 0;
}

/* Linux entry to branch to (x0 = fdt), or 0 to continue into the XNU loader. */
uintptr_t chain_select(uintptr_t fdt)
{
	uintptr_t linux_entry = (uintptr_t)_linux_start;
	if ((linux_entry & 0x1fffff) || (uintptr_t)_linux_end - linux_entry < 64 ||
	    !mem_eq(linux_entry + 56, "ARM\x64", 4))
		return 0;	/* no usable embedded kernel: XNU */
	uint64_t start = 0, end = 0;
	int normal = 1;
	if (fdt_initrd(fdt, &start, &end)) {
		normal = bootconfig_has(start, end, "androidboot.force_normal_boot");
		if (normal < 0)
			normal = end - start < RECOVERY_INITRD_MIN;
	}
#if defined(FUXI_CHAIN_FORCE_LINUX)
	normal = 0;	/* test build: always Linux */
#endif
	return normal ? 0 : linux_entry;
}
