#include "fuxi_wlan_arena.h"
#include "fuxi_wlan_ath12k.h"
#include "fuxi_wlan_control.h"
#include <pexpert/device_tree.h>

#define WLA_BYTES (128u << 20)
#define WLA_BLOCKS 16384u
static struct fwa_arena wla_pool;
static struct fwa_block *wla_blocks;
static unsigned wla_express, wla_msi, wla_failed;
static unsigned wla_scan_log_remaining;
static struct {
	const char *name, *file;
	void *memory;
	size_t bytes;
} wla_firmware[] = {
	{"amss.bin", "amss20.bin", NULL, 0},
	{"m3.bin", "m3.bin", NULL, 0},
	{"board-2.bin", "board-2.bin", NULL, 0},
	{"regdb.bin", "regdb_xiaomi.bin", NULL, 0},
};

static uint64_t
wla_now_ns(void)
{
	uint64_t ns = 0;
	absolutetime_to_nanoseconds(mach_absolute_time(), &ns);
	return ns;
}

static uint64_t
wla_now_ms(void)
{
	return wla_now_ns() / 1000000ull;
}

static void *
wla_alloc(size_t bytes)
{
	if (!bytes || bytes > (64u << 20)) { return NULL; }
	vm_size_t allocation = round_page(bytes + 16);
	vm_offset_t memory = 0;
	if (kmem_alloc(kernel_map, &memory, allocation,
	    KMA_DATA | KMA_ZERO | KMA_NOPAGEWAIT, VM_KERN_MEMORY_IOKIT) != KERN_SUCCESS) { return NULL; }
	*(vm_size_t *)memory = allocation;
	return (void *)(memory + 16);
}

static void
wla_free(void *memory)
{
	if (!memory) { return; }
	vm_offset_t base = (vm_offset_t)memory - 16;
	kmem_free(kernel_map, base, *(vm_size_t *)base);
}

static void
wl_ath_release(void)
{
	if (wl_ath_arena.va) { return; }
	wla_free(wla_blocks);
	wla_blocks = NULL;
	memset(&wla_pool, 0, sizeof(wla_pool));
	for (unsigned index = 0; index < sizeof(wla_firmware) / sizeof(wla_firmware[0]); index++) {
		wla_free(wla_firmware[index].memory);
		wla_firmware[index].memory = NULL;
		wla_firmware[index].bytes = 0;
	}
}

static void *
wla_dma_alloc(size_t bytes, uint64_t *bus)
{
	void *memory = wla_failed ? NULL : fwa_alloc(&wla_pool, bytes, bus);
	if (!memory) {
		if (bus) { *bus = 0; }
		printf("FUXI ATH12K: DMA allocation refused bytes %llu blocks %u\n", (uint64_t)bytes, wla_pool.count);
	}
	return memory;
}

static void
wla_dma_free(size_t bytes, void *memory, uint64_t bus)
{
	int error = !bytes && !bus ? fwa_kfree(&wla_pool, memory) :
	    fwa_free(&wla_pool, bytes, memory, bus);
	if (error) {
		if (!wla_failed) {
			printf("FUXI ATH12K: DMA free refused bytes %llu memory %p bus 0x%llx\n",
			    (unsigned long long)bytes, memory, (unsigned long long)bus);
		}
		wla_failed = 1;
	}
}

static uint64_t
wla_dma_map(void *memory, size_t bytes, int direction)
{
	if (wla_failed || direction < 0 || direction > 2) { return 0; }
	return fwa_map(&wla_pool, memory, bytes);
}

static void
wla_dma_sync(uint64_t bus, size_t bytes, int direction)
{
	if (direction < 0 || direction > 2 || bus < wla_pool.bus ||
	    bus - wla_pool.bus >= wla_pool.bytes ||
	    fwa_map(&wla_pool, wla_pool.memory + (bus - wla_pool.bus), bytes) != bus) {
		if (!wla_failed) {
			printf("FUXI ATH12K: DMA sync refused bus 0x%llx bytes %llu direction %d\n",
			    (unsigned long long)bus, (unsigned long long)bytes, direction);
		}
		wla_failed = 1;
		return;
	}
	__asm__ volatile("dsb sy" ::: "memory");
}

