# Layer Boundaries

No formal architectural layers are declared in the project, but the directory structure reveals clear implicit boundaries. This document names them, defines their dependency rules, and provides guidance for maintaining separation as the codebase grows.

## Identified Layers

```
┌─────────────────────────────────────────────────┐
│  Public API  (pyworkflow/__init__.py)            │  ← user entry point
├─────────────────────────────────────────────────┤
│  Core  (core/)                                   │  ← decorators, registry
├─────────────────────────────────────────────────┤
│  Engine  (engine/)                               │  ← execution, events, replay
├────────────────────────┬────────────────────────┤
│  Primitives            │  Context               │  ← workflow building blocks
│  (primitives/)         │  (context/)            │
├────────────────────────┴────────────────────────┤
│  Runtime  (runtime/ + celery/)                   │  ← execution backends
├────────────────────────┬────────────────────────┤
│  Storage  (storage/)   │  Serialization         │  ← persistence + encoding
│                        │  (serialization/)      │
├────────────────────────┴────────────────────────┤
│  Utilities + Observability  (utils/ + observability/) │  ← shared infra
└─────────────────────────────────────────────────┘
```

## Layer Definitions

### Public API
**Directory**: `pyworkflow/__init__.py`

The single import surface exposed to users. Re-exports `start`, `resume`, `cancel_workflow`, `workflow`, `step`, `sleep`, `hook`, `configure`, `get_logger`, storage backends, and all exception types. Nothing in this layer contains logic — it is strictly a re-export facade.

**Allowed imports**: Core, Engine, Primitives, Storage, Observability.

### Core
**Directory**: `pyworkflow/core/`

The `@workflow` and `@step` decorators plus the global registry (`registry.py`) and exception hierarchy (`exceptions.py`). Core does not execute workflows; it registers them and wraps user functions with the lifecycle hooks that the engine expects.

**Allowed imports**: Engine (events, exceptions), Context (to set up WorkflowContext on call), Utils.

### Engine
**Directory**: `pyworkflow/engine/`

Owns the execution contract: `executor.py` orchestrates the `start`/`resume` lifecycle; `events.py` defines the 26 `EventType` values and the `Event` dataclass; `replay.py` processes an ordered event list to restore `LocalContext` state. This layer knows nothing about Celery or specific storage implementations.

**Allowed imports**: Context (abstract), Storage (abstract `StorageBackend`), Serialization, Utils, Observability.

### Context
**Directory**: `pyworkflow/context/`

`WorkflowContext` (abstract base), `LocalContext` (full durable implementation), `MockContext` (testing), and `aws.py` (Lambda adapter). Context holds the in-memory execution state: event log cache, step results, pending sleeps and hooks, cancellation flag. Passed implicitly via `contextvars.ContextVar`.

**Allowed imports**: Storage (abstract), Serialization, Engine events, Utils.

### Primitives
**Directory**: `pyworkflow/primitives/`

`sleep()`, `hook()`, `define_hook()`, `shield()`, `start_child_workflow()`, `continue_as_new()`. Each primitive reads the current context via `get_context()`, records events via storage, and either completes normally or raises `SuspensionSignal` / `ContinueAsNewSignal`.

**Allowed imports**: Context, Engine (events, exceptions), Storage (abstract), Serialization, Utils.

### Runtime
**Directory**: `pyworkflow/runtime/`, `pyworkflow/celery/`

Execution backends. `runtime/local.py` runs workflows in-process. `runtime/celery.py` dispatches to Celery queues. `celery/tasks.py` defines the worker-side `execute_workflow_task` and `execute_step_task`. This layer is the only place allowed to import concrete Celery APIs.

**Allowed imports**: Engine, Context, Core (registry), Storage (abstract + concrete for config), Serialization, Observability.

### Storage
**Directory**: `pyworkflow/storage/`

`StorageBackend` ABC defines the persistence contract (run CRUD, append-only event log, hooks, schedules). Concrete backends (`file.py`, `postgres.py`, `sqlite.py`, `mysql.py`, `dynamodb.py`, `cassandra.py`, `memory.py`) implement it independently. `schemas.py` owns the `WorkflowRun`, `HookRecord`, `ScheduleRecord`, and `RunStatus` dataclasses shared across backends.

**Allowed imports**: Serialization, Utils. Must NOT import from Engine, Core, Runtime, or Primitives.

### Serialization
**Directory**: `pyworkflow/serialization/`

`encoder.py` converts Python objects to JSON-safe dicts (with cloudpickle fallback for complex types). `decoder.py` reverses the process. This layer has no dependencies on any other project layer — it is a pure utility.

**Allowed imports**: stdlib only (json, base64, datetime) plus cloudpickle.

### Utilities + Observability
**Directory**: `pyworkflow/utils/`, `pyworkflow/observability/`

`utils/duration.py` parses duration strings (`"5s"`, `"2m"`, `"1w"`) into `timedelta`. `observability/logging.py` configures the Loguru sink with structured context injection. These are leaf-level modules with no project-internal imports.

## Dependency Direction Rules

Dependencies must flow **downward only** in the stack above. No upward imports are permitted:

```
Public API → Core → Engine → (Context | Primitives) → (Runtime | Storage) → (Serialization | Utils)
```

**Violations to watch for**:
- `storage/` importing from `engine/` or `core/` (circular via executor)
- `serialization/` importing from any project layer
- `primitives/` importing from `runtime/` or `celery/` directly
- `context/` importing from `primitives/` (primitives read context; context must not depend on primitives)

## Evolving Toward Stricter Layering

The current structure is implicit but consistent. To formalize it:

1. **Add `__all__` guards** to each subpackage's `__init__.py` listing only what downstream layers may import. This surfaces accidental cross-layer coupling at import time.

2. **Enforce with ruff** — add `pyworkflow/storage/` to a `no-imports-from` ruff rule for `engine` and `core` modules.

3. **Separate `schemas.py`** from `storage/` into a top-level `models.py` or `schemas.py` so Engine and Context can import data models without depending on the Storage layer.

4. **Runtime plugin protocol** — define a `Runtime` protocol in `runtime/base.py` and have `engine/executor.py` depend only on the protocol, making runtime swaps completely transparent to the engine.
