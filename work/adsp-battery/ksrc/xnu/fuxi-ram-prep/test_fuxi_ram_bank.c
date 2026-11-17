#include "fuxi_ram_bank.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#if FUXI_RAM_PREP_ENABLED
#include "trace_fixture.h"
#endif

#define HOST_BASE UINT64_C(0x100000000)
#define CHECK(condition) do { \
    if (!(condition)) { fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); exit(1); } \
    checks++; \
} while (0)

static unsigned checks;
static unsigned cases;

static struct fuxi_ram_prep_manifest fixture_manifest(void)
{
    struct fuxi_ram_prep_manifest manifest;
    memset(&manifest, 0, sizeof(manifest));
    manifest.version = FUXI_RAM_PREP_VERSION;
    manifest.structure_bytes = (uint32_t)sizeof(manifest);
    manifest.page_size = (uint32_t)FUXI_RAM_PREP_PAGE_SIZE;
    manifest.flags = FUXI_RAM_PREP_EXPERIMENTAL;
    manifest.physical_base = HOST_BASE;
    manifest.physical_size = 16 * FUXI_RAM_PREP_PAGE_SIZE;
    manifest.bank_count = 2;
    manifest.banks[0].start = HOST_BASE;
    manifest.banks[0].size = 4 * FUXI_RAM_PREP_PAGE_SIZE;
    manifest.banks[1].start = HOST_BASE + 8 * FUXI_RAM_PREP_PAGE_SIZE;
    manifest.banks[1].size = 4 * FUXI_RAM_PREP_PAGE_SIZE;
    manifest.exclusion_count = 1;
    manifest.exclusions[0].start = HOST_BASE + FUXI_RAM_PREP_PAGE_SIZE;
    manifest.exclusions[0].size = FUXI_RAM_PREP_PAGE_SIZE;
    manifest.owner_count = 1;
    manifest.owner_coverage_complete = 1;
    manifest.owner_manifest_sha256[0] = 1;
    manifest.owners[0].id = 1;
    manifest.owners[0].flags = FUXI_RAM_OWNER_COMPLETE | FUXI_RAM_OWNER_PROVEN_ABSENT;
    manifest.owners[0].evidence_sha256[0] = 1;
    return manifest;
}

static void expect_bad_init(const struct fuxi_ram_prep_manifest *manifest, int expected)
{
    struct fuxi_ram_prep_state *state = calloc(1, sizeof(*state));
    uint8_t ledger[2] = {0};
    CHECK(state != NULL);
    CHECK(fuxi_ram_prep_init_zeroed(state, manifest, ledger, sizeof(ledger)) == expected);
    CHECK(!state->initialized && !ledger[0] && !ledger[1]);
    free(state);
}

static void test_manifest_contract(void)
{
    struct fuxi_ram_prep_manifest manifest = fixture_manifest();
    uint32_t *fields[] = {&manifest.version, &manifest.structure_bytes, &manifest.page_size,
        &manifest.flags, &manifest.bank_count, &manifest.exclusion_count, &manifest.owner_count,
        &manifest.owner_coverage_complete};
    for (size_t index = 0; index < sizeof(fields) / sizeof(fields[0]); index++) {
        uint32_t saved = *fields[index];
        *fields[index] = UINT32_MAX;
        expect_bad_init(&manifest, FUXI_RAM_PREP_BAD_MANIFEST);
        *fields[index] = saved;
    }
    manifest.banks[1] = manifest.banks[0];
    expect_bad_init(&manifest, FUXI_RAM_PREP_BAD_MANIFEST);
    manifest = fixture_manifest();
    manifest.owners[0].range_count = FUXI_RAM_PREP_MAX_OWNER_RANGES + 1;
    expect_bad_init(&manifest, FUXI_RAM_PREP_BAD_MANIFEST);
    manifest = fixture_manifest();
    manifest.owner_count = 2;
    manifest.owners[1] = manifest.owners[0];
    expect_bad_init(&manifest, FUXI_RAM_PREP_BAD_MANIFEST);
    manifest = fixture_manifest();
    manifest.owners[0].flags = FUXI_RAM_OWNER_COMPLETE | FUXI_RAM_OWNER_PLACEMENT_KNOWN;
    manifest.owners[0].range_count = 1;
    manifest.owners[0].ranges[0].start = HOST_BASE;
    expect_bad_init(&manifest, FUXI_RAM_PREP_BAD_RANGE);
    cases++;
}

