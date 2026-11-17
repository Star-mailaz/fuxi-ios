import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import stat


FIELDS = {
    0: ("BmStatus", "enum"), 2: ("BmCapacity", "centipercent"),
    3: ("BmVoltage", "uV"), 4: ("BmCurrent", "uA"),
    5: ("BmTemperature", "centidegree_C"), 7: ("BmUsbOnline", "bool"),
    8: ("BmUsbType", "enum"), 9: ("BmUsbVoltage", "uV"),
    10: ("BmUsbCurrent", "uA"), 11: ("BmTimeToEmpty", "s"),
    12: ("BmTimeToFull", "s"), 20: ("BmUsbAdapter", "enum"),
    21: ("BmUsbLimit", "uA"), 22: ("BmUsbMax", "uA"),
    24: ("BmThermalLevel", "level"), 25: ("BmChargeCurrent", "uA"),
    27: ("BmPowerMax", "reported_board_watts"), 28: ("BmPdVerified", "bool"),
    31: ("BmInputSuspend", "bool"),
}
ADAPTER_LABELS = {0: "unknown", 1: "SDP", 2: "DCP", 3: "CDP", 4: "ACA",
                  5: "Type-C", 6: "PD", 7: "PD_DRP", 8: "PD_PPS"}
STATUS_LABELS = {0: "unknown", 1: "charging", 2: "discharging", 3: "not_charging", 4: "full"}
NUMBER = r"[+-]?(?:0x[0-9a-fA-F]{1,16}|\d{1,16}(?:\.\d{1,9})?)"
VALUE = rf"(?:{NUMBER}|true|false|Yes|No|unknown|stale|default|-)(?:\s*(?:uV|µV|μV|mV|V|uA|µA|μA|mA|A|W))?(?:\([^)]{{0,32}}\))?"
PAIR = re.compile(rf'(?<![\w])"?([A-Za-z][A-Za-z0-9_]{{0,63}})"?\s*[=:]\s*({VALUE})(?=$|[\s,;|}})])')
MARKER = re.compile(r"FUXI BATTERY:|SWEET BATTERY:|Darwin Kernel Version")
FRESH_REQUIRED = (
    "FuxiBatterySourceStale", "FuxiBatteryChannelUp", "FuxiBatterySOCValid",
    "FuxiBatteryExternalKnown", "FuxiBatteryStatusKnown", "FuxiBatteryFreshFields",
    "FuxiBatteryMaxAgeMs", "FuxiBatterySOCAgeMs", "FuxiBatteryExternalAgeMs",
    "FuxiBatteryStatusAgeMs",
)


def number_value(text, default_unit=None):
    match = re.fullmatch(rf"({NUMBER}|true|false|Yes|No|unknown|stale|default|-)(?:\s*(uV|µV|μV|mV|V|uA|µA|μA|mA|A|W))?(?:\(([^)]{{0,32}})\))?", text)
    if not match:
        return {"value": None, "unit": default_unit, "annotation": "malformed"}
    token, unit, annotation = match.groups()
    unit = unit or default_unit
    if token in ("-", "unknown", "stale", "default") or annotation in ("default", "unknown", "invalid", "stale"):
        value = None
        annotation = annotation or token
    elif token in ("true", "Yes", "false", "No"):
        value = int(token in ("true", "Yes"))
    elif "0x" in token.lower():
        value = int(token, 16)
    else:
        value = float(token) if "." in token else int(token, 10)
    if value is not None and not math.isfinite(value):
        value = None
    if default_unit in ("uV", "uA", "mV", "mA") and value is not None:
        factors = {"uV": 1, "µV": 1, "μV": 1, "mV": 1000, "V": 1000000} if default_unit in ("uV", "mV") else {
            "uA": 1, "µA": 1, "μA": 1, "mA": 1000, "A": 1000000}
        if unit not in factors:
            value, annotation = None, "unit_mismatch"
        else:
            value *= factors[unit] / (1000 if default_unit in ("mV", "mA") else 1)
            unit = default_unit
            native = value * (1000 if default_unit in ("mV", "mA") else 1)
            if native < -(1 << 31) or native >= 1 << 31:
                value, annotation = None, "outside_native_int32"
    return {"value": value, "unit": unit, "annotation": annotation}


