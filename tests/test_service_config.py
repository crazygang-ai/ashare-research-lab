from __future__ import annotations

from pathlib import Path

import pytest

from ashare.service.config import EXPECTED_VERSION, load_service_config


def test_service_config_loads_phase4_defaults() -> None:
    config = load_service_config("configs/service.yaml")

    assert config.version == EXPECTED_VERSION
    assert config.host == "127.0.0.1"
    assert config.port == 8008
    assert config.database_read_only is True
    assert config.security["allow_http_workflow_run"] is False
    assert config.scheduler_enabled is False
    assert "scan" in config.known_artifact_kinds


def test_service_config_loads_ui_runner_defaults() -> None:
    config = load_service_config("configs/service.yaml")

    assert config.ui_runner["enabled"] is False
    assert config.ui_runner_enabled is False
    assert config.ui_runner_max_concurrent_runs == 1
    assert config.ui_runner_history_dir == (
        config.repo_root / "data/service/workflow-runs"
    ).resolve()
    assert config.ui_runner_log_dir == (
        config.repo_root / "data/service/workflow-logs"
    ).resolve()
    assert config.ui_runner_allowed_commands == ("stock-report", "hs300-daily")


def test_service_config_rejects_unknown_ui_runner_command(tmp_path: Path) -> None:
    path = tmp_path / "service.yaml"
    path.write_text(
        """
version: phase4.v1
ui_runner:
  allowed_commands:
    - shell
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Unknown ui_runner allowed command"):
        load_service_config(path)


def test_service_config_rejects_wrong_version(tmp_path: Path) -> None:
    path = tmp_path / "service.yaml"
    path.write_text("version: other\n", encoding="utf-8")

    with pytest.raises(ValueError, match="phase4.v1"):
        load_service_config(path)


def test_service_config_rejects_plaintext_secret(tmp_path: Path) -> None:
    path = tmp_path / "service.yaml"
    path.write_text(
        """
version: phase4.v1
security:
  api_key: plain-secret
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="plaintext secret"):
        load_service_config(path)


def test_service_config_overrides_resolve_relative_to_repo() -> None:
    config = load_service_config(
        "configs/service.yaml",
        overrides={"database": {"db_path": "data/processed/test.duckdb"}},
    )

    assert config.database_path == (config.repo_root / "data/processed/test.duckdb").resolve()
