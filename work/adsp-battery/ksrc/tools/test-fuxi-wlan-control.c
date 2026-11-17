#include <assert.h>
#include <stdio.h>
#include "fuxi_wlan_control.h"

static size_t
message(uint8_t *bytes, unsigned kind, unsigned operation, uint32_t sequence,
    uint64_t session, uint64_t generation, unsigned status)
{
	memset(bytes, 0, 80);
	fwc_write(bytes, 0x3143574e, 4);
	fwc_write(bytes + 4, 1, 2);
	fwc_write(bytes + 6, kind, 2);
	fwc_write(bytes + 8, operation, 2);
	fwc_write(bytes + 12, sequence, 4);
	fwc_write(bytes + 16, 40, 4);
	fwc_write(bytes + 20, status, 4);
	fwc_write(bytes + 24, session, 8);
	fwc_write(bytes + 32, generation, 8);
	return 40;
}

static void
rejected(struct fwc_probe *probe, const void *bytes, size_t length)
{
	struct fwc_probe before = *probe;
	assert(fwc_probe_receive(probe, probe->session, bytes, length));
	assert(!memcmp(probe, &before, sizeof(before)));
}

static void
info(struct fwc_probe *probe)
{
	uint8_t bytes[80];
	assert(fwc_probe_request(probe, bytes, 39) == 0);
	assert(fwc_probe_request(probe, bytes, sizeof(bytes)) == 40);
	assert(fwc_read16(bytes + 8) == 1 && fwc_read32(bytes + 12) == 1);
	assert(fwc_probe_request(probe, bytes, sizeof(bytes)) == 0);
#if defined(FWC_REFERENCE_CODEC)
	struct nw_control_view view;
	assert(!nw_control_decode(bytes, 40, &view));
	assert(view.header.kind == NW_CONTROL_REQUEST && view.header.operation == NW_CONTROL_INFO);
	assert(view.header.session == probe->session && !view.header.generation);
#endif
	message(bytes, 2, 1, 2, probe->session, 7, 0);
	rejected(probe, bytes, 40);
	message(bytes, 2, 1, 1, probe->session + 1, 7, 0);
	rejected(probe, bytes, 40);
	message(bytes, 2, 1, 1, probe->session, 0, 0);
	rejected(probe, bytes, 40);
	message(bytes, 2, 1, 1, probe->session, 7, 0);
	assert(!fwc_probe_receive(probe, probe->session, bytes, 40));
	assert(probe->info_ready && probe->generation == 7 && !probe->pending_operation);
	rejected(probe, bytes, 40);
}

static void
scan(struct fwc_probe *probe)
{
	uint8_t bytes[80];
	assert(fwc_probe_request(probe, bytes, 79) == 0);
	assert(fwc_probe_request(probe, bytes, sizeof(bytes)) == 80);
	assert(fwc_read16(bytes + 8) == 2 && fwc_read64(bytes + 32) == 7);
	assert(fwc_read16(bytes + 40) == 19 && fwc_read16(bytes + 42) == 37);
	for (unsigned index = 44; index < 80; index++) { assert(!bytes[index]); }
#if defined(FWC_REFERENCE_CODEC)
	struct nw_control_view view;
	assert(!nw_control_decode(bytes, 80, &view));
	assert(view.header.operation == NW_CONTROL_SCAN && view.header.sequence == 2);
	size_t length;
	const uint8_t *ssids = nw_control_get(&view, NW_CONTROL_ATTR_SCAN_SSIDS, &length);
	assert(ssids && length == 33 && !ssids[0]);
#endif
	message(bytes, 3, 0x101, 0, probe->session, 8, 0);
	rejected(probe, bytes, 40);
	message(bytes, 3, 0x101, 1, probe->session, 7, 0);
	rejected(probe, bytes, 40);
	message(bytes, 3, 0x101, 0, probe->session, 7, 0);
	assert(!fwc_probe_receive(probe, probe->session, bytes, 40));
	assert(!probe->scan_accepted && !probe->scan_done);
	message(bytes, 3, 0x102, 0, probe->session, 7, 0);
	assert(!fwc_probe_receive(probe, probe->session, bytes, 40));
	assert(probe->scan_done && !probe->scan_accepted);
	message(bytes, 2, 2, probe->pending_sequence, probe->session, 7, 0);
	assert(!fwc_probe_receive(probe, probe->session, bytes, 40));
	assert(probe->scan_done && probe->scan_accepted && !probe->error);
	assert(!fwc_probe_request(probe, bytes, sizeof(bytes)));
}

int
main(void)
{
	struct fwc_probe probe = { .session = 0x1122334455667788ull };
	info(&probe);
	scan(&probe);
	uint8_t bytes[80];
	struct fwc_probe failed = { .session = 13 };
	info(&failed);
	assert(fwc_probe_request(&failed, bytes, sizeof(bytes)) == 80);
	message(bytes, 2, 2, failed.pending_sequence, failed.session, 7, 2);
	assert(!fwc_probe_receive(&failed, failed.session, bytes, 40));
	assert(failed.error == 2 && !failed.scan_accepted);
	assert(!fwc_probe_request(&failed, bytes, sizeof(bytes)));
	failed = (struct fwc_probe){ .session = 13 };
	info(&failed);
	assert(fwc_probe_request(&failed, bytes, sizeof(bytes)) == 80);
	message(bytes, 3, 0x102, 0, failed.session, 7, 9);
	assert(!fwc_probe_receive(&failed, failed.session, bytes, 40));
	assert(failed.error == 9 && !failed.scan_accepted);
	message(bytes, 3, 0x102, 0, probe.session, 7, 0);
	for (size_t length = 0; length < 40; length++) { rejected(&probe, bytes, length); }
	rejected(&probe, bytes, 65537);
	for (unsigned offset = 0; offset < 40; offset++) {
		for (unsigned value = 0; value < 256; value++) {
			uint8_t original = bytes[offset];
			bytes[offset] = (uint8_t)value;
			struct fwc_probe copy = probe;
			int result = fwc_probe_receive(&copy, probe.session, bytes, 40);
			if (result) { assert(!memcmp(&copy, &probe, sizeof(copy))); }
			bytes[offset] = original;
		}
	}
	fwc_write(bytes + 16, 48, 4);
	fwc_write(bytes + 40, 1, 2);
	fwc_write(bytes + 42, 5, 2);
	bytes[44] = 'x';
	assert(!fwc_probe_receive(&probe, probe.session, bytes, 48));
	bytes[47] = 1;
	rejected(&probe, bytes, 48);
	bytes[47] = 0;
	fwc_write(bytes + 42, 3, 2);
	rejected(&probe, bytes, 48);
	fwc_write(bytes + 42, 9, 2);
	rejected(&probe, bytes, 48);
	fwc_write(bytes + 42, 5, 2);
	fwc_write(bytes + 16, 56, 4);
	memcpy(bytes + 48, bytes + 40, 8);
	rejected(&probe, bytes, 56);
	fwc_write(bytes + 48, FWC_ATTR_COUNT, 2);
	rejected(&probe, bytes, 56);
	struct fwc_probe exhausted = { .session = 1, .sequence = (uint32_t)-1 };
	assert(!fwc_probe_request(&exhausted, bytes, sizeof(bytes)));
	puts("PASS native scan control: handshake, wire ABI, session/generation/replay rejection, scan reply/event order, failure propagation and 10240 header mutations");
	return 0;
}
