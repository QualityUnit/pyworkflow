# Memory Optimization Implementation Summary

## Changes Implemented

This document summarizes the changes made to reduce idle worker memory consumption in PyWorkflow.

### 1. PostgreSQL Connection Pool Environment Variables

**File Modified**: `pyworkflow/storage/postgres.py`

**Changes**:
- Added `import os` to support environment variable reading
- Modified `PostgresStorageBackend.__init__()` to accept optional pool configuration parameters
- Added environment variable support for connection pool settings:
  - `PYWORKFLOW_POSTGRES_MIN_POOL_SIZE` (default: 1)
  - `PYWORKFLOW_POSTGRES_MAX_POOL_SIZE` (default: 10)
  - `PYWORKFLOW_POSTGRES_MAX_INACTIVE_LIFETIME` (default: 1800.0 seconds)
  - `PYWORKFLOW_POSTGRES_COMMAND_TIMEOUT` (default: 60.0 seconds)

**Impact**: Allows deployment-specific tuning without code changes. Smaller pool + faster connection expiry reduces idle memory.

**Recommended Production Settings**:
```bash
PYWORKFLOW_POSTGRES_MIN_POOL_SIZE=1
PYWORKFLOW_POSTGRES_MAX_POOL_SIZE=3
PYWORKFLOW_POSTGRES_MAX_INACTIVE_LIFETIME=300
PYWORKFLOW_POSTGRES_COMMAND_TIMEOUT=30
```

**Expected Memory Reduction**: 30-50 MB per worker (by reducing pool from 10 to 3 connections)

---

### 2. Disabled Redis Result Backend by Default

**File Modified**: `pyworkflow/celery/app.py`

**Changes**:
- Modified `create_celery_app()` to make `result_backend` default to `None` (disabled)
- Refactored Celery configuration to conditionally add result backend settings only when enabled
- Fixed sentinel backend detection to handle `None` result_backend
- Updated singleton backend to use broker URL instead of result backend

**Behavior**:
- **Default**: Result backend is disabled (PyWorkflow stores results in PostgreSQL)
- **Override**: Set `PYWORKFLOW_CELERY_RESULT_BACKEND` environment variable to enable
- **Backward Compatible**: Existing deployments with the env var set will continue working

**Impact**: Removes redundant Redis result backend, reducing memory overhead and Redis memory usage.

**Expected Memory Reduction**: 10-20 MB per worker + reduced Redis memory

---

## Testing & Verification

### Automated Tests Passed

1. **PostgreSQL Storage Tests**: All 57 tests passed
   ```bash
   python -m pytest tests/unit/backends/test_postgres_storage.py -v
   ```

2. **Workflow Tests**: All 8 tests passed
   ```bash
   python -m pytest tests/unit/test_workflow.py::TestWorkflowDecorator -v
   ```

3. **Configuration Tests**: Verified environment variable behavior
   - PostgreSQL pool settings correctly read from env vars
   - Celery result backend correctly disabled by default
   - Singleton backend correctly uses broker URL

### Manual Verification Steps

#### 1. Test PostgreSQL Connection Pool

```python
import asyncio
from pyworkflow.storage.config import configure_storage

async def test_pool():
    storage = configure_storage(
        type="postgres",
        postgres_host="localhost",
        postgres_database="pyworkflow",
    )
    await storage.connect()
    print(f"Pool size: min={storage.min_pool_size}, max={storage.max_pool_size}")
    print(f"Inactive lifetime: {storage.max_inactive_connection_lifetime}s")
    await storage.disconnect()

asyncio.run(test_pool())
```

**Expected Output**:
```
Pool size: min=1, max=3
Inactive lifetime: 300.0s
```

#### 2. Verify Result Backend Disabled

```python
from pyworkflow.celery.app import celery_app
print(f"Result backend: {celery_app.conf.result_backend}")
# Should print: Result backend: None
```

#### 3. Monitor Memory Usage

```bash
# Before changes (baseline)
kubectl top pods | grep pyworkflow-step-worker
# Example: pyworkflow-step-worker-abc 635Mi

# After changes (with new settings)
kubectl top pods | grep pyworkflow-step-worker
# Expected: pyworkflow-step-worker-abc 550-600Mi (50-85 MB reduction per worker)
```

