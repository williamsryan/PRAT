"""Tests for prat.discovery — feature identification per build system.

The paper's criteria, one per analyzer:

* cMake: boolean (``BOOL``) cache options are user-defined features.
* Autoconf: retain options "whose description includes the words 'feature' or
  'optional'".
* Cargo: return the features that are "non-default".
* Make: ``WITH_*`` toggles.

plus a filtering stage that discards standard compilation options and hides
debugging/developer options.
"""

from prat.discovery import (
    Feature,
    _cmake_features_from_sources,
    _parse_configure_help,
    discover_features,
    discover_features_cargo,
    discover_features_make,
    filter_features,
    is_developer_option,
    is_standard_option,
    strip_feature_prefix,
)


class TestFeature:
    def test_raw_name_defaults_to_name(self):
        assert Feature(name="TLS").raw_name == "TLS"

    def test_raw_name_is_kept_when_given(self):
        feature = Feature(name="TLS", raw_name="WITH_TLS")
        assert feature.raw_name == "WITH_TLS"


class TestPrefixHandling:
    def test_strips_known_prefixes(self):
        assert strip_feature_prefix("WITH_TLS") == "TLS"
        assert strip_feature_prefix("CONFIG_AV1_ENCODER") == "AV1_ENCODER"
        assert strip_feature_prefix("ENABLE_X") == "X"
        assert strip_feature_prefix("USE_WSIO") == "WSIO"

    def test_leaves_unprefixed_names_alone(self):
        assert strip_feature_prefix("qlog") == "qlog"


class TestFiltering:
    def test_shared_library_option_is_standard(self):
        """The paper's single reported false positive."""
        assert is_standard_option("BUILD_SHARED_LIBS") is True
        assert is_standard_option("STATIC_LIBRARIES") is True

    def test_prefixed_standard_options_are_recognized(self):
        assert is_standard_option("WITH_BUNDLED_DEPS") is True

    def test_real_features_are_not_standard(self):
        for name in ("WITH_TLS", "use_wsio", "CONFIG_AV1_ENCODER", "qlog"):
            assert is_standard_option(name) is False

    def test_debug_options_are_developer_options(self):
        for name in ("WITH_DEBUG", "ENABLE_ASAN", "WITH_COVERAGE", "WERROR"):
            assert is_developer_option(name) is True

    def test_developer_wording_in_description_counts(self):
        assert is_developer_option(
            "WITH_EXTRA", "Enable extra checks for developers"
        ) is True

    def test_real_features_are_not_developer_options(self):
        assert is_developer_option("WITH_TLS", "SSL/TLS support") is False

    def test_filter_partitions_and_records_reasons(self):
        features = [
            Feature(name="TLS", raw_name="WITH_TLS"),
            Feature(name="SHARED", raw_name="BUILD_SHARED_LIBS"),
            Feature(name="DEBUG", raw_name="WITH_DEBUG"),
        ]

        candidates, discarded = filter_features(features)

        assert [f.name for f in candidates] == ["TLS"]
        assert {f.name for f in discarded} == {"SHARED", "DEBUG"}
        assert all(f.filtered_reason for f in discarded)

    def test_developer_options_can_be_kept(self):
        features = [Feature(name="DEBUG", raw_name="WITH_DEBUG")]

        candidates, discarded = filter_features(
            features, keep_developer_options=True
        )

        assert [f.name for f in candidates] == ["DEBUG"]
        assert discarded == []


class TestAutoconfAnalyzer:
    HELP = """\
Optional Features:
  --disable-option-checking  ignore unrecognized --enable/--with options
  --enable-tls            enable optional TLS feature support
  --disable-bridge        disable the bridge feature
  --enable-fast-math      use fast math (changes numeric results)
  --enable-decoder=NAME   enable a specific decoder as an optional feature
"""

    def test_retains_only_options_whose_description_mentions_feature_or_optional(self):
        features = _parse_configure_help(self.HELP, require_feature_wording=True)

        names = {f.name for f in features}
        assert "TLS" in names
        assert "BRIDGE" in names
        # No "feature"/"optional" wording in its description.
        assert "FAST-MATH" not in names

    def test_strips_value_placeholders_from_option_names(self):
        features = _parse_configure_help(self.HELP, require_feature_wording=True)

        names = {f.name for f in features}
        assert "DECODER" in names
        assert not any("=" in name for name in names)

    def test_disable_polarity_implies_enabled_by_default(self):
        features = {
            f.name: f for f in _parse_configure_help(self.HELP, True)
        }

        assert features["BRIDGE"].default_enabled is True
        assert features["TLS"].default_enabled is False

    def test_filter_can_be_disabled(self):
        unfiltered = _parse_configure_help(self.HELP, require_feature_wording=False)

        assert "FAST-MATH" in {f.name for f in unfiltered}

    def test_absorbs_wrapped_description_lines(self):
        help_text = (
            "Optional Features:\n"
            "  --enable-widget\n"
            "                          an optional widget feature\n"
        )

        features = _parse_configure_help(help_text, require_feature_wording=True)

        assert [f.name for f in features] == ["WIDGET"]