static void test_range_boundaries(void)
{
    uint64_t end;
    struct fuxi_ram_prep_range range = {HOST_BASE, FUXI_RAM_PREP_PAGE_SIZE};
    CHECK(fuxi_ram_prep_range_end(range, &end) == FUXI_RAM_PREP_OK && end == HOST_BASE + range.size);
    range.size = 0;
    CHECK(fuxi_ram_prep_range_end(range, &end) == FUXI_RAM_PREP_BAD_RANGE);
    range.size = FUXI_RAM_PREP_PAGE_SIZE;
    range.start++;
    CHECK(fuxi_ram_prep_range_end(range, &end) == FUXI_RAM_PREP_BAD_RANGE);
    range.start = HOST_BASE;
    range.size++;
    CHECK(fuxi_ram_prep_range_end(range, &end) == FUXI_RAM_PREP_BAD_RANGE);
    range.start = UINT64_MAX & ~(FUXI_RAM_PREP_PAGE_SIZE - 1);
    range.size = FUXI_RAM_PREP_PAGE_SIZE;
    CHECK(fuxi_ram_prep_range_end(range, &end) == FUXI_RAM_PREP_OVERFLOW);
    range.start = (uint64_t)UINT32_MAX << 14;
    CHECK(fuxi_ram_prep_range_end(range, &end) == FUXI_RAM_PREP_OK);
    range.size *= 2;
    CHECK(fuxi_ram_prep_range_end(range, &end) == FUXI_RAM_PREP_BAD_PFN);
    struct fuxi_ram_prep_manifest manifest = fixture_manifest();
    manifest.physical_base = 0;
    manifest.physical_size = (UINT64_C(1) << 32) * FUXI_RAM_PREP_PAGE_SIZE;
    expect_bad_init(&manifest, FUXI_RAM_PREP_BAD_MANIFEST);
    cases++;
}

static void test_dense_index_and_storage(void)
{
    struct fuxi_ram_prep_manifest manifest = fixture_manifest();
    struct fuxi_ram_prep_state *state = calloc(1, sizeof(*state));
    uint8_t ledger[2] = {0};
    uint32_t index;
    CHECK(state != NULL);
    CHECK(fuxi_ram_prep_dense_index(state, HOST_BASE >> 14, &index) == FUXI_RAM_PREP_UNINITIALIZED);
    CHECK(fuxi_ram_prep_init_zeroed(state, &manifest, NULL, 2) == FUXI_RAM_PREP_LEDGER_CAPACITY);
    CHECK(fuxi_ram_prep_init_zeroed(state, &manifest, ledger, 1) == FUXI_RAM_PREP_LEDGER_CAPACITY);
    ledger[1] = 128;
    CHECK(fuxi_ram_prep_init_zeroed(state, &manifest, ledger, 2) == FUXI_RAM_PREP_DIRTY_LEDGER);
    ledger[1] = 0;
    CHECK(fuxi_ram_prep_init_zeroed(state, &manifest, ledger, 2) == FUXI_RAM_PREP_OK);
    CHECK(fuxi_ram_prep_dense_index(state, HOST_BASE >> 14, &index) == FUXI_RAM_PREP_OK && index == 0);
    CHECK(fuxi_ram_prep_dense_index(state, (HOST_BASE >> 14) + 4, &index) == FUXI_RAM_PREP_OK && index == 4);
    CHECK(fuxi_ram_prep_probe(state, (HOST_BASE >> 14) + 4) == FUXI_RAM_PREP_NOT_WHITELISTED);
    CHECK(fuxi_ram_prep_dense_index(state, (HOST_BASE >> 14) + 8, &index) == FUXI_RAM_PREP_OK && index == 8);
    CHECK(fuxi_ram_prep_dense_index(state, (HOST_BASE >> 14) + 15, &index) == FUXI_RAM_PREP_OK && index == 15);
    CHECK(fuxi_ram_prep_dense_index(state, (HOST_BASE >> 14) + 16, &index) == FUXI_RAM_PREP_OUTSIDE_SPAN);
    CHECK(fuxi_ram_prep_dense_index(state, UINT64_C(1) << 32, &index) == FUXI_RAM_PREP_BAD_PFN);
    CHECK(fuxi_ram_prep_probe(state, FUXI_RAM_PREP_GPU_BASE >> 14) == FUXI_RAM_PREP_GPU);
    CHECK(fuxi_ram_prep_init_zeroed(state, &manifest, ledger, 2) == FUXI_RAM_PREP_ALREADY_INITIALIZED);
    free(state);
    cases++;
}

