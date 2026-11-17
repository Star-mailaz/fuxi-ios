#ifndef FUXI_HTC_PREP_H
#define FUXI_HTC_PREP_H

#include <stddef.h>
#include <stdint.h>

#define FUXI_HTC_DEFAULT_ACTIVE 0u
#define FUXI_HTC_MAX_FRAME 4096u
#define FUXI_HTC_MAX_CONTROL 256u
#define FUXI_HTC_MAX_ENDPOINTS 9u
#define FUXI_HTC_MAX_TRAILER_RECORDS 63u
#define FUXI_HTC_MAX_CREDIT_REPORTS 62u
#define FUXI_HTC_CALLBACK_BUDGET 16u

enum fuxi_htc_result {
	FUXI_HTC_OK = 0,
	FUXI_HTC_INACTIVE = 1,
	FUXI_HTC_CALLBACK_LIMIT = 2,
	FUXI_HTC_CALLBACK_BUSY = 3,
	FUXI_HTC_INVALID_INPUT = -1,
	FUXI_HTC_INVALID_LENGTH = -2,
	FUXI_HTC_INVALID_PROTOCOL = -3,
	FUXI_HTC_INVALID_ENDPOINT = -4,
	FUXI_HTC_INVALID_CREDIT = -5,
	FUXI_HTC_INVALID_CONTROL = -6
};

enum fuxi_htc_control_kind {
	FUXI_HTC_CONTROL_NONE = 0,
	FUXI_HTC_CONTROL_READY = 1,
	FUXI_HTC_CONTROL_CONNECT_RESPONSE = 3,
	FUXI_HTC_CONTROL_OTHER = 255
};

struct fuxi_htc_frame {
	uint8_t endpoint;
	uint8_t flags;
	uint8_t control_byte1;
	uint8_t trailer_bytes;
	uint16_t payload_bytes;
	uint16_t control_bytes;
	uint16_t message_id;
	uint16_t credit_mask;
	uint16_t credit_delta[FUXI_HTC_MAX_ENDPOINTS];
	uint8_t trailer_records;
	uint8_t credit_reports;
	uint8_t control_kind;
	uint8_t ready_extended;
	uint16_t ready_credit_count;
	uint16_t ready_credit_size;
	uint8_t ready_max_endpoints;
	uint8_t ready_version;
	uint8_t ready_max_bundle;
	uint8_t connect_status;
	uint16_t connect_service_id;
	uint16_t connect_max_message;
	uint8_t connect_endpoint;
	uint8_t connect_metadata_bytes;
	uint8_t control[FUXI_HTC_MAX_CONTROL];
};

typedef void (*fuxi_htc_callback)(void *context,
    const struct fuxi_htc_frame *frame);

struct fuxi_htc_observer {
	unsigned active;
	unsigned callbacks_remaining;
	unsigned callbacks_delivered;
	unsigned in_callback;
	fuxi_htc_callback callback;
	void *context;
};

int fuxi_htc_parse_frame(const uint8_t *bytes, size_t length,
    struct fuxi_htc_frame *output);
int fuxi_htc_observer_init(struct fuxi_htc_observer *observer,
    fuxi_htc_callback callback, void *context);
int fuxi_htc_observe(struct fuxi_htc_observer *observer,
    const uint8_t *bytes, size_t length);

#endif