class TestCMakeSourceScan:
    def test_finds_option_declarations(self, tmp_path):
        (tmp_path / "CMakeLists.txt").write_text(
            'option(WITH_TLS "SSL/TLS support" ON)\n'
            'option(WITH_BRIDGE "Bridge support" OFF)\n'
        )

        features = {f.name: f for f in _cmake_features_from_sources(tmp_path)}

        assert set(features) == {"WITH_TLS", "WITH_BRIDGE"}
        assert features["WITH_TLS"].default_enabled is True
        assert features["WITH_BRIDGE"].default_enabled is False
        assert features["WITH_TLS"].description == "SSL/TLS support"

    def test_finds_set_cache_bool_declarations(self, tmp_path):
        (tmp_path / "CMakeLists.txt").write_text(
            'set(USE_WSIO OFF CACHE BOOL "WebSocket transport")\n'
        )

        features = {f.name: f for f in _cmake_features_from_sources(tmp_path)}

        assert features["USE_WSIO"].default_enabled is False
        assert features["USE_WSIO"].description == "WebSocket transport"

    def test_finds_project_specific_config_var_macros(self, tmp_path):
        """libaom declares every CONFIG_* toggle via set_aom_config_var."""
        (tmp_path / "CMakeLists.txt").write_text(
            'set_aom_config_var(CONFIG_AV1_ENCODER 1 "Enable AV1 encoder")\n'
            'set_aom_config_var(CONFIG_SIZE_LIMIT 0 "Limit max size")\n'
        )

        features = {f.name: f for f in _cmake_features_from_sources(tmp_path)}

        assert features["CONFIG_AV1_ENCODER"].default_enabled is True
        assert features["CONFIG_SIZE_LIMIT"].default_enabled is False

    def test_ignores_non_boolean_config_vars(self, tmp_path):
        (tmp_path / "CMakeLists.txt").write_text(
            'set_aom_config_var(CONFIG_NAME "value" "Some string")\n'
        )

        assert _cmake_features_from_sources(tmp_path) == []


