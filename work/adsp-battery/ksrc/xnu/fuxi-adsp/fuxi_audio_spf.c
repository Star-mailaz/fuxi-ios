#include <pexpert/arm64/board_config.h>
#if defined(FUXI)
#include <sys/systm.h>
#include <kern/clock.h>
#include <pexpert/pexpert.h>
#include <pexpert/device_tree.h>
#include "ShengAdsp.h"
#include "fuxi_audio_prep_gpr.h"

#define FUXI_SPF_PORT 0x1000u
#define FUXI_SPF_TOKEN 0x53504601u
#define FUXI_SPF_INTENT_BYTES 512u
/* 與 Sheng 參考實作相同：DSP 剛起來時常回「未就緒」，最多問 100 次，每次等 1 秒回覆、間隔至少 100 ms。 */
#define FUXI_SPF_MAX_QUERIES 100u
#define FUXI_SPF_REPLY_MS 1000u
#define FUXI_SPF_GAP_MS 100u

static struct {
    ShengAdspChannel *channel;
    uint64_t deadline;   /* 第一次查詢前是 channel 期限，之後是目前這次查詢的回覆期限 */
    uint64_t next_query; /* 未就緒、錯誤或逾時後，下一次查詢最早的時間 */
    FuxiAudioPrepSpfReply reply;
    struct {
        uint32_t length, header[6];
        int result;
    } rejected[4];
    unsigned invalid, reported_invalid, format;
    unsigned queries, not_ready, errors, timeouts;
    uint32_t token, last_state, last_status;
    int up, attempted, waiting, done, accepted, reported_accepted, reported_first, reply_ready, disconnected;
} gSpf;

void fuxi_audio_spf_start(void);
void fuxi_audio_spf_poll(void);

static unsigned format(void)
{
    uint32_t value = 0;
    DTEntry chosen;
    const void *property;
    unsigned bytes;
    if (PE_parse_boot_argn("fuxiaudiospf", &value, sizeof(value)))
        return value == 1 || value == 2 ? value : 0;
    if (SecureDTLookupEntry(NULL, "/chosen", &chosen) == kSuccess &&
        SecureDTGetProperty(chosen, "fuxi,audio-spf", &property, &bytes) == kSuccess &&
        bytes == sizeof(value))
        memcpy(&value, property, sizeof(value));
    return value == 1 || value == 2 ? value : 0;
}

static void channel_state(void *context, int up)
{
    (void)context;
    gSpf.up = up != 0;
    if (!up && gSpf.attempted && !gSpf.done)
        gSpf.disconnected = 1;
}

static void channel_receive(void *context, const uint8_t *data, uint32_t length)
{
    FuxiAudioPrepSpfReply reply;
    int result;
    (void)context;
    if (!gSpf.waiting || gSpf.done || !gSpf.up || gSpf.disconnected || gSpf.reply_ready ||
        mach_absolute_time() >= gSpf.deadline)
        return;
    result = length > FUXI_SPF_INTENT_BYTES ? FuxiAudioPrepLength :
        fuxi_audio_prep_spf_reply(data, length, FUXI_SPF_PORT, gSpf.token, &reply);
    if (result) {
        if (gSpf.invalid < 4) {
            gSpf.rejected[gSpf.invalid].length = length;
            gSpf.rejected[gSpf.invalid].result = result;
            if (data && length >= 24 && length <= FUXI_SPF_INTENT_BYTES)
                memcpy(gSpf.rejected[gSpf.invalid].header, data, 24);
            gSpf.invalid++;
        }
        return;
    }
    if (reply.kind == FuxiAudioPrepSpfAccepted) {
        gSpf.accepted = 1;
    } else {
        gSpf.reply = reply;
        gSpf.reply_ready = 1;
    }
}

void fuxi_audio_spf_start(void)
{
    const ShengAdspClient client = {channel_state, channel_receive};
    if (gSpf.channel || gSpf.done)
        return;
    gSpf.format = format();
    if (!gSpf.format)
        return;
    gSpf.channel = sheng_adsp_channel("adsp_apps", FUXI_SPF_INTENT_BYTES, 20, 0, &client, NULL);
    if (!gSpf.channel) {
        gSpf.done = 1;
        printf("FUXI AUDIO SPF: channel registration failed\n");
        return;
    }
    clock_interval_to_deadline(15000, NSEC_PER_MSEC, &gSpf.deadline);
    printf("FUXI AUDIO SPF: registered adsp_apps query-only client\n");
}

static void retry_or_stop(void)
{
    gSpf.waiting = 0;
    if (gSpf.queries >= FUXI_SPF_MAX_QUERIES) {
        gSpf.done = 1;
        printf("FUXI AUDIO SPF: not ready after %u queries (not ready %u, errors %u, timeouts %u, last state %u status %u)\n",
            gSpf.queries, gSpf.not_ready, gSpf.errors, gSpf.timeouts, gSpf.last_state, gSpf.last_status);
        return;
    }
    clock_interval_to_deadline(FUXI_SPF_GAP_MS, NSEC_PER_MSEC, &gSpf.next_query);
}

