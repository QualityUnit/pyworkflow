"""
Celery Transient Workflow - Fault Tolerance Example

This example demonstrates fault tolerance options for transient workflows.

Key difference from durable workflows:
- Transient workflows do NOT record events
- On worker failure, there's no state to recover from
- By default, failed transient workflows stay FAILED
- Optionally, they can be rescheduled to run from scratch

Configuration options:
1. recover_on_worker_loss=False (DEFAULT for transient)
   - On worker crash: workflow is marked as FAILED
   - No automatic retry
   - Use when: tasks have side effects or can't be safely repeated

2. recover_on_worker_loss=True
   - On worker crash: workflow is rescheduled from scratch
   - All steps run again (no event replay - there are no events!)
   - Use when: tasks are idempotent and can be safely restarted

Prerequisites:
    1. Start Redis: docker run -d -p 6379:6379 redis:7-alpine
    2. Start worker: pyworkflow --module examples.celery.transient.02_fault_tolerance worker run

Run with CLI:
    # Default behavior (no recovery)
    pyworkflow --module examples.celery.transient.02_fault_tolerance workflows run image_processor \
        --arg image_id=img-123

    # With recovery enabled
    pyworkflow --module examples.celery.transient.02_fault_tolerance workflows run batch_processor \
        --arg batch_id=batch-456

To test fault tolerance:
    1. Start the workflow
    2. Kill the worker during execution
    3. Start a new worker
    4. Observe the difference between recover_on_worker_loss=True/False
"""

import asyncio

from pyworkflow import step, workflow


@step(name="transient_download_image")
async def download_image(image_id: str) -> dict:
    """Download image from storage."""
    print(f"[Step] Downloading image {image_id}...")
    await asyncio.sleep(2)
    return {"image_id": image_id, "size_mb": 5.2, "downloaded": True}


@step(name="transient_resize_image")
async def resize_image(image: dict) -> dict:
    """Resize image to standard dimensions."""
    print(f"[Step] Resizing image {image['image_id']}...")
    print("       (taking 8 seconds - kill worker now to test!)")
    await asyncio.sleep(8)  # Long operation - good time to kill worker
    return {**image, "resized": True, "new_size_mb": 1.2}


@step(name="transient_apply_filters")
async def apply_filters(image: dict) -> dict:
    """Apply visual filters to image."""
    print(f"[Step] Applying filters to {image['image_id']}...")
    print("       (taking 6 seconds - kill worker now to test!)")
    await asyncio.sleep(6)  # Another good time to kill worker
    return {**image, "filtered": True}


@step(name="transient_upload_result")
async def upload_result(image: dict) -> dict:
    """Upload processed image."""
    print(f"[Step] Uploading processed {image['image_id']}...")
    await asyncio.sleep(2)
    return {**image, "uploaded": True, "url": f"https://cdn.example.com/{image['image_id']}"}


# ============================================================================
# Workflow 1: No Recovery (Default for Transient)
# ============================================================================


@workflow(
    durable=False,
    recover_on_worker_loss=False,  # DEFAULT for transient - no auto-recovery
    tags=["celery", "transient"],
)
async def image_processor(image_id: str) -> dict:
    """
    Image processing workflow - NO AUTO-RECOVERY.

    This is the default behavior for transient workflows.

    If a worker crashes during execution:
    - The workflow is marked as FAILED
    - No automatic retry occurs
    - A new workflow must be manually started

    Why use this:
    - The upload step has side effects (can't safely repeat)
    - Need manual review of failures
    - Each image should only be processed once
    """
    print(f"\n{'=' * 60}")
    print(f"Image Processor (NO RECOVERY): {image_id}")
    print("If worker crashes, workflow will FAIL permanently")
    print(f"{'=' * 60}\n")

    image = await download_image(image_id)
    image = await resize_image(image)
    image = await apply_filters(image)
    image = await upload_result(image)

    print(f"\n[Complete] Image available at: {image['url']}\n")
    return image


# ============================================================================
# Workflow 2: With Recovery (Restart from Scratch)
# ============================================================================


