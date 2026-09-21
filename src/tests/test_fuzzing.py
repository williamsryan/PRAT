"""Tests for prat.fuzzing — the MQTT fuzzing harness behind the paper's Table 7."""

import pytest

from prat.fuzzing import (
    DEFAULT_FUZZ_PORT,
    FuzzCampaign,
    FuzzResult,
    _classify_exit,
    _write_broker_config,
    check_boofuzz_available,
    compare_to_baseline,
    define_mqtt_requests,
    fuzz_variant,
)

boofuzz_required = pytest.mark.skipif(
    not check_boofuzz_available(), reason="boofuzz is not installed"
)


class TestFuzzResult:
    def test_coverage_percentages(self):
        result = FuzzResult(
            variant="variant_0",
            total_lines=10087, covered_lines=6428,
            total_functions=377, covered_functions=319,
        )

        assert result.line_coverage_pct == pytest.approx(63.7, abs=0.1)
        assert result.function_coverage_pct == pytest.approx(84.6, abs=0.1)

    def test_percentages_are_none_without_data(self):
        result = FuzzResult(variant="v")

        assert result.line_coverage_pct is None
        assert result.function_coverage_pct is None

    def test_duration_is_reported_in_minutes(self):
        result = FuzzResult(variant="v", duration_seconds=6480)

        assert result.duration_minutes == pytest.approx(108.0)

    def test_table_row_carries_every_paper_column(self):
        result = FuzzResult(
            variant="variant_0", removed_count=0,
            total_lines=10087, covered_lines=6428,
            total_functions=377, covered_functions=319,
            duration_seconds=6480,
        )

        row = result.table_row()

        for fragment in ("10087", "6428", "63.7%", "377", "319", "84.6%", "108"):
            assert fragment in row

    def test_table_row_handles_absent_coverage(self):
        assert "n/a" in FuzzResult(variant="v").table_row()


class TestClassifyExit:
    def test_negative_return_code_is_a_signal(self):
        assert _classify_exit(-11) == "SIGSEGV"

    def test_clean_exit_is_not_a_crash(self):
        assert _classify_exit(0) is None

    def test_nonzero_clean_exit_is_not_a_crash(self):
        assert _classify_exit(1) is None

    def test_none_is_not_a_crash(self):
        assert _classify_exit(None) is None


class TestCompareToBaseline:
    def test_crash_present_in_the_baseline_is_not_attributed_to_removal(self):
        campaign = FuzzCampaign(results=[
            FuzzResult(variant="variant_0", crashes=["SIGSEGV"]),
            FuzzResult(variant="variant_1", crashes=["SIGSEGV"]),
        ])

        compare_to_baseline(campaign)

        assert campaign.baseline_crashes == ["SIGSEGV"]
        assert campaign.introduced_crashes == {}
        assert campaign.any_introduced_crash is False

    def test_new_crash_is_attributed_to_removal(self):
        campaign = FuzzCampaign(results=[
            FuzzResult(variant="variant_0"),
            FuzzResult(variant="variant_1", crashes=["SIGABRT"]),
        ])

        compare_to_baseline(campaign)

        assert campaign.introduced_crashes == {"variant_1": ["SIGABRT"]}
        assert campaign.any_introduced_crash is True

    def test_empty_campaign_is_handled(self):
        campaign = compare_to_baseline(FuzzCampaign())

        assert campaign.baseline_crashes == []
        assert campaign.any_introduced_crash is False

    def test_table_renders_one_row_per_variant(self):
        campaign = FuzzCampaign(results=[
            FuzzResult(variant="variant_0", removed_count=0, total_lines=100,
                       covered_lines=60, total_functions=10, covered_functions=8),
            FuzzResult(variant="variant_1", removed_count=1, total_lines=90,
                       covered_lines=55, total_functions=9, covered_functions=7),
        ])

        table = campaign.table()

        assert table.count("\n") == 3  # header + rule + two rows
        assert "Lines" in table and "Fns" in table


class TestBrokerConfig:
    def test_writes_a_listener_on_the_requested_port(self, tmp_path):
        config = tmp_path / "broker.conf"

        _write_broker_config(config, 12345)
        text = config.read_text()

        assert "listener 12345" in text
        assert "allow_anonymous true" in text

    def test_default_port_avoids_the_real_mqtt_port(self):
        """Fuzzing must not be able to reach a broker someone is really running."""
        assert DEFAULT_FUZZ_PORT != 1883


class TestFuzzVariantGuards:
    def test_missing_binary_is_reported_not_raised(self, tmp_path):
        result = fuzz_variant(
            broker_binary=str(tmp_path / "absent"),
            project_path=str(tmp_path),
            variant="variant_0",
        )

        assert result.success is False
        assert "not found" in (result.error_message or "") or "boofuzz" in (
            result.error_message or ""
        )


@boofuzz_required
class TestMqttRequests:
    def test_registers_the_expected_packets(self):
        names = define_mqtt_requests()

        assert names == [
            "mqtt_connect",
            "mqtt_publish",
            "mqtt_subscribe",
            "mqtt_pingreq",
            "mqtt_disconnect",
        ]

    def test_connect_renders_a_valid_mqtt_311_packet(self):
        from boofuzz import s_get

        define_mqtt_requests()
        data = s_get("mqtt_connect").render()

        assert data[0] == 0x10                  # CONNECT, no flags
        assert data[1] == len(data) - 2         # remaining length is consistent
        assert data[2:4] == b"\x00\x04"         # protocol name length
        assert data[4:8] == b"MQTT"             # protocol name
        assert data[8] == 0x04                  # protocol level 4 = MQTT 3.1.1

    def test_publish_framing_is_self_consistent(self):
        from boofuzz import s_get

        define_mqtt_requests()
        data = s_get("mqtt_publish").render()

        assert data[0] == 0x30                  # PUBLISH, QoS 0
        assert data[1] == len(data) - 2
        assert b"prat/fuzz" in data

    def test_subscribe_uses_the_required_reserved_flags(self):
        from boofuzz import s_get

        define_mqtt_requests()
        data = s_get("mqtt_subscribe").render()

        # MQTT requires the SUBSCRIBE fixed-header flags to be 0b0010.
        assert data[0] == 0x82
        assert data[1] == len(data) - 2

    def test_pingreq_and_disconnect_are_two_byte_packets(self):
        from boofuzz import s_get

        define_mqtt_requests()

        assert s_get("mqtt_pingreq").render() == b"\xc0\x00"
        assert s_get("mqtt_disconnect").render() == b"\xe0\x00"
