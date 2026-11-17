#ifndef FUXI_RAM_BANK_PREP_H
#define FUXI_RAM_BANK_PREP_H

#include <stddef.h>
#include <stdint.h>

#ifndef FUXI_RAM_PREP_ENABLED
#define FUXI_RAM_PREP_ENABLED 0
#endif
#if FUXI_RAM_PREP_ENABLED != 0 && FUXI_RAM_PREP_ENABLED != 1
#error FUXI_RAM_PREP_ENABLED_must_be_zero_or_one
#endif

#define FUXI_RAM_PREP_VERSION 1u
#define FUXI_RAM_PREP_PAGE_SIZE UINT64_C(0x4000)
#define FUXI_RAM_PREP_MAX_BANKS 16u
#define FUXI_RAM_PREP_MAX_EXCLUSIONS 32u
#define FUXI_RAM_PREP_MAX_OWNERS 96u
#define FUXI_RAM_PREP_MAX_OWNER_RANGES 8u
#define FUXI_RAM_PREP_EXPERIMENTAL 1u
#define FUXI_RAM_OWNER_COMPLETE 1u
#define FUXI_RAM_OWNER_PLACEMENT_KNOWN 2u
#define FUXI_RAM_OWNER_PROVEN_ABSENT 4u
#define FUXI_RAM_PREP_GPU_BASE UINT64_C(0xafe000000)
#define FUXI_RAM_PREP_GPU_END UINT64_C(0xb00000000)

enum fuxi_ram_prep_result {
    FUXI_RAM_PREP_OK = 0,
    FUXI_RAM_PREP_BAD_MANIFEST,
    FUXI_RAM_PREP_BAD_RANGE,
    FUXI_RAM_PREP_OVERFLOW,
    FUXI_RAM_PREP_BAD_PFN,
    FUXI_RAM_PREP_OUTSIDE_SPAN,
    FUXI_RAM_PREP_NOT_WHITELISTED,
    FUXI_RAM_PREP_GPU,
    FUXI_RAM_PREP_STATIC,
    FUXI_RAM_PREP_OWNER,
    FUXI_RAM_PREP_DISABLED,
    FUXI_RAM_PREP_PENDING_OWNER,
    FUXI_RAM_PREP_DUPLICATE_RELEASE,
    FUXI_RAM_PREP_LEDGER_CAPACITY,
    FUXI_RAM_PREP_DIRTY_LEDGER,
    FUXI_RAM_PREP_ALREADY_INITIALIZED,
    FUXI_RAM_PREP_UNINITIALIZED,
    FUXI_RAM_PREP_CORRUPT_COUNTERS
};

struct fuxi_ram_prep_range {
    uint64_t start;
    uint64_t size;
};

struct fuxi_ram_prep_owner {
    uint32_t id;
    uint32_t flags;
    uint32_t range_count;
    uint32_t reserved;
    uint8_t evidence_sha256[32];
    struct fuxi_ram_prep_range ranges[FUXI_RAM_PREP_MAX_OWNER_RANGES];
};

struct fuxi_ram_prep_manifest {
    uint32_t version;
    uint32_t structure_bytes;
    uint32_t page_size;
    uint32_t flags;
    uint64_t physical_base;
    uint64_t physical_size;
    uint32_t bank_count;
    uint32_t exclusion_count;
    uint32_t owner_count;
    uint32_t owner_coverage_complete;
    uint8_t owner_manifest_sha256[32];
    struct fuxi_ram_prep_range banks[FUXI_RAM_PREP_MAX_BANKS];
    struct fuxi_ram_prep_range exclusions[FUXI_RAM_PREP_MAX_EXCLUSIONS];
    struct fuxi_ram_prep_owner owners[FUXI_RAM_PREP_MAX_OWNERS];
};

struct fuxi_ram_prep_counts {
    uint64_t span_pages;
    uint64_t whitelist_pages;
    uint64_t known_excluded_pages;
    uint64_t geometric_candidate_pages;
    uint64_t shadow_released_pages;
    uint64_t remaining_geometric_pages;
    uint32_t host_admissible_known;
    uint64_t host_admissible_pages;
};

struct fuxi_ram_prep_state {
    uint32_t initialized;
    uint32_t owners_complete;
    uint64_t span_end;
    struct fuxi_ram_prep_manifest manifest;
    struct fuxi_ram_prep_counts counts;
    uint8_t *shadow_ledger;
    size_t shadow_ledger_bytes;
};

int fuxi_ram_prep_range_end(struct fuxi_ram_prep_range range, uint64_t *end);
int fuxi_ram_prep_init_zeroed(struct fuxi_ram_prep_state *state,
    const struct fuxi_ram_prep_manifest *manifest, uint8_t *shadow_ledger, size_t ledger_bytes);
int fuxi_ram_prep_dense_index(const struct fuxi_ram_prep_state *state, uint64_t pfn, uint32_t *index);
int fuxi_ram_prep_probe(const struct fuxi_ram_prep_state *state, uint64_t pfn);
int fuxi_ram_prep_shadow_release(struct fuxi_ram_prep_state *state, struct fuxi_ram_prep_range range);
int fuxi_ram_prep_get_counts(const struct fuxi_ram_prep_state *state, struct fuxi_ram_prep_counts *counts);

#endif