static void test_default_disable(void)
{
    struct fuxi_ram_prep_manifest manifest = fixture_manifest();
    struct fuxi_ram_prep_state *state = calloc(1, sizeof(*state));
    struct fuxi_ram_prep_counts counts;
    uint8_t ledger[2] = {0};
    CHECK(state != NULL);
    manifest.flags = 0;
    CHECK(fuxi_ram_prep_init_zeroed(state, &manifest, ledger, 2) == FUXI_RAM_PREP_OK);
    CHECK(fuxi_ram_prep_probe(state, HOST_BASE >> 14) == FUXI_RAM_PREP_DISABLED);
    struct fuxi_ram_prep_range range = {HOST_BASE, FUXI_RAM_PREP_PAGE_SIZE};
    CHECK(fuxi_ram_prep_shadow_release(state, range) == FUXI_RAM_PREP_DISABLED);
    CHECK(fuxi_ram_prep_get_counts(state, &counts) == FUXI_RAM_PREP_OK);
    CHECK(!counts.host_admissible_known && !counts.shadow_released_pages && !ledger[0] && !ledger[1]);
    free(state);
    state = calloc(1, sizeof(*state));
    CHECK(state != NULL);
    manifest.flags = FUXI_RAM_PREP_EXPERIMENTAL;
    CHECK(fuxi_ram_prep_init_zeroed(state, &manifest, ledger, 2) == FUXI_RAM_PREP_OK);
    CHECK(fuxi_ram_prep_probe(state, HOST_BASE >> 14) ==
        (FUXI_RAM_PREP_ENABLED ? FUXI_RAM_PREP_OK : FUXI_RAM_PREP_DISABLED));
    if (!FUXI_RAM_PREP_ENABLED)
        CHECK(fuxi_ram_prep_shadow_release(state, range) == FUXI_RAM_PREP_DISABLED && !ledger[0]);
    free(state);
    cases++;
}

static void test_twelve_gib_span(void)
{
    struct fuxi_ram_prep_manifest manifest = fixture_manifest();
    manifest.physical_size = UINT64_C(12) << 30;
    manifest.bank_count = 1;
    manifest.banks[0].size = manifest.physical_size;
    manifest.exclusion_count = 0;
    size_t ledger_bytes = (size_t)(manifest.physical_size / FUXI_RAM_PREP_PAGE_SIZE / 8);
    uint8_t *ledger = calloc(ledger_bytes, 1);
    struct fuxi_ram_prep_state *state = calloc(1, sizeof(*state));
    struct fuxi_ram_prep_counts counts;
    uint32_t index;
    CHECK(state != NULL && ledger != NULL);
    CHECK(fuxi_ram_prep_init_zeroed(state, &manifest, ledger, ledger_bytes) == FUXI_RAM_PREP_OK);
    CHECK(fuxi_ram_prep_get_counts(state, &counts) == FUXI_RAM_PREP_OK);
    CHECK(counts.span_pages == 786432 && counts.geometric_candidate_pages == 786432);
    CHECK(fuxi_ram_prep_dense_index(state, (HOST_BASE + manifest.physical_size) / FUXI_RAM_PREP_PAGE_SIZE - 1,
        &index) == FUXI_RAM_PREP_OK && index == 786431);
    free(state);
    free(ledger);
    cases++;
}

