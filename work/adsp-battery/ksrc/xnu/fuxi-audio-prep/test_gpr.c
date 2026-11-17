#include "fuxi_audio_prep_gpr.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned checks;

#define CHECK(condition) do { \
    checks++; \
    if (!(condition)) { \
        fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #condition); \
        exit(1); \
    } \
} while (0)

static const uint8_t golden_query[40] = {
    0x60, 0x28, 0x00, 0x00, 0x02, 0x03, 0x00, 0x00,
    0x78, 0x56, 0x34, 0x12, 0x01, 0x00, 0x00, 0x00,
    0xef, 0xcd, 0xab, 0x89, 0x21, 0x10, 0x00, 0x01,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00
};

static const uint8_t golden_state[28] = {
    0x60, 0x1c, 0x00, 0x00, 0x03, 0x02, 0x00, 0x00,
    0x01, 0x00, 0x00, 0x00, 0x78, 0x56, 0x34, 0x12,
    0xef, 0xcd, 0xab, 0x89, 0x07, 0x10, 0x00, 0x02,
    0x01, 0x00, 0x00, 0x00
};

static void set_word(uint8_t *output, uint32_t value)
{
    output[0] = (uint8_t)value;
    output[1] = (uint8_t)(value >> 8);
    output[2] = (uint8_t)(value >> 16);
    output[3] = (uint8_t)(value >> 24);
}

static void test_golden_and_roundtrip(void)
{
    uint8_t storage[FUXI_AUDIO_PREP_GPR_MAX_BYTES + 2];
    uint8_t payload[FUXI_AUDIO_PREP_GPR_MAX_BYTES];
    FuxiAudioPrepGprView view;
    FuxiAudioPrepGprFields fields = {2, 3, 0x12345678, 1, 0x89abcdef, 0x01001021};
    size_t written = 0;

    memset(storage, 0xa5, sizeof(storage));
    CHECK(fuxi_audio_prep_spf_query(storage + 1, 40, fields.src_port,
        fields.token, &written) == FuxiAudioPrepOk);
    CHECK(written == sizeof(golden_query));
    CHECK(memcmp(storage + 1, golden_query, written) == 0);
    CHECK(storage[0] == 0xa5 && storage[41] == 0xa5);
    CHECK(fuxi_audio_prep_gpr_decode(storage + 1, written, &view) == FuxiAudioPrepOk);
    CHECK(view.payload_bytes == 16 && view.header_bytes == 24);
    CHECK(view.fields.opcode == FUXI_AUDIO_PREP_GET_SPF_STATE);
    CHECK(view.fields.src_port == fields.src_port && view.fields.token == fields.token);

    for (size_t index = 0; index < sizeof(payload); index++) {
        payload[index] = (uint8_t)(index * 13u);
    }
    for (size_t length = 0; length <= FUXI_AUDIO_PREP_GPR_MAX_BYTES - 24; length++) {
        CHECK(fuxi_audio_prep_gpr_encode(storage + 1, sizeof(storage) - 2,
            &fields, payload, length, &written) == FuxiAudioPrepOk);
        CHECK(fuxi_audio_prep_gpr_decode(storage + 1, written, &view) == FuxiAudioPrepOk);
        CHECK(view.payload_bytes == length && written == length + 24);
        CHECK(memcmp(view.payload, payload, length) == 0);
        CHECK(memcmp(&view.fields, &fields, sizeof(fields)) == 0);
        CHECK(storage[0] == 0xa5 && storage[sizeof(storage) - 1] == 0xa5);
    }
    for (uint32_t domain = 0; domain <= UINT8_MAX; domain++) {
        fields.src_domain = domain;
        fields.dst_domain = UINT8_MAX - domain;
        fields.src_port = UINT32_MAX;
        fields.token = UINT32_MAX;
        CHECK(fuxi_audio_prep_gpr_encode(storage, sizeof(storage), &fields,
            NULL, 0, &written) == FuxiAudioPrepOk);
        CHECK(fuxi_audio_prep_gpr_decode(storage, written, &view) == FuxiAudioPrepOk);
        CHECK(memcmp(&view.fields, &fields, sizeof(fields)) == 0);
    }

    memcpy(storage, golden_query, sizeof(golden_query));
    memcpy(payload, storage, 32);
    CHECK(fuxi_audio_prep_gpr_encode(storage, sizeof(storage), &fields,
        storage, 32, &written) == FuxiAudioPrepOk);
    CHECK(memcmp(storage + 24, payload, 32) == 0);
    memcpy(payload, storage + 28, 32);
    CHECK(fuxi_audio_prep_gpr_encode(storage, sizeof(storage), &fields,
        storage + 28, 32, &written) == FuxiAudioPrepOk);
    CHECK(memcmp(storage + 24, payload, 32) == 0);
}

