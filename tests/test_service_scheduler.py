from __future__ import annotations

import pytest

from ashare.service.config import load_service_config
from ashare.service.scheduler import SchedulerDisabledError, run_scheduler_once


def test_scheduler_once_dry_run_succeeds_when_disabled() -> None:
    config = load_service_config("configs/service.yaml")

    results = run_scheduler_once(
        config,
        name="phase4-fixture-research",
        dry_run=True,
    )

    assert results[0]["status"] == "planned"
    assert results[0]["source"] == "service-scheduler"


def test_scheduler_disabled_execute_fails_fast() -> None:
    config = load_service_config("configs/service.yaml")

    with pytest.raises(SchedulerDisabledError):
        run_scheduler_once(
            config,
            name="phase4-fixture-research",
            dry_run=False,
        )
