import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


sys.dont_write_bytecode = True
TOOL = Path(__file__).with_name("fuxi-charge-evidence.py")
SPEC = importlib.util.spec_from_file_location("charge_evidence", TOOL)
evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evidence)

REAL_RAW = "FUXI BATTERY: raw valid=0xffffffff last_timeout=-1 f0=1 f1=1 f2=10000 f3=4436000 f4=-343000 f5=3820 f6=4241 f7=1 f8=1 f9=4622000 f10=831000 f11=65535 f12=-1 f13=4241000 f14=4268000 f15=0 f16=4241000 f17=4268000 f18=4500000 f19=152 f20=6 f21=1200000 f22=12FUXI BATTERY: percent=100 mV=4436 mA=343 temp=3820 present=1 external=1 charging=1 full=1 adapter=0xe0004000 4626mV 831mA 4W\n"
REAL_SUMMARY = "FUXI BATTERY: percent=100 mV=4393 mA=-579 temp=3810 present=1 external=1 charging=0 full=1 critical=0 mAh raw=4241 full=4268 design=4500 cycles=152 tte_min=7 ttf_min=-1 adapter=0xe0004000 5136mV 356mA 2W | cycles=1 answers=32 timeouts=0 errors=0\n"
ITER3_CONSUMER = "SWEET BATTERY: static fallback, 100% 4200mV external=1 charging=0\nSWEET BATTERY: ADSP battery manager, 100% 4200mV 0mA external=1 charging=0\nSWEET BATTERY: published #1 100% external=1(unknown) charging=0(unknown) full=1 0mA\nSWEET BATTERY: read #1 by powerd (published #1: 100% external=9 charging=9)\nFUXI BATTERY: rejected field 0 value 0\nFUXI BATTERY: rejected field 12 value -1\nSWEET BATTERY: published #2 100% external=1 charging=1 full=1 -778mA\nSWEET BATTERY: read #8 by UserEventAgent (published #2: 100% external=1 charging=1)\nSWEET BATTERY: published #3 100% external=1 charging=0 full=1 -9mA\n"


def metadata(**updates):
    values = {"FuxiBatterySourceStale": 0, "FuxiBatteryChannelUp": 1,
              "FuxiBatterySOCValid": 1, "FuxiBatteryExternalKnown": 1,
              "FuxiBatteryStatusKnown": 1, "FuxiBatteryFreshFields": 0xffffffff,
              "FuxiBatteryMaxAgeMs": 90000, "FuxiBatterySOCAgeMs": 0,
              "FuxiBatteryExternalAgeMs": 1000, "FuxiBatteryStatusAgeMs": 2000}
    values.update(updates)
    return " ".join(f'"{key}" = {value}' for key, value in values.items())


class ChargeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fuxi-charge-host-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def parse(self, text, filename="boot.log", **options):
        path = self.root / filename
        path.write_bytes(text.encode("utf-8"))
        return evidence.parse_log(path, **options)

    def record(self, text):
        return self.parse(text)["boots"][0]["records"][0]

    def test_real_interleaved_truncated_field_fixture(self):
        report = self.parse(REAL_RAW)
        records = report["boots"][0]["records"]
        self.assertEqual(len(records), 2)
        raw = records[0]
        self.assertNotIn("BmUsbMax", raw["fields"])
        self.assertEqual(raw["derived"]["adapter_label_from_raw"], "PD")
        self.assertAlmostEqual(raw["derived"]["usb_input_telemetry_signed_w"], 3.840882)
        self.assertAlmostEqual(raw["derived"]["battery_net_charge_positive_w"], 1.521548)
        self.assertEqual(raw["derived"]["input_limit_a"], 1.2)
        self.assertEqual(raw["freshness"]["state"], "unknown")
        self.assertIsNone(raw["derived"]["usb_input_meter_w"])

    def test_real_summary_discharge_and_rounded_watts(self):
        record = self.record(REAL_SUMMARY)
        self.assertAlmostEqual(record["derived"]["usb_input_telemetry_signed_w"], 1.828416)
        self.assertAlmostEqual(record["derived"]["battery_net_charge_positive_w"], -2.543547)
        self.assertEqual(record["fields"]["adapter_watts_rounded"]["value"], 2)
        self.assertEqual(record["derived"]["battery_direction"], "discharging")
        self.assertEqual(record["derived"]["charging_flag_reported"], 0)

    def test_units_and_explicit_signs(self):
        for unit, voltage, current in (("u", "4000000uV", "-1000000uA"),
                                       ("m", "4000mV", "-1000mA"),
                                       ("base", "4V", "-1A"),
                                       ("micro", "4000000μV", "-1000000µA")):
            with self.subTest(unit=unit):
                record = self.record(f"FUXI BATTERY: raw BmVoltage={voltage} BmCurrent={current} BmUsbVoltage=9V BmUsbCurrent=+2A\n")
                self.assertEqual(record["derived"]["battery_net_charge_positive_w"], 4)
                self.assertEqual(record["derived"]["usb_input_telemetry_signed_w"], 18)

    def test_zero_and_negative_usb_not_absolute(self):
        for current, watts, direction in (("0", 0, "zero"), ("1000000", -4, "discharging"), ("-1000000", 4, "charging")):
            with self.subTest(current=current):
                record = self.record(f"FUXI BATTERY: raw valid=0xffffffff f3=4000000 f4={current} f9=5000000 f10=-200000\n")
                self.assertEqual(record["derived"]["battery_net_charge_positive_w"], watts)
                self.assertEqual(record["derived"]["battery_direction"], direction)
                self.assertEqual(record["derived"]["usb_input_telemetry_signed_w"], -1)
                self.assertIsNotNone(record["derived"]["usb_sign_note"])

    def test_native_numeric_hex_zero(self):
        record = self.record("FUXI BATTERY: raw valid=0xffffffff f3=0x3d0900 f4=0 f9=0 f10=0 f21=0\n")
        self.assertEqual(record["derived"]["battery_net_charge_positive_w"], 0)
        self.assertEqual(record["derived"]["usb_input_telemetry_signed_w"], 0)
        self.assertEqual(record["derived"]["input_limit_a"], 0)

    def test_unit_mismatch_and_native_bounds(self):
        for voltage in ("4A", "9999999999999999V", "-4V"):
            with self.subTest(voltage=voltage):
                record = self.record(f"FUXI BATTERY: raw BmVoltage={voltage} BmCurrent=-1A\n")
                self.assertIsNone(record["derived"]["battery_net_charge_positive_w"])

    def test_summary_unit_conversion(self):
        record = self.record("FUXI BATTERY: percent=50 mV=4V mA=1A external=1 charging=1\n")
        self.assertEqual(record["derived"]["battery_net_charge_positive_w"], 4)

    def test_invalid_mask_does_not_qualify_power(self):
        record = self.record("FUXI BATTERY: raw valid=0 f3=4000000 f4=-1000000 f9=9000000 f10=2000000 f20=6\n")
        self.assertIsNone(record["derived"]["battery_net_charge_positive_w"])
        self.assertIsNone(record["derived"]["adapter_label_from_raw"])

    def test_unknown_default_stale_annotations(self):
        for annotation in ("default", "unknown", "stale", "invalid"):
            with self.subTest(annotation=annotation):
                record = self.record(f"FUXI BATTERY: percent=100({annotation}) mV=4200 mA=1({annotation}) external=1(unknown) charging=0(unknown)\n")
                self.assertIsNone(record["fields"]["percent"]["value"])
                self.assertIsNone(record["derived"]["battery_net_charge_positive_w"])
                self.assertIsNone(record["derived"]["charging_flag_reported"])

    def test_bare_unknown_and_partial_dash(self):
        record = self.record("FUXI BATTERY: raw valid=0xffffffff f3=4000000 f4=- f7=unknown f9=stale f10=default\n")
        self.assertEqual(record["fields"]["BmUsbOnline"]["annotation"], "unknown")
        self.assertIsNone(record["derived"]["usb_input_telemetry_signed_w"])

    def test_bootstrap_is_not_measured(self):
        record = self.record("SWEET BATTERY: static fallback, 100% 4200mV external=1 charging=0\n")
        self.assertTrue(record["source_flags"]["fallback"])
        self.assertIsNone(record["derived"]["charging_flag_reported"])
        self.assertEqual(record["freshness"]["state"], "unknown")

    def test_sweet_publication_sign_and_unknown(self):
        record = self.record("SWEET BATTERY: published #3 57% external=0(unknown) charging=0(unknown) full=0 -300mA\n")
        self.assertEqual(record["fields"]["mA"]["value"], -300)
        self.assertIsNone(record["derived"]["charging_flag_reported"])
        self.assertIsNone(record["derived"]["battery_net_charge_positive_w"])

    def test_coherent_metadata_fresh(self):
        record = self.record("[10] " + metadata() + "\n")
        self.assertEqual(record["freshness"]["state"], "fresh")
        self.assertEqual(record["timestamp"]["value"], 10)

    def test_same_record_fresh_telemetry_still_not_meter_or_fast_pass(self):
        record = self.record("[10] FUXI BATTERY: raw valid=0xffffffff f0=1 f2=5000 f3=4000000 f4=-1000000 f7=1 f9=9000000 f10=2000000 " + metadata() + "\n")
        self.assertEqual(record["derived"]["charging_flag_freshness_qualified"], 1)
        self.assertTrue(record["derived"]["usb_telemetry_freshness_qualified"])
        self.assertTrue(record["derived"]["battery_telemetry_freshness_qualified"])
        self.assertIsNone(record["derived"]["usb_input_meter_w"])
        self.assertEqual(record["derived"]["acceptable_fast_charge"], "not_established")

    def test_stale_loss_and_ttl_boundary(self):
        for updates in ({"FuxiBatterySourceStale": 1}, {"FuxiBatteryChannelUp": 0},
                        {"FuxiBatteryExternalAgeMs": 90000}, {"FuxiBatterySOCValid": 0}):
            with self.subTest(updates=updates):
                self.assertEqual(self.record(metadata(**updates) + "\n")["freshness"]["state"], "stale")

    def test_online_zero_status_age_exception(self):
        record = self.record(metadata(FuxiBatteryFreshFields=132, FuxiBatteryStatusAgeMs=4294967295) + " AppleRawExternalConnected=0\n")
        self.assertEqual(record["freshness"]["state"], "fresh")
        self.assertEqual(self.parse(metadata() + "\n")["boots"][0]["summary"]["physical_unplug"], "not_established")

    def test_inconsistent_fresh_mask(self):
        record = self.record(metadata(FuxiBatteryFreshFields=0) + "\n")
        self.assertEqual(record["freshness"]["state"], "unknown")

    def test_metadata_across_lines_not_merged(self):
        lines = metadata().split(' "')
        report = self.parse("\n".join(lines) + "\n")
        self.assertIn("coherent_nonstaged_freshness", report["boots"][0]["summary"]["missing"])
        self.assertTrue(all(record["freshness"]["state"] != "fresh" for record in report["boots"][0]["records"]))

    def test_two_files_and_two_boot_segments_not_mixed(self):
        first = self.parse("Darwin Kernel Version first\n" + REAL_RAW, filename="first.log")
        second = self.parse("Darwin Kernel Version second\n" + REAL_SUMMARY, filename="second.log")
        self.assertNotEqual(first["log_sha256"], second["log_sha256"])
        combined = self.parse("Darwin Kernel Version first\n" + REAL_RAW + "Darwin Kernel Version second\n" + REAL_SUMMARY)
        self.assertEqual(len(combined["boots"]), 2)
        self.assertEqual(combined["boots"][0]["summary"]["adapter_labels_from_raw"], ["PD"])
        self.assertEqual(combined["boots"][1]["summary"]["adapter_labels_from_raw"], [])

    def test_pd_low_power_full_is_neither_peak_nor_broken(self):
        boot = self.parse(REAL_RAW)["boots"][0]
        self.assertTrue(boot["summary"]["full_soc_context"])
        self.assertEqual(boot["summary"]["fast_charge_acceptance"], "not_established")
        self.assertNotIn("broken", json.dumps(boot))
        self.assertIn("charger_power_meter_measurement", boot["summary"]["missing"])

    def test_staged_after_observation_taints_only_that_boot(self):
        log = "Darwin Kernel Version staged\n" + REAL_RAW + "FUXI BATTERY: TEST (fuxi,adsp=4) SweetBattery now gets a staged reading: 57%, unplugged, -300 mA\nSWEET BATTERY: published #2 57% external=0 charging=0 full=0 -300mA\nDarwin Kernel Version normal\n" + REAL_RAW
        boots = self.parse(log)["boots"]
        self.assertTrue(boots[0]["staged"])
        self.assertFalse(boots[1]["staged"])
        self.assertEqual(boots[0]["summary"]["physical_unplug"], "not_established")
        self.assertIn("nonstaged_experiment", boots[0]["summary"]["missing"])

    def test_unflagged_57_percent_is_not_automatically_staged(self):
        boot = self.parse("SWEET BATTERY: published #1 57% external=0 charging=0 full=0 -300mA\n")["boots"][0]
        self.assertFalse(boot["staged"])
        self.assertEqual(boot["summary"]["physical_unplug"], "not_established")

    def test_window_does_not_inherit_time_or_mix_wall_clock(self):
        log = "[1] " + REAL_RAW + "[10s] " + REAL_SUMMARY + REAL_RAW + "2026-11-16T12:30:00+08:00 " + REAL_SUMMARY
        boot = self.parse(log, window=(5, 15))["boots"][0]
        self.assertEqual(boot["summary"]["relative_time_range_s"], [10, 10])
        self.assertEqual(boot["summary"]["untimed_window_records"], 4)
        self.assertEqual(boot["summary"]["observed_power_by_source"]["raw_usb_input_telemetry_signed_w"]["count"], 0)

    def test_timestamp_formats_and_unknown_range(self):
        for prefix in ("[10000ms] ", "t=10s ", "time=10s "):
            with self.subTest(prefix=prefix):
                self.assertEqual(self.record(prefix + REAL_SUMMARY)["timestamp"]["value"], 10)
        self.assertIsNone(self.parse(REAL_SUMMARY)["boots"][0]["summary"]["relative_time_range_s"])

    def test_truncated_eof_and_duplicate_key(self):
        record = self.record("FUXI BATTERY: raw valid=0xffffffff f3=4000000 f4=-1000000")
        self.assertTrue(record["unterminated_line"])
        self.assertNotIn("BmCurrent", record["fields"])
        record = self.record("FUXI BATTERY: raw valid=0xffffffff f3=4000000 f4=-1000000 f4=+1000000\n")
        self.assertEqual(record["fields"]["BmCurrent"]["annotation"], "duplicate_key")
        self.assertIsNone(record["derived"]["battery_net_charge_positive_w"])

    def test_long_log_bounds_and_prefix_hash(self):
        text = REAL_SUMMARY * 200
        report = self.parse(text, max_bytes=2048, max_records=2)
        self.assertTrue(report["incomplete"])
        self.assertEqual(report["scanned_bytes"], 2048)
        self.assertIsNone(report["log_sha256"])
        self.assertEqual(report["scanned_prefix_sha256"], hashlib.sha256(text.encode()[:2048]).hexdigest())
        self.assertEqual(len(report["boots"][0]["records"]), 2)
        self.assertGreater(report["boots"][0]["omitted_records"], 0)

    def test_oversized_line_skipped_and_boot_limit(self):
        report = self.parse("noise" * 2000 + REAL_RAW + REAL_SUMMARY, max_line_bytes=1024)
        self.assertEqual(report["oversized_lines_skipped"], 1)
        self.assertEqual(len(report["boots"][0]["records"]), 1)
        report = self.parse("Darwin Kernel Version first\n" + REAL_RAW + "Darwin Kernel Version second\n" + REAL_SUMMARY, max_boots=1)
        self.assertTrue(report["boot_limit_hit"])
        self.assertIsNone(report["log_sha256"])

    def test_config_hashes_stay_declared_and_separate(self):
        experiment = {"experiment_id": "full-pd", "kind": "ci", "config": {"rated_watts": 67, "staged": True},
                      "boot_hashes": {"kernel_sha256": "1" * 64}, "physical_unplug": True}
        log = "kernel_sha256=" + "2" * 64 + "\nboot-args = fuxiadsp=4\n" + REAL_RAW
        report = self.parse(log, experiment=experiment)
        self.assertEqual(report["experiment_declared_unverified"], experiment)
        self.assertEqual(report["boots"][0]["boot_hashes_from_log"]["kernel_sha256"][0]["value"], "2" * 64)
        self.assertEqual(report["boots"][0]["summary"]["physical_unplug"], "not_established")

    def test_qc_pd_67w_labels_and_source_hash_are_not_power(self):
        boot = self.parse("charger label=QC3.0 rated=67W protocol=PD\nksrc_commit=" + "1" * 40 + "\n")["boots"][0]
        self.assertEqual([item["label"] for item in boot["unverified_text_labels"]], ["QC3.0", "67W", "PD"])
        self.assertIn("ksrc_commit", boot["source_identifiers_from_log"])
        self.assertEqual(boot["boot_hashes_from_log"], {})
        self.assertIn("boot_artifact_hash_from_log", boot["summary"]["missing"])
        self.assertEqual(boot["summary"]["fast_charge_acceptance"], "not_established")

    def test_conflicting_boot_hashes_not_overwritten(self):
        boot = self.parse("kernel_sha256=" + "1" * 64 + "\nkernel_sha256=" + "2" * 64 + "\n")["boots"][0]
        self.assertEqual(len(boot["boot_hashes_from_log"]["kernel_sha256"]), 2)
        self.assertEqual(boot["summary"]["boot_hash_conflicts"], ["kernel_sha256"])

    def test_mapping_matches_owning_enum(self):
        header = TOOL.parents[1] / "xnu/fuxi-adsp/ShengBattmgr.h"
        body = re.search(r"enum\s*\{(.*?)\};", header.read_text(), re.S)[1]
        names = [name.strip() for name in re.sub(r"/\*.*?\*/", "", body, flags=re.S).split(",")]
        for index, (name, unit) in evidence.FIELDS.items():
            self.assertEqual(names[index], name)

    def test_cli_manifest_and_no_cross_file_aggregation(self):
        self.parse(REAL_RAW, filename="first.log")
        self.parse(REAL_SUMMARY, filename="second.log")
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps({"experiments": [{"log": "first.log", "experiment_id": "pd-full", "config": {"rated_watts": 67}}]}))
        result = subprocess.run([sys.executable, str(TOOL), str(self.root / "first.log"), str(self.root / "second.log"), "--manifest", str(manifest)], capture_output=True, text=True, check=True)
        output = json.loads(result.stdout)
        self.assertFalse(output["cross_boot_aggregation"])
        self.assertEqual(output["reports"][0]["experiment_declared_unverified"]["experiment_id"], "pd-full")
        self.assertEqual(output["reports"][1]["experiment_declared_unverified"], {})

    def test_invalid_bounds_and_window(self):
        for options in ({"max_bytes": 0}, {"max_records": -1}, {"tail_bytes": -1}, {"window": (20, 10)}, {"window": (float("nan"), 10)}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.parse(REAL_RAW, **options)
        with self.assertRaises(ValueError):
            evidence.parse_log(self.root)

    def test_iter3_routing_bootstrap_and_actual_publication_are_separate(self):
        boot = self.parse(ITER3_CONSUMER)["boots"][0]
        summary = boot["summary"]
        self.assertTrue(summary["adsp_routing_log_seen"])
        self.assertEqual(summary["consumer_publication_numbers_with_known_flags"], [2, 3])
        self.assertTrue(summary["consumer_readback_of_known_publication_seen"])
        self.assertIn("coherent_nonstaged_freshness", summary["missing"])
        self.assertEqual(summary["physical_unplug"], "not_established")
        route = next(record for record in boot["records"] if record["kind"] == "adsp_routing")
        self.assertIsNone(route["derived"]["battery_net_charge_positive_w"])
        self.assertIsNone(route["derived"]["charging_flag_reported"])
        initial = next(record for record in boot["records"] if record["kind"] == "sweet_publication" and record["publication_number"] == 1)
        self.assertIsNone(initial["fields"]["external"]["value"])

    def test_rejected_unknown_and_time_unavailable_not_fault(self):
        boot = self.parse(ITER3_CONSUMER)["boots"][0]
        rejected = [record for record in boot["records"] if record["kind"] == "rejection"]
        self.assertEqual([record["rejection"]["field"] for record in rejected], ["BmStatus", "BmTimeToFull"])
        self.assertEqual(boot["summary"]["rejection_counts"]["unknown_status_enum"], 1)
        self.assertEqual(boot["summary"]["rejection_counts"]["unavailable_time_estimate_in_current_codec"], 1)
        for record in rejected:
            self.assertFalse(record["rejection"]["hardware_fault_proven"])
            self.assertFalse(record["rejection"]["accepted_fresh_observation"])
            self.assertEqual(record["rejection"]["ttl_extension"], "none_under_current_producer_gate")
            self.assertIsNone(record["derived"]["charging_flag_reported"])

    def test_unclassified_rejection_and_truncated_rejection(self):
        record = self.record("FUXI BATTERY: rejected field 3 value 1000000\n")
        self.assertEqual(record["rejection"]["meaning"], "unclassified_semantic_rejection_requires_context")
        self.assertFalse(record["rejection"]["hardware_fault_proven"])
        self.assertEqual(self.parse("FUXI BATTERY: rejected field 12 value -1")["boots"][0]["records"], [])

    def test_unknown_status_and_full_can_coexist_without_fault_claim(self):
        record = self.record("FUXI BATTERY: raw valid=0xffffffff f0=0 f2=10000 f7=1 f12=-1 full=1\n")
        self.assertEqual(record["derived"]["battery_status_label"], "unknown")
        self.assertEqual(record["derived"]["fully_charged_flag_reported"], 1)
        self.assertIsNone(record["derived"]["charging_flag_reported"])
        self.assertIsNone(record["derived"]["time_to_full_minutes_codec"])

    def test_time_units_and_codec_unavailable_bounds(self):
        for seconds, expected in ((1200, 20), (60, 1), (0, None), (-1, None), (360000, None)):
            with self.subTest(seconds=seconds):
                record = self.record(f"FUXI BATTERY: raw valid=0xffffffff f11={seconds} f12={seconds}\n")
                self.assertEqual(record["fields"]["BmTimeToFull"]["unit"], "s")
                self.assertEqual(record["derived"]["time_to_full_minutes_codec"], expected)
                self.assertEqual(record["derived"]["time_to_empty_minutes_codec"], expected)

    def test_iter3_filtered_raw_status_time_and_signed_current(self):
        record = self.record("FUXI BATTERY: raw valid=0xffffeffe last_timeout=-1 f0=- f2=10000 f3=4394000 f4=569000 f7=1 f9=5140000 f10=356000 f12=- f20=1 f21=100000\n")
        self.assertIsNone(record["derived"]["battery_status_label"])
        self.assertIsNone(record["derived"]["time_to_full_minutes_codec"])
        self.assertEqual(record["derived"]["battery_direction"], "discharging")
        self.assertAlmostEqual(record["derived"]["usb_input_telemetry_signed_w"], 1.82984)

    def test_readback_unknown_sentinel_nine_and_mismatching_flags(self):
        record = self.record("SWEET BATTERY: read #1 by powerd (published #1: 100% external=9 charging=9)\n")
        self.assertEqual(record["kind"], "sweet_readback")
        self.assertEqual(record["publication_number"], 1)
        self.assertIsNone(record["derived"]["charging_flag_reported"])
        boot = self.parse("SWEET BATTERY: published #2 100% external=1 charging=1 full=1 -778mA\nSWEET BATTERY: read #8 by powerd (published #2: 100% external=0 charging=0)\n")["boots"][0]
        self.assertFalse(boot["summary"]["consumer_readback_of_known_publication_seen"])

    def test_iter3_ci_completion_markers_are_not_device_measurements(self):
        first = self.parse("  🎉 XNU Build Done!\nGenerated metal4 ADT(s) and cmdline.txt\n", filename="5g-build.log")
        second = self.parse("  🎉 XNU Build Done!\n17 inputs match; iig(DriverKit-286)\n", filename="9g-build.log")
        for report in (first, second):
            boot = report["boots"][0]
            self.assertTrue(boot["summary"]["ci_build_completion_log_seen"])
            self.assertEqual(boot["records"], [])
            self.assertFalse(boot["summary"]["adsp_routing_log_seen"])
            self.assertIn("device_boot_identity", boot["summary"]["missing"])
            self.assertEqual(boot["summary"]["fast_charge_acceptance"], "not_established")

    def test_rejections_respect_window_and_boot_isolation(self):
        text = "Darwin Kernel Version first\n[1] FUXI BATTERY: rejected field 0 value 0\n[10] FUXI BATTERY: rejected field 12 value -1\nDarwin Kernel Version second\n[10] FUXI BATTERY: rejected field 0 value 0\n"
        boots = self.parse(text, window=(5, 15))["boots"]
        self.assertEqual(boots[0]["summary"]["rejection_counts"]["unknown_status_enum"], 0)
        self.assertEqual(boots[0]["summary"]["rejection_counts"]["unavailable_time_estimate_in_current_codec"], 1)
        self.assertEqual(boots[1]["summary"]["rejection_counts"]["unknown_status_enum"], 1)

    def test_charging_flag_with_net_discharge_note_is_not_fault(self):
        record = self.record("FUXI BATTERY: percent=100 mV=4357 mA=-778 external=1 charging=1 full=1\n")
        self.assertEqual(record["derived"]["fully_charged_flag_reported"], 1)
        self.assertEqual(record["derived"]["charging_with_net_discharge_note"], "requires_load_and_freshness_context_not_fault_proof")
        self.assertEqual(record["derived"]["acceptable_fast_charge"], "not_established")

    def test_bounded_ci_tail_has_range_hash_not_full_or_prefix_hash(self):
        text = "n" * 1000 + "\nXNU Build Done!\n"
        prefix = self.parse(text, max_bytes=128)
        self.assertFalse(prefix["boots"][0]["summary"]["ci_build_completion_log_seen"])
        tail = self.parse(text, tail_bytes=32)
        self.assertTrue(tail["boots"][0]["summary"]["ci_build_completion_log_seen"])
        self.assertEqual(tail["scanned_bytes"], 32)
        self.assertEqual(tail["scanned_range_sha256"], hashlib.sha256(text.encode()[-32:]).hexdigest())
        self.assertIsNone(tail["log_sha256"])
        self.assertIsNone(tail["scanned_prefix_sha256"])
        self.assertEqual(tail["hash_scope"], "scanned_byte_range_only")
        self.assertTrue(tail["leading_fragment_discarded"])
        self.assertEqual(tail["boundary_probe_bytes"], 1)
        self.assertIn("unscanned_prefix_context", tail["boots"][0]["summary"]["missing"])

    def test_tail_boundary_and_missing_staged_prefix_never_accept_physical(self):
        message = "[10] FUXI BATTERY: raw valid=0xffffffff f0=1 f2=5700 f3=4000000 f4=-1000000 f7=1 f9=9000000 f10=2000000 " + metadata() + "\n"
        text = "boot-args = fuxiadsp=4\n" + message
        report = self.parse(text, tail_bytes=len(message.encode()))
        self.assertFalse(report["leading_fragment_discarded"])
        record = report["boots"][0]["records"][0]
        self.assertTrue(record["excluded_from_physical_evidence"])
        self.assertFalse(record["derived"]["usb_telemetry_freshness_qualified"])
        self.assertIsNone(record["derived"]["charging_flag_freshness_qualified"])
        self.assertEqual(report["boots"][0]["summary"]["physical_unplug"], "not_established")

    def test_tail_smaller_file_retains_full_file_hash(self):
        report = self.parse(REAL_SUMMARY, tail_bytes=10000)
        self.assertEqual(report["scanned_byte_range"], [0, len(REAL_SUMMARY.encode())])
        self.assertEqual(report["hash_scope"], "full_file")
        self.assertEqual(report["log_sha256"], hashlib.sha256(REAL_SUMMARY.encode()).hexdigest())
        self.assertEqual(report["line_number_basis"], "absolute_file_line")

    def test_tail_oversized_leading_fragment_does_not_skip_next_whole_line(self):
        report = self.parse("n" * 1000 + "\nXNU Build Done!\n", tail_bytes=200, max_line_bytes=32)
        self.assertEqual(report["oversized_lines_skipped"], 1)
        self.assertTrue(report["boots"][0]["summary"]["ci_build_completion_log_seen"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
