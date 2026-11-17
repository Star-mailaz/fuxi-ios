#include "fuxi_haptic_fifo.h"

#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned checks;

static const uint16_t expected_read_addresses[] = {
    0xf000, 0xf001, 0xf002, 0xf003, 0xf004, 0xf005, 0xf00b, 0xf00c,
    0xf046, 0xf048, 0xf049, 0xf04a, 0xf04b, 0xf04c, 0xf04d, 0xf04e,
    0xf050, 0xf051, 0xf05c, 0xf05d, 0xf063, 0xf068, 0xf070, 0xf071, 0xf072,
    0xf100, 0xf101, 0xf102, 0xf103, 0xf104, 0xf105, 0xf108, 0xf109,
    0xf124, 0xf12a, 0xf12d, 0xf130, 0xf131, 0xf1a0,
    0xf200, 0xf201, 0xf202, 0xf203, 0xf204, 0xf205, 0xf20b, 0xf241, 0xf246,
    0xf009, 0xf00a
};

#define CHECK(condition) do { \
    checks++; \
    if (!(condition)) { \
        fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); \
        exit(1); \
    } \
} while (0)

typedef struct {
    uint8_t raw[3][256];
    unsigned owners[3];
    unsigned reads, owner_reads, writes;
    unsigned fail_read, corrupt_read, fail_owner, change_owner, drop_owner;
    unsigned mutate_after, short_write, drop_write, fail_write;
    uint16_t mutate_address, drop_read_address;
    FuxiHapticFifoState *corrupt_plan;
} Model;

static unsigned peripheral_for(uint16_t address)
{
    CHECK(address >= 0xf000 && address <= 0xf2ff);
    return (address - 0xf000u) / 256u;
}

static int model_owner(void *context, uint16_t base, unsigned *owner)
{
    Model *model = context;
    unsigned peripheral = peripheral_for(base);
    CHECK((base & 0xffu) == 0);
    model->owner_reads++;
    if (model->owner_reads == model->fail_owner) return -1;
    if (model->owner_reads == model->drop_owner) return 0;
    *owner = model->owners[peripheral];
    if (model->owner_reads == model->change_owner) *owner ^= 1u;
    return 0;
}

static int model_read(void *context, uint16_t address, uint8_t *value)
{
    Model *model = context;
    unsigned peripheral = peripheral_for(address);
    CHECK(fuxi_haptic_fifo_read_allowed(address));
    model->reads++;
    if (model->reads == model->fail_read) return -1;
    if (address == model->drop_read_address) return 0;
    if (model->reads == model->mutate_after)
        model->raw[peripheral_for(model->mutate_address)][model->mutate_address & 0xffu] ^= 1;
    if (model->corrupt_plan && model->reads == 5)
        model->corrupt_plan->plan.chunks[0].bytes[0] ^= 1;
    *value = model->raw[peripheral][address & 0xffu];
    if (model->reads == model->corrupt_read) *value ^= 1;
    return 0;
}

static int model_write(void *context, uint16_t address, const uint8_t *bytes,
    unsigned length, unsigned *transferred)
{
    Model *model = context;
    (void)address;
    (void)bytes;
    model->writes++;
    *transferred = model->short_write ? length - 1u : length;
    if (model->drop_write) *transferred = length;
    return model->fail_write ? -1 : 0;
}

static void fixture(Model *model)
{
    memset(model, 0, sizeof(*model));
    model->owners[2] = 3;
    model->raw[0][0x01] = 4;
    model->raw[0][0x04] = 0x15;
    model->raw[0][0x05] = 0x0a;
    model->raw[0][0x46] = 0x80;
    model->raw[0][0x48] = 0x1c;
    model->raw[0][0x49] = 1;
    model->raw[0][0x4a] = 0x84;
    model->raw[0][0x4b] = 4;
    model->raw[0][0x4c] = 1;
    model->raw[0][0x4d] = 0xc8;
    model->raw[0][0x4e] = 0xe0;
    model->raw[0][0x50] = 0x41;
    model->raw[0][0x5c] = 4;
    model->raw[0][0x5d] = 0x76;
    model->raw[0][0x63] = 0x89;
    model->raw[0][0x68] = 0x54;
    model->raw[0][0x72] = 4;
    model->raw[1][0x01] = 4;
    model->raw[1][0x04] = 0x15;
    model->raw[1][0x05] = 0x0b;
    model->raw[1][0x08] = 1;
    model->raw[1][0x09] = 8;
    model->raw[1][0xa0] = 0x84;
    model->raw[2][0x00] = 2;
    model->raw[2][0x04] = 0x31;
    model->raw[2][0x05] = 1;
    model->raw[2][0x41] = 0xe0;
}

