#include "fuxi_haptic_fifo.h"

static const uint8_t cfg_offsets[] = {
    0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x0b, 0x0c, 0x46, 0x48,
    0x49, 0x4a, 0x4b, 0x4c, 0x4d, 0x4e, 0x50, 0x51, 0x5c, 0x5d,
    0x63, 0x68, 0x70, 0x71, 0x72
};
static const uint8_t ptn_offsets[] = {
    0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x08, 0x09, 0x24, 0x2a,
    0x2d, 0x30, 0x31, 0xa0
};
static const uint8_t boost_offsets[] = {
    0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x0b, 0x41, 0x46
};

_Static_assert(FUXI_HAPTIC_FIFO_ACTIVE_GATE == 0u && FUXI_HAPTIC_FIFO_MAX_WRITES == 0u,
    "FIFO preparation must remain read-only");
_Static_assert(FUXI_HAPTIC_FIFO_MAX_REFILLS == 0u && FUXI_HAPTIC_FIFO_MAX_STOP_POLLS == 0u,
    "FIFO preparation must not refill or stop hardware");
_Static_assert(2u * (sizeof(cfg_offsets) + sizeof(ptn_offsets) + sizeof(boost_offsets) + 4u) ==
    FUXI_HAPTIC_FIFO_MAX_READS, "FIFO read budget must match the snapshot inventory");
_Static_assert(FUXI_HAPTIC_FIFO_MAX_OWNER_READS == FUXI_HAPTIC_FIFO_MAX_READS + 6u,
    "FIFO owner budget must include both end-of-snapshot checks");

static void zero_bytes(void *target, size_t count)
{
    uint8_t *bytes = target;
    size_t index;
    for (index = 0; index < count; index++) bytes[index] = 0;
}

int fuxi_haptic_fifo_encode(const uint8_t *codes, unsigned count,
    unsigned vmax_mv, uint16_t tlra_code, FuxiHapticFifoPlan *plan)
{
    FuxiHapticFifoPlan encoded;
    unsigned index, cursor;
    if (!codes || !plan) return FuxiHapticFifoInvalid;
    if (count <= FUXI_HAPTIC_FIFO_TAIL_ZEROS || count > FUXI_HAPTIC_FIFO_MAX_SAMPLES ||
        !vmax_mv || vmax_mv > FUXI_HAPTIC_FIFO_MAX_VMAX_MV || vmax_mv % 50u ||
        !tlra_code || tlra_code > 4095u) return FuxiHapticFifoBounds;
    for (index = 0; index < count; index++) {
        if (codes[index] > FUXI_HAPTIC_FIFO_MAX_CODE) return FuxiHapticFifoBounds;
        if (index >= count - FUXI_HAPTIC_FIFO_TAIL_ZEROS && codes[index])
            return FuxiHapticFifoInvalid;
    }
    zero_bytes(&encoded, sizeof(encoded));
    encoded.sample_count = count;
    encoded.vmax_mv = vmax_mv;
    encoded.tlra_code = tlra_code;
    encoded.nominal_data_us = count * (unsigned)tlra_code * 5u;
    for (index = 0; index < count; index++) encoded.sample_codes[index] = codes[index];
    cursor = 0;
    while (count - cursor >= 4u) {
        FuxiHapticFifoChunk *chunk = &encoded.chunks[encoded.chunk_count++];
        chunk->address = 0xf120;
        chunk->length = 4;
        for (index = 0; index < 4; index++) chunk->bytes[index] = codes[cursor++];
    }
    while (cursor < count) {
        FuxiHapticFifoChunk *chunk = &encoded.chunks[encoded.chunk_count++];
        chunk->address = 0xf12c;
        chunk->length = 1;
        chunk->bytes[0] = codes[cursor++];
    }
    *plan = encoded;
    return FuxiHapticFifoOk;
}

