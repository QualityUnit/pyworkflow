"""
Celery Durable Workflow - Long Running with Sleep

This example demonstrates automatic sleep resumption with Celery workers.
- Workflow suspends during sleep (releases resources)
- Celery automatically resumes after sleep completes
- No manual intervention required (unlike local runtime)

Prerequisites:
    1. Start Redis: docker run -d -p 6379:6379 redis:7-alpine
    2. Start worker: pyworkflow --module examples.celery.durable.02_long_running worker run

Run with CLI:
    pyworkflow --module examples.celery.durable.02_long_running workflows run onboarding_workflow \
        --arg user_id=user-456

Watch the worker output to see automatic resumption after each sleep.

Check status:
    pyworkflow runs list --status suspended
    pyworkflow runs status <run_id>
"""

from pyworkflow import sleep, step, workflow


@step()
async def send_welcome_email(user_id: str) -> dict:
    """Send welcome email to new user."""
    print(f"[Step] Sending welcome email to {user_id}...")
    return {"user_id": user_id, "welcome_sent": True}


@step()
async def send_tips_email(user: dict) -> dict:
    """Send helpful tips email after delay."""
    print(f"[Step] Sending tips email to {user['user_id']}...")
    return {**user, "tips_sent": True}


@step()
async def send_survey_email(user: dict) -> dict:
    """Send feedback survey after delay."""
    print(f"[Step] Sending survey email to {user['user_id']}...")
    return {**user, "survey_sent": True}


@workflow(tags=["celery", "durable"])
async def onboarding_workflow(user_id: str) -> dict:
    """
    User onboarding workflow with scheduled emails.

    Demonstrates automatic sleep resumption:
    1. Send welcome email immediately
    2. Wait 30 seconds, then send tips email
    3. Wait another 30 seconds, then send survey

    With Celery runtime, sleeps are handled automatically:
    - Workflow suspends and worker is freed
    - Celery schedules resumption task
    - Worker picks up and continues execution
    """
    user = await send_welcome_email(user_id)

    print("[Workflow] Sleeping for 30 seconds before tips email...")
    await sleep("30s")

    user = await send_tips_email(user)

    print("[Workflow] Sleeping for 30 seconds before survey...")
    await sleep("30s")

    user = await send_survey_email(user)
    return user


async def main() -> None:
    """Run the onboarding workflow example."""
    import argparse

    import pyworkflow

    parser = argparse.ArgumentParser(description="User Onboarding Workflow with Sleeps")
    parser.add_argument("--user-id", default="user-456", help="User ID to onboard")
    args = parser.parse_args()

    # Configuration is automatically loaded from pyworkflow.config.yaml
    print(f"Starting onboarding workflow for {args.user_id}...")
    print("(Workflow will sleep between emails - watch the worker output)")
    run_id = await pyworkflow.start(onboarding_workflow, args.user_id)
    print(f"Workflow started with run_id: {run_id}")
    print(f"\nCheck status: pyworkflow runs status {run_id}")
    print("List suspended: pyworkflow runs list --status suspended")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