static void test_encode_failures(void)
{
    uint8_t output[64];
    uint8_t before[64];
    FuxiAudioPrepGprFields fields = {2, 3, 1, 1, 0, 0x01001021};
    size_t written = 123;

    memset(output, 0xa5, sizeof(output));
    memcpy(before, output, sizeof(output));
    CHECK(fuxi_audio_prep_gpr_encode(NULL, 64, &fields, NULL, 0, &written) == FuxiAudioPrepArgument);
    CHECK(fuxi_audio_prep_gpr_encode(output, 64, NULL, NULL, 0, &written) == FuxiAudioPrepArgument);
    CHECK(fuxi_audio_prep_gpr_encode(output, 64, &fields, NULL, 1, &written) == FuxiAudioPrepArgument);
    CHECK(fuxi_audio_prep_gpr_encode(output, 64, &fields, NULL, 0, NULL) == FuxiAudioPrepArgument);
    CHECK(fuxi_audio_prep_gpr_encode(output, 23, &fields, NULL, 0, &written) == FuxiAudioPrepCapacity);
    CHECK(fuxi_audio_prep_spf_query(output, 39, 1, 0, &written) == FuxiAudioPrepCapacity);
    CHECK(fuxi_audio_prep_gpr_encode(output, SIZE_MAX, &fields, output,
        SIZE_MAX, &written) == FuxiAudioPrepRange);
    CHECK(fuxi_audio_prep_gpr_encode(output, SIZE_MAX, &fields, output,
        537, &written) == FuxiAudioPrepRange);
    fields.src_domain = 256;
    CHECK(fuxi_audio_prep_gpr_encode(output, 64, &fields, NULL, 0, &written) == FuxiAudioPrepRange);
    fields.src_domain = 3;
    fields.dst_domain = UINT32_MAX;
    CHECK(fuxi_audio_prep_gpr_encode(output, 64, &fields, NULL, 0, &written) == FuxiAudioPrepRange);
    CHECK(written == 123 && memcmp(output, before, sizeof(output)) == 0);
}

static void expect_decode_failure(const uint8_t *input, size_t length, int expected)
{
    FuxiAudioPrepGprView view;
    unsigned char before[sizeof(view)];

    memset(&view, 0xa5, sizeof(view));
    memcpy(before, &view, sizeof(view));
    CHECK(fuxi_audio_prep_gpr_decode(input, length, &view) == expected);
    CHECK(memcmp(&view, before, sizeof(view)) == 0);
}

