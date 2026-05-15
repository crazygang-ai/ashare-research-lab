from __future__ import annotations

import subprocess


def test_service_cli_help_commands() -> None:
    for args in [
        ["ashare", "serve", "--help"],
        ["ashare", "service-workflow", "--help"],
        ["ashare", "service-scheduler", "--help"],
    ]:
        result = subprocess.run(args, check=True, capture_output=True, text=True)
        assert "Usage" in result.stdout


def test_ashare_help_lists_phase4_commands() -> None:
    result = subprocess.run(["ashare", "--help"], check=True, capture_output=True, text=True)

    for command in ["serve", "service-workflow", "service-scheduler"]:
        assert command in result.stdout


def test_service_workflow_and_scheduler_dry_run_cli() -> None:
    workflow = subprocess.run(
        [
            "ashare",
            "service-workflow",
            "--name",
            "phase4-fixture-research",
            "--service-config",
            "configs/service.yaml",
            "--dry-run",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    scheduler = subprocess.run(
        [
            "ashare",
            "service-scheduler",
            "--service-config",
            "configs/service.yaml",
            "--once",
            "--name",
            "phase4-fixture-research",
            "--dry-run",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "status: planned" in workflow.stdout
    assert "target_db_paths:" in workflow.stdout
    assert "status: planned" in scheduler.stdout
