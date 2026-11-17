#ifndef FUXI_WLAN_CONTROL_H
#define FUXI_WLAN_CONTROL_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>

#define FWC_FEATURE_SCAN_DWELL_MS (1U << 31)
#define FWC_ATTR_SCAN_DWELL_MS 46
#define FWC_ATTR_COUNT 47

struct fwc_probe {
	uint64_t session, generation;
	uint32_t sequence, pending_sequence;
	unsigned pending_operation, info_ready, scan_queued, scan_accepted, scan_done;
	int error;
};

static inline uint16_t
fwc_read16(const uint8_t *bytes)
{
	return (uint16_t)((uint16_t)bytes[0] | (uint16_t)bytes[1] << 8);
}

static inline uint32_t
fwc_read32(const uint8_t *bytes)
{
	return (uint32_t)fwc_read16(bytes) | (uint32_t)fwc_read16(bytes + 2) << 16;
}

static inline uint64_t
fwc_read64(const uint8_t *bytes)
{
	return (uint64_t)fwc_read32(bytes) | (uint64_t)fwc_read32(bytes + 4) << 32;
}

static inline void
fwc_write(uint8_t *bytes, uint64_t value, unsigned count)
{
	for (unsigned index = 0; index < count; index++) {
		bytes[index] = (uint8_t)(value >> (index * 8));
	}
}

static inline int
fwc_message_valid(uint64_t session, const void *message, size_t length)
{
	if (!session || !message || length < 40 || length > 65536 || (length & 3)) { return 0; }
	const uint8_t *bytes = message;
	unsigned kind = fwc_read16(bytes + 6), operation = fwc_read16(bytes + 8);
	if (fwc_read32(bytes) != 0x3143574e || fwc_read16(bytes + 4) != 1 ||
	    fwc_read16(bytes + 10) || fwc_read32(bytes + 16) != length ||
	    fwc_read64(bytes + 24) != session || fwc_read32(bytes + 20) >= 11 ||
	    !fwc_read64(bytes + 32) || (kind != 2 && kind != 3) ||
	    (kind == 2 && (operation < 1 || operation >= 14)) ||
	    (kind == 3 && (operation < 0x100 || operation >= 0x10f))) { return 0; }
	uint64_t attributes = 0;
	for (size_t offset = 40; offset < length;) {
		unsigned attribute = fwc_read16(bytes + offset), size = fwc_read16(bytes + offset + 2);
		if (!attribute || attribute >= FWC_ATTR_COUNT || size < 4 || size > length - offset ||
		    (attributes & ((uint64_t)1 << attribute))) { return 0; }
		attributes |= (uint64_t)1 << attribute;
		size_t padded = (size + 3u) & ~(size_t)3u;
		if (padded > length - offset) { return 0; }
		for (size_t index = size; index < padded; index++) {
			if (bytes[offset + index]) { return 0; }
		}
		offset += padded;
	}
	return 1;
}

static inline const uint8_t *
fwc_attribute(const uint8_t *bytes, size_t length, unsigned attribute, size_t *size)
{
	*size = 0;
	for (size_t offset = 40; offset < length;) {
		unsigned entry = fwc_read16(bytes + offset + 2);
		if (fwc_read16(bytes + offset) == attribute) {
			*size = entry - 4;
			return bytes + offset + 4;
		}
		offset += (entry + 3u) & ~3u;
	}
	return NULL;
}

static inline size_t
fwc_probe_request(struct fwc_probe *probe, uint8_t *bytes, size_t capacity)
{
	if (!probe || !bytes || !probe->session || probe->error ||
	    probe->pending_operation || probe->scan_queued) { return 0; }
	unsigned operation = probe->info_ready ? 2 : 1;
	size_t length = operation == 2 ? 80 : 40;
	if (capacity < length || probe->sequence == UINT32_MAX) { return 0; }
	memset(bytes, 0, length);
	fwc_write(bytes, 0x3143574e, 4);
	fwc_write(bytes + 4, 1, 2);
	fwc_write(bytes + 6, 1, 2);
	fwc_write(bytes + 8, operation, 2);
	fwc_write(bytes + 12, ++probe->sequence, 4);
	fwc_write(bytes + 16, length, 4);
	fwc_write(bytes + 24, probe->session, 8);
	fwc_write(bytes + 32, probe->generation, 8);
	if (operation == 2) {
		fwc_write(bytes + 40, 19, 2);
		fwc_write(bytes + 42, 37, 2);
		probe->scan_queued = 1;
	}
	probe->pending_sequence = probe->sequence;
	probe->pending_operation = operation;
	return length;
}

static inline int
fwc_probe_receive(struct fwc_probe *probe, uint64_t session, const void *message, size_t length)
{
	if (!probe || !message || !session || session != probe->session ||
	    length < 40 || length > 65536 || (length & 3)) { return 1; }
	const uint8_t *bytes = message;
	unsigned kind = fwc_read16(bytes + 6), operation = fwc_read16(bytes + 8);
	unsigned status = fwc_read32(bytes + 20);
	uint64_t generation = fwc_read64(bytes + 32);
	if (fwc_read32(bytes) != 0x3143574e || fwc_read16(bytes + 4) != 1 ||
	    fwc_read16(bytes + 10) || fwc_read32(bytes + 16) != length ||
	    fwc_read64(bytes + 24) != session || status >= 11 || !generation ||
	    (kind != 2 && kind != 3) ||
	    (kind == 2 && (operation < 1 || operation >= 14)) ||
	    (kind == 3 && (operation < 0x100 || operation >= 0x10f))) { return 1; }
	uint64_t attributes = 0;
	for (size_t offset = 40; offset < length;) {
		unsigned attribute = fwc_read16(bytes + offset);
		unsigned size = fwc_read16(bytes + offset + 2);
		if (!attribute || attribute >= FWC_ATTR_COUNT || size < 4 || size > length - offset ||
		    (attributes & ((uint64_t)1 << attribute))) { return 1; }
		attributes |= (uint64_t)1 << attribute;
		size_t padded = (size + 3u) & ~(size_t)3u;
		if (padded > length - offset) { return 1; }
		for (size_t index = size; index < padded; index++) {
			if (bytes[offset + index]) { return 1; }
		}
		offset += padded;
	}
	if (kind == 2) {
		if (!probe->pending_operation || operation != probe->pending_operation ||
		    fwc_read32(bytes + 12) != probe->pending_sequence ||
		    (operation != 1 && generation != probe->generation)) { return 1; }
		probe->pending_operation = 0;
		if (status) { probe->error = (int)status; return 0; }
		if (operation == 1) {
			probe->generation = generation;
			probe->info_ready = 1;
		} else {
			probe->scan_accepted = 1;
		}
	} else {
		if (!probe->info_ready || generation != probe->generation ||
		    fwc_read32(bytes + 12)) { return 1; }
		if (operation == 0x101 || operation == 0x102) {
			if (!probe->scan_queued) { return 1; }
			if (status) { probe->error = (int)status; }
			if (operation == 0x102) { probe->scan_done = 1; }
		}
	}
	return 0;
}
#endif