static FuxiHapticFifoRequest request_for(const uint8_t *codes, unsigned count)
{
    FuxiHapticFifoRequest request;
    memset(&request, 0, sizeof(request));
    request.sample_codes = codes;
    request.sample_count = count;
    request.vmax_mv = 1200;
    request.tlra_code = FUXI_HAPTIC_FIFO_PROFILE_TLRA_CODE;
    return request;
}

static int prepare(Model *model, const FuxiHapticFifoRequest *request, FuxiHapticFifoState *state)
{
    uint8_t before[3][256];
    FuxiHapticFifoIo io = {model, model_owner, model_read, model_write};
    int result;
    memcpy(before, model->raw, sizeof(before));
    result = fuxi_haptic_fifo_prepare(&io, request, state);
    CHECK(model->writes == 0);
    CHECK(model->reads <= FUXI_HAPTIC_FIFO_MAX_READS);
    CHECK(model->owner_reads <= FUXI_HAPTIC_FIFO_MAX_OWNER_READS);
    CHECK(!memcmp(before[2], model->raw[2], sizeof(before[2])));
    if (!model->mutate_after) CHECK(!memcmp(before, model->raw, sizeof(before)));
    CHECK(!fuxi_haptic_fifo_independent_cutoff_verified());
    return result;
}

static void check_locked(Model *model, const FuxiHapticFifoRequest *request, FuxiHapticFifoState *state)
{
    unsigned reads = model->reads, owners = model->owner_reads;
    CHECK(prepare(model, request, state) == FuxiHapticFifoLocked);
    CHECK(model->reads == reads && model->owner_reads == owners);
    fuxi_haptic_fifo_cleanup(state);
    fuxi_haptic_fifo_cleanup(state);
    CHECK(state->plan.sample_count == 0 && state->plan.chunk_count == 0);
    CHECK(prepare(model, request, state) == FuxiHapticFifoLocked);
    CHECK(model->reads == reads && model->owner_reads == owners);
}

