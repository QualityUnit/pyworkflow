"""
DynamoDB storage backend using aiobotocore.

This backend stores workflow data in AWS DynamoDB, suitable for:
- Serverless deployments
- Multi-region high availability
- Automatically scaled workloads

Uses single-table design with Global Secondary Indexes for efficient querying.
"""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from aiobotocore.session import get_session
from botocore.exceptions import ClientError

from pyworkflow.engine.events import Event, EventType
from pyworkflow.storage.base import StorageBackend
from pyworkflow.storage.schemas import (
    Hook,
    HookStatus,
    OverlapPolicy,
    RunStatus,
    Schedule,
    ScheduleSpec,
    ScheduleStatus,
    StepExecution,
    StepStatus,
    WorkflowRun,
)


class DynamoDBStorageBackend(StorageBackend):
    """
    DynamoDB storage backend using aiobotocore for async operations.

    Uses single-table design with the following key patterns:
    - PK: Entity type + ID (e.g., RUN#run_abc123)
    - SK: Sub-key for ordering (e.g., #METADATA, EVENT#00001)

    Global Secondary Indexes:
    - GSI1: Status-based queries (GSI1PK: entity type, GSI1SK: status#created_at)
    - GSI2: Workflow name queries (GSI2PK: WORKFLOW#name, GSI2SK: created_at)
    - GSI3: Idempotency key lookup (GSI3PK: IDEMPOTENCY#key)
    - GSI4: Parent-child relationships (GSI4PK: PARENT#run_id, GSI4SK: CHILD#run_id)
    - GSI5: Schedule due time (GSI5PK: ACTIVE_SCHEDULES, GSI5SK: next_run_time)
    """

    def __init__(
        self,
        table_name: str = "pyworkflow",
        region: str = "us-east-1",
        endpoint_url: str | None = None,
    ):
        """
        Initialize DynamoDB storage backend.

        Args:
            table_name: DynamoDB table name
            region: AWS region
            endpoint_url: Optional endpoint URL for local testing (e.g., http://localhost:8000)
        """
        self.table_name = table_name
        self.region = region
        self.endpoint_url = endpoint_url
        self._session = get_session()
        self._initialized = False

    @asynccontextmanager
    async def _get_client(self):
        """Get DynamoDB client context manager."""
        async with self._session.create_client(
            "dynamodb",
            region_name=self.region,
            endpoint_url=self.endpoint_url,
        ) as client:
            yield client

    async def connect(self) -> None:
        """Initialize connection and create table if needed."""
        if not self._initialized:
            await self._ensure_table_exists()
            self._initialized = True

    async def disconnect(self) -> None:
        """Close connection (no-op for DynamoDB, connection is per-request)."""
        self._initialized = False

    async def _ensure_table_exists(self) -> None:
        """Create table with GSIs if it doesn't exist."""
        async with self._get_client() as client:
            try:
                await client.describe_table(TableName=self.table_name)
                return  # Table exists
            except ClientError as e:
                if e.response["Error"]["Code"] != "ResourceNotFoundException":
                    raise

            # Create table with single-table design
            await client.create_table(
                TableName=self.table_name,
                KeySchema=[
                    {"AttributeName": "PK", "KeyType": "HASH"},
                    {"AttributeName": "SK", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "PK", "AttributeType": "S"},
                    {"AttributeName": "SK", "AttributeType": "S"},
                    {"AttributeName": "GSI1PK", "AttributeType": "S"},
                    {"AttributeName": "GSI1SK", "AttributeType": "S"},
                    {"AttributeName": "GSI2PK", "AttributeType": "S"},
                    {"AttributeName": "GSI2SK", "AttributeType": "S"},
                    {"AttributeName": "GSI3PK", "AttributeType": "S"},
                    {"AttributeName": "GSI4PK", "AttributeType": "S"},
                    {"AttributeName": "GSI4SK", "AttributeType": "S"},
                    {"AttributeName": "GSI5PK", "AttributeType": "S"},
                    {"AttributeName": "GSI5SK", "AttributeType": "S"},
                ],
                GlobalSecondaryIndexes=[
                    {
                        "IndexName": "GSI1",
                        "KeySchema": [
                            {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                            {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                    },
                    {
                        "IndexName": "GSI2",
                        "KeySchema": [
                            {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                            {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                    },
                    {
                        "IndexName": "GSI3",
                        "KeySchema": [
                            {"AttributeName": "GSI3PK", "KeyType": "HASH"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                    },
                    {
                        "IndexName": "GSI4",
                        "KeySchema": [
                            {"AttributeName": "GSI4PK", "KeyType": "HASH"},
                            {"AttributeName": "GSI4SK", "KeyType": "RANGE"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                    },
                    {
                        "IndexName": "GSI5",
                        "KeySchema": [
                            {"AttributeName": "GSI5PK", "KeyType": "HASH"},
                            {"AttributeName": "GSI5SK", "KeyType": "RANGE"},
                        ],
                        "Projection": {"ProjectionType": "ALL"},
                    },
                ],
                BillingMode="PAY_PER_REQUEST",  # On-demand capacity
            )

            # Wait for table to be active
            waiter = client.get_waiter("table_exists")
            await waiter.wait(TableName=self.table_name)

    # Helper methods for DynamoDB item conversion

    def _serialize_value(self, value: Any) -> dict[str, Any]:
        """Convert Python value to DynamoDB attribute value."""
        if value is None:
            return {"NULL": True}
        elif isinstance(value, bool):
            return {"BOOL": value}
        elif isinstance(value, (int, float)):
            return {"N": str(value)}
        elif isinstance(value, str):
            return {"S": value}
        elif isinstance(value, list):
            return {"L": [self._serialize_value(v) for v in value]}
        elif isinstance(value, dict):
            return {"M": {k: self._serialize_value(v) for k, v in value.items()}}
        else:
            return {"S": str(value)}

    def _deserialize_value(self, attr: dict[str, Any]) -> Any:
        """Convert DynamoDB attribute value to Python value."""
        if "NULL" in attr:
            return None
        elif "BOOL" in attr:
            return attr["BOOL"]
        elif "N" in attr:
            n = attr["N"]
            return int(n) if "." not in n else float(n)
        elif "S" in attr:
            return attr["S"]
        elif "L" in attr:
            return [self._deserialize_value(v) for v in attr["L"]]
        elif "M" in attr:
            return {k: self._deserialize_value(v) for k, v in attr["M"].items()}
        else:
            return None

    def _item_to_dict(self, item: dict[str, Any]) -> dict[str, Any]:
        """Convert DynamoDB item to Python dict."""
        return {k: self._deserialize_value(v) for k, v in item.items()}

    def _dict_to_item(self, data: dict[str, Any]) -> dict[str, Any]:
        """Convert Python dict to DynamoDB item."""
        return {k: self._serialize_value(v) for k, v in data.items() if v is not None}

    # Workflow Run Operations

    async def create_run(self, run: WorkflowRun) -> None:
        """Create a new workflow run record."""
        async with self._get_client() as client:
            item = {
                "PK": f"RUN#{run.run_id}",
                "SK": "#METADATA",
                "entity_type": "run",
                "run_id": run.run_id,
                "workflow_name": run.workflow_name,
                "status": run.status.value,
                "created_at": run.created_at.isoformat(),
                "updated_at": run.updated_at.isoformat(),
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "completed_at": run.completed_at.isoformat() if run.completed_at else None,
                "input_args": run.input_args,
                "input_kwargs": run.input_kwargs,
                "result": run.result,
                "error": run.error,
                "idempotency_key": run.idempotency_key,
                "max_duration": run.max_duration,
                "context": json.dumps(run.context),
                "recovery_attempts": run.recovery_attempts,
                "max_recovery_attempts": run.max_recovery_attempts,
                "recover_on_worker_loss": run.recover_on_worker_loss,
                "parent_run_id": run.parent_run_id,
                "nesting_depth": run.nesting_depth,
                "continued_from_run_id": run.continued_from_run_id,
                "continued_to_run_id": run.continued_to_run_id,
                # GSI keys
                "GSI1PK": "RUNS",
                "GSI1SK": f"{run.status.value}#{run.created_at.isoformat()}",
                "GSI2PK": f"WORKFLOW#{run.workflow_name}",
                "GSI2SK": run.created_at.isoformat(),
            }

            # Add idempotency GSI if key exists
            if run.idempotency_key:
                item["GSI3PK"] = f"IDEMPOTENCY#{run.idempotency_key}"

            # Add parent-child GSI if parent exists
            if run.parent_run_id:
                item["GSI4PK"] = f"PARENT#{run.parent_run_id}"
                item["GSI4SK"] = f"CHILD#{run.run_id}"

            await client.put_item(
                TableName=self.table_name,
                Item=self._dict_to_item(item),
                ConditionExpression="attribute_not_exists(PK)",
            )

    async def get_run(self, run_id: str) -> WorkflowRun | None:
        """Retrieve a workflow run by ID."""
        async with self._get_client() as client:
            response = await client.get_item(
                TableName=self.table_name,
                Key={
                    "PK": {"S": f"RUN#{run_id}"},
                    "SK": {"S": "#METADATA"},
                },
            )

            item = response.get("Item")
            if not item:
                return None

            return self._item_to_workflow_run(self._item_to_dict(item))

    async def get_run_by_idempotency_key(self, key: str) -> WorkflowRun | None:
        """Retrieve a workflow run by idempotency key."""
        async with self._get_client() as client:
            response = await client.query(
                TableName=self.table_name,
                IndexName="GSI3",
                KeyConditionExpression="GSI3PK = :pk",
                ExpressionAttributeValues={":pk": {"S": f"IDEMPOTENCY#{key}"}},
                Limit=1,
            )

            items = response.get("Items", [])
            if not items:
                return None

            return self._item_to_workflow_run(self._item_to_dict(items[0]))

    async def update_run_status(
        self,
        run_id: str,
        status: RunStatus,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update workflow run status."""
        async with self._get_client() as client:
            now = datetime.now(UTC).isoformat()

            update_expr = "SET #status = :status, updated_at = :updated_at, GSI1SK = :gsi1sk"
            expr_names = {"#status": "status"}
            expr_values: dict[str, Any] = {
                ":status": {"S": status.value},
                ":updated_at": {"S": now},
                ":gsi1sk": {"S": f"{status.value}#{now}"},
            }

            if result is not None:
                update_expr += ", #result = :result"
                expr_names["#result"] = "result"
                expr_values[":result"] = {"S": result}

            if error is not None:
                update_expr += ", #error = :error"
                expr_names["#error"] = "error"
                expr_values[":error"] = {"S": error}

            if status == RunStatus.COMPLETED:
                update_expr += ", completed_at = :completed_at"
                expr_values[":completed_at"] = {"S": now}

            await client.update_item(
                TableName=self.table_name,
                Key={
                    "PK": {"S": f"RUN#{run_id}"},
                    "SK": {"S": "#METADATA"},
                },
                UpdateExpression=update_expr,
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values,
            )

    async def update_run_recovery_attempts(
        self,
        run_id: str,
        recovery_attempts: int,
    ) -> None:
        """Update the recovery attempts counter for a workflow run."""
        async with self._get_client() as client:
            await client.update_item(
                TableName=self.table_name,
                Key={
                    "PK": {"S": f"RUN#{run_id}"},
                    "SK": {"S": "#METADATA"},
                },
                UpdateExpression="SET recovery_attempts = :ra, updated_at = :now",
                ExpressionAttributeValues={
                    ":ra": {"N": str(recovery_attempts)},
                    ":now": {"S": datetime.now(UTC).isoformat()},
                },
            )

    async def update_run_context(
        self,
        run_id: str,
        context: dict,
    ) -> None:
        """Update the step context for a workflow run."""
        async with self._get_client() as client:
            await client.update_item(
                TableName=self.table_name,
                Key={
                    "PK": {"S": f"RUN#{run_id}"},
                    "SK": {"S": "#METADATA"},
                },
                UpdateExpression="SET #ctx = :ctx, updated_at = :now",
                ExpressionAttributeNames={
                    "#ctx": "context",
                },
                ExpressionAttributeValues={
                    ":ctx": {"S": json.dumps(context)},
                    ":now": {"S": datetime.now(UTC).isoformat()},
                },
            )

    async def get_run_context(self, run_id: str) -> dict:
        """Get the current step context for a workflow run."""
        run = await self.get_run(run_id)
        return run.context if run else {}

    async def list_runs(
        self,
        query: str | None = None,
        status: RunStatus | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[WorkflowRun], str | None]:
        """List workflow runs with optional filtering and pagination."""
        async with self._get_client() as client:
            # Use GSI1 for status-based queries, otherwise scan
            if status:
                key_condition = "GSI1PK = :pk AND begins_with(GSI1SK, :status)"
                expr_values: dict[str, Any] = {
                    ":pk": {"S": "RUNS"},
                    ":status": {"S": f"{status.value}#"},
                }

                params: dict[str, Any] = {
                    "TableName": self.table_name,
                    "IndexName": "GSI1",
                    "KeyConditionExpression": key_condition,
                    "ExpressionAttributeValues": expr_values,
                    "Limit": limit + 1,
                    "ScanIndexForward": False,  # Descending order
                }

                if cursor:
                    # Decode cursor (run_id)
                    run = await self.get_run(cursor)
                    if run:
                        params["ExclusiveStartKey"] = {
                            "GSI1PK": {"S": "RUNS"},
                            "GSI1SK": {"S": f"{run.status.value}#{run.created_at.isoformat()}"},
                            "PK": {"S": f"RUN#{cursor}"},
                            "SK": {"S": "#METADATA"},
                        }

                response = await client.query(**params)
            else:
                # Scan with filter for non-status queries
                params = {
                    "TableName": self.table_name,
                    "IndexName": "GSI1",
                    "KeyConditionExpression": "GSI1PK = :pk",
                    "ExpressionAttributeValues": {":pk": {"S": "RUNS"}},
                    "Limit": limit + 1,
                    "ScanIndexForward": False,
                }

                filter_exprs = []
                expr_values = {}

                if query:
                    filter_exprs.append(
                        "(contains(workflow_name, :query) OR contains(input_kwargs, :query))"
                    )
                    expr_values[":query"] = {"S": query}

                if start_time:
                    filter_exprs.append("created_at >= :start_time")
                    expr_values[":start_time"] = {"S": start_time.isoformat()}

                if end_time:
                    filter_exprs.append("created_at < :end_time")
                    expr_values[":end_time"] = {"S": end_time.isoformat()}

                if filter_exprs:
                    params["FilterExpression"] = " AND ".join(filter_exprs)
                    params["ExpressionAttributeValues"].update(expr_values)

                if cursor:
                    run = await self.get_run(cursor)
                    if run:
                        params["ExclusiveStartKey"] = {
                            "GSI1PK": {"S": "RUNS"},
                            "GSI1SK": {"S": f"{run.status.value}#{run.created_at.isoformat()}"},
                            "PK": {"S": f"RUN#{cursor}"},
                            "SK": {"S": "#METADATA"},
                        }

                response = await client.query(**params)

            items = response.get("Items", [])
            has_more = len(items) > limit

            if has_more:
                items = items[:limit]

            runs = [self._item_to_workflow_run(self._item_to_dict(item)) for item in items]
            next_cursor = runs[-1].run_id if runs and has_more else None

            return runs, next_cursor

    # Event Log Operations

    async def record_event(self, event: Event) -> None:
        """Record an event to the append-only event log."""
        async with self._get_client() as client:
            # Get next sequence number using atomic counter
            response = await client.update_item(
                TableName=self.table_name,
                Key={
                    "PK": {"S": f"RUN#{event.run_id}"},
                    "SK": {"S": "#EVENT_COUNTER"},
                },
                UpdateExpression="ADD seq :inc",
                ExpressionAttributeValues={":inc": {"N": "1"}},
                ReturnValues="UPDATED_NEW",
            )

            sequence = int(response["Attributes"]["seq"]["N"]) - 1

            item = {
                "PK": f"RUN#{event.run_id}",
                "SK": f"EVENT#{sequence:05d}",
                "entity_type": "event",
                "event_id": event.event_id,
                "run_id": event.run_id,
                "sequence": sequence,
                "type": event.type.value,
                "timestamp": event.timestamp.isoformat(),
                "data": json.dumps(event.data),
            }

            await client.put_item(
                TableName=self.table_name,
                Item=self._dict_to_item(item),
            )

    async def get_events(
        self,
        run_id: str,
        event_types: list[str] | None = None,
    ) -> list[Event]:
        """Retrieve all events for a workflow run, ordered by sequence."""
        async with self._get_client() as client:
            params: dict[str, Any] = {
                "TableName": self.table_name,
                "KeyConditionExpression": "PK = :pk AND begins_with(SK, :sk_prefix)",
                "ExpressionAttributeValues": {
                    ":pk": {"S": f"RUN#{run_id}"},
                    ":sk_prefix": {"S": "EVENT#"},
                },
            }

            if event_types:
                placeholders = [f":type{i}" for i in range(len(event_types))]
                params["FilterExpression"] = f"#type IN ({', '.join(placeholders)})"
                params["ExpressionAttributeNames"] = {"#type": "type"}
                for i, et in enumerate(event_types):
                    params["ExpressionAttributeValues"][f":type{i}"] = {"S": et}

            # Handle pagination for large event logs
            events = []
            while True:
                response = await client.query(**params)
                items = response.get("Items", [])
                events.extend([self._item_to_event(self._item_to_dict(item)) for item in items])

                if "LastEvaluatedKey" not in response:
                    break
                params["ExclusiveStartKey"] = response["LastEvaluatedKey"]

            return events

    async def get_latest_event(
        self,
        run_id: str,
        event_type: str | None = None,
    ) -> Event | None:
        """Get the latest event for a run, optionally filtered by type."""
        async with self._get_client() as client:
            params: dict[str, Any] = {
                "TableName": self.table_name,
                "KeyConditionExpression": "PK = :pk AND begins_with(SK, :sk_prefix)",
                "ExpressionAttributeValues": {
                    ":pk": {"S": f"RUN#{run_id}"},
                    ":sk_prefix": {"S": "EVENT#"},
                },
                "ScanIndexForward": False,  # Descending order
                "Limit": 10 if event_type else 1,  # Get more if filtering
            }

            if event_type:
                params["FilterExpression"] = "#type = :event_type"
                params["ExpressionAttributeNames"] = {"#type": "type"}
                params["ExpressionAttributeValues"][":event_type"] = {"S": event_type}

            response = await client.query(**params)
            items = response.get("Items", [])

            if not items:
                return None

            return self._item_to_event(self._item_to_dict(items[0]))

    # Step Operations

    async def create_step(self, step: StepExecution) -> None:
        """Create a step execution record."""
        async with self._get_client() as client:
            retry_count = step.attempt - 1 if step.attempt > 0 else 0

            item = {
                "PK": f"RUN#{step.run_id}",
                "SK": f"STEP#{step.step_id}",
                "entity_type": "step",
                "step_id": step.step_id,
                "run_id": step.run_id,
                "step_name": step.step_name,
                "status": step.status.value,
                "created_at": step.created_at.isoformat(),
                "started_at": step.started_at.isoformat() if step.started_at else None,
                "completed_at": step.completed_at.isoformat() if step.completed_at else None,
                "input_args": step.input_args,
                "input_kwargs": step.input_kwargs,
                "result": step.result,
                "error": step.error,
                "retry_count": retry_count,
            }

            await client.put_item(
                TableName=self.table_name,
                Item=self._dict_to_item(item),
            )

    async def get_step(self, step_id: str) -> StepExecution | None:
        """Retrieve a step execution by ID."""
        # Steps are stored under their run, so we need to scan
        # Note: For high-volume production use, consider adding a GSI on step_id
        async with self._get_client() as client:
            items = []

            # Scan with pagination to find the step
            response = await client.scan(
                TableName=self.table_name,
                FilterExpression="entity_type = :et AND step_id = :sid",
                ExpressionAttributeValues={
                    ":et": {"S": "step"},
                    ":sid": {"S": step_id},
                },
            )

            items.extend(response.get("Items", []))

            # Continue scanning if there are more pages and we haven't found it
            while "LastEvaluatedKey" in response and not items:
                response = await client.scan(
                    TableName=self.table_name,
                    FilterExpression="entity_type = :et AND step_id = :sid",
                    ExpressionAttributeValues={
                        ":et": {"S": "step"},
                        ":sid": {"S": step_id},
                    },
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                )
                items.extend(response.get("Items", []))

            if not items:
                return None

            return self._item_to_step_execution(self._item_to_dict(items[0]))

    async def update_step_status(
        self,
        step_id: str,
        status: str,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update step execution status."""
        # First find the step to get its run_id
        step = await self.get_step(step_id)
        if not step:
            return

        async with self._get_client() as client:
            update_expr = "SET #status = :status"
            expr_names = {"#status": "status"}
            expr_values: dict[str, Any] = {":status": {"S": status}}

            if result is not None:
                update_expr += ", #result = :result"
                expr_names["#result"] = "result"
                expr_values[":result"] = {"S": result}

            if error is not None:
                update_expr += ", #error = :error"
                expr_names["#error"] = "error"
                expr_values[":error"] = {"S": error}

            if status == "completed":
                update_expr += ", completed_at = :completed_at"
                expr_values[":completed_at"] = {"S": datetime.now(UTC).isoformat()}

            await client.update_item(
                TableName=self.table_name,
                Key={
                    "PK": {"S": f"RUN#{step.run_id}"},
                    "SK": {"S": f"STEP#{step_id}"},
                },
                UpdateExpression=update_expr,
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values,
            )

    async def list_steps(self, run_id: str) -> list[StepExecution]:
        """List all steps for a workflow run."""
        async with self._get_client() as client:
            response = await client.query(
                TableName=self.table_name,
                KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
                ExpressionAttributeValues={
                    ":pk": {"S": f"RUN#{run_id}"},
                    ":sk_prefix": {"S": "STEP#"},
                },
            )

            items = response.get("Items", [])
            steps = [self._item_to_step_execution(self._item_to_dict(item)) for item in items]

            # Sort by created_at
            steps.sort(key=lambda s: s.created_at)
            return steps

    # Hook Operations

    async def create_hook(self, hook: Hook) -> None:
        """Create a hook record."""
        async with self._get_client() as client:
            # Main hook item
            item = {
                "PK": f"HOOK#{hook.hook_id}",
                "SK": "#METADATA",
                "entity_type": "hook",
                "hook_id": hook.hook_id,
                "run_id": hook.run_id,
                "token": hook.token,
                "created_at": hook.created_at.isoformat(),
                "received_at": hook.received_at.isoformat() if hook.received_at else None,
                "expires_at": hook.expires_at.isoformat() if hook.expires_at else None,
                "status": hook.status.value,
                "payload": hook.payload,
                "metadata": json.dumps(hook.metadata),
                # GSI for run_id lookup
                "GSI1PK": f"RUN_HOOKS#{hook.run_id}",
                "GSI1SK": f"{hook.status.value}#{hook.created_at.isoformat()}",
            }

            # Token lookup item
            token_item = {
                "PK": f"TOKEN#{hook.token}",
                "SK": f"HOOK#{hook.hook_id}",
                "entity_type": "hook_token",
                "hook_id": hook.hook_id,
            }

            # Write both items
            await client.put_item(
                TableName=self.table_name,
                Item=self._dict_to_item(item),
            )
            await client.put_item(
                TableName=self.table_name,
                Item=self._dict_to_item(token_item),
            )

    async def get_hook(self, hook_id: str) -> Hook | None:
        """Retrieve a hook by ID."""
        async with self._get_client() as client:
            response = await client.get_item(
                TableName=self.table_name,
                Key={
                    "PK": {"S": f"HOOK#{hook_id}"},
                    "SK": {"S": "#METADATA"},
                },
            )

            item = response.get("Item")
            if not item:
                return None

            return self._item_to_hook(self._item_to_dict(item))

    async def get_hook_by_token(self, token: str) -> Hook | None:
        """Retrieve a hook by its token."""
        async with self._get_client() as client:
            # First get the hook_id from the token lookup item
            response = await client.query(
                TableName=self.table_name,
                KeyConditionExpression="PK = :pk",
                ExpressionAttributeValues={":pk": {"S": f"TOKEN#{token}"}},
                Limit=1,
            )

            items = response.get("Items", [])
            if not items:
                return None

            hook_id = self._deserialize_value(items[0]["hook_id"])
            return await self.get_hook(hook_id)

    async def update_hook_status(
        self,
        hook_id: str,
        status: HookStatus,
        payload: str | None = None,
    ) -> None:
        """Update hook status and optionally payload."""
        async with self._get_client() as client:
            update_expr = "SET #status = :status"
            expr_names = {"#status": "status"}
            expr_values: dict[str, Any] = {":status": {"S": status.value}}

            if payload is not None:
                update_expr += ", payload = :payload"
                expr_values[":payload"] = {"S": payload}

            if status == HookStatus.RECEIVED:
                update_expr += ", received_at = :received_at"
                expr_values[":received_at"] = {"S": datetime.now(UTC).isoformat()}

            await client.update_item(
                TableName=self.table_name,
                Key={
                    "PK": {"S": f"HOOK#{hook_id}"},
                    "SK": {"S": "#METADATA"},
                },
                UpdateExpression=update_expr,
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values,
            )

    async def list_hooks(
        self,
        run_id: str | None = None,
        status: HookStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Hook]:
        """List hooks with optional filtering."""
        async with self._get_client() as client:
            if run_id:
                # Use GSI1 for run_id-based queries
                params: dict[str, Any] = {
                    "TableName": self.table_name,
                    "IndexName": "GSI1",
                    "KeyConditionExpression": "GSI1PK = :pk",
                    "ExpressionAttributeValues": {":pk": {"S": f"RUN_HOOKS#{run_id}"}},
                    "Limit": limit + offset,
                    "ScanIndexForward": False,
                }

                if status:
                    params["KeyConditionExpression"] += " AND begins_with(GSI1SK, :status)"
                    params["ExpressionAttributeValues"][":status"] = {"S": f"{status.value}#"}

                response = await client.query(**params)
            else:
                # Scan for all hooks
                params = {
                    "TableName": self.table_name,
                    "FilterExpression": "entity_type = :et",
                    "ExpressionAttributeValues": {":et": {"S": "hook"}},
                    "Limit": limit + offset,
                }

                if status:
                    params["FilterExpression"] += " AND #status = :status"
                    params["ExpressionAttributeNames"] = {"#status": "status"}
                    params["ExpressionAttributeValues"][":status"] = {"S": status.value}

                response = await client.scan(**params)

            items = response.get("Items", [])

            # Apply offset
            items = items[offset : offset + limit]

            return [self._item_to_hook(self._item_to_dict(item)) for item in items]

    # Cancellation Flag Operations

    async def set_cancellation_flag(self, run_id: str) -> None:
        """Set a cancellation flag for a workflow run."""
        async with self._get_client() as client:
            await client.put_item(
                TableName=self.table_name,
                Item=self._dict_to_item(
                    {
                        "PK": f"CANCEL#{run_id}",
                        "SK": "#FLAG",
                        "entity_type": "cancellation",
                        "run_id": run_id,
                        "created_at": datetime.now(UTC).isoformat(),
                    }
                ),
            )

    async def check_cancellation_flag(self, run_id: str) -> bool:
        """Check if a cancellation flag is set for a workflow run."""
        async with self._get_client() as client:
            response = await client.get_item(
                TableName=self.table_name,
                Key={
                    "PK": {"S": f"CANCEL#{run_id}"},
                    "SK": {"S": "#FLAG"},
                },
            )

            return "Item" in response

    async def clear_cancellation_flag(self, run_id: str) -> None:
        """Clear the cancellation flag for a workflow run."""
        async with self._get_client() as client:
            await client.delete_item(
                TableName=self.table_name,
                Key={
                    "PK": {"S": f"CANCEL#{run_id}"},
                    "SK": {"S": "#FLAG"},
                },
            )

    # Continue-As-New Chain Operations

    async def update_run_continuation(
        self,
        run_id: str,
        continued_to_run_id: str,
    ) -> None:
        """Update the continuation link for a workflow run."""
        async with self._get_client() as client:
            await client.update_item(
                TableName=self.table_name,
                Key={
                    "PK": {"S": f"RUN#{run_id}"},
                    "SK": {"S": "#METADATA"},
                },
                UpdateExpression="SET continued_to_run_id = :ctr, updated_at = :now",
                ExpressionAttributeValues={
                    ":ctr": {"S": continued_to_run_id},
                    ":now": {"S": datetime.now(UTC).isoformat()},
                },
            )

    async def get_workflow_chain(
        self,
        run_id: str,
    ) -> list[WorkflowRun]:
        """Get all runs in a continue-as-new chain."""
        # Find the first run in the chain
        current_id: str | None = run_id
        while current_id:
            run = await self.get_run(current_id)
            if not run or not run.continued_from_run_id:
                break
            current_id = run.continued_from_run_id

        # Now collect all runs in the chain from first to last
        runs = []
        while current_id:
            run = await self.get_run(current_id)
            if not run:
                break
            runs.append(run)
            current_id = run.continued_to_run_id

        return runs

    # Child Workflow Operations

    async def get_children(
        self,
        parent_run_id: str,
        status: RunStatus | None = None,
    ) -> list[WorkflowRun]:
        """Get all child workflow runs for a parent workflow."""
        async with self._get_client() as client:
            params: dict[str, Any] = {
                "TableName": self.table_name,
                "IndexName": "GSI4",
                "KeyConditionExpression": "GSI4PK = :pk",
                "ExpressionAttributeValues": {":pk": {"S": f"PARENT#{parent_run_id}"}},
            }

            if status:
                params["FilterExpression"] = "#status = :status"
                params["ExpressionAttributeNames"] = {"#status": "status"}
                params["ExpressionAttributeValues"][":status"] = {"S": status.value}

            response = await client.query(**params)
            items = response.get("Items", [])

            runs = [self._item_to_workflow_run(self._item_to_dict(item)) for item in items]
            runs.sort(key=lambda r: r.created_at)
            return runs

    async def get_parent(self, run_id: str) -> WorkflowRun | None:
        """Get the parent workflow run for a child workflow."""
        run = await self.get_run(run_id)
        if not run or not run.parent_run_id:
            return None

        return await self.get_run(run.parent_run_id)

    async def get_nesting_depth(self, run_id: str) -> int:
        """Get the nesting depth for a workflow."""
        run = await self.get_run(run_id)
        return run.nesting_depth if run else 0

    # Schedule Operations

    async def create_schedule(self, schedule: Schedule) -> None:
        """Create a new schedule record."""
        async with self._get_client() as client:
            spec_value = schedule.spec.cron or schedule.spec.interval or ""
            spec_type = "cron" if schedule.spec.cron else "interval"
            timezone = schedule.spec.timezone

            item = {
                "PK": f"SCHEDULE#{schedule.schedule_id}",
                "SK": "#METADATA",
                "entity_type": "schedule",
                "schedule_id": schedule.schedule_id,
                "workflow_name": schedule.workflow_name,
                "spec": spec_value,
                "spec_type": spec_type,
                "timezone": timezone,
                "input_args": schedule.args,
                "input_kwargs": schedule.kwargs,
                "status": schedule.status.value,
                "overlap_policy": schedule.overlap_policy.value,
                "next_run_time": schedule.next_run_time.isoformat()
                if schedule.next_run_time
                else None,
                "last_run_at": schedule.last_run_at.isoformat() if schedule.last_run_at else None,
                "running_run_ids": json.dumps(schedule.running_run_ids),
                "created_at": schedule.created_at.isoformat(),
                "updated_at": schedule.updated_at.isoformat()
                if schedule.updated_at
                else datetime.now(UTC).isoformat(),
                # GSI keys
                "GSI1PK": "SCHEDULES",
                "GSI1SK": f"{schedule.status.value}#{schedule.created_at.isoformat()}",
                "GSI2PK": f"WORKFLOW#{schedule.workflow_name}",
                "GSI2SK": schedule.created_at.isoformat(),
            }

            # Add active schedules GSI for due schedule queries
            if schedule.status == ScheduleStatus.ACTIVE and schedule.next_run_time:
                item["GSI5PK"] = "ACTIVE_SCHEDULES"
                item["GSI5SK"] = schedule.next_run_time.isoformat()

            await client.put_item(
                TableName=self.table_name,
                Item=self._dict_to_item(item),
            )

    async def get_schedule(self, schedule_id: str) -> Schedule | None:
        """Retrieve a schedule by ID."""
        async with self._get_client() as client:
            response = await client.get_item(
                TableName=self.table_name,
                Key={
                    "PK": {"S": f"SCHEDULE#{schedule_id}"},
                    "SK": {"S": "#METADATA"},
                },
            )

            item = response.get("Item")
            if not item:
                return None

            return self._item_to_schedule(self._item_to_dict(item))

    async def update_schedule(self, schedule: Schedule) -> None:
        """Update an existing schedule."""
        async with self._get_client() as client:
            spec_value = schedule.spec.cron or schedule.spec.interval or ""
            spec_type = "cron" if schedule.spec.cron else "interval"
            timezone = schedule.spec.timezone
            now = datetime.now(UTC)

            item = {
                "PK": f"SCHEDULE#{schedule.schedule_id}",
                "SK": "#METADATA",
                "entity_type": "schedule",
                "schedule_id": schedule.schedule_id,
                "workflow_name": schedule.workflow_name,
                "spec": spec_value,
                "spec_type": spec_type,
                "timezone": timezone,
                "input_args": schedule.args,
                "input_kwargs": schedule.kwargs,
                "status": schedule.status.value,
                "overlap_policy": schedule.overlap_policy.value,
                "next_run_time": schedule.next_run_time.isoformat()
                if schedule.next_run_time
                else None,
                "last_run_at": schedule.last_run_at.isoformat() if schedule.last_run_at else None,
                "running_run_ids": json.dumps(schedule.running_run_ids),
                "created_at": schedule.created_at.isoformat(),
                "updated_at": schedule.updated_at.isoformat()
                if schedule.updated_at
                else now.isoformat(),
                # GSI keys
                "GSI1PK": "SCHEDULES",
                "GSI1SK": f"{schedule.status.value}#{schedule.created_at.isoformat()}",
                "GSI2PK": f"WORKFLOW#{schedule.workflow_name}",
                "GSI2SK": schedule.created_at.isoformat(),
            }

            # Add active schedules GSI for due schedule queries
            if schedule.status == ScheduleStatus.ACTIVE and schedule.next_run_time:
                item["GSI5PK"] = "ACTIVE_SCHEDULES"
                item["GSI5SK"] = schedule.next_run_time.isoformat()

            await client.put_item(
                TableName=self.table_name,
                Item=self._dict_to_item(item),
            )

    async def delete_schedule(self, schedule_id: str) -> None:
        """Mark a schedule as deleted (soft delete)."""
        schedule = await self.get_schedule(schedule_id)
        if not schedule:
            return

        schedule.status = ScheduleStatus.DELETED
        schedule.updated_at = datetime.now(UTC)
        await self.update_schedule(schedule)

    async def list_schedules(
        self,
        workflow_name: str | None = None,
        status: ScheduleStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Schedule]:
        """List schedules with optional filtering."""
        async with self._get_client() as client:
            if workflow_name:
                # Use GSI2 for workflow_name queries
                params: dict[str, Any] = {
                    "TableName": self.table_name,
                    "IndexName": "GSI2",
                    "KeyConditionExpression": "GSI2PK = :pk",
                    "ExpressionAttributeValues": {":pk": {"S": f"WORKFLOW#{workflow_name}"}},
                    "Limit": limit + offset,
                    "ScanIndexForward": False,
                }

                if status:
                    params["FilterExpression"] = "#status = :status"
                    params["ExpressionAttributeNames"] = {"#status": "status"}
                    params["ExpressionAttributeValues"][":status"] = {"S": status.value}

                response = await client.query(**params)
            elif status:
                # Use GSI1 for status queries
                params = {
                    "TableName": self.table_name,
                    "IndexName": "GSI1",
                    "KeyConditionExpression": "GSI1PK = :pk AND begins_with(GSI1SK, :status)",
                    "ExpressionAttributeValues": {
                        ":pk": {"S": "SCHEDULES"},
                        ":status": {"S": f"{status.value}#"},
                    },
                    "Limit": limit + offset,
                    "ScanIndexForward": False,
                }

                response = await client.query(**params)
            else:
                # Query all schedules
                params = {
                    "TableName": self.table_name,
                    "IndexName": "GSI1",
                    "KeyConditionExpression": "GSI1PK = :pk",
                    "ExpressionAttributeValues": {":pk": {"S": "SCHEDULES"}},
                    "Limit": limit + offset,
                    "ScanIndexForward": False,
                }

                response = await client.query(**params)

            items = response.get("Items", [])

            # Apply offset
            items = items[offset : offset + limit]

            return [self._item_to_schedule(self._item_to_dict(item)) for item in items]

    async def get_due_schedules(self, now: datetime) -> list[Schedule]:
        """Get all schedules that are due to run."""
        async with self._get_client() as client:
            response = await client.query(
                TableName=self.table_name,
                IndexName="GSI5",
                KeyConditionExpression="GSI5PK = :pk AND GSI5SK <= :now",
                ExpressionAttributeValues={
                    ":pk": {"S": "ACTIVE_SCHEDULES"},
                    ":now": {"S": now.isoformat()},
                },
            )

            items = response.get("Items", [])
            schedules = [self._item_to_schedule(self._item_to_dict(item)) for item in items]

            # Sort by next_run_time
            schedules.sort(key=lambda s: s.next_run_time or datetime.min.replace(tzinfo=UTC))
            return schedules

    async def add_running_run(self, schedule_id: str, run_id: str) -> None:
        """Add a run_id to the schedule's running_run_ids list."""
        schedule = await self.get_schedule(schedule_id)
        if not schedule:
            raise ValueError(f"Schedule {schedule_id} not found")

        if run_id not in schedule.running_run_ids:
            schedule.running_run_ids.append(run_id)
            schedule.updated_at = datetime.now(UTC)
            await self.update_schedule(schedule)

    async def remove_running_run(self, schedule_id: str, run_id: str) -> None:
        """Remove a run_id from the schedule's running_run_ids list."""
        schedule = await self.get_schedule(schedule_id)
        if not schedule:
            raise ValueError(f"Schedule {schedule_id} not found")

        if run_id in schedule.running_run_ids:
            schedule.running_run_ids.remove(run_id)
            schedule.updated_at = datetime.now(UTC)
            await self.update_schedule(schedule)

    # Helper methods for converting DynamoDB items to domain objects

    def _item_to_workflow_run(self, item: dict[str, Any]) -> WorkflowRun:
        """Convert DynamoDB item to WorkflowRun object."""
        return WorkflowRun(
            run_id=item["run_id"],
            workflow_name=item["workflow_name"],
            status=RunStatus(item["status"]),
            created_at=datetime.fromisoformat(item["created_at"]),
            updated_at=datetime.fromisoformat(item["updated_at"]),
            started_at=datetime.fromisoformat(item["started_at"])
            if item.get("started_at")
            else None,
            completed_at=datetime.fromisoformat(item["completed_at"])
            if item.get("completed_at")
            else None,
            input_args=item.get("input_args", "[]"),
            input_kwargs=item.get("input_kwargs", "{}"),
            result=item.get("result"),
            error=item.get("error"),
            idempotency_key=item.get("idempotency_key"),
            max_duration=item.get("max_duration"),
            # Support both 'context' (new) and 'metadata' (legacy) keys
            context=json.loads(item.get("context", item.get("metadata", "{}"))),
            recovery_attempts=item.get("recovery_attempts", 0),
            max_recovery_attempts=item.get("max_recovery_attempts", 3),
            recover_on_worker_loss=item.get("recover_on_worker_loss", True),
            parent_run_id=item.get("parent_run_id"),
            nesting_depth=item.get("nesting_depth", 0),
            continued_from_run_id=item.get("continued_from_run_id"),
            continued_to_run_id=item.get("continued_to_run_id"),
        )

    def _item_to_event(self, item: dict[str, Any]) -> Event:
        """Convert DynamoDB item to Event object."""
        return Event(
            event_id=item["event_id"],
            run_id=item["run_id"],
            sequence=item.get("sequence", 0),
            type=EventType(item["type"]),
            timestamp=datetime.fromisoformat(item["timestamp"]),
            data=json.loads(item.get("data", "{}")),
        )

    def _item_to_step_execution(self, item: dict[str, Any]) -> StepExecution:
        """Convert DynamoDB item to StepExecution object."""
        retry_count = item.get("retry_count", 0)
        return StepExecution(
            step_id=item["step_id"],
            run_id=item["run_id"],
            step_name=item["step_name"],
            status=StepStatus(item["status"]),
            created_at=datetime.fromisoformat(item["created_at"]),
            started_at=datetime.fromisoformat(item["started_at"])
            if item.get("started_at")
            else None,
            completed_at=datetime.fromisoformat(item["completed_at"])
            if item.get("completed_at")
            else None,
            input_args=item.get("input_args", "[]"),
            input_kwargs=item.get("input_kwargs", "{}"),
            result=item.get("result"),
            error=item.get("error"),
            attempt=retry_count + 1,
        )

    def _item_to_hook(self, item: dict[str, Any]) -> Hook:
        """Convert DynamoDB item to Hook object."""
        return Hook(
            hook_id=item["hook_id"],
            run_id=item["run_id"],
            token=item["token"],
            created_at=datetime.fromisoformat(item["created_at"]),
            received_at=datetime.fromisoformat(item["received_at"])
            if item.get("received_at")
            else None,
            expires_at=datetime.fromisoformat(item["expires_at"])
            if item.get("expires_at")
            else None,
            status=HookStatus(item["status"]),
            payload=item.get("payload"),
            metadata=json.loads(item.get("metadata", "{}")),
        )

    def _item_to_schedule(self, item: dict[str, Any]) -> Schedule:
        """Convert DynamoDB item to Schedule object."""
        spec_value = item.get("spec", "")
        spec_type = item.get("spec_type", "interval")
        timezone = item.get("timezone", "UTC")

        if spec_type == "cron":
            spec = ScheduleSpec(cron=spec_value, timezone=timezone)
        else:
            spec = ScheduleSpec(interval=spec_value, timezone=timezone)

        return Schedule(
            schedule_id=item["schedule_id"],
            workflow_name=item["workflow_name"],
            spec=spec,
            status=ScheduleStatus(item["status"]),
            args=item.get("input_args", "[]"),
            kwargs=item.get("input_kwargs", "{}"),
            overlap_policy=OverlapPolicy(item.get("overlap_policy", "skip")),
            created_at=datetime.fromisoformat(item["created_at"]),
            updated_at=datetime.fromisoformat(item["updated_at"])
            if item.get("updated_at")
            else None,
            last_run_at=datetime.fromisoformat(item["last_run_at"])
            if item.get("last_run_at")
            else None,
            next_run_time=datetime.fromisoformat(item["next_run_time"])
            if item.get("next_run_time")
            else None,
            running_run_ids=json.loads(item.get("running_run_ids", "[]")),
        )