#if FUXI_RAM_PREP_ENABLED
static void expect_pending_owner(const struct fuxi_ram_prep_manifest *manifest)
{
    struct fuxi_ram_prep_state *state = calloc(1, sizeof(*state));
    uint8_t ledger[2] = {0};
    struct fuxi_ram_prep_counts counts;
    struct fuxi_ram_prep_range range = {HOST_BASE + 2 * FUXI_RAM_PREP_PAGE_SIZE, FUXI_RAM_PREP_PAGE_SIZE};
    CHECK(state != NULL);
    CHECK(fuxi_ram_prep_init_zeroed(state, manifest, ledger, 2) == FUXI_RAM_PREP_OK);
    CHECK(fuxi_ram_prep_probe(state, range.start >> 14) == FUXI_RAM_PREP_PENDING_OWNER);
    CHECK(fuxi_ram_prep_shadow_release(state, range) == FUXI_RAM_PREP_PENDING_OWNER);
    CHECK(fuxi_ram_prep_get_counts(state, &counts) == FUXI_RAM_PREP_OK);
    CHECK(!counts.host_admissible_known && !counts.shadow_released_pages && !ledger[0] && !ledger[1]);
    free(state);
}

static void test_owner_evidence(void)
{
    struct fuxi_ram_prep_manifest manifest = fixture_manifest();
    manifest.owner_count = 0;
    expect_pending_owner(&manifest);
    manifest = fixture_manifest();
    manifest.owner_coverage_complete = 0;
    expect_pending_owner(&manifest);
    manifest = fixture_manifest();
    memset(manifest.owner_manifest_sha256, 0, 32);
    expect_pending_owner(&manifest);
    manifest = fixture_manifest();
    memset(manifest.owners[0].evidence_sha256, 0, 32);
    expect_pending_owner(&manifest);
    manifest = fixture_manifest();
    manifest.owners[0].flags = FUXI_RAM_OWNER_PLACEMENT_KNOWN | FUXI_RAM_OWNER_COMPLETE;
    expect_pending_owner(&manifest);
    manifest = fixture_manifest();
    manifest.owners[0].flags = FUXI_RAM_OWNER_PROVEN_ABSENT;
    expect_pending_owner(&manifest);
    cases++;
}

static void test_exclusion_union_and_observed_owner(void)
{
    struct fuxi_ram_prep_manifest manifest = fixture_manifest();
    struct fuxi_ram_prep_state *state = calloc(1, sizeof(*state));
    struct fuxi_ram_prep_counts counts;
    uint8_t ledger[2] = {0};
    CHECK(state != NULL);
    manifest.exclusion_count = 2;
    manifest.exclusions[1] = manifest.exclusions[0];
    manifest.owners[0].flags = FUXI_RAM_OWNER_COMPLETE | FUXI_RAM_OWNER_PLACEMENT_KNOWN;
    manifest.owners[0].range_count = 2;
    manifest.owners[0].ranges[0] = manifest.exclusions[0];
    manifest.owners[0].ranges[1].start = HOST_BASE + 9 * FUXI_RAM_PREP_PAGE_SIZE;
    manifest.owners[0].ranges[1].size = FUXI_RAM_PREP_PAGE_SIZE;
    CHECK(fuxi_ram_prep_init_zeroed(state, &manifest, ledger, 2) == FUXI_RAM_PREP_OK);
    CHECK(fuxi_ram_prep_probe(state, (HOST_BASE >> 14) + 1) == FUXI_RAM_PREP_STATIC);
    CHECK(fuxi_ram_prep_probe(state, (HOST_BASE >> 14) + 9) == FUXI_RAM_PREP_OWNER);
    CHECK(fuxi_ram_prep_get_counts(state, &counts) == FUXI_RAM_PREP_OK);
    CHECK(counts.span_pages == 16 && counts.whitelist_pages == 8 && counts.known_excluded_pages == 2);
    CHECK(counts.geometric_candidate_pages == 6 && counts.host_admissible_known && counts.host_admissible_pages == 6);
    free(state);
    state = calloc(1, sizeof(*state));
    CHECK(state != NULL);
    manifest.owners[0].flags = 0;
    CHECK(fuxi_ram_prep_init_zeroed(state, &manifest, ledger, 2) == FUXI_RAM_PREP_OK);
    CHECK(fuxi_ram_prep_probe(state, (HOST_BASE >> 14) + 9) == FUXI_RAM_PREP_OWNER);
    CHECK(fuxi_ram_prep_probe(state, HOST_BASE >> 14) == FUXI_RAM_PREP_PENDING_OWNER);
    free(state);
    cases++;
}

