#ifndef FUXI_TORCH_AUDIT_H
#define FUXI_TORCH_AUDIT_H
#include <stdint.h>

#define FUXI_TORCH_AUDIT_CAPACITY 64u

typedef struct {
    unsigned operation;
    unsigned offset;
    uint8_t value;
    int result;
    uint64_t elapsed_us;
} FuxiTorchAuditEvent;

typedef struct {
    uint64_t started;
    unsigned count;
    unsigned dropped;
    FuxiTorchAuditEvent events[FUXI_TORCH_AUDIT_CAPACITY];
} FuxiTorchAudit;

static inline void fuxi_torch_audit_begin(FuxiTorchAudit *audit, uint64_t now)
{
    if (!audit) return;
    audit->started = now;
    audit->count = 0;
    audit->dropped = 0;
}

static inline void fuxi_torch_audit_record(FuxiTorchAudit *audit, unsigned operation,
    unsigned offset, uint8_t value, int result, uint64_t now)
{
    if (!audit) return;
    if (audit->count >= FUXI_TORCH_AUDIT_CAPACITY) {
        if (audit->dropped != UINT32_MAX) audit->dropped++;
        return;
    }
    FuxiTorchAuditEvent *event = &audit->events[audit->count++];
    event->operation = operation;
    event->offset = offset;
    event->value = value;
    event->result = result;
    event->elapsed_us = now >= audit->started ? (now - audit->started) / 1000 : UINT64_MAX;
}
#endif
