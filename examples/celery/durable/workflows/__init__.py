"""
Example workflows demonstrating PyWorkflow features.

This package contains example workflows organized by feature:
- basic: Simple order processing workflow
- long_running: Long-running onboarding workflow with sleeps
- retries: Retry handling with flaky APIs
- batch_processing: Processing data in batches
- idempotency: Idempotent payment processing
- fault_tolerance: Worker crash recovery
- hooks: Human-in-the-loop approvals with webhooks
- cancellation: Cancellable workflows with cleanup
- child_workflows: Parent-child workflow orchestration
- child_workflow_patterns: Advanced child workflow patterns
- continue_as_new: Long-running workflows with state reset
- schedules: Scheduled/recurring workflows

Usage:
    # Start workers
    pyworkflow worker start

    # List registered workflows
    pyworkflow workflows list

    # Trigger a workflow
    pyworkflow workflows run order_workflow --input '{"order_id": "123", "amount": 99.99}'
"""

# Basic workflow
from .basic import order_workflow

# Batch processing
from .batch_processing import batch_workflow

# Cancellation
from .cancellation import cancel_demo_simple_workflow, cancellable_order_workflow

# Child workflow patterns
from .child_workflow_patterns import (
    error_handling_parent_workflow,
    failing_child_workflow,
    level_1_workflow,
    level_2_workflow,
    level_3_workflow,
    parallel_parent_workflow,
    parallel_task_workflow,
    try_exceed_max_depth,
)
from .child_workflows import (
    notification_workflow,
    order_fulfillment_workflow,
    shipping_workflow,
)

# Child workflows
from .child_workflows import (
    payment_workflow as child_payment_workflow,
)

# Continue as new
from .continue_as_new import batch_processor, message_consumer, recurring_report

# Fault tolerance / recovery
from .fault_tolerance import critical_pipeline, data_pipeline

# Webhooks / Human-in-the-loop
from .hooks import approval_workflow, multi_approval_workflow, simple_approval_workflow

# Idempotency
from .idempotency import payment_workflow as idempotent_payment_workflow

# Long-running workflow with sleeps
from .long_running import onboarding_workflow

# Retry handling
from .retries import retry_demo_workflow

# Schedules
from .schedules import cleanup_workflow

__all__ = [
    # Basic
    "order_workflow",
    # Long-running
    "onboarding_workflow",
    # Retries
    "retry_demo_workflow",
    # Batch processing
    "batch_workflow",
    # Idempotency
    "idempotent_payment_workflow",
    # Fault tolerance
    "data_pipeline",
    "critical_pipeline",
    # Hooks
    "simple_approval_workflow",
    "approval_workflow",
    "multi_approval_workflow",
    # Cancellation
    "cancellable_order_workflow",
    "cancel_demo_simple_workflow",
    # Child workflows
    "child_payment_workflow",
    "shipping_workflow",
    "notification_workflow",
    "order_fulfillment_workflow",
    # Child workflow patterns
    "level_1_workflow",
    "level_2_workflow",
    "level_3_workflow",
    "parallel_task_workflow",
    "parallel_parent_workflow",
    "failing_child_workflow",
    "error_handling_parent_workflow",
    "try_exceed_max_depth",
    # Continue as new
    "batch_processor",
    "message_consumer",
    "recurring_report",
    # Schedules
    "cleanup_workflow",
]