static void test_shadow_release_once(void)
{
    struct fuxi_ram_prep_manifest manifest = fixture_manifest();
    struct fuxi_ram_prep_state *state = calloc(1, sizeof(*state));
    struct fuxi_ram_prep_counts counts;
    uint8_t ledger[2] = {0};
    CHECK(state != NULL);
    CHECK(fuxi_ram_prep_init_zeroed(state, &manifest, ledger, 2) == FUXI_RAM_PREP_OK);
    struct fuxi_ram_prep_range range = {HOST_BASE + 2 * FUXI_RAM_PREP_PAGE_SIZE, 2 * FUXI_RAM_PREP_PAGE_SIZE};
    CHECK(fuxi_ram_prep_shadow_release(state, range) == FUXI_RAM_PREP_OK);
    CHECK(fuxi_ram_prep_shadow_release(state, range) == FUXI_RAM_PREP_DUPLICATE_RELEASE);
    range.start = HOST_BASE;
    range.size = 4 * FUXI_RAM_PREP_PAGE_SIZE;
    CHECK(fuxi_ram_prep_shadow_release(state, range) == FUXI_RAM_PREP_STATIC && ledger[0] == 12 && !ledger[1]);
    range.size = FUXI_RAM_PREP_PAGE_SIZE;
    CHECK(fuxi_ram_prep_shadow_release(state, range) == FUXI_RAM_PREP_OK);
    range.start = HOST_BASE + 8 * FUXI_RAM_PREP_PAGE_SIZE;
    range.size = 5 * FUXI_RAM_PREP_PAGE_SIZE;
    CHECK(fuxi_ram_prep_shadow_release(state, range) == FUXI_RAM_PREP_NOT_WHITELISTED && !ledger[1]);
    range.start = HOST_BASE + 10 * FUXI_RAM_PREP_PAGE_SIZE;
    range.size = FUXI_RAM_PREP_PAGE_SIZE;
    CHECK(fuxi_ram_prep_shadow_release(state, range) == FUXI_RAM_PREP_OK);
    range.start = HOST_BASE + 8 * FUXI_RAM_PREP_PAGE_SIZE;
    range.size = 4 * FUXI_RAM_PREP_PAGE_SIZE;
    CHECK(fuxi_ram_prep_shadow_release(state, range) == FUXI_RAM_PREP_DUPLICATE_RELEASE && ledger[1] == 4);
    range.size = 2 * FUXI_RAM_PREP_PAGE_SIZE;
    CHECK(fuxi_ram_prep_shadow_release(state, range) == FUXI_RAM_PREP_OK);
    range.start = HOST_BASE + 11 * FUXI_RAM_PREP_PAGE_SIZE;
    range.size = FUXI_RAM_PREP_PAGE_SIZE;
    CHECK(fuxi_ram_prep_shadow_release(state, range) == FUXI_RAM_PREP_OK);
    CHECK(fuxi_ram_prep_get_counts(state, &counts) == FUXI_RAM_PREP_OK);
    CHECK(counts.geometric_candidate_pages == 7 && counts.shadow_released_pages == 7 && !counts.remaining_geometric_pages);
    CHECK(counts.known_excluded_pages + counts.geometric_candidate_pages == counts.whitelist_pages);
    CHECK(fuxi_ram_prep_init_zeroed(state, &manifest, ledger, 2) == FUXI_RAM_PREP_ALREADY_INITIALIZED);
    struct fuxi_ram_prep_state *fresh = calloc(1, sizeof(*fresh));
    CHECK(fresh != NULL);
    CHECK(fuxi_ram_prep_init_zeroed(fresh, &manifest, ledger, 2) == FUXI_RAM_PREP_DIRTY_LEDGER);
    state->counts.shadow_released_pages++;
    CHECK(fuxi_ram_prep_get_counts(state, &counts) == FUXI_RAM_PREP_CORRUPT_COUNTERS);
    CHECK(fuxi_ram_prep_shadow_release(state, range) == FUXI_RAM_PREP_CORRUPT_COUNTERS);
    free(fresh);
    free(state);
    cases++;
}