static void test_encoding_and_journal(void)
{
    uint8_t codes[32], unpacked[32];
    FuxiHapticFifoPlan plan, corrupted;
    FuxiHapticFifoJournal journal;
    unsigned count, index, chunk_index, byte_index, cursor, transferred;
    for (count = 5; count <= 32; count++) {
        for (index = 0; index < 32; index++) codes[index] = (uint8_t)(index % 33u);
        for (index = count - 4; index < count; index++) codes[index] = 0;
        CHECK(fuxi_haptic_fifo_encode(codes, count, 1200, 1142, &plan) == 0);
        CHECK(fuxi_haptic_fifo_validate_plan(&plan) == 0);
        CHECK(plan.chunk_count == count / 4u + count % 4u);
        CHECK(plan.nominal_data_us == count * 5710u);
        cursor = 0;
        memset(&journal, 0, sizeof(journal));
        for (chunk_index = 0; chunk_index < plan.chunk_count; chunk_index++) {
            const FuxiHapticFifoChunk *chunk = &plan.chunks[chunk_index];
            CHECK(chunk->address == (chunk_index < count / 4u ? 0xf120 : 0xf12c));
            CHECK(chunk->length == (chunk_index < count / 4u ? 4u : 1u));
            for (byte_index = 0; byte_index < chunk->length; byte_index++)
                unpacked[cursor++] = chunk->bytes[byte_index];
            CHECK(fuxi_haptic_fifo_record_transfer(&plan, &journal, chunk_index, 0, chunk->length) == 0);
        }
        CHECK(cursor == count && !memcmp(unpacked, codes, count));
        CHECK(journal.complete && journal.acknowledged_bytes == count);
        CHECK(fuxi_haptic_fifo_record_transfer(&plan, &journal, 0, 0, 4) == FuxiHapticFifoLocked);
        for (chunk_index = 0; chunk_index < plan.chunk_count; chunk_index++) {
            for (transferred = 0; transferred <= plan.chunks[chunk_index].length + 1u; transferred++) {
                if (transferred == plan.chunks[chunk_index].length) continue;
                memset(&journal, 0, sizeof(journal));
                for (index = 0; index < chunk_index; index++)
                    CHECK(fuxi_haptic_fifo_record_transfer(&plan, &journal, index, 0, plan.chunks[index].length) == 0);
                cursor = journal.acknowledged_bytes;
                CHECK(fuxi_haptic_fifo_record_transfer(&plan, &journal, chunk_index, 0, transferred) == FuxiHapticFifoPartialWrite);
                CHECK(journal.failed && journal.acknowledged_bytes == cursor);
                CHECK(fuxi_haptic_fifo_record_transfer(&plan, &journal, chunk_index, 0, plan.chunks[chunk_index].length) == FuxiHapticFifoLocked);
            }
            memset(&journal, 0, sizeof(journal));
            for (index = 0; index < chunk_index; index++)
                CHECK(fuxi_haptic_fifo_record_transfer(&plan, &journal, index, 0, plan.chunks[index].length) == 0);
            CHECK(fuxi_haptic_fifo_record_transfer(&plan, &journal, chunk_index, -1, plan.chunks[chunk_index].length) == FuxiHapticFifoPartialWrite);
        }
        for (chunk_index = 0; chunk_index < FUXI_HAPTIC_FIFO_MAX_CHUNKS; chunk_index++) {
            corrupted = plan;
            corrupted.chunks[chunk_index].address ^= 1;
            CHECK(fuxi_haptic_fifo_validate_plan(&corrupted) == FuxiHapticFifoCorrupt);
            corrupted = plan;
            corrupted.chunks[chunk_index].length = UINT_MAX;
            CHECK(fuxi_haptic_fifo_validate_plan(&corrupted) == FuxiHapticFifoCorrupt);
            for (byte_index = 0; byte_index < 4; byte_index++) {
                corrupted = plan;
                corrupted.chunks[chunk_index].bytes[byte_index] ^= 1;
                CHECK(fuxi_haptic_fifo_validate_plan(&corrupted) == FuxiHapticFifoCorrupt);
            }
        }
        for (index = 0; index < 32; index++) {
            corrupted = plan;
            corrupted.sample_codes[index] ^= 1;
            CHECK(fuxi_haptic_fifo_validate_plan(&corrupted) == FuxiHapticFifoCorrupt);
        }
    }
    corrupted = plan;
    corrupted.sample_count = UINT_MAX;
    CHECK(fuxi_haptic_fifo_validate_plan(&corrupted) == FuxiHapticFifoCorrupt);
    corrupted = plan;
    corrupted.chunk_count = UINT_MAX;
    CHECK(fuxi_haptic_fifo_validate_plan(&corrupted) == FuxiHapticFifoCorrupt);
    corrupted = plan;
    corrupted.nominal_data_us++;
    CHECK(fuxi_haptic_fifo_validate_plan(&corrupted) == FuxiHapticFifoCorrupt);
    memset(&journal, 0, sizeof(journal));
    CHECK(fuxi_haptic_fifo_record_transfer(&plan, &journal, 1, 0, 4) == FuxiHapticFifoBounds);
    memset(&journal, 0, sizeof(journal));
    journal.acknowledged_bytes = UINT_MAX;
    CHECK(fuxi_haptic_fifo_record_transfer(&plan, &journal, 0, 0, 4) == FuxiHapticFifoCorrupt);
    memset(&journal, 0, sizeof(journal));
    CHECK(fuxi_haptic_fifo_record_transfer(&corrupted, &journal, 0, 0, 4) == FuxiHapticFifoCorrupt);
    CHECK(journal.failed);
}