static void test_decode_boundaries(void)
{
    uint8_t input[64];
    FuxiAudioPrepGprView view;

    expect_decode_failure(NULL, 0, FuxiAudioPrepArgument);
    CHECK(fuxi_audio_prep_gpr_decode(golden_query, 40, NULL) == FuxiAudioPrepArgument);
    expect_decode_failure(golden_query, SIZE_MAX, FuxiAudioPrepLength);
    for (size_t length = 0; length < sizeof(golden_query); length++) {
        uint8_t *exact = malloc(length ? length : 1);
        CHECK(exact != NULL);
        memcpy(exact, golden_query, length);
        expect_decode_failure(exact, length,
            length < 24 ? FuxiAudioPrepShort : FuxiAudioPrepLength);
        free(exact);
    }
    memcpy(input, golden_query, 40);
    input[40] = 0;
    expect_decode_failure(input, 41, FuxiAudioPrepLength);
    for (uint32_t version = 1; version < 16; version++) {
        input[0] = (uint8_t)(0x60u | version);
        expect_decode_failure(input, 40, FuxiAudioPrepVersion);
    }
    input[0] = 0x60;
    for (unsigned client_data = 0; client_data < 16; client_data++) {
        input[6] = (uint8_t)client_data;
        CHECK(fuxi_audio_prep_gpr_decode(input, 40, &view) == FuxiAudioPrepOk);
        CHECK(view.client_data == client_data);
    }
    for (unsigned bit = 20; bit < 32; bit++) {
        set_word(input + 4, 0x302u | (1u << bit));
        expect_decode_failure(input, 40, FuxiAudioPrepReserved);
    }
    set_word(input + 4, 0x302u);
    input[6] = 0;
    input[7] = 0x80;
    expect_decode_failure(input, 40, FuxiAudioPrepReserved);
    input[7] = 0;
    for (uint32_t words = 0; words < 16; words++) {
        set_word(input, (40u << 8) | (words << 4));
        if (words < 6) {
            expect_decode_failure(input, 40, FuxiAudioPrepHeader);
        } else if (words > 10) {
            expect_decode_failure(input, 40, FuxiAudioPrepLength);
        } else {
            CHECK(fuxi_audio_prep_gpr_decode(input, 40, &view) == FuxiAudioPrepOk);
            CHECK(view.header_bytes == words * 4u && view.payload_bytes == 40u - words * 4u);
        }
    }
    set_word(input, (0xffffffu << 8) | 0x60u);
    expect_decode_failure(input, 40, FuxiAudioPrepLength);
    for (uint32_t bytes = 0; bytes < 64; bytes++) {
        set_word(input, (bytes << 8) | 0x60u);
        if (bytes != 40) {
            expect_decode_failure(input, 40, FuxiAudioPrepLength);
        }
    }
    for (uint32_t words = 6; words < 16; words++) {
        memset(input, 0, sizeof(input));
        set_word(input, ((words * 4u) << 8) | (words << 4));
        CHECK(fuxi_audio_prep_gpr_decode(input, words * 4u, &view) == FuxiAudioPrepOk);
        CHECK(view.payload_bytes == 0 && view.payload == input + words * 4u);
    }
}

static void expect_reply_failure(const uint8_t *input, size_t length, int expected)
{
    FuxiAudioPrepSpfReply reply = {FuxiAudioPrepSpfRemoteError, 44, 55};

    CHECK(fuxi_audio_prep_spf_reply(input, length, 0x12345678, 0x89abcdef, &reply) == expected);
    CHECK(reply.kind == FuxiAudioPrepSpfRemoteError && reply.state == 44 && reply.status == 55);
}