static void test_gpu_whitelist_conflict(void)
{
    struct fuxi_ram_prep_manifest manifest = fixture_manifest();
    manifest.physical_base = FUXI_RAM_PREP_GPU_BASE - FUXI_RAM_PREP_PAGE_SIZE;
    manifest.physical_size = FUXI_RAM_PREP_GPU_END - manifest.physical_base + FUXI_RAM_PREP_PAGE_SIZE;
    manifest.bank_count = 1;
    manifest.banks[0].start = manifest.physical_base;
    manifest.banks[0].size = manifest.physical_size;
    manifest.exclusion_count = 0;
    size_t ledger_bytes = (size_t)((manifest.physical_size / FUXI_RAM_PREP_PAGE_SIZE + 7) / 8);
    uint8_t *ledger = calloc(ledger_bytes, 1);
    struct fuxi_ram_prep_state *state = calloc(1, sizeof(*state));
    struct fuxi_ram_prep_counts counts;
    CHECK(state != NULL && ledger != NULL);
    CHECK(fuxi_ram_prep_init_zeroed(state, &manifest, ledger, ledger_bytes) == FUXI_RAM_PREP_OK);
    CHECK(fuxi_ram_prep_get_counts(state, &counts) == FUXI_RAM_PREP_OK);
    CHECK(counts.span_pages == 2050 && counts.known_excluded_pages == 2048 && counts.geometric_candidate_pages == 2);
    CHECK(fuxi_ram_prep_probe(state, FUXI_RAM_PREP_GPU_BASE >> 14) == FUXI_RAM_PREP_GPU);
    CHECK(fuxi_ram_prep_probe(state, (FUXI_RAM_PREP_GPU_END >> 14) - 1) == FUXI_RAM_PREP_GPU);
    CHECK(fuxi_ram_prep_shadow_release(state, manifest.banks[0]) == FUXI_RAM_PREP_GPU && !ledger[0]);
    struct fuxi_ram_prep_range range = {manifest.physical_base, FUXI_RAM_PREP_PAGE_SIZE};
    CHECK(fuxi_ram_prep_shadow_release(state, range) == FUXI_RAM_PREP_OK);
    range.start = FUXI_RAM_PREP_GPU_END;
    CHECK(fuxi_ram_prep_shadow_release(state, range) == FUXI_RAM_PREP_OK);
    CHECK(fuxi_ram_prep_get_counts(state, &counts) == FUXI_RAM_PREP_OK);
    CHECK(counts.shadow_released_pages == 2 && !counts.remaining_geometric_pages);
    free(state);
    free(ledger);
    cases++;
}