void fuxi_audio_spf_poll(void)
{
    uint8_t packet[40];
    size_t length = 0;
    int result;
    if (!gSpf.channel || gSpf.done)
        return;
    if (gSpf.disconnected) {
        gSpf.done = 1;
        printf("FUXI AUDIO SPF: channel closed before state reply\n");
        return;
    }
    while (gSpf.reported_invalid < gSpf.invalid) {
        unsigned index = gSpf.reported_invalid++;
        const uint32_t *header = gSpf.rejected[index].header;
        printf("FUXI AUDIO SPF: rejected reply %u error %d bytes %u header %#x route %#x ports %#x/%#x token %#x opcode %#x\n",
            index + 1, gSpf.rejected[index].result, gSpf.rejected[index].length,
            header[0], header[1], header[2], header[3], header[4], header[5]);
    }
    if (gSpf.accepted && !gSpf.reported_accepted) {
        gSpf.reported_accepted = 1;
        printf("FUXI AUDIO SPF: query accepted, awaiting state\n");
    }
    if (gSpf.reply_ready) {
        gSpf.reply_ready = 0;
        if (gSpf.reply.kind == FuxiAudioPrepSpfRemoteError) {
            gSpf.errors++;
            gSpf.last_status = gSpf.reply.status;
        } else {
            gSpf.last_state = gSpf.reply.state;
            if (gSpf.reply.state == 1) {
                gSpf.done = 1;
                gSpf.waiting = 0;
                printf("FUXI AUDIO SPF: state 1 after %u queries (not ready %u, errors %u, timeouts %u), playback untested\n",
                    gSpf.queries, gSpf.not_ready, gSpf.errors, gSpf.timeouts);
                return;
            }
            gSpf.not_ready++;
        }
        if (!gSpf.reported_first) {
            gSpf.reported_first = 1;
            if (gSpf.reply.kind == FuxiAudioPrepSpfRemoteError)
                printf("FUXI AUDIO SPF: first answer remote error %u, retrying\n", gSpf.reply.status);
            else
                printf("FUXI AUDIO SPF: first answer state %u, retrying\n", gSpf.reply.state);
        }
        retry_or_stop();
        return;
    }
    if (gSpf.waiting) {
        if (!gSpf.up) {
            gSpf.done = 1;
            printf("FUXI AUDIO SPF: channel closed before state reply\n");
        } else if (mach_absolute_time() >= gSpf.deadline) {
            gSpf.timeouts++;
            retry_or_stop();
        }
        return;
    }
    if (!gSpf.attempted && mach_absolute_time() >= gSpf.deadline) {
        gSpf.done = 1;
        printf("FUXI AUDIO SPF: channel timeout\n");
        return;
    }
    if (!gSpf.up) {
        if (gSpf.attempted) {
            gSpf.done = 1;
            printf("FUXI AUDIO SPF: channel closed before state reply\n");
        }
        return;
    }
    if (gSpf.attempted && mach_absolute_time() < gSpf.next_query)
        return;
    gSpf.token = FUXI_SPF_TOKEN + gSpf.queries;
    if (gSpf.format == 2) {
        const FuxiAudioPrepGprFields fields = {
            FUXI_AUDIO_PREP_DOMAIN_ADSP, FUXI_AUDIO_PREP_DOMAIN_APPS,
            FUXI_SPF_PORT, FUXI_AUDIO_PREP_APM_PORT, gSpf.token, FUXI_AUDIO_PREP_GET_SPF_STATE
        };
        result = fuxi_audio_prep_gpr_encode(packet, sizeof(packet), &fields, NULL, 0, &length);
    } else {
        result = fuxi_audio_prep_spf_query(packet, sizeof(packet), FUXI_SPF_PORT, gSpf.token, &length);
    }
    if (!result && length == (gSpf.format == 2 ? 24u : 40u))
        result = sheng_adsp_send(gSpf.channel, packet, (uint32_t)length);
    else if (!result)
        result = FuxiAudioPrepLength;
    gSpf.attempted = 1;
    if (result) {
        gSpf.done = 1;
        printf("FUXI AUDIO SPF: query queue failed %d after %u queries\n", result, gSpf.queries);
        return;
    }
    gSpf.queries++;
    gSpf.waiting = 1;
    clock_interval_to_deadline(FUXI_SPF_REPLY_MS, NSEC_PER_MSEC, &gSpf.deadline);
    if (gSpf.queries == 1)
        printf("FUXI AUDIO SPF: state query queued bytes %u\n", (unsigned)length);
}
#endif