static void test_bounds(void)
{
    uint8_t codes[32] = {0x20, 0x20, 0x20, 0x20};
    FuxiHapticFifoPlan plan, before;
    static const unsigned counts[] = {0, 1, 4, 33, UINT_MAX};
    static const unsigned voltages[] = {0, 1, 49, 51, 1201, UINT_MAX};
    unsigned index, code;
    memset(&plan, 0xa5, sizeof(plan));
    before = plan;
    for (index = 0; index < sizeof(counts) / sizeof(counts[0]); index++) {
        CHECK(fuxi_haptic_fifo_encode(codes, counts[index], 1200, 1142, &plan) == FuxiHapticFifoBounds);
        CHECK(!memcmp(&plan, &before, sizeof(plan)));
    }
    for (index = 0; index < sizeof(voltages) / sizeof(voltages[0]); index++)
        CHECK(fuxi_haptic_fifo_encode(codes, 8, voltages[index], 1142, &plan) == FuxiHapticFifoBounds);
    CHECK(fuxi_haptic_fifo_encode(codes, 8, 1200, 0, &plan) == FuxiHapticFifoBounds);
    CHECK(fuxi_haptic_fifo_encode(codes, 8, 1200, 4096, &plan) == FuxiHapticFifoBounds);
    for (code = 33; code < 256; code++) {
        codes[0] = (uint8_t)code;
        CHECK(fuxi_haptic_fifo_encode(codes, 8, 1200, 1142, &plan) == FuxiHapticFifoBounds);
    }
    codes[0] = 32;
    codes[7] = 1;
    CHECK(fuxi_haptic_fifo_encode(codes, 8, 1200, 1142, &plan) == FuxiHapticFifoInvalid);
    codes[7] = 0;
    CHECK(fuxi_haptic_fifo_encode(codes, 8, 50, 1, &plan) == 0 && plan.nominal_data_us == 40);
    CHECK(fuxi_haptic_fifo_encode(codes, 32, 1200, 4095, &plan) == 0 && plan.nominal_data_us == 655200);
    CHECK(fuxi_haptic_fifo_encode(NULL, 8, 1200, 1142, &plan) == FuxiHapticFifoInvalid);
    CHECK(fuxi_haptic_fifo_encode(codes, 8, 1200, 1142, NULL) == FuxiHapticFifoInvalid);
    CHECK(fuxi_haptic_fifo_validate_plan(NULL) == FuxiHapticFifoInvalid);
}

static void test_status(void)
{
    unsigned fill = UINT_MAX, empty = UINT_MAX;
    CHECK(fuxi_haptic_fifo_decode_status(0, 0, 0x40, 0, 640, &fill, &empty) == FuxiHapticFifoProfileFork);
    CHECK(fill == UINT_MAX && empty == UINT_MAX);
    CHECK(fuxi_haptic_fifo_decode_status(5, 0, 0x40, 0, 640, &fill, &empty) == FuxiHapticFifoProfileFork);
    CHECK(fuxi_haptic_fifo_decode_status(5, 0x80, 0x40, 1, 640, &fill, &empty) == FuxiHapticFifoCorrupt);
    CHECK(fuxi_haptic_fifo_decode_status(5, 0x80, 0x60, 0, 640, &fill, &empty) == FuxiHapticFifoCorrupt);
    CHECK(fuxi_haptic_fifo_decode_status(5, 0x80, 0x20, 0, 640, &fill, &empty) == FuxiHapticFifoCorrupt);
    CHECK(fuxi_haptic_fifo_decode_status(5, 0x80, 0x0f, 0xff, 640, &fill, &empty) == FuxiHapticFifoCorrupt);
    CHECK(fuxi_haptic_fifo_decode_status(5, 0x80, 0, 0, 2049, &fill, &empty) == FuxiHapticFifoBounds);
    CHECK(fuxi_haptic_fifo_decode_status(5, 0x80, 0, 0, 0, &fill, &empty) == FuxiHapticFifoBounds);
    CHECK(fuxi_haptic_fifo_decode_status(5, 0x80, 0x22, 0x80, 640, &fill, &empty) == 0 && fill == 640 && !empty);
    CHECK(fuxi_haptic_fifo_decode_status(5, 0x80, 0x40, 0, 640, &fill, &empty) == 0 && !fill && empty);
    CHECK(!fuxi_haptic_fifo_independent_cutoff_verified());
}

