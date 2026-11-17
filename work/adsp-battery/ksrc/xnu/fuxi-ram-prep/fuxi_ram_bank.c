#include "fuxi_ram_bank.h"
#include <string.h>

#define FUXI_RAM_PREP_INITIALIZED UINT32_C(0x46525031)

int fuxi_ram_prep_range_end(struct fuxi_ram_prep_range range, uint64_t *end)
{
    if (!end || !range.size || ((range.start | range.size) & (FUXI_RAM_PREP_PAGE_SIZE - 1)))
        return FUXI_RAM_PREP_BAD_RANGE;
    if (range.size > UINT64_MAX - range.start)
        return FUXI_RAM_PREP_OVERFLOW;
    *end = range.start + range.size;
    if (((*end - 1) >> 14) > UINT32_MAX)
        return FUXI_RAM_PREP_BAD_PFN;
    return FUXI_RAM_PREP_OK;
}

static int has_evidence(const uint8_t evidence[32])
{
    for (size_t index = 0; index < 32; index++)
        if (evidence[index]) return 1;
    return 0;
}

static int contains_page(struct fuxi_ram_prep_range range, uint64_t physical)
{
    return physical >= range.start && physical - range.start < range.size;
}

static int geometry_result(const struct fuxi_ram_prep_manifest *manifest, uint64_t physical)
{
    int whitelisted = 0;
    if (physical >= FUXI_RAM_PREP_GPU_BASE && physical < FUXI_RAM_PREP_GPU_END)
        return FUXI_RAM_PREP_GPU;
    for (uint32_t index = 0; index < manifest->bank_count; index++)
        if (contains_page(manifest->banks[index], physical)) whitelisted = 1;
    if (!whitelisted) return FUXI_RAM_PREP_NOT_WHITELISTED;
    for (uint32_t index = 0; index < manifest->exclusion_count; index++)
        if (contains_page(manifest->exclusions[index], physical)) return FUXI_RAM_PREP_STATIC;
    for (uint32_t owner_index = 0; owner_index < manifest->owner_count; owner_index++) {
        const struct fuxi_ram_prep_owner *owner = &manifest->owners[owner_index];
        for (uint32_t range_index = 0; range_index < owner->range_count; range_index++)
            if (contains_page(owner->ranges[range_index], physical)) return FUXI_RAM_PREP_OWNER;
    }
    return FUXI_RAM_PREP_OK;
}

static int validate_manifest(const struct fuxi_ram_prep_manifest *manifest, uint64_t *span_end,
    int *owners_complete)
{
    if (!manifest || manifest->version != FUXI_RAM_PREP_VERSION ||
        manifest->structure_bytes != sizeof(*manifest) ||
        manifest->page_size != FUXI_RAM_PREP_PAGE_SIZE ||
        (manifest->flags & ~FUXI_RAM_PREP_EXPERIMENTAL) ||
        manifest->bank_count > FUXI_RAM_PREP_MAX_BANKS ||
        manifest->exclusion_count > FUXI_RAM_PREP_MAX_EXCLUSIONS ||
        manifest->owner_count > FUXI_RAM_PREP_MAX_OWNERS || manifest->owner_coverage_complete > 1)
        return FUXI_RAM_PREP_BAD_MANIFEST;
    struct fuxi_ram_prep_range span = {manifest->physical_base, manifest->physical_size};
    int result = fuxi_ram_prep_range_end(span, span_end);
    if (result != FUXI_RAM_PREP_OK) return result;
    if (manifest->physical_size / FUXI_RAM_PREP_PAGE_SIZE > UINT32_MAX)
        return FUXI_RAM_PREP_BAD_MANIFEST;
    uint64_t previous_end = manifest->physical_base;
    for (uint32_t index = 0; index < manifest->bank_count; index++) {
        uint64_t end;
        result = fuxi_ram_prep_range_end(manifest->banks[index], &end);
        if (result != FUXI_RAM_PREP_OK) return result;
        if (manifest->banks[index].start < previous_end || end > *span_end)
            return FUXI_RAM_PREP_BAD_MANIFEST;
        previous_end = end;
    }
    for (uint32_t index = 0; index < manifest->exclusion_count; index++) {
        uint64_t end;
        result = fuxi_ram_prep_range_end(manifest->exclusions[index], &end);
        if (result != FUXI_RAM_PREP_OK) return result;
    }
    *owners_complete = manifest->owner_coverage_complete && manifest->owner_count &&
        has_evidence(manifest->owner_manifest_sha256);
    for (uint32_t index = 0; index < manifest->owner_count; index++) {
        const struct fuxi_ram_prep_owner *owner = &manifest->owners[index];
        if (!owner->id || owner->reserved || owner->range_count > FUXI_RAM_PREP_MAX_OWNER_RANGES ||
            (owner->flags & ~(FUXI_RAM_OWNER_COMPLETE | FUXI_RAM_OWNER_PLACEMENT_KNOWN | FUXI_RAM_OWNER_PROVEN_ABSENT)) ||
            ((owner->flags & FUXI_RAM_OWNER_PROVEN_ABSENT) &&
             (owner->range_count || (owner->flags & FUXI_RAM_OWNER_PLACEMENT_KNOWN))))
            return FUXI_RAM_PREP_BAD_MANIFEST;
        for (uint32_t earlier = 0; earlier < index; earlier++)
            if (manifest->owners[earlier].id == owner->id) return FUXI_RAM_PREP_BAD_MANIFEST;
        for (uint32_t range_index = 0; range_index < owner->range_count; range_index++) {
            uint64_t end;
            result = fuxi_ram_prep_range_end(owner->ranges[range_index], &end);
            if (result != FUXI_RAM_PREP_OK) return result;
        }
        if (!(owner->flags & FUXI_RAM_OWNER_COMPLETE) || !has_evidence(owner->evidence_sha256) ||
            !((owner->flags & FUXI_RAM_OWNER_PROVEN_ABSENT) ||
              ((owner->flags & FUXI_RAM_OWNER_PLACEMENT_KNOWN) && owner->range_count)))
            *owners_complete = 0;
    }
    return FUXI_RAM_PREP_OK;
}

