from pathlib import Path

import pandas as pd

from ashare.ingest.cache import CacheKey, build_params_hash, read_cached_frame, write_cached_frame


def test_params_hash_is_stable_for_key_order() -> None:
    left = build_params_hash("akshare", "daily_prices", {"b": 2, "a": 1})
    right = build_params_hash("akshare", "daily_prices", {"a": 1, "b": 2})

    assert left == right


def test_cache_writes_frame_and_metadata(tmp_path: Path) -> None:
    key = CacheKey(
        source="csv",
        dataset="daily_prices",
        params_hash=build_params_hash("csv", "daily_prices", {"stock_codes": ["000001.SZ"]}),
    )
    frame = pd.DataFrame({"stock_code": ["000001.SZ"], "close": [10.0]})

    path = write_cached_frame(
        tmp_path,
        key,
        frame,
        {
            "request_params": {"stock_codes": ["000001.SZ"]},
            "provider_version_or_unknown": "csv-local",
        },
    )
    cached = read_cached_frame(tmp_path, key)
    metadata = path.with_suffix(".json").read_text(encoding="utf-8")

    assert path.is_file()
    assert cached is not None
    assert cached.to_dict("records") == frame.to_dict("records")
    assert '"source": "csv"' in metadata
    assert '"dataset": "daily_prices"' in metadata
    assert '"params_hash":' in metadata
    assert '"row_count": 1' in metadata