static int
wla_fw_get(const char *name, const uint8_t **data, size_t *bytes)
{
	if (!name || !data || !bytes) { return -1; }
	*data = NULL;
	*bytes = 0;
	const char *base = name;
	for (const char *cursor = name; *cursor; cursor++) {
		if (*cursor == '/') { base = cursor + 1; }
	}
	if (!strcmp(base, "wlan_mac.bin")) {
		DTEntry chosen;
		const void *property;
		unsigned length;
		static char text[13];
		if (SecureDTLookupEntry(NULL, "/chosen", &chosen) != kSuccess ||
		    SecureDTGetProperty(chosen, "mac-address-wifi0", &property, &length) != kSuccess ||
		    fwa_mac_text(property, length, text)) { return -1; }
		*data = (const uint8_t *)text;
		*bytes = 12;
		return 0;
	}
	unsigned index;
	for (index = 0; index < sizeof(wla_firmware) / sizeof(wla_firmware[0]); index++) {
		if (!strcmp(base, wla_firmware[index].name)) { break; }
	}
	if (index == sizeof(wla_firmware) / sizeof(wla_firmware[0])) { return -1; }
	if (!wla_firmware[index].memory) {
		char path[128];
		vnode_t file = NULL;
		vfs_context_t context = vfs_context_kernel();
		snprintf(path, sizeof(path), "/usr/local/share/fuxi/wlan/%s", wla_firmware[index].file);
		int error = vnode_open(path, FREAD | O_NOFOLLOW | O_NONBLOCK, 0, 0, &file, context);
		if (error) { return -1; }
		struct vnode_attr attributes;
		VATTR_INIT(&attributes);
		VATTR_WANTED(&attributes, va_data_size);
		error = vnode_getattr(file, &attributes, context);
		if (error || vnode_vtype(file) != VREG || !VATTR_IS_SUPPORTED(&attributes, va_data_size) ||
		    !attributes.va_data_size || attributes.va_data_size > WL_FW_MAX) { error = -1; }
		void *memory = error ? NULL : wla_alloc((size_t)attributes.va_data_size);
		if (!memory) { error = -1; }
		if (!error) {
			int residual = 0;
			error = vn_rdwr(UIO_READ, file, (caddr_t)memory, (int)attributes.va_data_size, 0,
			    UIO_SYSSPACE, 0, vfs_context_ucred(context), &residual, vfs_context_proc(context));
			if (residual) { error = -1; }
		}
		if (vnode_close(file, FREAD, context)) { error = -1; }
		if (error) {
			wla_free(memory);
			return -1;
		}
		wla_firmware[index].memory = memory;
		wla_firmware[index].bytes = (size_t)attributes.va_data_size;
		printf("FUXI ATH12K: firmware %s from %s bytes %llu\n", base,
		    wla_firmware[index].file, (uint64_t)wla_firmware[index].bytes);
	}
	*data = wla_firmware[index].memory;
	*bytes = wla_firmware[index].bytes;
	return 0;
}

static int
wla_cfg_read(int encoded, int size, uint32_t *value)
{
	unsigned offset;
	if (!value || fwa_config_offset((uint32_t)encoded, (unsigned)size, wla_express, &offset) ||
	    fw_faults || wla_failed) { return -1; }
	uint32_t word = wl_prd(WL_EPCFG + (offset & ~3u));
	if (fw_faults) { return -1; }
	*value = size == 4 ? word : (word >> (8 * (offset & 3u))) & (size == 2 ? 0xffffu : 0xffu);
	return 0;
}