static void test_preflight_and_faults(void)
{
    uint8_t codes[8] = {0x20, 0x20, 0x20, 0x20, 0, 0, 0, 0};
    FuxiHapticFifoRequest request = request_for(codes, 8);
    FuxiHapticFifoState state;
    Model model;
    unsigned index, evidence;
    static const uint16_t identities[] = {
        0xf000, 0xf001, 0xf004, 0xf005, 0xf100, 0xf101, 0xf104, 0xf105,
        0xf200, 0xf201, 0xf204, 0xf205, 0xf241
    };
    static const uint16_t busy_addresses[] = {0xf00b, 0xf04c, 0xf246, 0xf20b, 0xf108, 0xf12d};
    static const uint8_t busy_values[] = {3, 0x81, 0x80, 1, 0, 1};
    static const uint16_t forks[] = {0xf124, 0xf072, 0xf05d, 0xf049, 0xf063, 0xf068};
    fixture(&model);
    fuxi_haptic_fifo_init(&state);
    CHECK(prepare(&model, &request, &state) == FuxiHapticFifoGateClosed);
    CHECK(state.probed && state.phase == FuxiHapticFifoRejected);
    CHECK(state.snapshot.tlra_us == 5710 && state.snapshot.vmax_mv == 1400);
    CHECK(state.snapshot.fifo_capacity == 640 && !state.snapshot.fifo_status_available);
    CHECK((state.blockers & 0x3fu) == 0x3fu);
    CHECK(model.reads == 104 && model.owner_reads == 110);
    check_locked(&model, &request, &state);
    for (evidence = 0; evidence <= 3; evidence++) {
        fixture(&model);
        fuxi_haptic_fifo_init(&state);
        request.active_requested = UINT_MAX;
        request.evidence = (FuxiHapticFifoEvidence)evidence;
        model.short_write = model.drop_write = model.fail_write = 1;
        CHECK(prepare(&model, &request, &state) == FuxiHapticFifoGateClosed);
        CHECK(state.blockers & FuxiHapticFifoBlockIndependentCutoff);
        CHECK(state.blockers & FuxiHapticFifoBlockExternalRoute);
    }
    for (index = 1; index <= 104; index++) {
        fixture(&model);
        fuxi_haptic_fifo_init(&state);
        model.fail_read = index;
        CHECK(prepare(&model, &request, &state) == FuxiHapticFifoIoError);
        CHECK(model.reads == index);
        check_locked(&model, &request, &state);
        fixture(&model);
        fuxi_haptic_fifo_init(&state);
        model.corrupt_read = index;
        CHECK(prepare(&model, &request, &state) == FuxiHapticFifoUnstable);
        check_locked(&model, &request, &state);
    }
    for (index = 1; index <= 110; index++) {
        fixture(&model);
        fuxi_haptic_fifo_init(&state);
        model.fail_owner = index;
        CHECK(prepare(&model, &request, &state) == FuxiHapticFifoIoError);
        check_locked(&model, &request, &state);
        fixture(&model);
        fuxi_haptic_fifo_init(&state);
        model.change_owner = index;
        CHECK(prepare(&model, &request, &state) == FuxiHapticFifoHardware);
        check_locked(&model, &request, &state);
    }
    for (index = 0; index < sizeof(identities) / sizeof(identities[0]); index++) {
        fixture(&model);
        fuxi_haptic_fifo_init(&state);
        model.raw[peripheral_for(identities[index])][identities[index] & 0xffu] ^= 0x80;
        CHECK(prepare(&model, &request, &state) == FuxiHapticFifoHardware);
    }
    for (index = 0; index < sizeof(busy_addresses) / sizeof(busy_addresses[0]); index++) {
        fixture(&model);
        fuxi_haptic_fifo_init(&state);
        model.raw[peripheral_for(busy_addresses[index])][busy_addresses[index] & 0xffu] = busy_values[index];
        CHECK(prepare(&model, &request, &state) == FuxiHapticFifoBusy);
    }
    for (index = 0; index < sizeof(forks) / sizeof(forks[0]); index++) {
        fixture(&model);
        fuxi_haptic_fifo_init(&state);
        model.raw[peripheral_for(forks[index])][forks[index] & 0xffu] ^= 1;
        if (forks[index] == 0xf072) model.raw[0][0x72] = 8;
        CHECK(prepare(&model, &request, &state) == FuxiHapticFifoProfileFork);
    }
    fixture(&model);
    fuxi_haptic_fifo_init(&state);
    model.raw[0][0x0c] = 4;
    CHECK(prepare(&model, &request, &state) == FuxiHapticFifoFault);
    fixture(&model);
    fuxi_haptic_fifo_init(&state);
    model.raw[1][0xa0] = 4;
    CHECK(prepare(&model, &request, &state) == FuxiHapticFifoHardware);
    fixture(&model);
    fuxi_haptic_fifo_init(&state);
    model.corrupt_plan = &state;
    CHECK(prepare(&model, &request, &state) == FuxiHapticFifoCorrupt);
    fixture(&model);
    fuxi_haptic_fifo_init(&state);
    model.mutate_after = 53;
    model.mutate_address = 0xf072;
    CHECK(prepare(&model, &request, &state) == FuxiHapticFifoUnstable);
    fixture(&model);
    fuxi_haptic_fifo_init(&state);
    request.tlra_code = 1176;
    CHECK(prepare(&model, &request, &state) == FuxiHapticFifoProfileFork);
    request.tlra_code = 1142;
    fixture(&model);
    fuxi_haptic_fifo_init(&state);
    model.raw[0][0x70] = 5;
    model.raw[0][0x71] = 0x80;
    model.raw[0][0x09] = 0x40;
    CHECK(prepare(&model, &request, &state) == FuxiHapticFifoGateClosed);
    CHECK(state.snapshot.fifo_status_available && state.snapshot.fifo_empty);
    CHECK(state.blockers & FuxiHapticFifoBlockIndependentCutoff);
    fixture(&model);
    fuxi_haptic_fifo_init(&state);
    model.raw[0][0x70] = 5;
    model.raw[0][0x71] = 0x80;
    model.raw[0][0x09] = 0x40;
    model.raw[0][0x0a] = 1;
    CHECK(prepare(&model, &request, &state) == FuxiHapticFifoCorrupt);
    model.raw[0][0x0a] = 0;
    model.raw[0][0x0b] = 3;
    fuxi_haptic_fifo_init(&state);
    model.reads = model.owner_reads = 0;
    CHECK(prepare(&model, &request, &state) == FuxiHapticFifoBusy);
    fixture(&model);
    fuxi_haptic_fifo_init(&state);
    model.raw[0][0x48] = 24;
    model.raw[0][0x4a] = 0x80;
    model.raw[0][0x4d] = model.raw[0][0x4e] = 0;
    model.raw[0][0x4b] = 0x10;
    CHECK(prepare(&model, &request, &state) == FuxiHapticFifoGateClosed);
    CHECK(!(state.blockers & (FuxiHapticFifoNeedsVmaxStage | FuxiHapticFifoNeedsHoldDisable)));
    CHECK(state.blockers & FuxiHapticFifoBlockExternalRoute);
    fixture(&model);
    fuxi_haptic_fifo_init(&state);
    request.sample_count = UINT_MAX;
    CHECK(prepare(&model, &request, &state) == FuxiHapticFifoBounds);
    CHECK(!model.reads && !model.owner_reads);
}

