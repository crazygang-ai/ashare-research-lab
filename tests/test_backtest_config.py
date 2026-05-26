from __future__ import annotations

import pytest

from ashare.backtest.config import merge_backtest_config


def test_backtest_config_rejects_non_positive_board_lot_size() -> None:
    with pytest.raises(ValueError, match="trading_rules.board_lot_size must be positive"):
        merge_backtest_config({"trading_rules": {"board_lot_size": 0}})


def test_backtest_config_rejects_enabled_real_index_until_supported() -> None:
    with pytest.raises(ValueError, match="benchmark.real_index.enabled is not supported"):
        merge_backtest_config(
            {
                "benchmark": {
                    "real_index": {
                        "enabled": True,
                        "index_code": "000300.SH",
                        "source": "akshare",
                    }
                }
            }
        )


def test_backtest_config_rejects_real_index_benchmark_names_until_supported() -> None:
    with pytest.raises(ValueError, match="benchmark.primary must be one of"):
        merge_backtest_config({"benchmark": {"primary": "real_index"}})