static int
wla_cfg_write(int encoded, int size, uint32_t value)
{
	unsigned offset;
	if (fwa_config_offset((uint32_t)encoded, (unsigned)size, wla_express, &offset) ||
	    fw_faults || wla_failed) { return -1; }
	unsigned aligned = offset & ~3u;
	if (size != 4) {
		uint32_t shift = (offset & 3u) * 8;
		uint32_t mask = (size == 2 ? 0xffffu : 0xffu) << shift;
		uint32_t old = wl_prd(WL_EPCFG + aligned);
		if (fw_faults) { return -1; }
		if (aligned == 4 || aligned == wla_express + 8 || aligned == wla_express + 16) {
			old &= 0xffffu;
		}
		value = (old & ~mask) | ((value << shift) & mask);
	}
	wl_pwr(WL_EPCFG + aligned, value);
	__asm__ volatile("dsb sy" ::: "memory");
	return fw_faults ? -1 : 0;
}

static int
wla_msi_target(uint32_t *low, uint32_t *high, uint32_t *data)
{
	if (!low || !high || !data || !wl_enabled || !wla_pool.memory || wla_failed) { return -1; }
	*low = (uint32_t)wla_pool.bus;
	*high = (uint32_t)(wla_pool.bus >> 32);
	*data = 0;
	return 0;
}

static void *
wla_map_phys(uint64_t address, size_t bytes)
{
	if (!bytes || address < WL_BAR0 || address - WL_BAR0 >= 0x200000 ||
	    bytes > 0x200000 - (address - WL_BAR0)) { return NULL; }
	return (void *)(fw_va(WL_BAR0) + (address - WL_BAR0));
}

static void
wla_poll(void)
{
#if defined(FUXI_ATH12K_LINKED)
	nw_wifi_irq_mode(0);
	nw_wifi_poll();
#endif
}

static void
wla_log(int level, const char *line)
{
	if (!line) { return; }
	if (level > 6) {
		if (!wla_scan_log_remaining ||
		    (strncmp(line, "scan event ", sizeof("scan event ") - 1) &&
		     strncmp(line, "send 11d scan ", sizeof("send 11d scan ") - 1))) { return; }
		wla_scan_log_remaining--;
	}
	printf("FUXI ATH12K: %llu %.180s\n", wla_now_ms(), line);
}

static void
wla_halt(void)
{
	wla_failed = 1;
	printf("FUXI ATH12K: module halted; contain once, worker exits\n");
	wl5_abort(18);
	(void)thread_terminate(current_thread());
	thread_block(THREAD_CONTINUE_NULL);
	for (;;) { wl_sleep(1000); }
}

extern void _disable_preemption(void);
extern void _enable_preemption(void);

#if defined(FUXI_ATH12K_LINKED)
/* The pinned module namespaces Linux exports. See ath12k/debug.h for ATH12K_DBG_WMI. */
extern unsigned int nwk_ath12k_debug_mask __attribute__((weak_import));
#define WLA_DBG_WMI 0x00000002u
static struct fwc_probe wla_control;
static unsigned wla_control_awake;

static int
wla_control_send(void *context, uint64_t session, const void *bytes, size_t length)
{
	struct fwc_probe *probe = context;
	if (fwc_probe_receive(probe, session, bytes, length)) {
		probe->error = -1;
		return 2;
	}
	const uint8_t *message = bytes;
	if (fwc_read16(message + 6) == 2 || fwc_read16(message + 8) == 0x102) {
		printf("FUXI ATH12K: control operation %u status %u generation %llu\n",
		    fwc_read16(message + 8), fwc_read32(message + 20), probe->generation);
	}
	return 0;
}

static void
wla_control_wake(void *context)
{
	(void)context;
	wla_control_awake = 1;
}

static int
wla_control_read(void *context, void *destination, size_t length)
{
	memcpy(destination, context, length);
	return 0;
}
#include "fuxi_wlan_ios.inc"
#endif

static bool
wla_available(void)
{
#if defined(FUXI_ATH12K_LINKED)
	return true;
#else
	return false;
#endif
}

