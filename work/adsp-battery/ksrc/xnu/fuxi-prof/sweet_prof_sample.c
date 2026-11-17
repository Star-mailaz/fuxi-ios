/* Saved user stacks are approximate; no target suspension or logging per sweep. */
#include <pexpert/arm64/board_config.h>
#if defined(FUXI)
#include <kern/task.h>
#include <kern/thread.h>
#include <kern/sched_prim.h>
#include <kern/clock.h>
#include <kern/kalloc.h>
#include <kern/misc_protos.h>
#include <kern/spl.h>
#include <arm/thread.h>
#include <arm64/proc_reg.h>
#include <vm/vm_map.h>
#include <vm/vm_shared_region.h>
#include <string.h>
#include "sweet_prof_logic.h"
#ifndef SP_NO_LIVE
#include <kern/processor.h>
#include <kern/cpu_number.h>
#include <machine/machine_routines.h>
/* Live user registers (FUXI). A thread on a core saves its user registers only at an exception, so the saved pc/lr of a thread
 * running user code are its last trap's. For a thread on a core the sweep cross-calls that core: the handler, in interrupt
 * context, copies the registers the IPI's own exception saved when it came from user mode (the last trap's when the core was in
 * the kernel) and reads no user memory; the sweep then walks the frames from that fp as before. One request per core at a
 * time: a core that has not answered its last request is skipped, so cpu_xcall never waits on one of ours. Such samples carry
 * x16 = 0x7fffffff; "PROF live" counts requests, answers from the thread, answers from another thread, and skips. */
#define SP_CPUS 16
struct sp_live { thread_t thread; uint64_t pc,lr,fp; uint32_t gen,done,ok; };
static struct sp_live sp_lives[SP_CPUS];
static uint32_t sp_live_gen;
static unsigned long long sp_live_n[4];
static uint64_t sp_live_wait;
static void sp_live_ipi(void *arg) {
 struct sp_live *l=arg;
 uint32_t g=__atomic_load_n(&l->gen,__ATOMIC_ACQUIRE),ok=0;
 thread_t t=current_thread();
 if(t==l->thread) {
  arm_saved_state_t *ss=find_user_regs(t);
  if(ss && is_saved_state64(ss)){l->pc=get_saved_state_pc(ss);l->lr=get_saved_state_lr(ss);l->fp=get_saved_state_fp(ss);ok=1;}
 }
 l->ok=ok;
 __atomic_store_n(&l->done,g,__ATOMIC_RELEASE);
}
static int sp_live(thread_t thread,int cpu,uint64_t *pc,uint64_t *lr,uint64_t *fp) {
 if(cpu<0 || cpu>=SP_CPUS || cpu==(int)cpu_number()){sp_live_n[3]++;return 0;}
 struct sp_live *l=&sp_lives[cpu];
 if(__atomic_load_n(&l->done,__ATOMIC_ACQUIRE)!=__atomic_load_n(&l->gen,__ATOMIC_RELAXED)){sp_live_n[3]++;return 0;}
 uint32_t g=++sp_live_gen;if(!g)g=++sp_live_gen;
 l->thread=thread;__atomic_store_n(&l->gen,g,__ATOMIC_RELEASE);sp_live_n[0]++;
 if(cpu_xcall(cpu,sp_live_ipi,l)!=KERN_SUCCESS){__atomic_store_n(&l->done,g,__ATOMIC_RELEASE);sp_live_n[3]++;return 0;}
 uint64_t until=mach_absolute_time()+sp_live_wait;
 while(__atomic_load_n(&l->done,__ATOMIC_ACQUIRE)!=g && mach_absolute_time()<until){}
 if(__atomic_load_n(&l->done,__ATOMIC_ACQUIRE)!=g){sp_live_n[3]++;return 0;}
 if(!l->ok){sp_live_n[2]++;return 0;}
 sp_live_n[1]++;*pc=l->pc;*lr=l->lr;*fp=l->fp;return 1;
}
/* Flat profile of the live samples: counts per (thread, 64-byte pc bucket), the top SP_PC_TOP printed at the end as
 * "PROFPC t<tid> 0x<bucket> <count>", so a thread's whole on-core time maps to functions offline (the keyed rows above
 * keep only each thread's twelve most frequent exact stacks). */
