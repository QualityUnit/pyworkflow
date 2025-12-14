"""
PyWorkflow Runtime Abstraction Layer.

Runtimes determine WHERE workflow code executes:
- LocalRuntime: In-process execution (for CI, testing, simple scripts)
- CeleryRuntime: Distributed execution via Celery workers
- LambdaRuntime: AWS Lambda execution (future)
- DurableLambdaRuntime: AWS Durable Lambda execution (future)
"""

from pyworkflow.runtime.base import Runtime
from pyworkflow.runtime.factory import get_runtime, register_runtime, validate_runtime_durable
from pyworkflow.runtime.local import LocalRuntime

__all__ = [
    "Runtime",
    "LocalRuntime",
    "get_runtime",
    "register_runtime",
    "validate_runtime_durable",
]
