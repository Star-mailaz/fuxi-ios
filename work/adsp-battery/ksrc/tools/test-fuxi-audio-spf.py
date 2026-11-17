import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'xnu/fuxi-adsp'
PREP = ROOT / 'xnu/fuxi-audio-prep'

HOST = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "ShengAdsp.h"
#include "fuxi_audio_prep_gpr.h"
typedef void *DTEntry;
#define kSuccess 0
#define NSEC_PER_MSEC 1000000u
static uint64_t now;
static unsigned argument, adt_value, adt_bytes, registrations, sends, callback_depth, sent_length;
static bool have_argument, have_adt, register_failure;
static int send_error;
static ShengAdspClient callbacks;
static uint8_t sent[40];
struct ShengAdspChannel { unsigned marker; };
static struct ShengAdspChannel channel;
static uint64_t mach_absolute_time(void) { return now; }
static void clock_interval_to_deadline(unsigned interval,unsigned scale,uint64_t *deadline) {
    *deadline=now+(uint64_t)interval*scale;
}
static int PE_parse_boot_argn(const char *name,void *value,unsigned bytes) {
    assert(!strcmp(name,"fuxiaudiospf") && bytes==4);
    memcpy(value,&argument,bytes); return have_argument;
}
static int SecureDTLookupEntry(void *root,const char *name,DTEntry *entry) {
    assert(!root && !strcmp(name,"/chosen")); *entry=&adt_value; return have_adt?0:1;
}
static int SecureDTGetProperty(DTEntry entry,const char *name,const void **property,unsigned *bytes) {
    assert(entry==&adt_value && !strcmp(name,"fuxi,audio-spf"));
    *property=&adt_value; *bytes=adt_bytes; return 0;
}
ShengAdspChannel *sheng_adsp_channel(const char *name,uint32_t size,uint32_t count,int initiator,
    const ShengAdspClient *client,void *context) {
    assert(!strcmp(name,"adsp_apps") && size==512 && count==20 && !initiator && !context);
    assert(!callback_depth); callbacks=*client; registrations++;
    return register_failure?NULL:&channel;
}
int sheng_adsp_send(ShengAdspChannel *target,const void *data,uint32_t length) {
    assert(target==&channel && (length==24 || length==40) && !callback_depth);
    memcpy(sent,data,length); sent_length=length; sends++; return send_error;
}
#include "fuxi_audio_spf.c"
static void reset(void) {
    memset(&gSpf,0,sizeof(gSpf)); memset(&callbacks,0,sizeof(callbacks));
    now=0; argument=0; adt_value=0; adt_bytes=4;
    registrations=0; sends=0; callback_depth=0; sent_length=0;
    have_argument=false; have_adt=false; register_failure=false; send_error=0;
}
static void state(int up) {
    callback_depth++; callbacks.state(NULL,up); callback_depth--;
}
static void deliver(uint32_t opcode,uint32_t token,uint32_t status) {
    uint8_t packet[512]={0}, payload[8]={0}; size_t length=0;
    FuxiAudioPrepGprFields fields={3,2,1,FUXI_SPF_PORT,token,opcode};
    unsigned bytes=4;
    if(opcode==FUXI_AUDIO_PREP_BASIC_RESULT) {
        uint32_t command=FUXI_AUDIO_PREP_GET_SPF_STATE;
        memcpy(payload,&command,4); memcpy(payload+4,&status,4); bytes=8;
    } else memcpy(payload,&status,4);
    assert(!fuxi_audio_prep_gpr_encode(packet,sizeof(packet),&fields,payload,bytes,&length));
    packet[6]=1;
    callback_depth++; callbacks.receive(NULL,packet,(uint32_t)length); callback_depth--;
}
static void begin(void) {
    reset(); have_adt=true; adt_value=1; fuxi_audio_spf_start();
    assert(registrations==1 && !sends); state(1); fuxi_audio_spf_poll();
    assert(sends==1 && gSpf.attempted && !gSpf.done);
    FuxiAudioPrepGprView query;
    assert(!fuxi_audio_prep_gpr_decode(sent,sizeof(sent),&query));
    assert(query.fields.opcode==FUXI_AUDIO_PREP_GET_SPF_STATE &&
           query.fields.src_port==FUXI_SPF_PORT && query.fields.token==FUXI_SPF_TOKEN &&
           query.payload_bytes==16);
    for(unsigned index=0;index<16;index++) assert(!query.payload[index]);
}
int main(void) {
    reset(); fuxi_audio_spf_start(); fuxi_audio_spf_poll(); assert(!registrations && !sends);
    for(unsigned value=0;value<4;value++) {
        reset(); have_adt=true; adt_value=value; fuxi_audio_spf_start();
        assert(registrations==(value==1 || value==2));
    }
    reset(); have_adt=true; adt_value=1; adt_bytes=8;
    fuxi_audio_spf_start(); assert(!registrations);
    reset(); have_adt=true; adt_value=1; have_argument=true; argument=0;
    fuxi_audio_spf_start(); assert(!registrations);
    reset(); have_argument=true; argument=1;
    fuxi_audio_spf_start(); fuxi_audio_spf_start(); assert(registrations==1);
    reset(); have_adt=true; adt_value=2;
    fuxi_audio_spf_start(); state(1); fuxi_audio_spf_poll();
    assert(sends==1 && sent_length==24);
    FuxiAudioPrepGprView bare;
    assert(!fuxi_audio_prep_gpr_decode(sent,sent_length,&bare) &&
           !bare.payload_bytes && bare.fields.opcode==FUXI_AUDIO_PREP_GET_SPF_STATE);
    deliver(FUXI_AUDIO_PREP_SPF_STATE_REPLY,FUXI_SPF_TOKEN,1);
    fuxi_audio_spf_poll(); assert(gSpf.done && gSpf.reply.state==1);
    reset(); have_adt=true; adt_value=1; register_failure=true;
    fuxi_audio_spf_start(); fuxi_audio_spf_start(); assert(registrations==1 && gSpf.done);
    reset(); have_adt=true; adt_value=1; fuxi_audio_spf_start();
    now=15000ull*NSEC_PER_MSEC; fuxi_audio_spf_poll(); assert(gSpf.done && !sends);
    begin(); deliver(FUXI_AUDIO_PREP_BASIC_RESULT,FUXI_SPF_TOKEN,0);
    fuxi_audio_spf_poll(); assert(gSpf.accepted && !gSpf.done && sends==1);
    deliver(FUXI_AUDIO_PREP_SPF_STATE_REPLY,FUXI_SPF_TOKEN,1);
    fuxi_audio_spf_poll(); assert(gSpf.done && gSpf.reply.state==1 && sends==1);
    state(0); state(1); fuxi_audio_spf_poll(); assert(sends==1);
    begin();
    for(unsigned index=0;index<10;index++)
        deliver(FUXI_AUDIO_PREP_SPF_STATE_REPLY,FUXI_SPF_TOKEN+1,1);
    assert(gSpf.invalid==4 && !gSpf.reply_ready);
    assert(gSpf.rejected[0].length==28 && gSpf.rejected[0].result==FuxiAudioPrepRoute &&
           gSpf.rejected[0].header[4]==FUXI_SPF_TOKEN+1 &&
           gSpf.rejected[0].header[5]==FUXI_AUDIO_PREP_SPF_STATE_REPLY);
    uint8_t oversized[513]={0};
    callbacks.receive(NULL,oversized,sizeof(oversized));
    assert(gSpf.invalid==4);
    /* 回覆期限 1 秒：逾時後等 100 ms 才重問，下一次用新 token。 */
    now=999ull*NSEC_PER_MSEC; fuxi_audio_spf_poll(); assert(!gSpf.timeouts && sends==1);
    now=1000ull*NSEC_PER_MSEC; fuxi_audio_spf_poll();
    assert(gSpf.timeouts==1 && !gSpf.waiting && !gSpf.done && sends==1);
    now=1099ull*NSEC_PER_MSEC; fuxi_audio_spf_poll(); assert(sends==1);
    now=1100ull*NSEC_PER_MSEC; fuxi_audio_spf_poll();
    assert(sends==2 && gSpf.waiting && gSpf.token==FUXI_SPF_TOKEN+1);
    FuxiAudioPrepGprView second;
    assert(!fuxi_audio_prep_gpr_decode(sent,sizeof(sent),&second) && second.fields.token==FUXI_SPF_TOKEN+1);
    deliver(FUXI_AUDIO_PREP_SPF_STATE_REPLY,FUXI_SPF_TOKEN,1);
    assert(!gSpf.reply_ready);
    deliver(FUXI_AUDIO_PREP_SPF_STATE_REPLY,FUXI_SPF_TOKEN+1,1);
    fuxi_audio_spf_poll(); assert(gSpf.done && gSpf.queries==2 && gSpf.timeouts==1);
    /* 遠端錯誤與未就緒都重問，直到 state 1。 */
    begin(); deliver(FUXI_AUDIO_PREP_BASIC_RESULT,FUXI_SPF_TOKEN,5);
    fuxi_audio_spf_poll();
    assert(!gSpf.done && gSpf.errors==1 && gSpf.last_status==5 && gSpf.reported_first && sends==1);
    for(unsigned index=1;index<4;index++) {
        now+=100ull*NSEC_PER_MSEC; fuxi_audio_spf_poll();
        assert(sends==index+1 && gSpf.token==FUXI_SPF_TOKEN+index);
        deliver(FUXI_AUDIO_PREP_SPF_STATE_REPLY,FUXI_SPF_TOKEN+index,index==3?1:0);
        fuxi_audio_spf_poll();
    }
    assert(gSpf.done && gSpf.queries==4 && gSpf.not_ready==2 && gSpf.errors==1 && gSpf.last_state==1);
    now+=1000ull*NSEC_PER_MSEC; fuxi_audio_spf_poll(); assert(sends==4);
    /* 一律未就緒：第 100 次後停止，不再送。 */
    begin();
    for(unsigned index=0;index<FUXI_SPF_MAX_QUERIES;index++) {
        assert(sends==index+1);
        deliver(FUXI_AUDIO_PREP_SPF_STATE_REPLY,FUXI_SPF_TOKEN+index,0);
        fuxi_audio_spf_poll();
        now+=100ull*NSEC_PER_MSEC; fuxi_audio_spf_poll();
    }
    assert(gSpf.done && sends==FUXI_SPF_MAX_QUERIES && gSpf.not_ready==FUXI_SPF_MAX_QUERIES);
    now+=10000ull*NSEC_PER_MSEC; fuxi_audio_spf_poll(); assert(sends==FUXI_SPF_MAX_QUERIES);
    /* 一律逾時：同樣在第 100 次後停止。 */
    begin();
    for(unsigned index=0;index<2*FUXI_SPF_MAX_QUERIES+5;index++) {
        now+=1000ull*NSEC_PER_MSEC; fuxi_audio_spf_poll();
    }
    assert(gSpf.done && sends==FUXI_SPF_MAX_QUERIES && gSpf.timeouts==FUXI_SPF_MAX_QUERIES);
    /* 兩次查詢之間斷線就結束。 */
    begin(); deliver(FUXI_AUDIO_PREP_SPF_STATE_REPLY,FUXI_SPF_TOKEN,0); fuxi_audio_spf_poll();
    assert(!gSpf.done && !gSpf.waiting);
    state(0); fuxi_audio_spf_poll(); assert(gSpf.done);
    state(1); now+=1000ull*NSEC_PER_MSEC; fuxi_audio_spf_poll(); assert(sends==1);
    begin(); state(0); state(1); fuxi_audio_spf_poll(); assert(gSpf.done && sends==1);
    begin(); now=1000ull*NSEC_PER_MSEC;
    deliver(FUXI_AUDIO_PREP_SPF_STATE_REPLY,FUXI_SPF_TOKEN,1);
    assert(!gSpf.reply_ready);
    fuxi_audio_spf_poll(); assert(!gSpf.done && gSpf.timeouts==1 && sends==1);
    reset(); have_adt=true; adt_value=1; send_error=-1;
    fuxi_audio_spf_start(); state(1); fuxi_audio_spf_poll();
    assert(gSpf.done && sends==1); fuxi_audio_spf_poll(); assert(sends==1);
    /* 之後的重問送出失敗也結束。 */
    begin(); deliver(FUXI_AUDIO_PREP_SPF_STATE_REPLY,FUXI_SPF_TOKEN,0); fuxi_audio_spf_poll();
    send_error=-1; now+=100ull*NSEC_PER_MSEC; fuxi_audio_spf_poll();
    assert(gSpf.done && sends==2 && gSpf.queries==1);
    now+=1000ull*NSEC_PER_MSEC; fuxi_audio_spf_poll(); assert(sends==2);
    puts("PASS production audio SPF client: default off, ADT gate, exact query, callback send exclusion, reply route/token, bounded rejection, at most 100 spaced queries with fresh tokens, per-query deadlines and disconnect; DSP simulated");
}
'''


def main():
    owner = (SOURCE / 'fuxi_adsp.c').read_text()
    assert owner.count('fuxi_audio_spf_start();') == 1
    assert owner.count('fuxi_audio_spf_poll();') == 1
    assert owner.index('gStarted = 1;') < owner.index('fuxi_audio_spf_start();')
    assert owner.index('fuxi_audio_spf_start();') < owner.index('kernel_thread_start(adspThread')
    with tempfile.TemporaryDirectory(prefix='fuxi-audio-spf-') as temporary:
        directory = Path(temporary)
        for name in ('pexpert/arm64/board_config.h', 'sys/systm.h', 'kern/clock.h',
                     'pexpert/pexpert.h', 'pexpert/device_tree.h'):
            header = directory / name
            header.parent.mkdir(parents=True, exist_ok=True)
            header.write_text('')
        source = directory / 'host.c'
        source.write_text(HOST)
        executable = directory / 'host'
        subprocess.run([os.environ.get('CC', 'clang'), '-std=c11', '-O1', '-g', '-DFUXI',
                        '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', '-I', str(directory), '-I', str(SOURCE),
                        '-I', str(PREP), str(source), str(PREP / 'fuxi_audio_prep_gpr.c'),
                        '-o', str(executable)], check=True)
        subprocess.run([str(executable)], check=True, timeout=20)


if __name__ == '__main__':
    main()