int fuxi_haptic_fifo_validate_plan(const FuxiHapticFifoPlan *plan)
{
    FuxiHapticFifoPlan encoded;
    unsigned index, byte_index;
    int result;
    if (!plan) return FuxiHapticFifoInvalid;
    result = fuxi_haptic_fifo_encode(plan->sample_codes, plan->sample_count,
        plan->vmax_mv, plan->tlra_code, &encoded);
    if (result) return FuxiHapticFifoCorrupt;
    if (plan->chunk_count != encoded.chunk_count ||
        plan->nominal_data_us != encoded.nominal_data_us) return FuxiHapticFifoCorrupt;
    for (index = 0; index < FUXI_HAPTIC_FIFO_MAX_SAMPLES; index++)
        if (plan->sample_codes[index] != encoded.sample_codes[index]) return FuxiHapticFifoCorrupt;
    for (index = 0; index < FUXI_HAPTIC_FIFO_MAX_CHUNKS; index++) {
        if (plan->chunks[index].address != encoded.chunks[index].address ||
            plan->chunks[index].length != encoded.chunks[index].length) return FuxiHapticFifoCorrupt;
        for (byte_index = 0; byte_index < 4; byte_index++)
            if (plan->chunks[index].bytes[byte_index] != encoded.chunks[index].bytes[byte_index])
                return FuxiHapticFifoCorrupt;
    }
    return FuxiHapticFifoOk;
}

int fuxi_haptic_fifo_record_transfer(const FuxiHapticFifoPlan *plan,
    FuxiHapticFifoJournal *journal, unsigned chunk_index,
    int transport_result, unsigned transferred)
{
    unsigned index, expected_bytes = 0;
    int result;
    if (!plan || !journal) return FuxiHapticFifoInvalid;
    if (journal->failed || journal->complete) return FuxiHapticFifoLocked;
    result = fuxi_haptic_fifo_validate_plan(plan);
    if (result) {
        journal->failed = 1;
        return result;
    }
    if (chunk_index != journal->next_chunk || chunk_index >= plan->chunk_count) {
        journal->failed = 1;
        return FuxiHapticFifoBounds;
    }
    for (index = 0; index < chunk_index; index++) expected_bytes += plan->chunks[index].length;
    if (journal->acknowledged_bytes != expected_bytes) {
        journal->failed = 1;
        return FuxiHapticFifoCorrupt;
    }
    if (transport_result || transferred != plan->chunks[chunk_index].length) {
        journal->failed = 1;
        return FuxiHapticFifoPartialWrite;
    }
    journal->acknowledged_bytes += transferred;
    journal->next_chunk++;
    journal->complete = journal->next_chunk == plan->chunk_count;
    return FuxiHapticFifoOk;
}

int fuxi_haptic_fifo_read_allowed(uint16_t address)
{
    const uint8_t *offsets;
    size_t count, index;
    switch (address & 0xff00u) {
    case 0xf000:
        if (address == 0xf009 || address == 0xf00a) return 1;
        offsets = cfg_offsets;
        count = sizeof(cfg_offsets);
        break;
    case 0xf100:
        offsets = ptn_offsets;
        count = sizeof(ptn_offsets);
        break;
    case 0xf200:
        offsets = boost_offsets;
        count = sizeof(boost_offsets);
        break;
    default:
        return 0;
    }
    for (index = 0; index < count; index++)
        if (offsets[index] == (address & 0xffu)) return 1;
    return 0;
}

int fuxi_haptic_fifo_write_allowed(uint16_t address, unsigned length)
{
    (void)address;
    (void)length;
    return 0;
}

int fuxi_haptic_fifo_decode_status(uint8_t selector, uint8_t selector_xt,
    uint8_t msb, uint8_t lsb, unsigned capacity, unsigned *fill, unsigned *empty)
{
    unsigned decoded_fill, decoded_empty, decoded_full;
    if (!fill || !empty) return FuxiHapticFifoInvalid;
    if (selector != 0x05 || selector_xt != 0x80) return FuxiHapticFifoProfileFork;
    if (!capacity || capacity > 2048u) return FuxiHapticFifoBounds;
    decoded_fill = ((unsigned)(msb & 0x0fu) << 8) | lsb;
    decoded_empty = !!(msb & 0x40u);
    decoded_full = !!(msb & 0x20u);
    if (decoded_fill > capacity || (decoded_empty && decoded_fill) ||
        (decoded_full && decoded_fill != capacity) || (decoded_empty && decoded_full))
        return FuxiHapticFifoCorrupt;
    *fill = decoded_fill;
    *empty = decoded_empty;
    return FuxiHapticFifoOk;
}

unsigned fuxi_haptic_fifo_independent_cutoff_verified(void)
{
    return 0;
}

void fuxi_haptic_fifo_init(FuxiHapticFifoState *state)
{
    if (state) zero_bytes(state, sizeof(*state));
}

