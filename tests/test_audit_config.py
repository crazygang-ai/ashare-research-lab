from __future__ import annotations

from pathlib import Path

import pytest

from ashare.audit.config import EXPECTED_VERSION, load_audit_config


def test_audit_config_loads_defaults() -> None:
    config = load_audit_config("configs/audit.yaml")

    assert config.data["version"] == EXPECTED_VERSION
    assert config.enabled is True
    assert config.default_run_mode == "exploratory"
    assert config.manifest_filename == "run_manifest.json"
    assert config.default_artifact_root == (config.repo_root / "data/reports/generated").resolve()


def test_audit_config_rejects_wrong_version(tmp_path: Path) -> None:
    path = tmp_path / "audit.yaml"
    path.write_text("version: other\n", encoding="utf-8")

    with pytest.raises(ValueError, match="phase5.v1"):
        load_audit_config(path)


def test_audit_config_rejects_secret_like_keys(tmp_path: Path) -> None:
    path = tmp_path / "audit.yaml"
    path.write_text(
        """
version: phase5.v1
run_tracking:
  enabled: true
  api_key: plain
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="secret-like"):
        load_audit_config(path)