class TestCargoAnalyzer:
    def test_excludes_features_in_the_default_array(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text(
            "[features]\n"
            'default = ["boringssl-vendored"]\n'
            'boringssl-vendored = []\n'
            'qlog = ["dep:qlog"]\n'
            'ffi = []\n'
        )

        features = {f.name for f in discover_features_cargo(str(tmp_path))}

        assert features == {"QLOG", "FFI"}
        assert "BORINGSSL-VENDORED" not in features

    def test_excludes_transitive_default_features(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text(
            "[features]\n"
            'default = ["a"]\n'
            'a = ["b"]\n'
            'b = []\n'
            'c = []\n'
        )

        features = {f.name for f in discover_features_cargo(str(tmp_path))}

        assert features == {"C"}

    def test_reads_workspace_member_manifests(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text(
            "[workspace]\n"
            'members = ["quiche"]\n'
        )
        member = tmp_path / "quiche"
        member.mkdir()
        (member / "Cargo.toml").write_text(
            "[features]\ndefault = []\nqlog = []\n"
        )

        features = {f.name for f in discover_features_cargo(str(tmp_path))}

        assert "QLOG" in features

    def test_no_features_section_yields_nothing(self, tmp_path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "x"\n')

        assert discover_features_cargo(str(tmp_path)) == []


class TestMakeAnalyzer:
    def test_finds_with_toggles_in_config_mk(self, tmp_path):
        (tmp_path / "config.mk").write_text(
            "# Comment describing TLS support\n"
            "WITH_TLS:=yes\n"
            "WITH_BRIDGE:=yes\n"
            "WITH_WEBSOCKETS:=no\n"
        )

        features = {f.name: f for f in discover_features_make(str(tmp_path))}

        assert set(features) == {"WITH_TLS", "WITH_BRIDGE", "WITH_WEBSOCKETS"}
        assert features["WITH_TLS"].default_enabled is True
        assert features["WITH_WEBSOCKETS"].default_enabled is False

    def test_uses_preceding_comment_as_description(self, tmp_path):
        (tmp_path / "config.mk").write_text(
            "# Build with websockets support in the broker\n"
            "WITH_WEBSOCKETS:=no\n"
        )

        features = {f.name: f for f in discover_features_make(str(tmp_path))}

        assert "websockets support" in features["WITH_WEBSOCKETS"].description

    def test_no_make_files_yields_nothing(self, tmp_path):
        assert discover_features_make(str(tmp_path)) == []


class TestDiscoverFeatures:
    def test_merges_results_from_every_applicable_build_system(self, tmp_path):
        """Mosquitto ships both CMakeLists.txt and config.mk; BRIDGE is only in
        the latter, so taking the first matching analyzer would miss it."""
        (tmp_path / "CMakeLists.txt").write_text(
            'option(WITH_TLS "SSL/TLS support" ON)\n'
        )
        (tmp_path / "config.mk").write_text(
            "WITH_TLS:=yes\nWITH_BRIDGE:=yes\n"
        )

        features = {f.name for f in discover_features(str(tmp_path))}

        assert features == {"WITH_TLS", "WITH_BRIDGE"}

    def test_deduplicates_and_keeps_the_description(self, tmp_path):
        (tmp_path / "CMakeLists.txt").write_text(
            'option(WITH_TLS "SSL/TLS support" ON)\n'
        )
        (tmp_path / "config.mk").write_text("WITH_TLS:=yes\n")

        features = {f.name: f for f in discover_features(str(tmp_path))}

        assert len(features) == 1
        assert features["WITH_TLS"].description == "SSL/TLS support"

    def test_applies_the_filtering_stage(self, tmp_path):
        (tmp_path / "CMakeLists.txt").write_text(
            'option(WITH_TLS "SSL/TLS support" ON)\n'
            'option(BUILD_SHARED_LIBS "Build shared" ON)\n'
            'option(WITH_DEBUG "Debug build" OFF)\n'
        )

        features = {f.name for f in discover_features(str(tmp_path))}

        assert features == {"WITH_TLS"}

    def test_filters_can_be_bypassed(self, tmp_path):
        (tmp_path / "CMakeLists.txt").write_text(
            'option(BUILD_SHARED_LIBS "Build shared" ON)\n'
        )

        unfiltered = {f.name for f in discover_features(
            str(tmp_path), apply_filters=False
        )}
        filtered = {f.name for f in discover_features(str(tmp_path))}

        assert "BUILD_SHARED_LIBS" in unfiltered
        assert "BUILD_SHARED_LIBS" not in filtered

    def test_cmake_own_cache_variables_are_discarded(self, tmp_path):
        """`cmake -LA` lists CMake's built-ins; none of them are features."""
        (tmp_path / "CMakeLists.txt").write_text(
            'option(WITH_TLS "SSL/TLS support" ON)\n'
        )

        features = {f.name for f in discover_features(str(tmp_path))}

        assert features == {"WITH_TLS"}
        assert not any(name.startswith("CMAKE_") for name in features)

    def test_adapter_normalizes_option_names(self, tmp_path):
        """MosquittoAdapter re-adds WITH_, so discovery must hand it the stem."""
        from prat.adapters.mosquitto import MosquittoAdapter

        (tmp_path / "config.mk").write_text("WITH_TLS:=yes\n")
        adapter = MosquittoAdapter(str(tmp_path))

        features = discover_features(str(tmp_path), adapter=adapter)

        assert [f.name for f in features] == ["TLS"]
        assert features[0].raw_name == "WITH_TLS"
        # Round-trips back to the real build flag.
        assert "WITH_TLS" in adapter.format_feature_flag(features[0].name, True)

    def test_unknown_project_yields_nothing(self, tmp_path):
        assert discover_features(str(tmp_path)) == []
