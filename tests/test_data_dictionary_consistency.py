from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "docs/build_data_dictionary.py"
SPEC = importlib.util.spec_from_file_location("build_data_dictionary", BUILD_SCRIPT)
assert SPEC is not None
build_data_dictionary = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(build_data_dictionary)
render_data_dictionary = build_data_dictionary.render_data_dictionary
render_factor_definitions = build_data_dictionary.render_factor_definitions
PHASE_1A4_FACTORS = {
    "return_20d",
    "return_60d",
    "above_ma60",
    "low_liquidity",
    "is_st",
    "is_suspended",
    "is_delisted",
    "pe_ttm_percentile",
    "pb_percentile",
    "revenue_yoy",
    "profit_yoy",
}
ALLOWED_DIRECTIONS = {"higher_is_better", "lower_is_better", "boolean_filter"}
REQUIRED_SCHEMA_FIELDS = {
    "daily_prices.adj_factor",
    "daily_prices.is_suspended",
    "daily_prices.amount",
    "valuation_daily.pe_ttm",
    "valuation_daily.pb",
    "fundamental_reports.revenue",
    "fundamental_reports.net_profit",
    "fundamental_reports.publish_time",
    "fundamental_reports.effective_date",
    "securities.delist_date",
    "securities.delist_publish_time",
    "securities.delist_effective_date",
    "universe_members.in_effective_date",
    "universe_members.out_effective_date",
    "st_status.in_effective_date",
    "st_status.out_effective_date",
    "industry_classifications.in_effective_date",
    "industry_classifications.out_effective_date",
    "factor_values.factor_value",
    "factor_values.as_of_date",
    "factor_values.source_run_id",
}
REQUIRED_SCHEMA_KEYS = {"type", "source", "description", "unit", "pit_visibility"}
REQUIRED_FACTOR_KEYS = {
    "factor_name",
    "type",
    "source",
    "raw_fields",
    "formula",
    "unit",
    "frequency",
    "effective_date",
    "direction",
    "missing",
    "outlier",
    "normalize",
    "hard_filter",
    "soft_penalty",
    "score_group",
    "phase",
    "description",
    "params",
}
PARAM_PATHS = {
    "return_20d": ("factors", "return_20d"),
    "return_60d": ("factors", "return_60d"),
    "above_ma60": ("factors", "above_ma60"),
    "pe_ttm_percentile": ("factors", "pe_ttm_percentile"),
    "pb_percentile": ("factors", "pb_percentile"),
    "revenue_yoy": ("factors", "revenue_yoy"),
    "profit_yoy": ("factors", "profit_yoy"),
    "low_liquidity": ("hard_filters", "low_liquidity"),
    "is_st": ("hard_filters", "is_st"),
    "is_suspended": ("hard_filters", "is_suspended"),
    "is_delisted": ("hard_filters", "is_delisted"),
}


def _load_yaml(path: str) -> dict[str, object]:
    data = yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_data_dictionary_yaml_has_required_sections() -> None:
    data_dictionary = _load_yaml("configs/data_dictionary.yaml")

    assert isinstance(data_dictionary.get("schema_fields"), dict)
    assert isinstance(data_dictionary.get("factors"), dict)


def test_required_schema_fields_are_defined() -> None:
    schema_fields = _load_yaml("configs/data_dictionary.yaml")["schema_fields"]
    assert isinstance(schema_fields, dict)

    missing = REQUIRED_SCHEMA_FIELDS - set(schema_fields)
    assert not missing
    for field_name in REQUIRED_SCHEMA_FIELDS:
        entry = schema_fields[field_name]
        assert isinstance(entry, dict)
        assert REQUIRED_SCHEMA_KEYS <= set(entry)


def test_phase_1a4_factors_are_defined_with_valid_directions() -> None:
    factors = _load_yaml("configs/data_dictionary.yaml")["factors"]
    assert isinstance(factors, dict)

    missing = PHASE_1A4_FACTORS - set(factors)
    assert not missing
    for name in PHASE_1A4_FACTORS:
        entry = factors[name]
        assert isinstance(entry, dict)
        assert REQUIRED_FACTOR_KEYS <= set(entry)
        assert entry.get("phase") == "1a-4"
        assert entry.get("direction") in ALLOWED_DIRECTIONS


def test_phase_1a4_factor_params_match_factor_config() -> None:
    data_dictionary = _load_yaml("configs/data_dictionary.yaml")
    factor_config = _load_yaml("configs/factors.yaml")
    factors = data_dictionary["factors"]
    assert isinstance(factors, dict)

    for factor_name, (section, config_name) in PARAM_PATHS.items():
        entry = factors[factor_name]
        assert isinstance(entry, dict)
        config_section = factor_config[section]
        assert isinstance(config_section, dict)
        config_entry = config_section[config_name]
        assert isinstance(config_entry, dict)
        assert entry["params"] == config_entry.get("params", {})


def test_required_factor_descriptions_encode_phase_1a4_decisions() -> None:
    factors = _load_yaml("configs/data_dictionary.yaml")["factors"]
    assert isinstance(factors, dict)

    is_suspended = factors["is_suspended"]
    assert isinstance(is_suspended, dict)
    suspended_description = str(is_suspended["description"])
    for keyword in ("不可交易", "daily_prices", "data_missing"):
        assert keyword in suspended_description

    for factor_name in ("pe_ttm_percentile", "pb_percentile"):
        entry = factors[factor_name]
        assert isinstance(entry, dict)
        description = str(entry["description"])
        for keyword in ("单股票", "历史", "分位", "不是横截面"):
            assert keyword in description


def test_generated_markdown_matches_renderer_output() -> None:
    data_dictionary = _load_yaml("configs/data_dictionary.yaml")

    assert (ROOT / "docs/data_dictionary.md").read_text(
        encoding="utf-8"
    ) == render_data_dictionary(data_dictionary)
    assert (ROOT / "docs/factor_definitions.md").read_text(
        encoding="utf-8"
    ) == render_factor_definitions(data_dictionary)


def test_generated_markdown_contains_do_not_edit_notice() -> None:
    for relative_path in ("docs/data_dictionary.md", "docs/factor_definitions.md"):
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "Do not edit by hand" in text