int fuxi_ram_prep_init_zeroed(struct fuxi_ram_prep_state *state,
    const struct fuxi_ram_prep_manifest *manifest, uint8_t *shadow_ledger, size_t ledger_bytes)
{
    if (!state) return FUXI_RAM_PREP_BAD_MANIFEST;
    if (state->initialized) return FUXI_RAM_PREP_ALREADY_INITIALIZED;
    uint64_t span_end;
    int owners_complete;
    int result = validate_manifest(manifest, &span_end, &owners_complete);
    if (result != FUXI_RAM_PREP_OK) return result;
    uint64_t span_pages = manifest->physical_size / FUXI_RAM_PREP_PAGE_SIZE;
    uint64_t needed = (span_pages + 7) / 8;
    if (!shadow_ledger || needed > ledger_bytes) return FUXI_RAM_PREP_LEDGER_CAPACITY;
    for (size_t index = 0; index < (size_t)needed; index++)
        if (shadow_ledger[index]) return FUXI_RAM_PREP_DIRTY_LEDGER;
    struct fuxi_ram_prep_counts counts = {0};
    counts.span_pages = span_pages;
    for (uint32_t bank_index = 0; bank_index < manifest->bank_count; bank_index++) {
        struct fuxi_ram_prep_range bank = manifest->banks[bank_index];
        counts.whitelist_pages += bank.size / FUXI_RAM_PREP_PAGE_SIZE;
        for (uint64_t physical = bank.start; physical < bank.start + bank.size; physical += FUXI_RAM_PREP_PAGE_SIZE)
            if (geometry_result(manifest, physical) == FUXI_RAM_PREP_OK) counts.geometric_candidate_pages++;
    }
    counts.known_excluded_pages = counts.whitelist_pages - counts.geometric_candidate_pages;
    state->manifest = *manifest;
    state->span_end = span_end;
    state->owners_complete = (uint32_t)owners_complete;
    state->shadow_ledger = shadow_ledger;
    state->shadow_ledger_bytes = (size_t)needed;
    state->counts = counts;
    state->initialized = FUXI_RAM_PREP_INITIALIZED;
    return FUXI_RAM_PREP_OK;
}

int fuxi_ram_prep_dense_index(const struct fuxi_ram_prep_state *state, uint64_t pfn, uint32_t *index)
{
    if (!state || state->initialized != FUXI_RAM_PREP_INITIALIZED) return FUXI_RAM_PREP_UNINITIALIZED;
    if (!index) return FUXI_RAM_PREP_BAD_MANIFEST;
    if (pfn > UINT32_MAX) return FUXI_RAM_PREP_BAD_PFN;
    uint64_t physical = pfn << 14;
    if (physical < state->manifest.physical_base || physical >= state->span_end)
        return FUXI_RAM_PREP_OUTSIDE_SPAN;
    *index = (uint32_t)((physical - state->manifest.physical_base) / FUXI_RAM_PREP_PAGE_SIZE);
    return FUXI_RAM_PREP_OK;
}