#### 4. Verify Workflow Execution

```python
# Test that workflows still work without result backend
from pyworkflow import start

@workflow
async def test_wf():
    return "success"

run_id = await start(test_wf)
# Should complete normally - results stored in PostgreSQL, not Redis
```

#### 5. Monitor Active PostgreSQL Connections

```sql
SELECT count(*), application_name
FROM pg_stat_activity
WHERE datname='pyworkflow'
GROUP BY application_name;
```

**Expected**: Max 3 connections per worker (down from 10)

---

## Deployment Configuration

### Kubernetes Environment Variables

Add these environment variables to worker pod specifications:

```yaml
env:
  # PostgreSQL Connection Pool Settings
  - name: PYWORKFLOW_POSTGRES_MIN_POOL_SIZE
    value: "1"
  - name: PYWORKFLOW_POSTGRES_MAX_POOL_SIZE
    value: "3"
  - name: PYWORKFLOW_POSTGRES_MAX_INACTIVE_LIFETIME
    value: "300"
  - name: PYWORKFLOW_POSTGRES_COMMAND_TIMEOUT
    value: "30"

  # DO NOT set PYWORKFLOW_CELERY_RESULT_BACKEND
  # (to keep result backend disabled)

  # Existing settings (keep these)
  - name: PYWORKFLOW_WORKER_MAX_MEMORY
    value: "500000"  # 488 MB
  - name: PYWORKFLOW_WORKER_MAX_TASKS
    value: "5"
```

---

## Expected Impact

### Memory Reduction

| Component | Reduction per Worker | Notes |
|-----------|---------------------|-------|
| PostgreSQL Pool | 30-50 MB | Reduced from 10 to 3 connections |
| Redis Result Backend | 10-20 MB | Removed redundant backend |
| **Total per Worker** | **40-70 MB** | Conservative estimate |
| **Total (2 idle workers)** | **80-140 MB** | Current deployment |

### Additional Benefits

1. **Reduced Redis Memory**: Result backend data no longer stored in Redis
2. **Faster Connection Cleanup**: 300s inactive lifetime vs 1800s default
3. **Improved Efficiency**: Fewer idle PostgreSQL connections
4. **No Functional Impact**: Results still stored reliably in PostgreSQL

---

## Monitoring Recommendations

After deployment, monitor the following:

1. **Worker Memory Usage**:
   ```bash
   kubectl top pods | grep pyworkflow-step-worker
   ```

2. **PostgreSQL Connection Count**:
   ```sql
   SELECT count(*) FROM pg_stat_activity WHERE datname='pyworkflow';
   ```

3. **Worker Logs**: Check for `PoolAcquireTimeoutError` (indicates pool too small)

4. **Workflow Execution**: Verify workflows complete successfully without result backend

---

## Rollback Plan

If issues arise, revert by:

1. **Re-enable Result Backend**:
   ```yaml
   env:
   - name: PYWORKFLOW_CELERY_RESULT_BACKEND
     value: "redis://localhost:6379/1"
   ```

2. **Increase PostgreSQL Pool**:
   ```yaml
   env:
   - name: PYWORKFLOW_POSTGRES_MAX_POOL_SIZE
     value: "10"
   ```

3. **Redeploy workers**

---

## Future Optimizations (Out of Scope)

For further memory reduction, consider:

1. **Autoscale Settings**: `--autoscale=10,0` (scale to zero when idle)
2. **Gevent Pool**: Switch from prefork to gevent (60-80% memory reduction)
3. **KEDA Autoscaling**: Enable true scale-to-zero for pods
4. **jemalloc Allocator**: 15-25% memory reduction
5. **PgBouncer**: Connection pooling for 20+ workers

---

## References

- Plan Document: `/home/yasha/.claude/projects/-home-yasha-Desktop-projects-pyworkflow/c49e57ac-2638-4b45-88dd-f77d9e7ac8f1.jsonl`
- GitHub Issue: Memory optimization for idle workers
- Previous Commits:
  - `85a8858`: Added worker memory limits
  - `001c91b`: Disabled PostgreSQL statement cache

---

## Implementation Date

2026-02-03
