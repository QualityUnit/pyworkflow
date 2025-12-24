"""
Workflow primitives for durable execution.

Primitives provide building blocks for workflow orchestration:
- sleep: Durable delays without holding resources
- hook: Wait for external events (webhooks, approvals, callbacks)
- define_hook: Create typed hooks with Pydantic validation
- resume_hook: Resume suspended workflows from external systems
- shield: Protection from cancellation for critical sections
- continue_as_new: Continue workflow with fresh event history
"""

from pyworkflow.primitives.continue_as_new import continue_as_new
from pyworkflow.primitives.define_hook import TypedHook, define_hook
from pyworkflow.primitives.hooks import hook
from pyworkflow.primitives.resume_hook import ResumeResult, resume_hook
from pyworkflow.primitives.shield import shield
from pyworkflow.primitives.sleep import sleep

__all__ = [
    # Sleep
    "sleep",
    # Hooks
    "hook",
    "define_hook",
    "TypedHook",
    "resume_hook",
    "ResumeResult",
    # Cancellation
    "shield",
    # Continue-as-new
    "continue_as_new",
]