int fuxi_ram_prep_probe(const struct fuxi_ram_prep_state *state, uint64_t pfn)
{
    uint32_t index;
    if (!state || state->initialized != FUXI_RAM_PREP_INITIALIZED) return FUXI_RAM_PREP_UNINITIALIZED;
    if (pfn > UINT32_MAX) return FUXI_RAM_PREP_BAD_PFN;
    uint64_t physical = pfn << 14;
    if (physical >= FUXI_RAM_PREP_GPU_BASE && physical < FUXI_RAM_PREP_GPU_END)
        return FUXI_RAM_PREP_GPU;
    int result = fuxi_ram_prep_dense_index(state, pfn, &index);
    if (result != FUXI_RAM_PREP_OK) return result;
    result = geometry_result(&state->manifest, physical);
    if (result != FUXI_RAM_PREP_OK) return result;
    if (!FUXI_RAM_PREP_ENABLED || !(state->manifest.flags & FUXI_RAM_PREP_EXPERIMENTAL))
        return FUXI_RAM_PREP_DISABLED;
    if (!state->owners_complete) return FUXI_RAM_PREP_PENDING_OWNER;
    return FUXI_RAM_PREP_OK;
}

int fuxi_ram_prep_get_counts(const struct fuxi_ram_prep_state *state, struct fuxi_ram_prep_counts *counts)
{
    if (!state || state->initialized != FUXI_RAM_PREP_INITIALIZED) return FUXI_RAM_PREP_UNINITIALIZED;
    if (!counts) return FUXI_RAM_PREP_BAD_MANIFEST;
    if (state->counts.whitelist_pages > state->counts.span_pages ||
        state->counts.geometric_candidate_pages > state->counts.whitelist_pages ||
        state->counts.known_excluded_pages != state->counts.whitelist_pages - state->counts.geometric_candidate_pages ||
        state->counts.shadow_released_pages > state->counts.geometric_candidate_pages)
        return FUXI_RAM_PREP_CORRUPT_COUNTERS;
    *counts = state->counts;
    counts->remaining_geometric_pages = counts->geometric_candidate_pages - counts->shadow_released_pages;
    counts->host_admissible_known = FUXI_RAM_PREP_ENABLED && state->owners_complete &&
        (state->manifest.flags & FUXI_RAM_PREP_EXPERIMENTAL);
    counts->host_admissible_pages = counts->host_admissible_known ? counts->geometric_candidate_pages : 0;
    return FUXI_RAM_PREP_OK;
}

int fuxi_ram_prep_shadow_release(struct fuxi_ram_prep_state *state, struct fuxi_ram_prep_range range)
{
    uint64_t end;
    int result = fuxi_ram_prep_range_end(range, &end);
    if (result != FUXI_RAM_PREP_OK) return result;
    struct fuxi_ram_prep_counts counts;
    result = fuxi_ram_prep_get_counts(state, &counts);
    if (result != FUXI_RAM_PREP_OK) return result;
    for (uint64_t physical = range.start; physical < end; physical += FUXI_RAM_PREP_PAGE_SIZE) {
        uint32_t index;
        result = fuxi_ram_prep_probe(state, physical >> 14);
        if (result != FUXI_RAM_PREP_OK) return result;
        result = fuxi_ram_prep_dense_index(state, physical >> 14, &index);
        if (result != FUXI_RAM_PREP_OK) return result;
        if (index / 8 >= state->shadow_ledger_bytes) return FUXI_RAM_PREP_LEDGER_CAPACITY;
        if (state->shadow_ledger[index / 8] & (1u << (index % 8)))
            return FUXI_RAM_PREP_DUPLICATE_RELEASE;
    }
    uint64_t pages = range.size / FUXI_RAM_PREP_PAGE_SIZE;
    if (pages > counts.remaining_geometric_pages) return FUXI_RAM_PREP_CORRUPT_COUNTERS;
    for (uint64_t physical = range.start; physical < end; physical += FUXI_RAM_PREP_PAGE_SIZE) {
        uint32_t index = (uint32_t)((physical - state->manifest.physical_base) / FUXI_RAM_PREP_PAGE_SIZE);
        state->shadow_ledger[index / 8] |= (uint8_t)(1u << (index % 8));
    }
    state->counts.shadow_released_pages += pages;
    return FUXI_RAM_PREP_OK;
}
