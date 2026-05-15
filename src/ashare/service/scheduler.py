"""APScheduler entry points for configured Phase 4 workflows."""

from __future__ import annotations

import time
from typing import Any

from ashare.service.config import ServiceConfig
from ashare.service.workflows import run_workflow


class SchedulerDisabledError(RuntimeError):
    """Raised when scheduler execution is requested while disabled."""


def run_scheduler_once(
    config: ServiceConfig,
    *,
    name: str | None,
    dry_run: bool,
    source: str = "service-scheduler",
) -> list[dict[str, Any]]:
    if not dry_run and not config.scheduler_enabled:
        raise SchedulerDisabledError("service scheduler is disabled in config.")
    names = [name] if name is not None else sorted(config.workflows)
    return [
        run_workflow(
            config,
            workflow_name,
            dry_run=dry_run,
            source=source,
            allow_disabled_dry_run=dry_run,
        )
        for workflow_name in names
    ]


def start_embedded_scheduler(config: ServiceConfig) -> object | None:
    if not config.scheduler_enabled:
        return None
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(timezone=config.scheduler_timezone)
    _add_jobs(scheduler, config, source="serve-embedded")
    scheduler.start()
    return scheduler


def run_scheduler_forever(
    config: ServiceConfig,
    *,
    name: str | None,
    dry_run: bool,
) -> None:
    if not config.scheduler_enabled:
        raise SchedulerDisabledError("service scheduler is disabled in config.")
    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler(timezone=config.scheduler_timezone)
    _add_jobs(scheduler, config, source="service-scheduler", name=name, dry_run=dry_run)
    scheduler.start()


def _add_jobs(
    scheduler: object,
    config: ServiceConfig,
    *,
    source: str,
    name: str | None = None,
    dry_run: bool = False,
) -> None:
    from apscheduler.triggers.cron import CronTrigger

    names = [name] if name is not None else sorted(config.workflows)
    for workflow_name in names:
        workflow = config.workflows.get(workflow_name, {})
        if not isinstance(workflow, dict) or not bool(workflow.get("enabled", False)):
            continue
        schedule = workflow.get("schedule", {})
        if not isinstance(schedule, dict) or schedule.get("trigger") != "cron":
            continue
        trigger_kwargs = {
            key: value
            for key, value in schedule.items()
            if key not in {"trigger"} and value is not None
        }
        trigger = CronTrigger(timezone=config.scheduler_timezone, **trigger_kwargs)
        scheduler.add_job(  # type: ignore[attr-defined]
            run_workflow,
            trigger=trigger,
            args=[config, workflow_name],
            kwargs={"dry_run": dry_run, "source": source, "allow_disabled_dry_run": False},
            id=f"ashare-{workflow_name}",
            replace_existing=True,
        )


def sleep_forever() -> None:
    while True:
        time.sleep(3600)