static int
wl_ath_run(void)
{
#if defined(FUXI_ATH12K_LINKED)
	static const struct lx_platform platform = {
		wla_now_ms, wl_sleep, wla_poll, wla_log, wla_halt, wla_alloc, wla_free,
		wla_dma_alloc, wla_dma_free, wla_dma_map, wla_dma_sync, wla_fw_get,
		wla_now_ns, wla_now_ns, fw_delay, _disable_preemption, _enable_preemption
	};
	static struct nw_board board;
	int ios_mode = 0;
	PE_parse_boot_argn("fuxiwifiios", &ios_mode, sizeof(ios_mode));
	bool ios = ios_mode == 2;
	memset(&wla_control, 0, sizeof(wla_control));
	wla_control_awake = 0;
	nw_wifi_set_platform(&platform);
	const struct nw_control_transport control = {
		&wla_control, ios ? wli_receive : wla_control_send, wla_control_wake
	};
	int control_error = nw_wifi_control_transport_set(&control);
	if (control_error) {
		printf("FUXI ATH12K: control transport refused status %d\n", control_error);
		return 6;
	}
	printf("FUXI ATH12K: %s control transport installed\n", ios ? "iOS native" : "diagnostic");
	uint32_t flags = 0;
	wla_express = wl_diag_cap(WL_EPCFG, 0x10, false, &flags);
	wla_msi = wl_diag_cap(WL_EPCFG, 5, false, &flags);
	if (!wla_express || !wla_msi || flags || fw_faults || !wla_available() ||
	    wl_prd(WL_EPCFG) != 0x110717cb || (wl_prd(WL_EPCFG + 4) & 4) ||
	    wl_mrd(wl_bhi + 0x28) != 0 || wl_disable_irqs() || wl_download_aspm()) { return 1; }
	const uint8_t *data;
	size_t bytes;
	for (unsigned attempt = 0; attempt < 1200; attempt++) {
		if (!wla_fw_get("amss.bin", &data, &bytes) &&
		    !wla_fw_get("m3.bin", &data, &bytes) &&
		    !wla_fw_get("board-2.bin", &data, &bytes)) { break; }
		if (attempt == 1199) { return 2; }
		wl_sleep(100);
	}
	uint64_t alignment = WLA_BYTES;
	wl_iova_next = (wl_iova_next + alignment - 1) & ~(alignment - 1);
	wla_blocks = wla_alloc(WLA_BLOCKS * sizeof(*wla_blocks));
	if (!wla_blocks || wl_dma_alloc(&wl_ath_arena, WLA_BYTES) || wl_dma_nc(&wl_ath_arena) ||
	    fwa_init(&wla_pool, (void *)wl_ath_arena.va, wl_ath_arena.iova, WLA_BYTES, wla_blocks, WLA_BLOCKS) ||
	    wl_smmu_enable() || wl_smmu_fault(18) || wl_rc_check()) { return 3; }
	board = (struct nw_board){
		(void *)fw_va(WL_BAR0), 0x200000, 0x1107, (uint16_t)wla_msi, 1000,
		wla_cfg_read, wla_cfg_write, wla_msi_target, wla_map_phys, 0
	};
	wl_pwr(WL_EPCFG + 4, (wl_prd(WL_EPCFG + 4) & 0xffff) | 0x406);
	if (fw_faults || (wl_prd(WL_EPCFG + 4) & 0x406) != 0x406) { return 4; }
	printf("FUXI ATH12K: start from PBL, full BAR, owned 128 MiB DMA, IRQ polling; legacy MHI skipped\n");
	nw_wifi_irq_mode(0);
	int error = nw_wifi_start(&platform, &board);
	bool trace_scan = !error && ios && (fuxi_wifi_ux() & FUXI_WIFI_UX_SCAN_TRACE) && &nwk_ath12k_debug_mask;
	unsigned int prior_debug_mask = 0;
	if (trace_scan) {
		prior_debug_mask = nwk_ath12k_debug_mask;
		nwk_ath12k_debug_mask = prior_debug_mask | WLA_DBG_WMI;
		wla_scan_log_remaining = 384;
		printf("FUXI ATH12K: WMI scan trace enabled\n");
	}
	bool attached = false, completed = false;
	uint64_t started = wla_now_ms(), report = started;
	unsigned spins = 0;
	while (!error && !fw_faults && !wla_failed && !wla_control.error &&
	    ((ios && wli.published) || wla_now_ms() - started < 90000)) {
		wla_control_awake = 0;
		/* nonzero while frames move: go round again without sleeping, but not for ever */
		int moving = nw_wifi_step();
		if (trace_scan && !wla_scan_log_remaining) {
			nwk_ath12k_debug_mask = prior_debug_mask;
			trace_scan = false;
		}
		uint64_t now = wla_now_ms();
		if (!attached && nw_wifi_stats.stage >= 4) {
			error = nw_wifi_control_attach(ios ? &wli.session : &wla_control.session);
			attached = !error;
			printf("FUXI ATH12K: control attached result %d\n", error);
		}
		if (attached && !error && ios) {
			error = wli_step(now);
			if (error) { wli_fail(error); }
		}
		if (attached && !error && !ios) {
			uint8_t request[80];
			size_t length = fwc_probe_request(&wla_control, request, sizeof(request));
			if (length) {
				error = nw_wifi_control_receive(wla_control.session, length, wla_control_read, request);
				printf("FUXI ATH12K: control request %u queued result %d\n",
				    fwc_read16(request + 8), error);
			}
		}
		if (!ios && wla_control.scan_accepted && wla_control.scan_done &&
		    !wla_control.error && nw_wifi_stats.scans) {
			completed = true;
			break;
		}
		if (now >= report) {
			report = now + 5000;
			printf("FUXI ATH12K: stage %u scans %u BSS %u error %d\n", nw_wifi_stats.stage,
			    nw_wifi_stats.scans, nw_wifi_stats.bss_seen, nw_wifi_stats.last_err);
			if (wl_smmu_fault(0) || wl_rc_check()) { error = -1; break; }
		}
		if (!wla_control_awake && (!moving || ++spins >= 64)) {
			spins = 0;
			wl_sleep(1);
		}
	}
	if (trace_scan) {
		nwk_ath12k_debug_mask = prior_debug_mask;
		wla_scan_log_remaining = 0;
	}
	if (ios) { wli_fail(error ? error : EIO); }
	if (!error && wla_control.error) {
		error = wla_control.error < 0 ? wla_control.error : -wla_control.error;
	}
	int count = completed ? nw_wifi_bss_count() : 0;
	printf("FUXI ATH12K: scan completed %u BSS count %d start error %d DMA error %u faults %u\n",
	    completed, count, error, wla_failed, fw_faults);
	for (int index = 0; completed && index < count && index < 64; index++) {
		struct nw_bss_info info;
		if (!nw_wifi_bss_get(index, &info)) {
			char ssid[33];
			unsigned length = MIN((unsigned)info.ssid_len, 32u);
			for (unsigned at = 0; at < length; at++) {
				ssid[at] = info.ssid[at] >= 0x20 && info.ssid[at] < 0x7f ? (char)info.ssid[at] : '?';
			}
			ssid[length] = 0;
			printf("FUXI ATH12K: BSS %d freq %u RSSI %d SSID %s\n", index,
			    info.freq_mhz, info.signal_dbm, ssid);
		}
	}
	nw_wifi_stop();
	if (wl_disable_irqs()) { error = -1; }
	bool success = !error && completed && count > 0 && !wla_failed && !fw_faults;
	printf("FUXI ATH12K: diagnostic %s; common containment follows\n", success ? "scan observed" : "incomplete");
	return success ? 0 : 5;
#else
	return 1;
#endif
}