static int check_owner(const FuxiHapticFifoIo *io, FuxiHapticFifoState *state, unsigned peripheral)
{
    unsigned owner = 255u;
    if (state->owner_reads >= FUXI_HAPTIC_FIFO_MAX_OWNER_READS) return FuxiHapticFifoBounds;
    state->owner_reads++;
    if (io->owner(io->context, (uint16_t)(0xf000u + peripheral * 256u), &owner))
        return FuxiHapticFifoIoError;
    if (owner != (peripheral == 2u ? 3u : 0u)) return FuxiHapticFifoHardware;
    return FuxiHapticFifoOk;
}

static int read_byte(const FuxiHapticFifoIo *io, FuxiHapticFifoState *state,
    unsigned peripheral, uint8_t offset, uint8_t *value)
{
    uint16_t address = (uint16_t)(0xf000u + peripheral * 256u + offset);
    uint8_t observed;
    int result;
    if (!fuxi_haptic_fifo_read_allowed(address) ||
        state->reads >= FUXI_HAPTIC_FIFO_MAX_READS) return FuxiHapticFifoBounds;
    result = check_owner(io, state, peripheral);
    if (result) return result;
    state->reads++;
    observed = (uint8_t)(state->reads ^ 0xa5u);
    if (io->read(io->context, address, &observed)) return FuxiHapticFifoIoError;
    *value = observed;
    return FuxiHapticFifoOk;
}

static int take_snapshot(const FuxiHapticFifoIo *io,
    FuxiHapticFifoState *state, FuxiHapticFifoSnapshot *snapshot)
{
    const uint8_t *offsets;
    size_t count, index;
    unsigned peripheral;
    uint8_t selector = 0xff, selector_xt = 0xff;
    int result;
    zero_bytes(snapshot, sizeof(*snapshot));
    for (peripheral = 0; peripheral < 3; peripheral++) {
        if (peripheral == 0) { offsets = cfg_offsets; count = sizeof(cfg_offsets); }
        else if (peripheral == 1) { offsets = ptn_offsets; count = sizeof(ptn_offsets); }
        else { offsets = boost_offsets; count = sizeof(boost_offsets); }
        for (index = 0; index < count; index++) {
            result = read_byte(io, state, peripheral, offsets[index],
                &snapshot->raw[peripheral][offsets[index]]);
            if (result) return result;
        }
    }
    result = read_byte(io, state, 0, 0x09, &snapshot->raw[0][0x09]);
    if (result) return result;
    result = read_byte(io, state, 0, 0x0a, &snapshot->raw[0][0x0a]);
    if (result) return result;
    result = read_byte(io, state, 0, 0x70, &selector);
    if (result) return result;
    result = read_byte(io, state, 0, 0x71, &selector_xt);
    if (result) return result;
    if (selector != snapshot->raw[0][0x70] || selector_xt != snapshot->raw[0][0x71])
        return FuxiHapticFifoUnstable;
    for (peripheral = 0; peripheral < 3; peripheral++) {
        result = check_owner(io, state, peripheral);
        if (result) return result;
    }
    return FuxiHapticFifoOk;
}

