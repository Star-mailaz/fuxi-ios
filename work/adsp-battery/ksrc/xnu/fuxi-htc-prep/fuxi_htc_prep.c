#include "fuxi_htc_prep.h"

static uint16_t
fuxi_htc_read16(const uint8_t *bytes)
{
	return (uint16_t)((uint16_t)bytes[0] | ((uint16_t)bytes[1] << 8));
}

static int
fuxi_htc_parse_trailer(const uint8_t *bytes, size_t length,
    struct fuxi_htc_frame *frame)
{
	size_t position = 0;
	while (position < length) {
		if (length - position < 4u) {
			return FUXI_HTC_INVALID_LENGTH;
		}
		const uint8_t *record = bytes + position;
		size_t record_bytes = record[1];
		if (record_bytes > length - position - 4u) {
			return FUXI_HTC_INVALID_LENGTH;
		}
		if (record[2] || record[3] || record[0] > 1u) {
			return FUXI_HTC_INVALID_PROTOCOL;
		}
		if (frame->trailer_records >= FUXI_HTC_MAX_TRAILER_RECORDS) {
			return FUXI_HTC_INVALID_LENGTH;
		}
		frame->trailer_records++;
		if (record[0] == 1u) {
			if (!record_bytes || record_bytes % 4u) {
				return FUXI_HTC_INVALID_CREDIT;
			}
			for (size_t offset = 0; offset < record_bytes; offset += 4u) {
				const uint8_t *report = record + 4u + offset;
				unsigned endpoint = report[0];
				if (endpoint >= FUXI_HTC_MAX_ENDPOINTS) {
					return FUXI_HTC_INVALID_ENDPOINT;
				}
				if (report[2] || report[3] ||
				    frame->credit_reports >= FUXI_HTC_MAX_CREDIT_REPORTS) {
					return FUXI_HTC_INVALID_CREDIT;
				}
				unsigned total = (unsigned)frame->credit_delta[endpoint] + report[1];
				if (total > UINT16_MAX) {
					return FUXI_HTC_INVALID_CREDIT;
				}
				frame->credit_delta[endpoint] = (uint16_t)total;
				frame->credit_mask |= (uint16_t)(1u << endpoint);
				frame->credit_reports++;
			}
		}
		position += 4u + record_bytes;
	}
	return FUXI_HTC_OK;
}

static int
fuxi_htc_parse_control(const uint8_t *bytes, size_t length,
    struct fuxi_htc_frame *frame)
{
	if (length < 4u || length > FUXI_HTC_MAX_CONTROL) {
		return FUXI_HTC_INVALID_CONTROL;
	}
	frame->message_id = fuxi_htc_read16(bytes);
	frame->control_bytes = (uint16_t)length;
	frame->control_kind = FUXI_HTC_CONTROL_OTHER;
	for (size_t index = 0; index < length; index++) {
		frame->control[index] = bytes[index];
	}
	if (frame->message_id == 1u) {
		if ((length != 8u && length != 12u) || bytes[7]) {
			return FUXI_HTC_INVALID_CONTROL;
		}
		frame->control_kind = FUXI_HTC_CONTROL_READY;
		frame->ready_credit_count = fuxi_htc_read16(bytes + 2u);
		frame->ready_credit_size = fuxi_htc_read16(bytes + 4u);
		frame->ready_max_endpoints = bytes[6];
		if (!frame->ready_credit_count || !frame->ready_credit_size ||
		    !frame->ready_max_endpoints ||
		    frame->ready_max_endpoints > FUXI_HTC_MAX_ENDPOINTS) {
			return FUXI_HTC_INVALID_CONTROL;
		}
		if (length == 12u) {
			if (bytes[8] > 1u || bytes[10] || bytes[11]) {
				return FUXI_HTC_INVALID_CONTROL;
			}
			frame->ready_extended = 1u;
			frame->ready_version = bytes[8];
			frame->ready_max_bundle = bytes[9];
		}
	} else if (frame->message_id == 3u) {
		if (length < 12u || length != 12u + bytes[8] ||
		    bytes[9] || bytes[10] || bytes[11] || bytes[4] > 4u) {
			return FUXI_HTC_INVALID_CONTROL;
		}
		frame->control_kind = FUXI_HTC_CONTROL_CONNECT_RESPONSE;
		frame->connect_service_id = fuxi_htc_read16(bytes + 2u);
		frame->connect_status = bytes[4];
		frame->connect_endpoint = bytes[5];
		frame->connect_max_message = fuxi_htc_read16(bytes + 6u);
		frame->connect_metadata_bytes = bytes[8];
		if (!frame->connect_service_id) {
			return FUXI_HTC_INVALID_CONTROL;
		}
		if (!frame->connect_status &&
		    (!frame->connect_endpoint ||
		     frame->connect_endpoint >= FUXI_HTC_MAX_ENDPOINTS ||
		     !frame->connect_max_message ||
		     frame->connect_max_message > FUXI_HTC_MAX_FRAME - 8u)) {
			return FUXI_HTC_INVALID_CONTROL;
		}
	}
	return FUXI_HTC_OK;
}