def timestamp(prefix):
    match = re.match(r"^\s*\[\s*(\d{1,12}(?:\.\d{1,9})?)\s*(ms|s)?\s*\]", prefix)
    if match:
        return {"clock": "relative_seconds", "value": float(match[1]) / (1000 if match[2] == "ms" else 1)}
    match = re.match(r"^\s*(?:t|time)=(\d{1,12}(?:\.\d{1,9})?)s\b", prefix)
    if match:
        return {"clock": "relative_seconds", "value": float(match[1])}
    match = re.search(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})?", prefix)
    if match:
        return {"clock": "wall_text_unaligned", "value": match[0]}
    return None


def freshness(properties, external=None):
    missing = [key for key in FRESH_REQUIRED if properties.get(key) is None]
    if properties.get("FuxiBatterySourceStale") == 1 or properties.get("FuxiBatteryChannelUp") == 0:
        return {"state": "stale", "missing": missing}
    if missing:
        return {"state": "unknown", "missing": missing}
    ttl = properties["FuxiBatteryMaxAgeMs"]
    ages = [properties[key] for key in FRESH_REQUIRED if key.endswith("AgeMs") and key != "FuxiBatteryMaxAgeMs" and
            not (external == 0 and key == "FuxiBatteryStatusAgeMs")]
    known = [properties[key] for key in FRESH_REQUIRED[:5]]
    mask = properties["FuxiBatteryFreshFields"]
    required_mask = (1 << 2) | (1 << 7) | (0 if external == 0 else 1)
    if not isinstance(mask, int) or mask < 0 or mask >= 1 << 32 or mask & required_mask != required_mask:
        return {"state": "unknown", "missing": ["consistent_core_fresh_mask"]}
    if ttl <= 0 or any(age < 0 or age >= ttl for age in ages) or known != [0, 1, 1, 1, 1]:
        return {"state": "stale", "missing": []}
    return {"state": "fresh", "missing": []}


def record_kind(marker, body):
    if marker == "metadata":
        return "metadata"
    if body.lstrip().startswith("rejected field"):
        return "rejection"
    if marker == "SWEET BATTERY:":
        if body.lstrip().startswith("read #"):
            return "sweet_readback"
        if "ADSP battery manager" in body:
            return "adsp_routing"
        return "sweet_publication"
    if body.lstrip().startswith("raw") or "BmUsb" in body:
        return "raw"
    return "summary" if "percent=" in body else "diagnostic"


def rejection_evidence(body, terminated):
    match = re.search(rf"\brejected field (\d{{1,2}}) value ({NUMBER})(?=$|\s)", body)
    if not match or not terminated and match.end() == len(body):
        return None
    index, value = int(match[1]), number_value(match[2])["value"]
    name = FIELDS[index][0] if index in FIELDS else None
    if index == 0 and value == 0:
        meaning = "unknown_status_enum"
    elif index in (11, 12) and value == -1:
        meaning = "unavailable_time_estimate_in_current_codec"
    else:
        meaning = "unclassified_semantic_rejection_requires_context"
    return {"field_index": index, "field": name, "reported_value": value,
            "meaning": meaning, "hardware_fault_proven": False,
            "accepted_fresh_observation": False,
            "ttl_extension": "none_under_current_producer_gate"}