#define SP_PC_BUCKETS 8192u
#define SP_PC_TOP 300u
struct sp_pc { uint64_t tid,pc; unsigned n; };
static struct sp_pc sp_pcs[SP_PC_BUCKETS];
static unsigned sp_pc_dropped;
static void sp_pc_add(uint64_t tid,uint64_t pc) {
 pc&=~(uint64_t)63;
 uint64_t h=(pc>>6)^(tid*0x9e3779b97f4a7c15ULL);
 for(unsigned i=0;i<64;i++){
  struct sp_pc *e=&sp_pcs[(h+i)%SP_PC_BUCKETS];
  if(!e->n){e->tid=tid;e->pc=pc;e->n=1;return;}
  if(e->tid==tid && e->pc==pc){e->n++;return;}
 }
 sp_pc_dropped++;
}
static void sp_pc_print(void) {
 for(unsigned k=0;k<SP_PC_TOP;k++){
  unsigned best=SP_PC_BUCKETS;
  for(unsigned i=0;i<SP_PC_BUCKETS;i++)if(sp_pcs[i].n && (best==SP_PC_BUCKETS || sp_pcs[i].n>sp_pcs[best].n))best=i;
  if(best==SP_PC_BUCKETS)break;
  printf("PROFPC t%llu 0x%llx %u\n",(unsigned long long)sp_pcs[best].tid,(unsigned long long)sp_pcs[best].pc,sp_pcs[best].n);
  sp_pcs[best].n=0;
 }
 printf("PROFPC done dropped=%u\n",sp_pc_dropped);
}
/* Inclusive profile of CoreAnimation's display thread and the target's main thread (FUXI): every live sample of a thread named
 * com.apple.coreanimation.display* or of the task's first thread
 * counts once for each distinct 64-byte bucket among its pc, its lr and up to SP_INC_FRAMES return addresses of its frame chain,
 * so a function's count is the time spent in it and below it. Printed as "PROFINC t<tid> 0x<bucket> <count>" (top SP_INC_TOP)
 * and "PROFINC done samples= dropped= frames=". lr names a leaf's caller (a leaf such as memmove saves no frame). */
#define SP_INC_BUCKETS 16384u
#define SP_INC_TOP 380u
#define SP_INC_FRAMES 24u
static struct sp_pc sp_incs[SP_INC_BUCKETS];
static unsigned sp_inc_dropped,sp_inc_samples,sp_inc_by[3]; /* samples by class: 0 live (on a core), 1 waiting, 2 runnable off-core */
/* Call edges of the same samples: (callee bucket, caller bucket) of consecutive distinct entries of pc, lr, frames, so the callers
 * of any function can be summed offline ("PROFEDGE <class> 0x<callee> 0x<caller> <count>", top SP_EDGE_TOP). */
#define SP_EDGE_BUCKETS 16384u
#define SP_EDGE_TOP 900u
struct sp_edge { uint64_t a,b; unsigned n; };
static struct sp_edge sp_edges[SP_EDGE_BUCKETS];
static unsigned sp_edge_dropped;
static void sp_edge_add(uint64_t a,uint64_t b) {
 uint64_t h=(a>>2)*0x9e3779b97f4a7c15ULL^(b>>2);
 for(unsigned i=0;i<64;i++){
  struct sp_edge *e=&sp_edges[(h+i)%SP_EDGE_BUCKETS];
  if(!e->n){e->a=a;e->b=b;e->n=1;return;}
  if(e->a==a && e->b==b){e->n++;return;}
 }
 sp_edge_dropped++;
}
static unsigned long long sp_inc_frames;
static void sp_inc_add(uint64_t tid,uint64_t pc) {
 uint64_t h=(pc>>2)*0x9e3779b97f4a7c15ULL^tid;
 for(unsigned i=0;i<64;i++){
  struct sp_pc *e=&sp_incs[(h+i)%SP_INC_BUCKETS];
  if(!e->n){e->tid=tid;e->pc=pc;e->n=1;return;}
  if(e->tid==tid && e->pc==pc){e->n++;return;}
 }
 sp_inc_dropped++;
}
/* cls 0 live, 1 wait, 2 ready: off-core samples use the saved user state, exact for a thread blocked in a trap; the class is kept in
 * bits 60-61 of the key's tid so one bucket table holds both. */
