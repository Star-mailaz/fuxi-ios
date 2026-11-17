/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* ADSP firmware files for fuxi_adsp.c, read in place from the device's own firmware partition: the split image NAME.b00,
 * NAME.b01, ... in /image of modem_a (else modem_b), a FAT16 volume read through sweet_ufs.c's read-only firmware-partition
 * reads. Nothing is installed and the boot image does not grow. Plain reads on the caller's thread (the ADSP thread is the
 * only caller). Adapted from UniXNU-sheng package/AdspFirmware.c (6880068; only its "modem:" source), BSD-2-Clause-Patent:
 * Copyright (c) 2026, UniXNU contributors (LICENSE.UniXNU-sheng). */
#include <pexpert/arm64/board_config.h>
#if defined(FUXI)
#include <sys/param.h>
#include <sys/systm.h>
#include <sys/errno.h>
#include <kern/kalloc.h>
#include "FatVolume.h"
#include "QcomMdt.h"

int fuxi_adsp_fw_open(const char *name, void **handle, uint64_t *size);
int fuxi_adsp_fw_read(void *handle, uint64_t offset, void *to, size_t length);
void fuxi_adsp_fw_close(void *handle);

extern int fuxi_ufs_part_find(const char *name, uint32_t *lun, uint64_t *first, uint64_t *blocks);
extern int fuxi_ufs_part_read(uint32_t lun, uint64_t lba, uint32_t blocks, void *dst);

#define FW_BLOCK 4096u
#define FW_RUN 256u /* blocks per UFS read: the driver's 1 MiB bounce buffer */

/* The partition (one for the boot) and its one-block cache. Static: no allocation, and the only user is the ADSP thread. */
static struct {
    uint32_t lun;
    uint64_t first, blocks;
    uint64_t cached; /* block in block (UINT64_MAX: none) */
    uint8_t block[FW_BLOCK];
} gPart;
static FatVolume gVolume;
static int gMounted;

/* Bytes of the partition: whole blocks straight into to, the ends of a range through the one-block cache. Never past its end. */
static int partitionRead(void *context, uint64_t offset, void *to, size_t length)
{
    (void)context;
    uint8_t *out = to;
    if (offset > gPart.blocks * FW_BLOCK || length > gPart.blocks * FW_BLOCK - offset) return EIO;
    while (length) {
        const uint64_t lba = offset / FW_BLOCK;
        const size_t within = (size_t)(offset % FW_BLOCK);
        if (!within && length >= FW_BLOCK) {
            const uint32_t n = length / FW_BLOCK > FW_RUN ? FW_RUN : (uint32_t)(length / FW_BLOCK);
            if (!fuxi_ufs_part_read(gPart.lun, gPart.first + lba, n, out)) return EIO;
            out += (size_t)n * FW_BLOCK; offset += (uint64_t)n * FW_BLOCK; length -= (size_t)n * FW_BLOCK;
            continue;
        }
        if (gPart.cached != lba) {
            gPart.cached = UINT64_MAX;
            if (!fuxi_ufs_part_read(gPart.lun, gPart.first + lba, 1, gPart.block)) return EIO;
            gPart.cached = lba;
        }
        const size_t take = FW_BLOCK - within < length ? FW_BLOCK - within : length;
        memcpy(out, gPart.block + within, take);
        out += take; offset += take; length -= take;
    }
    return 0;
}

static int mountPartition(void)
{
    static const char *const names[] = {"modem_a", "modem_b"};
    int rc = ENOENT;
    if (gMounted) return 0;
    for (unsigned i = 0; i < 2 && rc; ++i) {
        uint64_t blocks = 0;
        /* ENXIO while the UFS driver is not ready: the caller tries again later */
        if (!fuxi_ufs_part_find(names[i], &gPart.lun, &gPart.first, &blocks)) {rc = ENXIO; continue;}
        gPart.blocks = blocks;
        gPart.cached = UINT64_MAX;
        rc = fat_mount(&gVolume, blocks * FW_BLOCK, partitionRead, NULL) ? EFTYPE : 0;
        if (!rc) printf("FUXI ADSP: firmware volume %s (LUN %u, %llu MiB)\n", names[i], gPart.lun, blocks * FW_BLOCK >> 20);
    }
    if (!rc) gMounted = 1;
    return rc;
}

/* The two images the bring-up uses (adsp_dtb, then adsp) are open at the same time. */
#define FW_IMAGES 2u
struct modem_image {
    uint8_t used;
    QcomMdtSplit split;
    FatFile piece[QCOM_MDT_MAX_SEGMENTS];
};
static struct modem_image gImages[FW_IMAGES];

static int pieceRead(void *context, unsigned piece, uint64_t offset, void *to, size_t length)
{
    struct modem_image *m = context;
    if (piece >= QCOM_MDT_MAX_SEGMENTS) return EIO;
    return fat_read(&gVolume, &m->piece[piece], offset, to, length);
}

int fuxi_adsp_fw_open(const char *name, void **handle, uint64_t *size)
{
    char path[48];
    struct modem_image *m = NULL;
    int rc = mountPartition();
    if (rc) return rc;
    for (unsigned i = 0; i < FW_IMAGES && !m; ++i) if (!gImages[i].used) m = &gImages[i];
    if (!m) return ENFILE;
    bzero(m, sizeof(*m));
    snprintf(path, sizeof(path), "image/%s.b00", name);
    FatFile headers;
    rc = fat_open(&gVolume, path, &headers);
    if (rc == FatNotFound) rc = ENOENT;
    else if (rc) rc = EIO;
    else if (headers.size < 52 || headers.size > 64 * 1024) rc = EFTYPE;
    uint8_t *bytes = rc ? NULL : kalloc_data(headers.size, Z_WAITOK);
    if (!rc && !bytes) rc = ENOMEM;
    if (!rc && fat_read(&gVolume, &headers, 0, bytes, headers.size)) rc = EIO;
    if (!rc && qcom_mdt_split(&m->split, bytes, headers.size)) rc = EFTYPE;
    if (bytes) kfree_data(bytes, headers.size);
    for (unsigned i = 0; !rc && i < m->split.count; ++i) {
        if (!m->split.piece[i].size) continue;
        snprintf(path, sizeof(path), "image/%s.b%02u", name, i);
        if (fat_open(&gVolume, path, &m->piece[i])) rc = ENOENT;
        else if (m->piece[i].size < m->split.piece[i].size) rc = EFTYPE;
    }
    if (rc) return rc;
    m->used = 1;
    *handle = m;
    *size = m->split.size;
    return 0;
}

int fuxi_adsp_fw_read(void *handle, uint64_t offset, void *to, size_t length)
{
    struct modem_image *m = handle;
    if (!m || !m->used) return EBADF;
    return qcom_mdt_split_read(&m->split, pieceRead, m, offset, to, length) ? EIO : 0;
}

void fuxi_adsp_fw_close(void *handle)
{
    struct modem_image *m = handle;
    if (m) m->used = 0;
}
#endif /* FUXI */