def parse_record(body, kind, line_number, clock, terminated=True):
    fields, properties = {}, {}
    pairs = {}
    duplicates = []
    for match in PAIR.finditer(body):
        key, text = match.groups()
        if not terminated and match.end() == len(body):
            continue
        if key in pairs:
            duplicates.append(key)
        pairs[key] = text
    valid = number_value(pairs.get("valid", "-"))["value"]
    for index, (name, unit) in FIELDS.items():
        key = f"f{index}" if f"f{index}" in pairs else name
        if key in pairs:
            value = number_value(pairs[key], unit)
            value["diagnostic_valid_bit"] = bool(int(valid) & (1 << index)) if isinstance(valid, int) and valid >= 0 else None
            if key in duplicates:
                value["value"], value["annotation"] = None, "duplicate_key"
            fields[name] = value
    for key, text in pairs.items():
        if key.startswith(("FuxiBattery", "SweetBattery")) or key == "AppleRawExternalConnected":
            properties[key] = number_value(text)["value"] if key not in duplicates else None
    for key in ("percent", "external", "charging", "full", "mV", "mA", "temp", "adapter"):
        if key in pairs:
            fields[key] = number_value(pairs[key], {"mV": "mV", "mA": "mA", "temp": "centidegree_C"}.get(key))
            if key in duplicates:
                fields[key]["value"], fields[key]["annotation"] = None, "duplicate_key"
    if kind in ("sweet_publication", "sweet_readback", "adsp_routing"):
        match = re.search(r"(?<!\w)(\d{1,3})%", body)
        if match:
            fields["percent"] = number_value(match[1], "percent")
        for key, unit in (("mV", "mV"), ("mA", "mA")):
            match = re.search(rf"(?<!\w)({NUMBER}){unit}(?=$|[\s,])", body)
            if match:
                fields[key] = number_value(match[1], unit)
    adapter = re.search(rf"adapter={NUMBER}\s+({NUMBER})mV\s+({NUMBER})mA\s+({NUMBER})W(?=$|[\s|])", body)
    if adapter:
        for key, value, unit in zip(("adapter_voltage", "adapter_current_absolute", "adapter_watts_rounded"), adapter.groups(), ("mV", "mA", "W")):
            fields[key] = number_value(value, unit)
    external = fields.get("external", fields.get("BmUsbOnline", {})).get("value", properties.get("AppleRawExternalConnected"))
    record = {"line": line_number, "kind": kind, "timestamp": clock, "fields": fields,
              "properties": properties, "freshness": freshness(properties, external), "duplicates": duplicates,
              "source_flags": {"fallback": "static fallback" in body or properties.get("SweetBatteryFallback") == 1,
                               "estimated": "estimated" in body,
                               "staged": "staged" in body},
              "unterminated_line": not terminated}
    record["rejection"] = rejection_evidence(body, terminated) if kind == "rejection" else None
    publication = re.search(r"\bpublished #([0-9]{1,10})", body)
    record["publication_number"] = int(publication[1]) if publication else None
    record["derived"] = derive(record)
    return record


