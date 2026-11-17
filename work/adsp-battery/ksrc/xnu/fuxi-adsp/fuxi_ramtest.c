#include <pexpert/arm64/board_config.h>
#if defined(FUXI)
#include <sys/param.h>
#include <sys/systm.h>
#include <kern/thread.h>
#include <kern/sched_prim.h>
#include <pexpert/pexpert.h>
#include <pexpert/device_tree.h>
#include <vm/vm_kern.h>
#include <vm/pmap.h>
#include "fuxi_ramtest_pattern.h"

extern ppnum_t pmap_find_phys(pmap_t, addr64_t);
extern kern_return_t kernel_thread_start(thread_continue_t, void *, thread_t *);
extern kern_return_t thread_terminate(thread_t);
extern void thread_deallocate(thread_t);
extern wait_result_t thread_block(thread_continue_t);
extern void IOSleep(unsigned milliseconds);
void fuxi_ramtest_init(void);

static unsigned fr_started;
static unsigned fr_mode;

static void fr_evict(vm_offset_t address, vm_size_t size)
{
    uint64_t cache_type;
    __asm__ volatile("mrs %0, ctr_el0" : "=r"(cache_type));
    vm_size_t line = 4ull << ((cache_type >> 16) & 15u);
    __asm__ volatile("dsb ish" ::: "memory");
    for (vm_size_t offset = 0; offset < size; offset += line) {
        __asm__ volatile("dc civac, %0" :: "r"(address + offset) : "memory");
    }
    __asm__ volatile("dsb ish" ::: "memory");
}

static void fr_worker(void *argument, wait_result_t wait_result)
{
    (void)argument;
    (void)wait_result;
    vm_offset_t address = 0;
    const vm_size_t size = (vm_size_t)fuxi_ramtest_allocation_bytes(fr_mode);
    const size_t words = size / sizeof(uint64_t);
    unsigned high_pages = 0, completed = 0;
    uint64_t lowest = UINT64_MAX, highest = 0;
    IOSleep(20000);
    kern_return_t result = kmem_alloc(kernel_map, &address, size,
        KMA_DATA | KMA_NOPAGEWAIT, VM_KERN_MEMORY_IOKIT);
    if (result != KERN_SUCCESS) {
        printf("FUXI RAMTEST: allocation refused rc=%d bytes=%llu\n", result, (uint64_t)size);
        goto done;
    }
    for (vm_size_t offset = 0; offset < size; offset += PAGE_SIZE) {
        uint64_t physical = (uint64_t)pmap_find_phys(kernel_pmap, address + offset) << PAGE_SHIFT;
        if (!fuxi_ramtest_page_allowed(physical, PAGE_SIZE)) {
            printf("FUXI RAMTEST: refused physical=%#llx offset=%#llx; no pattern written\n",
                physical, (uint64_t)offset);
            goto release;
        }
        if (physical < lowest) lowest = physical;
        if (physical > highest) highest = physical;
        if (physical >= 0xa00000000ull) high_pages++;
    }
    printf("FUXI RAMTEST: allocated bytes=%llu pages=%llu high-pages=%u physical=%#llx..%#llx\n",
        (uint64_t)size, (uint64_t)(size / PAGE_SIZE), high_pages, lowest, highest);
    if (!high_pages) {
        printf("FUXI RAMTEST: no pages above old 5GiB aperture; coverage not accepted\n");
        goto release;
    }
    for (unsigned pass = 0; pass < 4; pass++) {
        fuxi_ramtest_fill((volatile uint64_t *)address, words, pass);
        fr_evict(address, size);
        IOSleep(50);
        size_t bad = fuxi_ramtest_verify((const volatile uint64_t *)address, words, pass);
        if (bad != words) {
            printf("FUXI RAMTEST: FAIL pass=%u word=%llu physical=%#llx expected=%#llx actual=%#llx\n",
                pass, (uint64_t)bad,
                ((uint64_t)pmap_find_phys(kernel_pmap, address + bad * sizeof(uint64_t)) << PAGE_SHIFT) |
                    ((bad * sizeof(uint64_t)) & PAGE_MASK),
                fuxi_ramtest_word(bad, pass), ((volatile uint64_t *)address)[bad]);
            goto release;
        }
        completed++;
        printf("FUXI RAMTEST: pass=%u bytes=%llu high-bytes=%llu cache-evicted verified\n",
            pass, (uint64_t)size, (uint64_t)high_pages * PAGE_SIZE);
    }
release:
    kmem_free(kernel_map, address, size);
    printf("FUXI RAMTEST: released bytes=%llu completed=%u/4 coverage=allocated-sample\n",
        (uint64_t)size, completed);
done:
    (void)thread_terminate(current_thread());
    thread_block(THREAD_CONTINUE_NULL);
}

void fuxi_ramtest_init(void)
{
    DTEntry chosen;
    const void *property = NULL;
    unsigned bytes = 0, mode = 0;
    uint64_t ram = 0, gpu[2] = {0};
    if (SecureDTLookupEntry(NULL, "/chosen", &chosen) != kSuccess ||
        SecureDTGetProperty(chosen, "fuxi,ramtest", &property, &bytes) != kSuccess || bytes != sizeof(mode)) return;
    memcpy(&mode, property, sizeof(mode));
    if (!fuxi_ramtest_allocation_bytes(mode) ||
        __atomic_exchange_n(&fr_started, 1u, __ATOMIC_ACQ_REL)) return;
    if (SecureDTGetProperty(chosen, "dram-size", &property, &bytes) != kSuccess || bytes != sizeof(ram)) return;
    memcpy(&ram, property, sizeof(ram));
    if (SecureDTGetProperty(chosen, "fuxi-gpu-memory", &property, &bytes) != kSuccess || bytes != sizeof(gpu)) return;
    memcpy(gpu, property, sizeof(gpu));
    if (ram != 0x23e000000ull || gpu[0] != 0xafe000000ull || gpu[1] != 0x2000000) {
        printf("FUXI RAMTEST: refused layout dram=%#llx gpu=%#llx/%#llx\n", ram, gpu[0], gpu[1]);
        return;
    }
    fr_mode = mode;
    thread_t thread = NULL;
    if (kernel_thread_start(fr_worker, NULL, &thread) != KERN_SUCCESS) {
        printf("FUXI RAMTEST: worker could not start\n");
        return;
    }
    thread_deallocate(thread);
}
#endif