static void test_actual_trace(void)
{
    struct fuxi_ram_prep_manifest manifest;
    load_actual_manifest(&manifest);
    size_t ledger_bytes = (size_t)((manifest.physical_size / FUXI_RAM_PREP_PAGE_SIZE + 7) / 8);
    uint8_t *ledger = calloc(ledger_bytes, 1);
    struct fuxi_ram_prep_state *state = calloc(1, sizeof(*state));
    struct fuxi_ram_prep_counts counts;
    uint64_t audited = 0, dense = 0, deferred = 0, rejected = 0;
    CHECK(state != NULL && ledger != NULL);
    CHECK(fuxi_ram_prep_init_zeroed(state, &manifest, ledger, ledger_bytes) == FUXI_RAM_PREP_OK);
    for (size_t run_index = 0; run_index < sizeof(actual_runs) / sizeof(actual_runs[0]); run_index++) {
        const struct actual_trace_run *run = &actual_runs[run_index];
        for (uint64_t page = 0; page < run->pages; page++) {
            uint64_t pfn = run->first_pfn + page;
            uint32_t index;
            int result = fuxi_ram_prep_probe(state, pfn);
            if (run->defer) {
                CHECK(result == FUXI_RAM_PREP_PENDING_OWNER);
                deferred++;
            } else {
                CHECK(result != FUXI_RAM_PREP_OK && result != FUXI_RAM_PREP_PENDING_OWNER && result != FUXI_RAM_PREP_DISABLED);
                rejected++;
            }
            if (fuxi_ram_prep_dense_index(state, pfn, &index) == FUXI_RAM_PREP_OK) {
                CHECK(index == pfn - (manifest.physical_base >> 14));
                dense++;
            }
            audited++;
        }
    }
    CHECK(audited == ACTUAL_AUDITED && dense == ACTUAL_DENSE && deferred == ACTUAL_DEFERRED && rejected == ACTUAL_REJECTED);
    CHECK(fuxi_ram_prep_shadow_release(state, manifest.banks[0]) == FUXI_RAM_PREP_PENDING_OWNER);
    CHECK(fuxi_ram_prep_get_counts(state, &counts) == FUXI_RAM_PREP_OK);
    CHECK(!counts.host_admissible_known && !counts.shadow_released_pages && counts.geometric_candidate_pages == deferred);
    CHECK(counts.geometric_candidate_pages == counts.remaining_geometric_pages + counts.shadow_released_pages);
    printf("{\"mode\":\"actual-trace\",\"audited_pfns\":%llu,\"dense_indices\":%llu,\"deferred_pfns\":%llu,"
        "\"rejected_pfns\":%llu,\"owners\":%u,\"shadow_released_pages\":0,\"allocatable_bytes\":null}\n",
        (unsigned long long)audited, (unsigned long long)dense, (unsigned long long)deferred,
        (unsigned long long)rejected, manifest.owner_count);
    free(state);
    free(ledger);
}
#endif

int main(int argument_count, char **arguments)
{
    if (argument_count == 2 && !strcmp(arguments[1], "asan-canary")) {
        volatile uint8_t *canary = malloc(1);
        CHECK(canary != NULL);
        canary[1] = 1;
        free((void *)canary);
        return 0;
    }
#if FUXI_RAM_PREP_ENABLED
    if (argument_count == 2 && !strcmp(arguments[1], "actual-trace")) {
        test_actual_trace();
        return 0;
    }
#endif
    CHECK(argument_count == 1);
    test_manifest_contract();
    test_range_boundaries();
    test_dense_index_and_storage();
    test_default_disable();
    test_twelve_gib_span();
#if FUXI_RAM_PREP_ENABLED
    test_owner_evidence();
    test_exclusion_union_and_observed_owner();
    test_shadow_release_once();
    test_gpu_whitelist_conflict();
#endif
    printf("{\"mode\":\"self-tests\",\"compiled_enabled\":%d,\"cases\":%u,\"checks\":%u}\n",
        FUXI_RAM_PREP_ENABLED, cases, checks);
    return 0;
}