static void test_spf_replies(void)
{
    uint8_t input[64];
    uint8_t payload[12] = {0x21, 0x10, 0x00, 0x01};
    FuxiAudioPrepGprFields fields = {3, 2, 1, 0x12345678, 0x89abcdef, FUXI_AUDIO_PREP_BASIC_RESULT};
    FuxiAudioPrepSpfReply reply;
    size_t written;
    const size_t route_offsets[] = {4, 5, 8, 12, 16};

    CHECK(fuxi_audio_prep_spf_reply(golden_state, sizeof(golden_state),
        fields.dst_port, fields.token, &reply) == FuxiAudioPrepOk);
    CHECK(reply.kind == FuxiAudioPrepSpfState && reply.state == 1 && reply.status == 0);
    memcpy(input, golden_state, sizeof(golden_state));
    input[24] = 0;
    CHECK(fuxi_audio_prep_spf_reply(input, 28, fields.dst_port,
        fields.token, &reply) == FuxiAudioPrepOk);
    CHECK(reply.kind == FuxiAudioPrepSpfState && reply.state == 0);
    input[24] = 2;
    CHECK(fuxi_audio_prep_spf_reply(input, 28, fields.dst_port,
        fields.token, &reply) == FuxiAudioPrepOk);
    CHECK(reply.state == 2);
    for (size_t index = 0; index < sizeof(route_offsets) / sizeof(route_offsets[0]); index++) {
        memcpy(input, golden_state, sizeof(golden_state));
        input[route_offsets[index]] ^= 1;
        expect_reply_failure(input, 28, FuxiAudioPrepRoute);
    }
    memcpy(input, golden_state, sizeof(golden_state));
    input[20] ^= 1;
    expect_reply_failure(input, 28, FuxiAudioPrepOpcode);
    expect_reply_failure(golden_state, 27, FuxiAudioPrepLength);
    CHECK(fuxi_audio_prep_spf_reply(golden_state, 28, fields.dst_port,
        fields.token, NULL) == FuxiAudioPrepArgument);

    for (size_t length = 0; length <= sizeof(payload); length++) {
        CHECK(fuxi_audio_prep_gpr_encode(input, sizeof(input), &fields,
            payload, length, &written) == FuxiAudioPrepOk);
        if (length != 8) {
            expect_reply_failure(input, written, FuxiAudioPrepPayload);
        } else {
            CHECK(fuxi_audio_prep_spf_reply(input, written, fields.dst_port,
                fields.token, &reply) == FuxiAudioPrepOk);
            CHECK(reply.kind == FuxiAudioPrepSpfAccepted && reply.state == 0 && reply.status == 0);
        }
    }
    payload[4] = 7;
    CHECK(fuxi_audio_prep_gpr_encode(input, sizeof(input), &fields,
        payload, 8, &written) == FuxiAudioPrepOk);
    CHECK(fuxi_audio_prep_spf_reply(input, written, fields.dst_port,
        fields.token, &reply) == FuxiAudioPrepOk);
    CHECK(reply.kind == FuxiAudioPrepSpfRemoteError && reply.status == 7);
    input[6] = 1;
    CHECK(fuxi_audio_prep_spf_reply(input, written, fields.dst_port,
        fields.token, &reply) == FuxiAudioPrepOk);
    CHECK(reply.kind == FuxiAudioPrepSpfRemoteError && reply.status == 7);
    payload[0] ^= 1;
    CHECK(fuxi_audio_prep_gpr_encode(input, sizeof(input), &fields,
        payload, 8, &written) == FuxiAudioPrepOk);
    expect_reply_failure(input, written, FuxiAudioPrepOpcode);
    fields.opcode = FUXI_AUDIO_PREP_SPF_STATE_REPLY;
    for (size_t length = 0; length <= sizeof(payload); length++) {
        CHECK(fuxi_audio_prep_gpr_encode(input, sizeof(input), &fields,
            payload, length, &written) == FuxiAudioPrepOk);
        if (length != 4) {
            expect_reply_failure(input, written, FuxiAudioPrepPayload);
        }
    }
}

static void test_header_mutations(void)
{
    uint8_t input[40];
    FuxiAudioPrepGprView view;
    FuxiAudioPrepSpfReply reply;

    for (size_t offset = 0; offset < 24; offset++) {
        for (unsigned value = 0; value <= UINT8_MAX; value++) {
            int result;
            memcpy(input, golden_query, sizeof(input));
            input[offset] = (uint8_t)value;
            result = fuxi_audio_prep_gpr_decode(input, sizeof(input), &view);
            if (result == FuxiAudioPrepOk) {
                CHECK(view.header_bytes >= 24 && view.header_bytes <= sizeof(input));
                CHECK(view.payload == input + view.header_bytes);
                CHECK(view.payload_bytes == sizeof(input) - view.header_bytes);
            } else {
                CHECK(result >= FuxiAudioPrepReserved && result <= FuxiAudioPrepShort);
            }
            memcpy(input, golden_state, sizeof(golden_state));
            input[offset] = (uint8_t)value;
            result = fuxi_audio_prep_spf_reply(input, sizeof(golden_state),
                0x12345678, 0x89abcdef, &reply);
            if (result == FuxiAudioPrepOk) {
                CHECK(reply.kind == FuxiAudioPrepSpfState && reply.state == 1);
                CHECK(memcmp(input, golden_state, 6) == 0 && !(input[6] & 0xf0u) &&
                    memcmp(input + 7, golden_state + 7, sizeof(golden_state) - 7) == 0);
            } else {
                CHECK(result < 0);
            }
        }
    }
}

int main(void)
{
    test_golden_and_roundtrip();
    test_encode_failures();
    test_decode_boundaries();
    test_spf_replies();
    test_header_mutations();
    printf("PASS fuxi-audio-prep GPR: %u checks\n", checks);
    return 0;
}