static void sp_inc_sample(vm_map_t map,uint64_t tid,unsigned cls,uint64_t pc,uint64_t lr,uint64_t fp) {
 tid|=(uint64_t)cls<<60;
 uint64_t seen[SP_INC_FRAMES+2];unsigned k=0;
 const uint64_t mask=((uint64_t)1<<47)-1;
 /* a live pc is anywhere in a function: bucket it; return addresses (lr, frames) and a blocked thread's trap pc are exact call
  * sites, kept exact so they symbolize to the caller (a 64-byte bucket can start in the previous function). */
 seen[k++]=cls==0 ? (pc&mask)&~(uint64_t)63 : pc&mask;
 if(lr)seen[k++]=lr&mask;
 uint64_t base=fp;
 for(unsigned n=0;n<SP_INC_FRAMES && fp && !(fp&7) && fp>=base && fp-base<1024*1024;n++) {
  uint64_t frame[2];
  if(vm_map_read_user(map,fp,frame,sizeof(frame))!=KERN_SUCCESS)break;
  if(frame[1])seen[k++]=frame[1]&mask;
  sp_inc_frames++;
  if(frame[0]<=fp)break;fp=frame[0];
 }
 for(unsigned i=0;i<k;i++){
  unsigned dup=0;
  for(unsigned j=0;j<i;j++)if(seen[j]==seen[i]){dup=1;break;}
  if(!dup)sp_inc_add(tid,seen[i]);
 }
 for(unsigned i=0;i+1<k;i++){
  if(seen[i]==seen[i+1])continue;
  unsigned dup=0;
  for(unsigned j=0;j<i;j++)if(seen[j]==seen[i] && seen[j+1]==seen[i+1]){dup=1;break;}
  if(!dup)sp_edge_add(seen[i]|(uint64_t)cls<<60,seen[i+1]);
 }
 sp_inc_samples++;if(cls<3)sp_inc_by[cls]++;
}
static void sp_inc_print(void) {
 for(unsigned k=0;k<SP_INC_TOP;k++){
  unsigned best=SP_INC_BUCKETS;
  for(unsigned i=0;i<SP_INC_BUCKETS;i++)if(sp_incs[i].n && (best==SP_INC_BUCKETS || sp_incs[i].n>sp_incs[best].n))best=i;
  if(best==SP_INC_BUCKETS)break;
  printf("PROFINC t%llu %c 0x%llx %u\n",(unsigned long long)(sp_incs[best].tid&(((uint64_t)1<<60)-1)),"LWR?"[(sp_incs[best].tid>>60)&3],(unsigned long long)sp_incs[best].pc,sp_incs[best].n);
  sp_incs[best].n=0;
 }
 printf("PROFINC done samples=%u live=%u wait=%u ready=%u dropped=%u frames=%llu\n",sp_inc_samples,sp_inc_by[0],sp_inc_by[1],sp_inc_by[2],sp_inc_dropped,sp_inc_frames);
 for(unsigned k=0;k<SP_EDGE_TOP;k++){
  unsigned best=SP_EDGE_BUCKETS;
  for(unsigned i=0;i<SP_EDGE_BUCKETS;i++)if(sp_edges[i].n && (best==SP_EDGE_BUCKETS || sp_edges[i].n>sp_edges[best].n))best=i;
  if(best==SP_EDGE_BUCKETS)break;
  printf("PROFEDGE %c 0x%llx 0x%llx %u\n","LWR?"[(sp_edges[best].a>>60)&3],(unsigned long long)(sp_edges[best].a&(((uint64_t)1<<60)-1)),(unsigned long long)sp_edges[best].b,sp_edges[best].n);
  sp_edges[best].n=0;
 }
 printf("PROFEDGE done dropped=%u\n",sp_edge_dropped);
}
#endif
void sweet_prof_task(task_t task,int pid);
static void sp_sleep(uint64_t deadline,uint64_t leeway) {
 static int event;
 assert_wait_deadline_with_leeway(&event,THREAD_UNINT,TIMEOUT_URGENCY_SYS_NORMAL|TIMEOUT_URGENCY_LEEWAY,deadline,leeway);
 thread_block(THREAD_CONTINUE_NULL);
}
static void sp_sweep(task_t task,struct sp_table *p) {
 thread_t thread;vm_map_t map=get_task_map(task);
 int first=1;
 task_lock(task);
 queue_iterate(&task->threads,thread,thread_t,task_threads) {
  int is_main=first;first=0; /* the task's first thread: the main thread of SpringBoard (sweetprof=10000+N) */
  (void)is_main;
  struct sp_sample s={0};arm_saved_state_t *ss=find_user_regs(thread);
  if(!ss || !is_saved_state64(ss)){p->skipped++;continue;}
  spl_t level=splsched();thread_lock(thread);
  int state=thread->state;
  if(state&TH_TERMINATE){thread_unlock(thread);splx(level);p->skipped++;continue;}
  s.tid=thread->thread_id;s.event=thread->wait_event;s.wr=thread->wait_result;
  s.state=machine_thread_on_core(thread)?0:(state&TH_WAIT)?1:(state&TH_RUN)?2:3;
#ifndef SP_NO_LIVE
  int cpu=s.state==0 && thread->last_processor ? thread->last_processor->cpu_id : -1;
#endif
  thread_unlock(thread);splx(level);
  s.pc=get_saved_state_pc(ss);s.lr=get_saved_state_lr(ss);s.x16=(int32_t)get_saved_state_reg(ss,16);
  uint64_t fp=get_saved_state_fp(ss);
#ifndef SP_NO_LIVE
  int live=0;uint64_t live_fp=0;
  if(s.state==0 && sp_live(thread,cpu,&s.pc,&s.lr,&fp)){s.x16=0x7fffffff;sp_pc_add(s.tid,s.pc);live=1;live_fp=fp;}
#endif
  uint64_t base=fp;
  for(unsigned n=0;n<8 && fp && !(fp&7) && fp>=base && fp-base<1024*1024;n++) {
   uint64_t frame[2];
   if(vm_map_read_user(map,fp,frame,sizeof(frame))!=KERN_SUCCESS)break;
   s.bt[n]=frame[1];if(frame[0]<=fp)break;fp=frame[0];
  }
  unsigned t=sp_thread_index(p,s.tid);
  if(t==SP_THREADS)continue;
  if(!p->threads[t].name[0] && get_bsdthread_info(thread))thread_get_thread_name(thread,p->threads[t].name);
#ifndef SP_NO_LIVE
  if((is_main || !strncmp(p->threads[t].name,"com.apple.coreanimation.display",31)) && (live || s.state==1 || s.state==2))
   sp_inc_sample(map,s.tid,live ? 0 : s.state,s.pc,s.lr,live ? live_fp : get_saved_state_fp(ss));
#endif
  sp_add(p,t,&s);
 }
 task_unlock(task);p->sweeps++;
}
/* Diagnostic: the calling thread's user frames plus the shared cache slide, one console line. */
void sweet_prof_user_bt(const char *tag);
void sweet_prof_user_bt(const char *tag) {
 thread_t thread=current_thread();task_t task=current_task();arm_saved_state_t *ss=find_user_regs(thread);
 if(!ss || !is_saved_state64(ss))return;
 uint64_t slide=0,bt[12]={0};vm_shared_region_t sr=vm_shared_region_get(task);
 if(sr){slide=sr->sr_slide;vm_shared_region_deallocate(sr);}
 vm_map_t map=get_task_map(task);uint64_t fp=get_saved_state_fp(ss),base=fp;unsigned n=0;
 for(;n<12 && fp && !(fp&7) && fp>=base && fp-base<1024*1024;n++) {
  uint64_t frame[2];
  if(vm_map_read_user(map,fp,frame,sizeof(frame))!=KERN_SUCCESS)break;
  bt[n]=frame[1];if(frame[0]<=fp){n++;break;}fp=frame[0];
 }
 printf("%s slide 0x%llx pc 0x%llx lr 0x%llx bt",tag,(unsigned long long)slide,(unsigned long long)get_saved_state_pc(ss),(unsigned long long)get_saved_state_lr(ss));
 for(unsigned i=0;i<n;i++)printf(" 0x%llx",(unsigned long long)bt[i]);
 printf("\n");
}
void sweet_prof_task(task_t task,int pid) {
 uint64_t deadline,period,leeway,duration;
 struct sp_table *p=kalloc_data(sizeof(*p),Z_WAITOK|Z_ZERO);
 if(!p){printf("PROF allocation failed\n");return;}
 uint64_t slide=0;vm_shared_region_t sr=vm_shared_region_get(task);
 if(sr){slide=sr->sr_slide;vm_shared_region_deallocate(sr);}
 task_lock(task);uint64_t mh=task->mach_header_vm_address;task_unlock(task);
 nanoseconds_to_absolutetime(2*NSEC_PER_MSEC,&period);nanoseconds_to_absolutetime(100*NSEC_PER_USEC,&leeway);
 nanoseconds_to_absolutetime(60ULL*NSEC_PER_SEC,&duration);
#ifndef SP_NO_LIVE
 nanoseconds_to_absolutetime(200*NSEC_PER_USEC,&sp_live_wait);
 memset(sp_pcs,0,sizeof(sp_pcs));sp_pc_dropped=0;
 memset(sp_incs,0,sizeof(sp_incs));sp_inc_dropped=sp_inc_samples=0;sp_inc_frames=0;memset(sp_inc_by,0,sizeof(sp_inc_by));memset(sp_edges,0,sizeof(sp_edges));sp_edge_dropped=0;
#endif
 uint64_t start=mach_absolute_time(),end=start+duration;deadline=start;
 while(mach_absolute_time()<end) {
  sp_sweep(task,p);
  uint64_t now=mach_absolute_time();if(now>=end)break;deadline+=period;
  if(deadline<=now){p->late++;deadline=now+period;}
  if(deadline>end)deadline=end;
  sp_sleep(deadline,leeway);
 }
 printf("PROF backboardd[%d] slide 0x%llx mh 0x%llx\n",pid,(unsigned long long)slide,(unsigned long long)mh);
 sp_print(p);kfree_data(p,sizeof(*p));
#ifndef SP_NO_LIVE
 printf("PROF live asked=%llu thread=%llu other=%llu skipped=%llu\n",sp_live_n[0],sp_live_n[1],sp_live_n[2],sp_live_n[3]);
 sp_pc_print();
 sp_inc_print();
#endif
}
#endif
