#ifndef FUXI_AUDIO_PREP_GPR_H
#define FUXI_AUDIO_PREP_GPR_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define FUXI_AUDIO_PREP_GPR_HEADER_BYTES 24u
#define FUXI_AUDIO_PREP_GPR_MAX_BYTES 560u
#define FUXI_AUDIO_PREP_APM_HEADER_BYTES 16u
#define FUXI_AUDIO_PREP_DOMAIN_ADSP 2u
#define FUXI_AUDIO_PREP_DOMAIN_APPS 3u
#define FUXI_AUDIO_PREP_APM_PORT 1u
#define FUXI_AUDIO_PREP_GET_SPF_STATE 0x01001021u
#define FUXI_AUDIO_PREP_SPF_STATE_REPLY 0x02001007u
#define FUXI_AUDIO_PREP_BASIC_RESULT 0x02001005u

enum FuxiAudioPrepResult {
    FuxiAudioPrepOk = 0,
    FuxiAudioPrepArgument = -1,
    FuxiAudioPrepShort = -2,
    FuxiAudioPrepVersion = -3,
    FuxiAudioPrepHeader = -4,
    FuxiAudioPrepLength = -5,
    FuxiAudioPrepReserved = -6,
    FuxiAudioPrepRoute = -7,
    FuxiAudioPrepOpcode = -8,
    FuxiAudioPrepPayload = -9,
    FuxiAudioPrepCapacity = -10,
    FuxiAudioPrepRange = -11
};

typedef struct {
    uint32_t dst_domain;
    uint32_t src_domain;
    uint32_t src_port;
    uint32_t dst_port;
    uint32_t token;
    uint32_t opcode;
} FuxiAudioPrepGprFields;

typedef struct {
    FuxiAudioPrepGprFields fields;
    uint32_t client_data;
    size_t header_bytes;
    size_t packet_bytes;
    const uint8_t *payload;
    size_t payload_bytes;
} FuxiAudioPrepGprView;

enum FuxiAudioPrepSpfReplyKind {
    FuxiAudioPrepSpfState,
    FuxiAudioPrepSpfAccepted,
    FuxiAudioPrepSpfRemoteError
};

typedef struct {
    enum FuxiAudioPrepSpfReplyKind kind;
    uint32_t state;
    uint32_t status;
} FuxiAudioPrepSpfReply;

int fuxi_audio_prep_gpr_encode(uint8_t *output, size_t capacity,
    const FuxiAudioPrepGprFields *fields, const void *payload,
    size_t payload_bytes, size_t *written);
int fuxi_audio_prep_gpr_decode(const uint8_t *input, size_t length,
    FuxiAudioPrepGprView *view);
int fuxi_audio_prep_spf_query(uint8_t *output, size_t capacity,
    uint32_t local_port, uint32_t token, size_t *written);
int fuxi_audio_prep_spf_reply(const uint8_t *input, size_t length,
    uint32_t local_port, uint32_t token, FuxiAudioPrepSpfReply *reply);

#ifdef __cplusplus
}
#endif

#endif