static void test_missing_outputs_and_unknown_fields(void)
{
    uint8_t codes[8] = {0x20, 0x20, 0x20, 0x20, 0, 0, 0, 0};
    FuxiHapticFifoRequest request = request_for(codes, 8);
    FuxiHapticFifoState state;
    Model model;
    unsigned index, value;
    static const uint8_t shutdown_values[] = {0x00, 0x04, 0x80, 0x84};
    for (index = 0; index < sizeof(expected_read_addresses) / sizeof(expected_read_addresses[0]); index++) {
        fixture(&model);
        fuxi_haptic_fifo_init(&state);
        model.drop_read_address = expected_read_addresses[index];
        CHECK(prepare(&model, &request, &state) == FuxiHapticFifoUnstable);
        check_locked(&model, &request, &state);
    }
    for (index = 1; index <= FUXI_HAPTIC_FIFO_MAX_OWNER_READS; index++) {
        fixture(&model);
        fuxi_haptic_fifo_init(&state);
        model.drop_owner = index;
        CHECK(prepare(&model, &request, &state) == FuxiHapticFifoHardware);
        check_locked(&model, &request, &state);
    }
    for (value = 0; value < 256u; value++) {
        fixture(&model);
        fuxi_haptic_fifo_init(&state);
        model.raw[0][0x4d] = (uint8_t)value;
        CHECK(prepare(&model, &request, &state) == FuxiHapticFifoGateClosed);
        CHECK(state.snapshot.raw[0][0x4d] == value);
        CHECK(state.blockers & FuxiHapticFifoBlockExternalRoute);
        CHECK(state.blockers & FuxiHapticFifoBlockIndependentCutoff);
        CHECK(state.blockers & FuxiHapticFifoBlockActiveGate);
    }
    for (index = 0; index < sizeof(shutdown_values) / sizeof(shutdown_values[0]); index++) {
        fixture(&model);
        fuxi_haptic_fifo_init(&state);
        model.raw[0][0x4a] = shutdown_values[index];
        CHECK(prepare(&model, &request, &state) == FuxiHapticFifoGateClosed);
        CHECK(!!(state.blockers & FuxiHapticFifoNeedsHoldDisable) == !!(shutdown_values[index] & 4u));
        CHECK(state.blockers & FuxiHapticFifoBlockIndependentCutoff);
        CHECK(state.blockers & FuxiHapticFifoBlockExternalRoute);
    }
}

