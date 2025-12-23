"""
Celery Transient Workflow Examples

These examples demonstrate transient (non-durable) workflows running on Celery workers.

Transient workflows:
- Do NOT persist state to storage
- Do NOT record events
- Cannot be resumed after suspension
- Are simpler and faster for short-lived tasks

Key differences from durable workflows:
| Feature               | Durable           | Transient         |
|-----------------------|-------------------|-------------------|
| Event recording       | Yes               | No                |
| State persistence     | Yes               | No                |
| Resumable after crash | Yes (from events) | No (starts fresh) |
| Sleep behavior        | Suspends workflow | Blocks inline     |
| Best for              | Long-running      | Quick tasks       |
"""