static int validate_snapshot(FuxiHapticFifoSnapshot *snapshot)
{
    const uint8_t *cfg = snapshot->raw[0];
    const uint8_t *ptn = snapshot->raw[1];
    const uint8_t *boost = snapshot->raw[2];
    int result;
    if (cfg[0x00] || cfg[0x01] != 4 || cfg[0x04] != 0x15 || cfg[0x05] != 0x0a ||
        ptn[0x00] || ptn[0x01] != 4 || ptn[0x04] != 0x15 || ptn[0x05] != 0x0b ||
        boost[0x00] != 2 || boost[0x01] || boost[0x04] != 0x31 || boost[0x05] != 1 ||
        (boost[0x41] & 0xe0u) != 0xe0u) return FuxiHapticFifoHardware;
    if (cfg[0x0c]) return FuxiHapticFifoFault;
    if ((cfg[0x0b] & 3u) || (cfg[0x4c] & 0x80u) || (boost[0x46] & 0x80u) ||
        (boost[0x0b] & 1u) || !(ptn[0x08] & 1u) || ptn[0x2d]) return FuxiHapticFifoBusy;
    snapshot->tlra_us = (((unsigned)cfg[0x5c] & 0x0fu) * 256u + cfg[0x5d]) * 5u;
    snapshot->vmax_mv = (unsigned)cfg[0x48] * 50u;
    if (snapshot->tlra_us != FUXI_HAPTIC_FIFO_PROFILE_TLRA_CODE * 5u ||
        (ptn[0x24] & 0x0fu) || (cfg[0x72] & 0x0cu) != 4u ||
        cfg[0x49] != 1 || cfg[0x63] != 0x89 || (cfg[0x68] & 3u))
        return FuxiHapticFifoProfileFork;
    if (!(ptn[0xa0] & 0x80u)) return FuxiHapticFifoHardware;
    snapshot->fifo_capacity = ((unsigned)(ptn[0xa0] & 0x0fu) + 1u) * 128u;
    if (cfg[0x70] == 5 && cfg[0x71] == 0x80) {
        result = fuxi_haptic_fifo_decode_status(cfg[0x70], cfg[0x71], cfg[0x09], cfg[0x0a],
            snapshot->fifo_capacity, &snapshot->fifo_fill, &snapshot->fifo_empty);
        if (result) return result;
        snapshot->fifo_status_available = 1;
        if (snapshot->fifo_fill) return FuxiHapticFifoBusy;
    }
    return FuxiHapticFifoOk;
}

static int fail_state(FuxiHapticFifoState *state, int result)
{
    state->phase = FuxiHapticFifoFailed;
    state->result = result;
    return result;
}

int fuxi_haptic_fifo_prepare(const FuxiHapticFifoIo *io,
    const FuxiHapticFifoRequest *request, FuxiHapticFifoState *state)
{
    FuxiHapticFifoSnapshot second;
    unsigned peripheral, offset;
    int result;
    if (!io || !request || !state || !io->owner || !io->read) return FuxiHapticFifoInvalid;
    if (state->phase != FuxiHapticFifoNew || state->reads || state->owner_reads)
        return FuxiHapticFifoLocked;
    result = fuxi_haptic_fifo_encode(request->sample_codes, request->sample_count,
        request->vmax_mv, request->tlra_code, &state->plan);
    if (result) return fail_state(state, result);
    state->phase = FuxiHapticFifoEncoded;
    result = take_snapshot(io, state, &state->snapshot);
    if (result) return fail_state(state, result);
    result = take_snapshot(io, state, &second);
    if (result) return fail_state(state, result);
    for (peripheral = 0; peripheral < 3; peripheral++)
        for (offset = 0; offset < 256; offset++)
            if (state->snapshot.raw[peripheral][offset] != second.raw[peripheral][offset])
                return fail_state(state, FuxiHapticFifoUnstable);
    result = fuxi_haptic_fifo_validate_plan(&state->plan);
    if (result) return fail_state(state, result);
    result = validate_snapshot(&state->snapshot);
    if (result) return fail_state(state, result);
    if (state->plan.tlra_code * 5u != state->snapshot.tlra_us)
        return fail_state(state, FuxiHapticFifoProfileFork);
    state->phase = FuxiHapticFifoProbed;
    state->probed = 1;
    state->blockers = FuxiHapticFifoBlockActiveGate | FuxiHapticFifoBlockIndependentCutoff |
        FuxiHapticFifoBlockExternalRoute | FuxiHapticFifoBlockClockProof;
    if (state->snapshot.vmax_mv != state->plan.vmax_mv) state->blockers |= FuxiHapticFifoNeedsVmaxStage;
    if (state->snapshot.raw[0][0x4a] & 4u) state->blockers |= FuxiHapticFifoNeedsHoldDisable;
    if (state->snapshot.raw[1][0x2a] & 0x0fu) state->blockers |= FuxiHapticFifoNeedsThresholdStage;
    state->phase = FuxiHapticFifoRejected;
    state->result = FuxiHapticFifoGateClosed;
    return state->result;
}

void fuxi_haptic_fifo_cleanup(FuxiHapticFifoState *state)
{
    if (!state) return;
    zero_bytes(&state->plan, sizeof(state->plan));
    if (state->phase == FuxiHapticFifoNew || state->phase == FuxiHapticFifoEncoded ||
        state->phase == FuxiHapticFifoProbed) {
        state->phase = FuxiHapticFifoFailed;
        state->result = FuxiHapticFifoLocked;
    }
}
