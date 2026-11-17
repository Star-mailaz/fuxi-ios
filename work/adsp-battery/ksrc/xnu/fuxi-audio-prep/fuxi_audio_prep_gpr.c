#include "fuxi_audio_prep_gpr.h"

#include <string.h>

static uint32_t read_le32(const uint8_t *input)
{
    return (uint32_t)input[0] | ((uint32_t)input[1] << 8) |
        ((uint32_t)input[2] << 16) | ((uint32_t)input[3] << 24);
}

static void write_le32(uint8_t *output, uint32_t value)
{
    output[0] = (uint8_t)value;
    output[1] = (uint8_t)(value >> 8);
    output[2] = (uint8_t)(value >> 16);
    output[3] = (uint8_t)(value >> 24);
}

int fuxi_audio_prep_gpr_encode(uint8_t *output, size_t capacity,
    const FuxiAudioPrepGprFields *fields, const void *payload,
    size_t payload_bytes, size_t *written)
{
    FuxiAudioPrepGprFields header;
    size_t packet_bytes;

    if (!output || !fields || !written || (payload_bytes && !payload)) {
        return FuxiAudioPrepArgument;
    }
    if (fields->dst_domain > UINT8_MAX || fields->src_domain > UINT8_MAX ||
        payload_bytes > FUXI_AUDIO_PREP_GPR_MAX_BYTES - FUXI_AUDIO_PREP_GPR_HEADER_BYTES) {
        return FuxiAudioPrepRange;
    }
    packet_bytes = FUXI_AUDIO_PREP_GPR_HEADER_BYTES + payload_bytes;
    if (packet_bytes > capacity) {
        return FuxiAudioPrepCapacity;
    }

    header = *fields;
    if (payload_bytes) {
        memmove(output + FUXI_AUDIO_PREP_GPR_HEADER_BYTES, payload, payload_bytes);
    }
    write_le32(output, ((uint32_t)packet_bytes << 8) | 0x60u);
    write_le32(output + 4, header.dst_domain | (header.src_domain << 8));
    write_le32(output + 8, header.src_port);
    write_le32(output + 12, header.dst_port);
    write_le32(output + 16, header.token);
    write_le32(output + 20, header.opcode);
    *written = packet_bytes;
    return FuxiAudioPrepOk;
}

int fuxi_audio_prep_gpr_decode(const uint8_t *input, size_t length,
    FuxiAudioPrepGprView *view)
{
    FuxiAudioPrepGprView decoded;
    uint32_t size_word;
    uint32_t domain_word;

    if (!input || !view) {
        return FuxiAudioPrepArgument;
    }
    if (length < FUXI_AUDIO_PREP_GPR_HEADER_BYTES) {
        return FuxiAudioPrepShort;
    }
    if (length > FUXI_AUDIO_PREP_GPR_MAX_BYTES) {
        return FuxiAudioPrepLength;
    }
    size_word = read_le32(input);
    domain_word = read_le32(input + 4);
    if ((size_word & 0xfu) != 0) {
        return FuxiAudioPrepVersion;
    }
    decoded.header_bytes = ((size_word >> 4) & 0xfu) * 4u;
    decoded.packet_bytes = size_word >> 8;
    if (decoded.header_bytes < FUXI_AUDIO_PREP_GPR_HEADER_BYTES) {
        return FuxiAudioPrepHeader;
    }
    if (decoded.packet_bytes != length || decoded.header_bytes > length) {
        return FuxiAudioPrepLength;
    }
    if (domain_word & 0xfff00000u) {
        return FuxiAudioPrepReserved;
    }
    decoded.fields.dst_domain = domain_word & 0xffu;
    decoded.fields.src_domain = (domain_word >> 8) & 0xffu;
    decoded.client_data = (domain_word >> 16) & 0xfu;
    decoded.fields.src_port = read_le32(input + 8);
    decoded.fields.dst_port = read_le32(input + 12);
    decoded.fields.token = read_le32(input + 16);
    decoded.fields.opcode = read_le32(input + 20);
    decoded.payload = input + decoded.header_bytes;
    decoded.payload_bytes = length - decoded.header_bytes;
    *view = decoded;
    return FuxiAudioPrepOk;
}

int fuxi_audio_prep_spf_query(uint8_t *output, size_t capacity,
    uint32_t local_port, uint32_t token, size_t *written)
{
    const uint8_t command_header[FUXI_AUDIO_PREP_APM_HEADER_BYTES] = {0};
    const FuxiAudioPrepGprFields fields = {
        FUXI_AUDIO_PREP_DOMAIN_ADSP, FUXI_AUDIO_PREP_DOMAIN_APPS,
        local_port, FUXI_AUDIO_PREP_APM_PORT, token, FUXI_AUDIO_PREP_GET_SPF_STATE
    };

    return fuxi_audio_prep_gpr_encode(output, capacity, &fields,
        command_header, sizeof(command_header), written);
}

int fuxi_audio_prep_spf_reply(const uint8_t *input, size_t length,
    uint32_t local_port, uint32_t token, FuxiAudioPrepSpfReply *reply)
{
    FuxiAudioPrepGprView view;
    FuxiAudioPrepSpfReply decoded = {FuxiAudioPrepSpfState, 0, 0};
    int result;

    if (!reply) {
        return FuxiAudioPrepArgument;
    }
    result = fuxi_audio_prep_gpr_decode(input, length, &view);
    if (result != FuxiAudioPrepOk) {
        return result;
    }
    if (view.fields.src_domain != FUXI_AUDIO_PREP_DOMAIN_ADSP ||
        view.fields.dst_domain != FUXI_AUDIO_PREP_DOMAIN_APPS ||
        view.fields.src_port != FUXI_AUDIO_PREP_APM_PORT ||
        view.fields.dst_port != local_port || view.fields.token != token) {
        return FuxiAudioPrepRoute;
    }
    switch (view.fields.opcode) {
    case FUXI_AUDIO_PREP_SPF_STATE_REPLY:
        if (view.payload_bytes != 4) {
            return FuxiAudioPrepPayload;
        }
        decoded.state = read_le32(view.payload);
        break;
    case FUXI_AUDIO_PREP_BASIC_RESULT:
        if (view.payload_bytes != 8) {
            return FuxiAudioPrepPayload;
        }
        if (read_le32(view.payload) != FUXI_AUDIO_PREP_GET_SPF_STATE) {
            return FuxiAudioPrepOpcode;
        }
        decoded.status = read_le32(view.payload + 4);
        decoded.kind = decoded.status ? FuxiAudioPrepSpfRemoteError : FuxiAudioPrepSpfAccepted;
        break;
    default:
        return FuxiAudioPrepOpcode;
    }
    *reply = decoded;
    return FuxiAudioPrepOk;
}