@step(name="transient_fetch_batch_items")
async def fetch_batch_items(batch_id: str) -> dict:
    """Fetch items in a batch."""
    print(f"[Step] Fetching batch {batch_id}...")
    await asyncio.sleep(2)
    return {"batch_id": batch_id, "items": ["a", "b", "c", "d", "e"], "fetched": True}


@step(name="transient_process_batch_items")
async def process_batch_items(batch: dict) -> dict:
    """Process all items in batch (idempotent)."""
    print(f"[Step] Processing {len(batch['items'])} items (kill worker during this step!)...")
    for i, item in enumerate(batch["items"]):
        print(f"  Processing item {item} ({i + 1}/{len(batch['items'])})...")
        await asyncio.sleep(3)  # 3 seconds per item - plenty of time to kill worker
    return {**batch, "processed": True, "processed_count": len(batch["items"])}


@step(name="transient_generate_report")
async def generate_report(batch: dict) -> dict:
    """Generate processing report (idempotent)."""
    print(f"[Step] Generating report for batch {batch['batch_id']}...")
    await asyncio.sleep(0.5)
    return {
        **batch,
        "report": f"Processed {batch['processed_count']} items successfully",
        "reported": True,
    }


@workflow(
    durable=False,
    recover_on_worker_loss=True,  # Enable recovery - restarts from scratch
    max_recovery_attempts=3,  # Allow up to 3 restarts
    tags=["celery", "transient"],
)
async def batch_processor(batch_id: str) -> dict:
    """
    Batch processing workflow - WITH AUTO-RECOVERY.

    This transient workflow will restart from scratch on worker failure.

    If a worker crashes during execution:
    - A WORKFLOW_INTERRUPTED event is recorded (even for transient!)
    - The workflow restarts from the beginning
    - All steps run again (no event replay for transient)
    - Up to 3 recovery attempts allowed

    Why use this:
    - All steps are idempotent (safe to repeat)
    - Processing can be safely restarted
    - Better reliability for batch jobs
    - Items are processed atomically (all or nothing)

    Note: For transient workflows, recovery means RESTART, not RESUME.
    Unlike durable workflows, there are no events to replay.
    """
    print(f"\n{'=' * 60}")
    print(f"Batch Processor (WITH RECOVERY): {batch_id}")
    print("If worker crashes, workflow will RESTART from scratch")
    print(f"{'=' * 60}\n")

    batch = await fetch_batch_items(batch_id)
    batch = await process_batch_items(batch)
    batch = await generate_report(batch)

    print(f"\n[Complete] {batch['report']}\n")
    return batch


# ============================================================================
# Comparison Helper
# ============================================================================


async def main() -> None:
    """Run the transient fault tolerance examples."""
    import argparse

    import pyworkflow

    parser = argparse.ArgumentParser(
        description="Transient Workflow Fault Tolerance Examples",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run image processor (no recovery on failure)
  python 02_fault_tolerance.py --workflow image --id img-123

  # Run batch processor (restarts on failure)
  python 02_fault_tolerance.py --workflow batch --id batch-456

To test:
  1. Start the workflow
  2. Kill the worker (Ctrl+C) during processing
  3. Start a new worker
  4. Observe: image_processor stays FAILED, batch_processor restarts
        """,
    )
    parser.add_argument(
        "--workflow",
        choices=["image", "batch"],
        default="batch",
        help="Which workflow to run",
    )
    parser.add_argument("--id", default="test-001", help="ID for the workflow")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("TRANSIENT WORKFLOW FAULT TOLERANCE DEMO")
    print("=" * 60)

    if args.workflow == "image":
        print("\nRunning: image_processor (recover_on_worker_loss=False)")
        print("Behavior: On worker crash -> FAILED (no recovery)")
        run_id = await pyworkflow.start(image_processor, args.id)
    else:
        print("\nRunning: batch_processor (recover_on_worker_loss=True)")
        print("Behavior: On worker crash -> RESTART from scratch")
        run_id = await pyworkflow.start(batch_processor, args.id)

    print(f"\nWorkflow dispatched with run_id: {run_id}")
    print("\nTo test fault tolerance:")
    print("  1. Watch the worker output")
    print("  2. Kill the worker during processing (Ctrl+C)")
    print("  3. Start a new worker")
    print("  4. Observe the recovery behavior")


if __name__ == "__main__":
    asyncio.run(main())
