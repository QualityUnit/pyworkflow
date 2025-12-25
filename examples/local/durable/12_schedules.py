"""
Durable Workflow - Schedules Example

This example demonstrates scheduled workflow execution in local runtime.
- Cron-based scheduling (every minute)
- Interval-based scheduling (every 30 seconds)
- Overlap policies to control concurrent executions
- Schedule management (create, pause, resume, trigger)
- LocalScheduler for automatic execution

Run: python examples/local/durable/12_schedules.py 2>/dev/null

Or use the CLI:
    pyworkflow --module examples.local.durable.12_schedules scheduler run --duration 65
"""

import asyncio
from datetime import datetime

from pyworkflow import (
    LocalScheduler,
    OverlapPolicy,
    ScheduleSpec,
    configure,
    create_schedule,
    get_schedule,
    list_schedules,
    pause_schedule,
    reset_config,
    resume_schedule,
    step,
    trigger_schedule,
    workflow,
)
from pyworkflow.storage import InMemoryStorageBackend


# --- Steps ---
@step()
async def collect_metrics() -> dict:
    """Collect system metrics."""
    timestamp = datetime.now().isoformat()
    print(f"  [Step] Collecting metrics at {timestamp}...")
    return {
        "timestamp": timestamp,
        "cpu_usage": 45.2,
        "memory_usage": 62.8,
        "disk_usage": 78.1,
    }


@step()
async def store_metrics(metrics: dict) -> dict:
    """Store metrics (simulated)."""
    print("  [Step] Storing metrics...")
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

    print(f"  [Step] Alert check: {alerts or 'None'}")
    return {**metrics, "alerts": alerts}


# --- Workflow ---
@workflow(durable=True)
async def metrics_workflow() -> dict:
    """
    Metrics collection workflow.

    Collects system metrics, stores them, and checks for alerts.
    """
    metrics = await collect_metrics()
    metrics = await store_metrics(metrics)
    metrics = await check_alerts(metrics)
    return metrics


async def main():
    # Configure with InMemoryStorageBackend
    reset_config()
    storage = InMemoryStorageBackend()
    configure(storage=storage, default_durable=True)

    print("=== Durable Workflow - Schedules Example ===\n")

    # Create a schedule that runs every minute
    print("Creating schedule (runs every minute)...")
    spec = ScheduleSpec(
        cron="* * * * *",  # Every minute
        timezone="UTC",
    )

    schedule = await create_schedule(
        workflow_name="metrics_workflow",
        spec=spec,
        overlap_policy=OverlapPolicy.SKIP,
        schedule_id="metrics-every-minute",
    )

    print("\nSchedule created:")
    print(f"  ID: {schedule.schedule_id}")
    print(f"  Workflow: {schedule.workflow_name}")
    print(f"  Cron: {schedule.spec.cron}")
    print(f"  Next run: {schedule.next_run_time}")
    print(f"  Overlap policy: {schedule.overlap_policy.value}")

    # Also create an interval-based schedule
    print("\nCreating interval schedule (every 30 seconds)...")
    interval_spec = ScheduleSpec(interval="30s", timezone="UTC")

    interval_schedule = await create_schedule(
        workflow_name="metrics_workflow",
        spec=interval_spec,
        overlap_policy=OverlapPolicy.SKIP,
        schedule_id="metrics-30s-interval",
    )
    print(f"  ID: {interval_schedule.schedule_id}")
    print(f"  Interval: {interval_schedule.spec.interval}")

    # Show all schedules
    print("\n=== All Schedules ===")
    schedules = await list_schedules()
    for sched in schedules:
        print(f"  {sched.schedule_id}: {sched.status.value}")

    # Demonstrate pause/resume
    print("\n=== Pause/Resume Demo ===")
    print(f"Pausing {interval_schedule.schedule_id}...")
    await pause_schedule(interval_schedule.schedule_id)

    schedules = await list_schedules()
    for sched in schedules:
        print(f"  {sched.schedule_id}: {sched.status.value}")

    print(f"\nResuming {interval_schedule.schedule_id}...")
    await resume_schedule(interval_schedule.schedule_id)

    # Demonstrate manual trigger
    print("\n=== Manual Trigger Demo ===")
    print("Triggering schedule immediately (bypasses cron)...")
    run_id = await trigger_schedule(schedule.schedule_id)
    print(f"Triggered run: {run_id}")

    # Check stats after trigger
    schedule = await get_schedule(schedule.schedule_id)
    print("\nSchedule stats after trigger:")
    print(f"  Total runs: {schedule.total_runs}")
    print(f"  Successful: {schedule.successful_runs}")
    print(f"  Failed: {schedule.failed_runs}")

    # Run the LocalScheduler
    print("\n" + "=" * 50)
    print("Starting LocalScheduler to demonstrate automatic execution.")
    print("The scheduler will poll for due schedules every 5 seconds.")
    print("Watch for workflow executions when schedules become due!")
    print("=" * 50)

    # Create and run the local scheduler
    local_scheduler = LocalScheduler(
        storage=storage,
        poll_interval=5.0,
    )

    print("\nScheduler running for 65 seconds...")
    await local_scheduler.run(duration=65.0)

    # Final stats
    print("\n=== Final Schedule Stats ===")
    for sched_id in ["metrics-every-minute", "metrics-30s-interval"]:
        sched = await get_schedule(sched_id)
        if sched:
            print(f"\n{sched.schedule_id}:")
            print(f"  Total runs: {sched.total_runs}")
            print(f"  Successful: {sched.successful_runs}")
            print(f"  Last run: {sched.last_run_at}")

    print("\n=== Key Takeaways ===")
    print("- Schedules created with cron and interval specs")
    print("- LocalScheduler polls storage and triggers due schedules")
    print("- Overlap policies prevent concurrent runs")
    print("- Pause/resume controls schedule execution")
    print("- Manual trigger bypasses schedule timing")
    print("- For production, use: pyworkflow scheduler run")
    print("- For Celery, use: pyworkflow worker run --beat")


if __name__ == "__main__":
    asyncio.run(main())
