"""
Workflow primitives for durable execution.

Primitives provide building blocks for workflow orchestration:
- sleep: Durable delays without holding resources
- hook: Wait for external events (webhooks, approvals, callbacks)
- define_hook: Create typed hooks with Pydantic validation
- resume_hook: Resume suspended workflows from external systems
"""

from pyworkflow.primitives.define_hook import TypedHook, define_hook
from pyworkflow.primitives.hooks import hook
from pyworkflow.primitives.resume_hook import ResumeResult, resume_hook
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
]
