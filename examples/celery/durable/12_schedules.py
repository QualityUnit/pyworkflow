"""
Celery Durable Workflow - Schedules Example

This example demonstrates scheduled workflow execution with Celery Beat.
- Cron-based scheduling (every minute)
- Interval-based scheduling (every 30 seconds)
- Overlap policies to control concurrent executions
- Schedule management (pause, resume, delete)

Prerequisites:
    1. Start Redis: docker run -d -p 6379:6379 redis:7-alpine
    2. Start worker: pyworkflow --module examples.celery.durable.12_schedules worker run
    3. Start beat: pyworkflow --module examples.celery.durable.12_schedules beat run

CLI Commands:
    # Create a schedule via CLI
    pyworkflow schedules create metrics_workflow --cron "* * * * *" --overlap skip

    # List all schedules
    pyworkflow schedules list

    # Pause/resume a schedule
    pyworkflow schedules pause <schedule_id>
    pyworkflow schedules resume <schedule_id>

    # Trigger immediately (bypass schedule)
    pyworkflow schedules trigger <schedule_id>

    # View schedule details
    pyworkflow schedules show <schedule_id>
"""

from datetime import datetime

from pyworkflow import (
    OverlapPolicy,
    scheduled_workflow,
    step,
    workflow,
)


# --- Steps ---
@step()
async def collect_metrics() -> dict:
    """Collect system metrics."""
    timestamp = datetime.now().isoformat()
    print(f"[Step] Collecting metrics at {timestamp}...")
    return {
        "timestamp": timestamp,
        "cpu_usage": 45.2,
        "memory_usage": 62.8,
        "disk_usage": 78.1,
    }


@step()
async def store_metrics(metrics: dict) -> dict:
    """Store metrics in database (simulated)."""
    print(f"[Step] Storing metrics: {metrics}")
    return {**metrics, "stored": True}


@step()
async def check_alerts(metrics: dict) -> dict:
    """Check if any metrics exceed thresholds."""
    alerts = []
    if metrics.get("cpu_usage", 0) > 80:
        alerts.append("High CPU usage")
    if metrics.get("memory_usage", 0) > 90:
        alerts.append("High memory usage")
    if metrics.get("disk_usage", 0) > 85:
        alerts.append("High disk usage")

    print(f"[Step] Alert check complete. Alerts: {alerts or 'None'}")
    return {**metrics, "alerts": alerts}


# --- Scheduled Workflow (using decorator) ---
@scheduled_workflow(
    cron="* * * * *",  # Every minute
    overlap_policy=OverlapPolicy.SKIP,  # Skip if previous run still active
    timezone="UTC",
)
async def metrics_workflow() -> dict:
    """
    Scheduled metrics collection workflow.

    Runs every minute via Celery Beat.
    Uses SKIP overlap policy - if a previous run is still active,
    new runs are skipped to prevent resource exhaustion.

    Steps:
    1. Collect current system metrics
    2. Store metrics in database
    3. Check for threshold alerts
    """
    metrics = await collect_metrics()
    metrics = await store_metrics(metrics)
    metrics = await check_alerts(metrics)
    return metrics


# --- Regular Workflow (for programmatic scheduling) ---
@workflow()
async def cleanup_workflow(days_old: int = 30) -> dict:
    """
    Cleanup old data workflow.

    This workflow is scheduled programmatically in main().
    """
    print(f"[Workflow] Cleaning up data older than {days_old} days...")
    return {"cleaned": True, "days_old": days_old}


async def main() -> None:
    """
    Create schedules programmatically.

    The @scheduled_workflow decorator automatically creates a schedule
    when activate_scheduled_workflows() is called (done by Beat).

    For regular @workflow functions, use create_schedule() to create
    schedules programmatically.
    """
    import argparse

    from pyworkflow import (
        OverlapPolicy,
        ScheduleSpec,
        create_schedule,
        delete_schedule,
        list_schedules,
        pause_schedule,
        resume_schedule,
    )

    parser = argparse.ArgumentParser(description="Schedule Management Example")
    parser.add_argument(
        "--action",
        choices=["create", "list", "pause", "resume", "delete"],
        default="create",
        help="Action to perform",
    )
    parser.add_argument("--schedule-id", help="Schedule ID for pause/resume/delete")
    args = parser.parse_args()

    print("=== Celery Schedules Example ===\n")

    if args.action == "create":
        # Create a schedule for the cleanup workflow
        print("Creating cleanup schedule (runs every 2 minutes)...")
        spec = ScheduleSpec(cron="*/2 * * * *", timezone="UTC")

        schedule = await create_schedule(
            workflow_name="cleanup_workflow",
            spec=spec,
            overlap_policy=OverlapPolicy.SKIP,
            schedule_id="cleanup-hourly",
            days_old=7,  # kwargs passed to workflow
        )
        print(f"Schedule created: {schedule.schedule_id}")
        print(f"  Workflow: {schedule.workflow_name}")
        print(f"  Cron: {schedule.spec.cron}")
        print(f"  Next run: {schedule.next_run_time}")

        # Also show the decorated workflow schedule
        print("\nThe @scheduled_workflow decorator creates:")
        print("  - metrics_workflow: runs every minute")
        print("  - Activated automatically when Beat starts")

    elif args.action == "list":
        schedules = await list_schedules()
        print(f"Found {len(schedules)} schedule(s):\n")
        for sched in schedules:
            print(f"  {sched.schedule_id}")
            print(f"    Workflow: {sched.workflow_name}")
            print(f"    Status: {sched.status.value}")
            print(f"    Spec: cron={sched.spec.cron}, interval={sched.spec.interval}")
            print(f"    Total runs: {sched.total_runs}")
            print()

    elif args.action == "pause" and args.schedule_id:
        schedule = await pause_schedule(args.schedule_id)
        print(f"Paused schedule: {schedule.schedule_id}")
        print(f"Status: {schedule.status.value}")

    elif args.action == "resume" and args.schedule_id:
        schedule = await resume_schedule(args.schedule_id)
        print(f"Resumed schedule: {schedule.schedule_id}")
        print(f"Status: {schedule.status.value}")

    elif args.action == "delete" and args.schedule_id:
        await delete_schedule(args.schedule_id)
        print(f"Deleted schedule: {args.schedule_id}")

    else:
        print("Invalid action or missing schedule-id")

    print("\n=== How to Run ===")
    print("1. Start worker: pyworkflow --module examples.celery.durable.12_schedules worker run")
    print("2. Start beat:   pyworkflow --module examples.celery.durable.12_schedules beat run")
    print("3. Watch logs to see scheduled executions!")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