int
fuxi_htc_parse_frame(const uint8_t *bytes, size_t length,
    struct fuxi_htc_frame *output)
{
	if (!bytes || !output) {
		return FUXI_HTC_INVALID_INPUT;
	}
	if (length < 8u || length > FUXI_HTC_MAX_FRAME) {
		return FUXI_HTC_INVALID_LENGTH;
	}
	struct fuxi_htc_frame parsed = {0};
	parsed.endpoint = bytes[0];
	parsed.flags = bytes[1];
	parsed.control_byte1 = bytes[5];
	if (parsed.endpoint >= FUXI_HTC_MAX_ENDPOINTS) {
		return FUXI_HTC_INVALID_ENDPOINT;
	}
	if ((parsed.flags & ~2u) || bytes[6] || bytes[7]) {
		return FUXI_HTC_INVALID_PROTOCOL;
	}
	size_t payload_bytes = fuxi_htc_read16(bytes + 2u);
	if (payload_bytes != length - 8u) {
		return FUXI_HTC_INVALID_LENGTH;
	}
	if (parsed.flags & 2u) {
		parsed.trailer_bytes = bytes[4];
		if (parsed.trailer_bytes < 4u || parsed.trailer_bytes > payload_bytes) {
			return FUXI_HTC_INVALID_LENGTH;
		}
		int result = fuxi_htc_parse_trailer(bytes + length - parsed.trailer_bytes,
		    parsed.trailer_bytes, &parsed);
		if (result) {
			return result;
		}
	} else if (bytes[4]) {
		return FUXI_HTC_INVALID_PROTOCOL;
	}
	payload_bytes -= parsed.trailer_bytes;
	parsed.payload_bytes = (uint16_t)payload_bytes;
	if (!parsed.endpoint && payload_bytes) {
		int result = fuxi_htc_parse_control(bytes + 8u, payload_bytes, &parsed);
		if (result) {
			return result;
		}
	}
	*output = parsed;
	return FUXI_HTC_OK;
}

int
fuxi_htc_observer_init(struct fuxi_htc_observer *observer,
    fuxi_htc_callback callback, void *context)
{
	if (!observer) {
		return FUXI_HTC_INVALID_INPUT;
	}
	*observer = (struct fuxi_htc_observer){0};
	observer->active = FUXI_HTC_DEFAULT_ACTIVE;
	observer->callbacks_remaining = FUXI_HTC_CALLBACK_BUDGET;
	observer->callback = callback;
	observer->context = context;
	return FUXI_HTC_OK;
}

int
fuxi_htc_observe(struct fuxi_htc_observer *observer,
    const uint8_t *bytes, size_t length)
{
	if (!observer) {
		return FUXI_HTC_INVALID_INPUT;
	}
	if (!observer->active) {
		return FUXI_HTC_INACTIVE;
	}
	if (observer->active != 1u || !observer->callback) {
		return FUXI_HTC_INVALID_INPUT;
	}
	if (observer->in_callback) {
		return FUXI_HTC_CALLBACK_BUSY;
	}
	if (!observer->callbacks_remaining) {
		return FUXI_HTC_CALLBACK_LIMIT;
	}
	struct fuxi_htc_frame parsed;
	int result = fuxi_htc_parse_frame(bytes, length, &parsed);
	if (result) {
		return result;
	}
	observer->callbacks_remaining--;
	observer->callbacks_delivered++;
	observer->in_callback = 1u;
	observer->callback(observer->context, &parsed);
	observer->in_callback = 0u;
	return FUXI_HTC_OK;
}
