#include <pexpert/arm64/board_config.h>
#if defined(FUXI)
#include <kern/locks.h>
#include "fuxi_rpmh_shared.h"

static LCK_GRP_DECLARE(fuxi_rpmh_group, "fuxi-rpmh");
static LCK_MTX_DECLARE(fuxi_rpmh_mutex, &fuxi_rpmh_group);
static int fuxi_rpmh_failed;

int fuxi_rpmh_acquire(void)
{
    lck_mtx_lock(&fuxi_rpmh_mutex);
    if (fuxi_rpmh_failed) {
        lck_mtx_unlock(&fuxi_rpmh_mutex);
        return -1;
    }
    return 0;
}

void fuxi_rpmh_release(int healthy)
{
    if (!healthy) fuxi_rpmh_failed = 1;
    lck_mtx_unlock(&fuxi_rpmh_mutex);
}
#endif