static void test_api_edges(void)
{
    uint8_t codes[8] = {0x20, 0x20, 0x20, 0x20, 0, 0, 0, 0};
    FuxiHapticFifoRequest request = request_for(codes, 8);
    FuxiHapticFifoState state;
    FuxiHapticFifoPlan plan;
    FuxiHapticFifoJournal journal = {0, 0, 0, 0};
    Model model;
    FuxiHapticFifoIo io = {&model, model_owner, model_read, NULL};
    unsigned index, fill = UINT_MAX, empty = UINT_MAX;
    static const FuxiHapticFifoPhase phases[] = {
        FuxiHapticFifoEncoded, FuxiHapticFifoProbed, FuxiHapticFifoRejected,
        FuxiHapticFifoFailed, (FuxiHapticFifoPhase)255
    };
    fixture(&model);
    fuxi_haptic_fifo_init(&state);
    CHECK(fuxi_haptic_fifo_prepare(NULL, &request, &state) == FuxiHapticFifoInvalid);
    CHECK(fuxi_haptic_fifo_prepare(&io, NULL, &state) == FuxiHapticFifoInvalid);
    CHECK(fuxi_haptic_fifo_prepare(&io, &request, NULL) == FuxiHapticFifoInvalid);
    io.owner = NULL;
    CHECK(fuxi_haptic_fifo_prepare(&io, &request, &state) == FuxiHapticFifoInvalid);
    io.owner = model_owner;
    io.read = NULL;
    CHECK(fuxi_haptic_fifo_prepare(&io, &request, &state) == FuxiHapticFifoInvalid);
    io.read = model_read;
    CHECK(!model.reads && !model.owner_reads && !model.writes);
    CHECK(fuxi_haptic_fifo_prepare(&io, &request, &state) == FuxiHapticFifoGateClosed);
    CHECK(state.probed && !model.writes);
    for (index = 0; index < sizeof(phases) / sizeof(phases[0]); index++) {
        fixture(&model);
        fuxi_haptic_fifo_init(&state);
        state.phase = phases[index];
        CHECK(prepare(&model, &request, &state) == FuxiHapticFifoLocked);
        CHECK(!model.reads && !model.owner_reads);
    }
    fuxi_haptic_fifo_init(&state);
    state.reads = 1;
    CHECK(prepare(&model, &request, &state) == FuxiHapticFifoLocked);
    fuxi_haptic_fifo_init(&state);
    state.owner_reads = 1;
    CHECK(prepare(&model, &request, &state) == FuxiHapticFifoLocked);
    fuxi_haptic_fifo_init(&state);
    fuxi_haptic_fifo_cleanup(&state);
    CHECK(state.phase == FuxiHapticFifoFailed && state.result == FuxiHapticFifoLocked);
    CHECK(prepare(&model, &request, &state) == FuxiHapticFifoLocked);
    fuxi_haptic_fifo_init(NULL);
    fuxi_haptic_fifo_cleanup(NULL);
    CHECK(fuxi_haptic_fifo_encode(codes, 8, 1200, 1142, &plan) == 0);
    CHECK(fuxi_haptic_fifo_encode(plan.sample_codes, 8, 1200, 1142, &plan) == 0);
    CHECK(!memcmp(plan.sample_codes, codes, sizeof(codes)));
    CHECK(fuxi_haptic_fifo_record_transfer(NULL, &journal, 0, 0, 4) == FuxiHapticFifoInvalid);
    CHECK(fuxi_haptic_fifo_record_transfer(&plan, NULL, 0, 0, 4) == FuxiHapticFifoInvalid);
    CHECK(fuxi_haptic_fifo_decode_status(5, 0x80, 0x40, 0, 640, NULL, &empty) == FuxiHapticFifoInvalid);
    CHECK(fuxi_haptic_fifo_decode_status(5, 0x80, 0x40, 0, 640, &fill, NULL) == FuxiHapticFifoInvalid);
    CHECK(fill == UINT_MAX && empty == UINT_MAX);
}

