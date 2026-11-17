#ifndef FUXI_HAPTIC_FIFO_H
#define FUXI_HAPTIC_FIFO_H

#include <stddef.h>
#include <stdint.h>

#define FUXI_HAPTIC_FIFO_ACTIVE_GATE 0u
#define FUXI_HAPTIC_FIFO_MAX_SAMPLES 32u
#define FUXI_HAPTIC_FIFO_MAX_CHUNKS 10u
#define FUXI_HAPTIC_FIFO_TAIL_ZEROS 4u
#define FUXI_HAPTIC_FIFO_MAX_CODE 0x20u
#define FUXI_HAPTIC_FIFO_MAX_VMAX_MV 1200u
#define FUXI_HAPTIC_FIFO_MAX_READS 104u
#define FUXI_HAPTIC_FIFO_MAX_OWNER_READS 110u
#define FUXI_HAPTIC_FIFO_MAX_WRITES 0u
#define FUXI_HAPTIC_FIFO_MAX_REFILLS 0u
#define FUXI_HAPTIC_FIFO_MAX_STOP_POLLS 0u
#define FUXI_HAPTIC_FIFO_PROFILE_TLRA_CODE 1142u

typedef enum {
    FuxiHapticFifoOk = 0,
    FuxiHapticFifoInvalid = -1,
    FuxiHapticFifoBounds = -2,
    FuxiHapticFifoHardware = -3,
    FuxiHapticFifoIoError = -4,
    FuxiHapticFifoUnstable = -5,
    FuxiHapticFifoBusy = -6,
    FuxiHapticFifoFault = -7,
    FuxiHapticFifoProfileFork = -8,
    FuxiHapticFifoCorrupt = -9,
    FuxiHapticFifoPartialWrite = -10,
    FuxiHapticFifoGateClosed = -11,
    FuxiHapticFifoLocked = -12
} FuxiHapticFifoResult;

typedef enum {
    FuxiHapticFifoNew,
    FuxiHapticFifoEncoded,
    FuxiHapticFifoProbed,
    FuxiHapticFifoRejected,
    FuxiHapticFifoFailed
} FuxiHapticFifoPhase;

typedef enum {
    FuxiHapticFifoEvidenceNone,
    FuxiHapticFifoEvidenceHap525HoldOnly,
    FuxiHapticFifoEvidenceHap530AutoStopOnly
} FuxiHapticFifoEvidence;

enum {
    FuxiHapticFifoBlockActiveGate = 1u << 0,
    FuxiHapticFifoBlockIndependentCutoff = 1u << 1,
    FuxiHapticFifoBlockExternalRoute = 1u << 2,
    FuxiHapticFifoBlockClockProof = 1u << 3,
    FuxiHapticFifoNeedsVmaxStage = 1u << 4,
    FuxiHapticFifoNeedsHoldDisable = 1u << 5,
    FuxiHapticFifoNeedsThresholdStage = 1u << 6
};

typedef struct {
    uint16_t address;
    unsigned length;
    uint8_t bytes[4];
} FuxiHapticFifoChunk;

typedef struct {
    unsigned sample_count;
    unsigned chunk_count;
    unsigned vmax_mv;
    unsigned nominal_data_us;
    uint16_t tlra_code;
    uint8_t sample_codes[FUXI_HAPTIC_FIFO_MAX_SAMPLES];
    FuxiHapticFifoChunk chunks[FUXI_HAPTIC_FIFO_MAX_CHUNKS];
} FuxiHapticFifoPlan;

typedef struct {
    unsigned next_chunk;
    unsigned acknowledged_bytes;
    unsigned failed;
    unsigned complete;
} FuxiHapticFifoJournal;

typedef struct {
    uint8_t raw[3][256];
    unsigned tlra_us;
    unsigned vmax_mv;
    unsigned fifo_capacity;
    unsigned fifo_status_available;
    unsigned fifo_fill;
    unsigned fifo_empty;
} FuxiHapticFifoSnapshot;

typedef struct {
    void *context;
    int (*owner)(void *context, uint16_t base, unsigned *owner);
    int (*read)(void *context, uint16_t address, uint8_t *value);
    int (*write)(void *context, uint16_t address, const uint8_t *bytes,
        unsigned length, unsigned *transferred);
} FuxiHapticFifoIo;

typedef struct {
    const uint8_t *sample_codes;
    unsigned sample_count;
    unsigned vmax_mv;
    uint16_t tlra_code;
    unsigned active_requested;
    FuxiHapticFifoEvidence evidence;
} FuxiHapticFifoRequest;

typedef struct {
    FuxiHapticFifoPhase phase;
    FuxiHapticFifoPlan plan;
    FuxiHapticFifoSnapshot snapshot;
    unsigned reads;
    unsigned owner_reads;
    unsigned probed;
    unsigned blockers;
    int result;
} FuxiHapticFifoState;

int fuxi_haptic_fifo_encode(const uint8_t *codes, unsigned count,
    unsigned vmax_mv, uint16_t tlra_code, FuxiHapticFifoPlan *plan);
int fuxi_haptic_fifo_validate_plan(const FuxiHapticFifoPlan *plan);
int fuxi_haptic_fifo_record_transfer(const FuxiHapticFifoPlan *plan,
    FuxiHapticFifoJournal *journal, unsigned chunk_index,
    int transport_result, unsigned transferred);
int fuxi_haptic_fifo_read_allowed(uint16_t address);
int fuxi_haptic_fifo_write_allowed(uint16_t address, unsigned length);
int fuxi_haptic_fifo_decode_status(uint8_t selector, uint8_t selector_xt,
    uint8_t msb, uint8_t lsb, unsigned capacity, unsigned *fill, unsigned *empty);
unsigned fuxi_haptic_fifo_independent_cutoff_verified(void);
void fuxi_haptic_fifo_init(FuxiHapticFifoState *state);
int fuxi_haptic_fifo_prepare(const FuxiHapticFifoIo *io,
    const FuxiHapticFifoRequest *request, FuxiHapticFifoState *state);
void fuxi_haptic_fifo_cleanup(FuxiHapticFifoState *state);

#endif
