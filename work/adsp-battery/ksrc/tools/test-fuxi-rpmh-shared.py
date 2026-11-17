import os
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
sources = root / 'xnu/fuxi-adsp'
shared = re.sub(r'^#include .*\n', '', (sources / 'fuxi_rpmh_shared.c').read_text(), flags=re.M)
adsp = (sources / 'fuxi_adsp.c').read_text()
vote = 'static int vote(' + adsp.split('static int vote(', 1)[1].split('/* ---- secure world calls ---- */', 1)[0]
preamble = r'''
#define FUXI 1
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "QcomRpmh.h"
#include "fuxi_rpmh_shared.h"
#define LCK_GRP_DECLARE(name,label) int name __attribute__((unused))
#define LCK_MTX_DECLARE(name,group) pthread_mutex_t name=PTHREAD_MUTEX_INITIALIZER
#define lck_mtx_lock pthread_mutex_lock
#define lck_mtx_unlock pthread_mutex_unlock
'''
model = r'''
#define FA_RSC_TCS 0xd00u
struct fa_window {unsigned unused;};
static struct fa_window gRsc;
static int gTcs=-1;
static unsigned gRscBits, gVoteLcx, gVoteLmx, gVoteDone;
static QcomRscLayout gLayout;
static QcomRpmhResource gLcx, gLmx;
static uint32_t registers[0x4000/4];
static unsigned writes, delays, triggers, stall, bad_cleanup;
static uint32_t rd(struct fa_window *window, uint32_t offset) {
    assert(window==&gRsc && !(offset&3) && offset<sizeof(registers));
    return registers[offset/4];
}
static void wr(struct fa_window *window, uint32_t offset, uint32_t value) {
    assert(window==&gRsc && !(offset&3) && offset<sizeof(registers));
    assert(pthread_mutex_trylock(&fuxi_rpmh_mutex)==EBUSY);
    writes++;
    if(offset==FA_RSC_TCS+8) {registers[(FA_RSC_TCS+4)/4]&=~value; return;}
    if(offset==FA_RSC_TCS+0x2a0+0x24 && !value && bad_cleanup && triggers) return;
    registers[offset/4]=value;
    if(offset==FA_RSC_TCS+0x2a0+0x24 && value==0x1010000) {
        triggers++;
        if(!stall) registers[(FA_RSC_TCS+4)/4]|=2;
    }
}
static void delay(unsigned microseconds) {delays+=microseconds;}
'''
tests = r'''
static unsigned active, sequences;
static void *worker(void *context) {
    const unsigned owner=(unsigned)(uintptr_t)context;
    for(unsigned round=0;round<2000;round++) {
        assert(!fuxi_rpmh_acquire());
        assert(!__atomic_fetch_add(&active,1,__ATOMIC_RELAXED));
        static unsigned command;
        command=owner;
        sched_yield();
        assert(command==owner);
        sequences++;
        assert(__atomic_fetch_sub(&active,1,__ATOMIC_RELAXED)==1);
        fuxi_rpmh_release(1);
    }
    return NULL;
}
static void fixture(void) {
    fuxi_rpmh_failed=0;
    memset(registers,0,sizeof(registers));
    gLayout=qcom_rsc_layout(3u<<16);
    gLcx.address=0x123400; gLmx.address=0x567800;
    gTcs=-1; gRscBits=gVoteLcx=gVoteLmx=gVoteDone=0;
    writes=delays=triggers=stall=bad_cleanup=0;
    registers[FA_RSC_TCS/4]=0xa5;
    registers[(FA_RSC_TCS+0x2a0+0x28)/4]=1;
    registers[(FA_RSC_TCS+0x2c)/4]=0xdead;
}
int main(void) {
    pthread_t workers[4];
    for(uintptr_t index=0;index<4;index++) assert(!pthread_create(&workers[index],NULL,worker,(void *)(index+1)));
    for(unsigned index=0;index<4;index++) assert(!pthread_join(workers[index],NULL));
    assert(!active && sequences==8000 && !fuxi_rpmh_failed);
    fixture(); assert(!vote(9,8));
    assert(triggers==1 && gVoteDone && gVoteLcx==9 && gVoteLmx==8);
    assert(registers[(FA_RSC_TCS+0x2a0+0x38)/4]==0x123400);
    assert(registers[(FA_RSC_TCS+0x2a0+0x3c)/4]==9);
    assert(registers[(FA_RSC_TCS+0x2a0+24+0x38)/4]==0x567800);
    assert(registers[(FA_RSC_TCS+0x2a0+24+0x3c)/4]==8);
    assert(registers[FA_RSC_TCS/4]==0xa5 && registers[(FA_RSC_TCS+0x2c)/4]==0xdead);
    assert(!registers[(FA_RSC_TCS+0x2a0+0x20)/4] && !fuxi_rpmh_failed);
    assert(!vote(0,0) && triggers==2 && !gVoteLcx && !gVoteLmx);
    const unsigned offsets[]={0x24,0x2c,0x20};
    for(unsigned index=0;index<3;index++) {
        fixture(); registers[(FA_RSC_TCS+0x2a0+offsets[index])/4]=1;
        assert(vote(1,1)==-EBUSY && !writes && !fuxi_rpmh_failed);
    }
    fixture(); registers[(FA_RSC_TCS+0x2a0+0x28)/4]=0;
    assert(vote(1,1)==-EBUSY && !writes && !fuxi_rpmh_failed);
    fixture(); registers[(FA_RSC_TCS+4)/4]=2;
    assert(vote(1,1)==-EBUSY && !writes && !fuxi_rpmh_failed);
    fixture(); registers[FA_RSC_TCS/4]=0xa7;
    assert(!vote(1,1) && registers[FA_RSC_TCS/4]==0xa7);
    fixture(); stall=1;
    assert(vote(1,1)==-ETIMEDOUT && delays==100000 && fuxi_rpmh_failed && !gVoteDone);
    unsigned old_writes=writes;
    assert(vote(2,2)==-EIO && writes==old_writes);
    fixture(); bad_cleanup=1;
    assert(vote(1,1)==-EIO && fuxi_rpmh_failed && !gVoteDone);
    assert(fuxi_rpmh_acquire()==-1);
    puts("PASS: shared RSC mutex, concurrent owners, real ADSP transaction, cleanup, timeout and quarantine");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='fuxi-rpmh-shared-') as temporary:
    directory = Path(temporary)
    cfile = directory / 'shared.c'
    binary = directory / 'shared'
    cfile.write_text(preamble + shared + model + vote + tests)
    subprocess.run([os.environ.get('CC', 'cc'), '-std=c11', '-g', '-Wall', '-Wextra', '-Werror',
                    '-pthread', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
                    '-I' + str(sources), str(cfile), str(sources / 'QcomRpmh.c'), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