def derive(record):
    fields = record["fields"]

    def value(key):
        field = fields.get(key, {})
        if field.get("diagnostic_valid_bit") is False:
            return None
        return field.get("value")

    def product(voltage, current, scale, sign=1):
        voltage, current = value(voltage), value(current)
        return sign * voltage * current / scale if voltage is not None and voltage >= 0 and current is not None else None

    raw = "BmVoltage" in fields or "BmUsbVoltage" in fields
    battery = product("BmVoltage", "BmCurrent", 1e12, -1) if raw else product("mV", "mA", 1e6)
    usb = product("BmUsbVoltage", "BmUsbCurrent", 1e12) if raw else product("adapter_voltage", "adapter_current_absolute", 1e6)
    adapter = value("BmUsbAdapter")
    label = ADAPTER_LABELS.get(adapter, "unmapped_enum") if adapter is not None else None
    family = value("adapter")
    family_label = "PD_family_label" if family == 0xe000400a else None
    charging = value("charging")
    if charging is None and value("BmStatus") in (1, 2, 3, 4) and value("BmUsbOnline") in (0, 1):
        charging = int(value("BmUsbOnline") == 1 and value("BmStatus") == 1)
    if charging not in (0, 1):
        charging = None
    if record["source_flags"]["fallback"] or record["source_flags"]["estimated"]:
        battery, usb, charging = None, None, None
    fresh = record["freshness"]["state"] == "fresh" and not record["source_flags"]["staged"]
    mask = record["properties"].get("FuxiBatteryFreshFields", 0)
    usb_mask, battery_mask = (1 << 7) | (1 << 9) | (1 << 10), (1 << 3) | (1 << 4)
    if record["kind"] in ("sweet_readback", "adsp_routing", "rejection"):
        battery, usb, charging, fresh = None, None, None, False
    status = value("BmStatus")
    time_full, time_empty = value("BmTimeToFull"), value("BmTimeToEmpty")
    return {"usb_input_telemetry_signed_w": usb, "usb_input_meter_w": None,
            "battery_net_charge_positive_w": battery,
            "battery_direction": None if battery is None else "charging" if battery > 0 else "discharging" if battery < 0 else "zero",
            "usb_sign_note": "negative raw USB current is not converted to absolute" if usb is not None and usb < 0 else None,
            "summary_usb_current_note": "vendor summary uses absolute USB current" if not raw and usb is not None else None,
            "adapter_label_from_raw": label, "adapter_label_from_family": family_label,
            "input_limit_a": value("BmUsbLimit") / 1e6 if value("BmUsbLimit") is not None else None,
            "battery_status_label": STATUS_LABELS.get(status, "unmapped_enum") if status is not None else None,
            "time_to_full_minutes_codec": int(time_full // 60) if time_full is not None and 0 < time_full < 360000 else None,
            "time_to_empty_minutes_codec": int(time_empty // 60) if time_empty is not None and 0 < time_empty < 360000 else None,
            "fully_charged_flag_reported": value("full") if value("full") in (0, 1) else None,
            "charging_with_net_discharge_note": "requires_load_and_freshness_context_not_fault_proof" if charging == 1 and battery is not None and battery < 0 else None,
            "charging_flag_reported": charging,
            "charging_flag_freshness_qualified": charging if fresh else None,
            "usb_telemetry_freshness_qualified": bool(fresh and usb is not None and mask & usb_mask == usb_mask),
            "battery_telemetry_freshness_qualified": bool(fresh and battery is not None and mask & battery_mask == battery_mask),
            "power_qualification": "diagnostic_telemetry_not_physical_meter",
            "acceptable_fast_charge": "not_established"}


def new_boot(index):
    return {"segment": index, "kernel_banner": None, "boot_args_from_log": [],
            "boot_hashes_from_log": {}, "source_identifiers_from_log": {},
            "unverified_text_labels": [], "staged": False, "staged_reasons": [],
            "records": [], "omitted_records": 0, "channel_events": [], "ci_completion_markers": []}


def summarize(boot, window):
    records = boot["records"]
    eligible = [record for record in records if record["window_membership"] != "unknown" or window is None]
    observed = {}
    for key in ("usb_input_telemetry_signed_w", "battery_net_charge_positive_w"):
        for kind in ("raw", "summary", "sweet_publication"):
            values = [record["derived"][key] for record in eligible if record["kind"] == kind and record["derived"][key] is not None]
            observed[f"{kind}_{key}"] = {"count": len(values), "min": min(values) if values else None,
                                        "max": max(values) if values else None}
    missing = ["physical_unplug_confirmation", "charger_power_meter_measurement", "accepted_GET_timestamps_and_generation"]
    if not any(record["freshness"]["state"] == "fresh" for record in eligible) or boot["staged"]:
        missing.append("coherent_nonstaged_freshness")
    if not records or any(record["timestamp"] is None for record in records):
        missing.append("timestamps_for_all_battery_records")
    if boot["kernel_banner"] is None:
        missing.append("device_boot_identity")
    if not boot["boot_hashes_from_log"]:
        missing.append("boot_artifact_hash_from_log")
    if boot["staged"]:
        missing.append("nonstaged_experiment")
    if any(record["unterminated_line"] for record in records):
        missing.append("partial_or_unterminated_log_records")
    if boot["omitted_records"]:
        missing.append("record_retention_limit")
    relative = [record["timestamp"]["value"] for record in records if record["timestamp"] and record["timestamp"]["clock"] == "relative_seconds"]
    publications = [record for record in eligible if record["kind"] == "sweet_publication" and
                    record["publication_number"] is not None and not record["source_flags"]["fallback"]]
    readbacks = [record for record in eligible if record["kind"] == "sweet_readback"]
    observed_numbers = {record["publication_number"] for record in publications if
                        record["fields"].get("external", {}).get("value") in (0, 1) and
                        record["fields"].get("charging", {}).get("value") in (0, 1)}
    published_flags = {(record["publication_number"], record["fields"].get("external", {}).get("value"),
                        record["fields"].get("charging", {}).get("value")) for record in publications
                       if record["publication_number"] in observed_numbers}
    matching_readback = any((record["publication_number"], record["fields"].get("external", {}).get("value"),
                             record["fields"].get("charging", {}).get("value")) in published_flags for record in readbacks)
    return {"observed_power_by_source": observed, "missing": missing,
            "adsp_routing_log_seen": any(record["kind"] == "adsp_routing" for record in eligible),
            "consumer_publication_numbers_with_known_flags": sorted(observed_numbers),
            "consumer_readback_of_known_publication_seen": matching_readback,
            "consumer_evidence_qualification": "publication/readback logs only; no coherent TTL snapshot or physical acceptance inferred",
            "rejection_counts": {meaning: sum(record["rejection"] is not None and record["rejection"]["meaning"] == meaning for record in eligible)
                                 for meaning in ("unknown_status_enum", "unavailable_time_estimate_in_current_codec",
                                                 "unclassified_semantic_rejection_requires_context")},
            "rejection_count_scope": "retained messages only; bounded producer logging is not a complete response count",
            "rejection_hardware_fault_proven": False,
            "ci_build_completion_log_seen": bool(boot["ci_completion_markers"]),
            "ci_evidence_qualification": "build completion marker only; not device charging or independent workflow status verification",
            "boot_hash_conflicts": [key for key, entries in boot["boot_hashes_from_log"].items()
                                    if len({entry["value"] for entry in entries}) > 1],
            "staged_detection": "explicit markers or declared staged config only; absence is not proof",
            "freshness_record_counts": {state: sum(record["freshness"]["state"] == state for record in eligible)
                                        for state in ("fresh", "stale", "unknown")},
            "adapter_labels_from_raw": sorted({record["derived"]["adapter_label_from_raw"] for record in eligible
                                                if record["derived"]["adapter_label_from_raw"] is not None}),
            "relative_time_range_s": [min(relative), max(relative)] if relative else None,
            "time_basis": "per-record explicit timestamps only; no cross-line clock inheritance",
            "untimed_window_records": sum(record["window_membership"] == "unknown" for record in records),
            "full_soc_context": any(record["fields"].get("percent", {}).get("value") == 100 or
                                    record["fields"].get("BmCapacity", {}).get("value") == 10000 for record in eligible),
            "physical_unplug": "not_established", "fast_charge_acceptance": "not_established",
            "peak_67w": "not_established; PD label and full-SOC low power are not peak acceptance or failure"}


def parse_log(path, experiment=None, window=None, max_bytes=64 * 1024 * 1024,
              max_line_bytes=65536, max_records=2000, max_boots=32, tail_bytes=0):
    if min(max_bytes, max_line_bytes, max_records, max_boots) <= 0:
        raise ValueError("bounds must be positive")
    if tail_bytes < 0:
        raise ValueError("tail bytes must be nonnegative")
    if window and (not all(value is None or math.isfinite(value) and value >= 0 for value in window) or
                   window[0] is not None and window[1] is not None and window[0] > window[1]):
        raise ValueError("invalid relative-second window")
    path = Path(path).resolve()
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("input must be an existing regular host log file")
    start_offset = max(0, before.st_size - min(tail_bytes, max_bytes)) if tail_bytes else 0
    digest = hashlib.sha256()
    boots, line_number, scanned, retained, oversized = [new_boot(1)], 0, 0, 0, 0
    boot_limit = False
    with path.open("rb") as stream:
        leading_fragment = False
        if start_offset:
            stream.seek(start_offset - 1)
            leading_fragment = stream.read(1) != b"\n"
        stream.seek(start_offset)
        discard_fragment = leading_fragment
        while scanned < max_bytes:
            chunk = stream.readline(min(max_line_bytes + 1, max_bytes - scanned))
            if not chunk:
                break
            scanned += len(chunk)
            digest.update(chunk)
            line_number += 1
            if len(chunk) > max_line_bytes:
                oversized += 1
                while not chunk.endswith(b"\n") and scanned < max_bytes:
                    chunk = stream.readline(min(max_line_bytes + 1, max_bytes - scanned))
                    scanned += len(chunk)
                    digest.update(chunk)
                    if not chunk:
                        break
                discard_fragment = False
                continue
            if discard_fragment:
                discard_fragment = False
                continue
            line = chunk.decode("utf-8", errors="replace").rstrip("\r\n")
            boot = boots[-1]
            if re.match(r"^\s*(?:\[[^]]{1,64}\]\s*)?Darwin Kernel Version", line):
                if boot["kernel_banner"] is not None:
                    if len(boots) >= max_boots:
                        boot_limit = True
                        break
                    boot = new_boot(len(boots) + 1)
                    boots.append(boot)
                boot["kernel_banner"] = line[:512]
            if "XNU Build Done!" in line and len(boot["ci_completion_markers"]) < 8:
                boot["ci_completion_markers"].append({"line": line_number, "marker": "XNU Build Done!"})
            args = re.search(r"boot-args\s*=\s*(.*)", line)
            if args and len(boot["boot_args_from_log"]) < 16:
                boot["boot_args_from_log"].append({"line": line_number, "value": args[1][:2048]})
            for match in re.finditer(r"\b(kernel|boot|loader|ksrc|harness)[_ -](sha256|commit)\s*[=:]\s*([0-9a-fA-F]{40,64})(?![0-9a-fA-F])", line):
                if len(match[3]) in (40, 64):
                    category = "boot_hashes_from_log" if match[1] in ("kernel", "boot", "loader") and match[2] == "sha256" and len(match[3]) == 64 else "source_identifiers_from_log"
                    entries = boot[category].setdefault(f"{match[1]}_{match[2]}", [])
                    if len(entries) < 8:
                        entries.append({"line": line_number, "value": match[3].lower()})
            for label in re.findall(r"\b(?:PD(?:_PPS|_DRP)?|QC(?:2\.0|3\.0|4\+)?|67\s?W)\b", line):
                if len(boot["unverified_text_labels"]) < 32:
                    boot["unverified_text_labels"].append({"line": line_number, "label": label, "qualification": "text_claim_not_measurement"})
            if re.search(r"(?:fuxi,adsp|fuxiadsp)\s*[=:]\s*4\b|staged reading|battery.*staged", line, re.I):
                boot["staged"] = True
                if len(boot["staged_reasons"]) < 8:
                    boot["staged_reasons"].append(line_number)
            markers = list(MARKER.finditer(line))
            segments = [(match.end(), markers[index + 1].start() if index + 1 < len(markers) else len(line), match[0])
                        for index, match in enumerate(markers) if match[0] != "Darwin Kernel Version"]
            if not segments and "FuxiBattery" in line:
                segments = [(0, len(line), "metadata")]
            for index, (start, end, marker) in enumerate(segments):
                body = line[start:end]
                clock = timestamp(line if marker == "metadata" else line[:start]) if index == 0 else None
                kind = record_kind(marker, body)
                if "channel up" in body or "channel down" in body:
                    if len(boot["channel_events"]) < 64:
                        boot["channel_events"].append({"line": line_number, "up": "channel up" in body, "timestamp": clock})
                terminated = chunk.endswith(b"\n") and (end == len(line) or not body or body[-1].isspace())
                record = parse_record(body, kind, line_number, clock, terminated)
                if not record["fields"] and not record["properties"] and not record["rejection"]:
                    continue
                membership = "all"
                if window:
                    if clock is None or clock["clock"] != "relative_seconds":
                        membership = "unknown"
                    elif (window[0] is not None and clock["value"] < window[0]) or (window[1] is not None and clock["value"] > window[1]):
                        continue
                    else:
                        membership = "inside"
                record["window_membership"] = membership
                if retained >= max_records:
                    boot["omitted_records"] += 1
                else:
                    boot["records"].append(record)
                    retained += 1
    after = path.stat()
    unchanged = (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    complete = start_offset == 0 and scanned == after.st_size and unchanged and not boot_limit
    for boot in boots:
        config = (experiment or {}).get("config", {})
        if config.get("staged") is True or config.get("fuxiadsp") == 4 or config.get("fuxi,adsp") == 4:
            boot["staged"] = True
            boot["staged_reasons"].append("declared_manifest_staged_config")
        for record in boot["records"]:
            record["excluded_from_physical_evidence"] = boot["staged"] or start_offset > 0
            if boot["staged"] or start_offset > 0:
                record["derived"]["charging_flag_freshness_qualified"] = None
                record["derived"]["usb_telemetry_freshness_qualified"] = False
                record["derived"]["battery_telemetry_freshness_qualified"] = False
        boot["summary"] = summarize(boot, window)
        if start_offset:
            boot["summary"]["missing"].append("unscanned_prefix_context")
        boot["summary"]["retained_records_only"] = True
    return {"schema": "fuxi-charge-evidence-v1", "input": str(path),
            "log_sha256": digest.hexdigest() if complete else None,
            "scanned_prefix_sha256": digest.hexdigest() if start_offset == 0 else None,
            "scanned_range_sha256": digest.hexdigest(),
            "hash_scope": "full_file" if complete else "scanned_byte_range_only" if start_offset else "scanned_prefix_only",
            "scanned_byte_range": [start_offset, start_offset + scanned],
            "line_number_basis": "scan_start_not_absolute_file_line" if start_offset else "absolute_file_line",
            "leading_fragment_discarded": leading_fragment, "boundary_probe_bytes": int(start_offset > 0),
            "scanned_bytes": scanned, "file_bytes": after.st_size, "file_changed_during_read": not unchanged,
            "bounds": {"max_bytes": max_bytes, "max_line_bytes": max_line_bytes, "max_records": max_records, "max_boots": max_boots, "tail_bytes": tail_bytes},
            "incomplete": not complete or oversized > 0 or any(boot["omitted_records"] or
                any(record["unterminated_line"] for record in boot["records"]) for boot in boots),
            "partial_or_unterminated_records": sum(record["unterminated_line"] for boot in boots for record in boot["records"]),
            "oversized_lines_skipped": oversized, "boot_limit_hit": boot_limit,
            "experiment_declared_unverified": experiment or {}, "requested_relative_window_s": window,
            "boots": boots}


def main():
    parser = argparse.ArgumentParser(description="Read existing host log files only; no device access or charging controls.")
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--since", type=float)
    parser.add_argument("--until", type=float)
    parser.add_argument("--max-bytes", type=int, default=64 * 1024 * 1024)
    parser.add_argument("--max-line-bytes", type=int, default=65536)
    parser.add_argument("--max-records", type=int, default=2000)
    parser.add_argument("--max-boots", type=int, default=32)
    parser.add_argument("--tail-bytes", type=int, default=0)
    arguments = parser.parse_args()
    experiments = {}
    if arguments.manifest:
        if arguments.manifest.stat().st_size > 1024 * 1024:
            parser.error("manifest exceeds 1 MiB")
        manifest = json.loads(arguments.manifest.read_text(encoding="utf-8"))
        for item in manifest["experiments"]:
            path = Path(item["log"])
            key = str((arguments.manifest.parent / path).resolve())
            if key in experiments:
                parser.error("duplicate log in manifest")
            experiments[key] = item
    window = (arguments.since, arguments.until) if arguments.since is not None or arguments.until is not None else None
    try:
        reports = [parse_log(path, experiments.get(str(path.resolve())), window, arguments.max_bytes,
                             arguments.max_line_bytes, arguments.max_records, arguments.max_boots, arguments.tail_bytes) for path in arguments.logs]
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({"reports": reports, "cross_boot_aggregation": False}, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