int main(void)
{
    unsigned address, index, expected;
    test_encoding_and_journal();
    test_bounds();
    test_status();
    test_preflight_and_faults();
    test_missing_outputs_and_unknown_fields();
    test_api_edges();
    for (address = 0; address <= 65535u; address++) {
        expected = 0;
        for (index = 0; index < sizeof(expected_read_addresses) / sizeof(expected_read_addresses[0]); index++)
            if (expected_read_addresses[index] == address) expected = 1;
        CHECK((unsigned)fuxi_haptic_fifo_read_allowed((uint16_t)address) == expected);
        CHECK(!fuxi_haptic_fifo_write_allowed((uint16_t)address, 0));
        CHECK(!fuxi_haptic_fifo_write_allowed((uint16_t)address, 1));
        CHECK(!fuxi_haptic_fifo_write_allowed((uint16_t)address, 4));
        CHECK(!fuxi_haptic_fifo_write_allowed((uint16_t)address, UINT_MAX));
    }
    CHECK(!fuxi_haptic_fifo_read_allowed(0xf120));
    CHECK(!fuxi_haptic_fifo_read_allowed(0xf12c));
    CHECK(!fuxi_haptic_fifo_read_allowed(0xf066));
    CHECK(FUXI_HAPTIC_FIFO_ACTIVE_GATE == 0 && FUXI_HAPTIC_FIFO_MAX_REFILLS == 0);
    printf("PASS: %u checks; actual FIFO C helper; 104 read/110 ownership fault points; "
        "OEM packing, bounds, corruption, partial-transfer journal, profile forks, false empty, "
        "missing callback outputs, exact allowlists, unknown EXT_TRIG/bit7, "
        "gate rejection and zero hardware writes; no autonomous-stop claim\n", checks);
    return 0;
}
