"""Hook management commands."""

import json
from typing import Any

import click
from InquirerPy import inquirer

from pyworkflow.cli.output.formatters import (
    format_json,
    format_key_value,
    format_plain,
    format_table,
    print_breadcrumb,
    print_error,
    print_info,
    print_success,
)
from pyworkflow.cli.output.styles import (
    DIM,
    PYWORKFLOW_STYLE,
    RESET,
    SYMBOLS,
    Colors,
)
from pyworkflow.cli.utils.async_helpers import async_command
from pyworkflow.cli.utils.storage import create_storage
from pyworkflow.storage.schemas import HookStatus


@click.group(name="hooks")
def hooks() -> None:
    """Manage hooks (list, info, resume)."""
    pass


def _build_hook_choices(hooks_list: list[Any]) -> list[dict[str, str]]:
    """Build choices list for hook selection."""
    choices = []
    for hook in hooks_list:
        name = hook.name or hook.hook_id
        display = f"{name} - {hook.run_id}"
        if hook.expires_at:
            display += f" (expires: {hook.expires_at.strftime('%Y-%m-%d %H:%M')})"
        choices.append({"name": display, "value": hook.token})
    return choices


async def _select_pending_hook_async(storage: Any) -> str | None:
    """
    Display an interactive menu to select a pending hook.

    Args:
        storage: Storage backend

    Returns:
        Selected hook token or None if cancelled
    """
    hooks_list = await storage.list_hooks(status=HookStatus.PENDING)

    if not hooks_list:
        print_info("No pending hooks found")
        return None

    choices = _build_hook_choices(hooks_list)

    try:
        result = await inquirer.select(  # type: ignore[func-returns-value]
            message="Select hook to resume",
            choices=choices,
            style=PYWORKFLOW_STYLE,
            pointer=SYMBOLS["pointer"],
            qmark="?",
            amark=SYMBOLS["success"],
        ).execute_async()
        return result
    except KeyboardInterrupt:
        print(f"\n{DIM}Cancelled{RESET}")
        return None


async def _prompt_for_payload_async(hook: Any) -> dict[str, Any]:
    """
    Interactively prompt for payload fields based on hook's schema.

    Args:
        hook: Hook object with optional payload_schema

    Returns:
        Dictionary of field values
    """
    # If no schema, prompt for raw JSON
    if not hook.payload_schema:
        try:
            raw = await inquirer.text(  # type: ignore[func-returns-value]
                message="Enter payload (JSON)",
                default="{}",
                style=PYWORKFLOW_STYLE,
                qmark="?",
                amark=SYMBOLS["success"],
            ).execute_async()
            return json.loads(raw) if raw else {}
        except KeyboardInterrupt:
            print(f"\n{DIM}Cancelled{RESET}")
            raise click.Abort()

    # Parse JSON schema
    schema = json.loads(hook.payload_schema)
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    payload: dict[str, Any] = {}

    for field_name, field_schema in properties.items():
        field_type = field_schema.get("type", "string")
        default = field_schema.get("default")
        is_required = field_name in required

        # Build instruction text
        if is_required:
            instruction = f"({field_type}, required)"
        else:
            default_display = repr(default) if default is not None else "None"
            instruction = f"({field_type}, default={default_display})"

        try:
            # Handle boolean type with confirm prompt
            if field_type == "boolean":
                default_val = default if default is not None else False
                value = await inquirer.confirm(  # type: ignore[func-returns-value]
                    message=field_name,
                    default=default_val,
                    style=PYWORKFLOW_STYLE,
                    qmark="?",
                    amark=SYMBOLS["success"],
                    instruction=instruction,
                ).execute_async()
                payload[field_name] = value

            # Handle integer type with number prompt
            elif field_type == "integer":
                default_val = default if default is not None else None
                value = await inquirer.number(  # type: ignore[func-returns-value]
                    message=field_name,
                    default=default_val,
                    style=PYWORKFLOW_STYLE,
                    qmark="?",
                    amark=SYMBOLS["success"],
                    instruction=instruction,
                    float_allowed=False,
                ).execute_async()
                if value is not None:
                    payload[field_name] = int(value)
                elif default is not None:
                    payload[field_name] = default

            # Handle number/float type with number prompt
            elif field_type == "number":
                default_val = default if default is not None else None
                value = await inquirer.number(  # type: ignore[func-returns-value]
                    message=field_name,
                    default=default_val,
                    style=PYWORKFLOW_STYLE,
                    qmark="?",
                    amark=SYMBOLS["success"],
                    instruction=instruction,
                    float_allowed=True,
                ).execute_async()
                if value is not None:
                    payload[field_name] = float(value)
                elif default is not None:
                    payload[field_name] = default

            # Handle string/object/array types with text prompt
            else:
                if default is not None:
                    default_str = json.dumps(default) if not isinstance(default, str) else default
                else:
                    default_str = ""

                value_str = await inquirer.text(  # type: ignore[func-returns-value]
                    message=field_name,
                    default=default_str,
                    style=PYWORKFLOW_STYLE,
                    qmark="?",
                    amark=SYMBOLS["success"],
                    instruction=instruction,
                    mandatory=is_required,
                ).execute_async()

                if value_str == "" and default is not None:
                    payload[field_name] = default
                elif value_str == "" and not is_required:
                    continue  # Skip optional fields with no input
                elif value_str:
                    # Try JSON parse for complex types
                    if field_type in ("object", "array"):
                        try:
                            payload[field_name] = json.loads(value_str)
                        except json.JSONDecodeError:
                            payload[field_name] = value_str
                    else:
                        payload[field_name] = value_str

        except KeyboardInterrupt:
            print(f"\n{DIM}Cancelled{RESET}")
            raise click.Abort()

    return payload


@hooks.command(name="list")
@click.option(
    "--run-id",
    help="Filter by workflow run ID",
)
@click.option(
    "--status",
    type=click.Choice([s.value for s in HookStatus], case_sensitive=False),
    help="Filter by hook status",
)
@click.option(
    "--limit",
    type=int,
    default=20,
    help="Maximum number of hooks to display (default: 20)",
)
@click.pass_context
@async_command
async def list_hooks_cmd(
    ctx: click.Context,
    run_id: str | None,
    status: str | None,
    limit: int,
) -> None:
    """
    List hooks.

    Examples:

        # List all hooks
        pyworkflow hooks list

        # List pending hooks only
        pyworkflow hooks list --status pending

        # List hooks for specific workflow run
        pyworkflow hooks list --run-id run_abc123
    """
    # Get context data
    config = ctx.obj["config"]
    output = ctx.obj["output"]
    storage_type = ctx.obj["storage_type"]
    storage_path = ctx.obj["storage_path"]

    # Create storage backend
    storage = create_storage(storage_type, storage_path, config)

    # Parse status filter
    status_filter = HookStatus(status) if status else None

    # List hooks
    try:
        hooks_list = await storage.list_hooks(
            run_id=run_id,
            status=status_filter,
            limit=limit,
        )

        if not hooks_list:
            print_info("No hooks found")
            return

        # Format output
        if output == "json":
            data = [
                {
                    "token": hook.token,
                    "hook_id": hook.hook_id,
                    "run_id": hook.run_id,
                    "name": hook.name,
                    "status": hook.status.value,
                    "created_at": hook.created_at.isoformat() if hook.created_at else None,
                    "expires_at": hook.expires_at.isoformat() if hook.expires_at else None,
                    "has_schema": hook.payload_schema is not None,
                }
                for hook in hooks_list
            ]
            format_json(data)

        elif output == "plain":
            tokens = [hook.token for hook in hooks_list]
            format_plain(tokens)

        else:  # table
            data = [
                {
                    "Token": hook.token,
                    "Name": hook.name or "-",
                    "Status": hook.status.value,
                    "Run ID": hook.run_id,
                    "Created": hook.created_at.strftime("%Y-%m-%d %H:%M")
                    if hook.created_at
                    else "-",
                    "Expires": hook.expires_at.strftime("%Y-%m-%d %H:%M")
                    if hook.expires_at
                    else "-",
                }
                for hook in hooks_list
            ]
            format_table(
                data,
                ["Token", "Name", "Status", "Run ID", "Created", "Expires"],
                title="Hooks",
            )

    except Exception as e:
        print_error(f"Failed to list hooks: {e}")
        if ctx.obj["verbose"]:
            raise
        raise click.Abort()


@hooks.command(name="info")
@click.argument("token")
@click.pass_context
@async_command
async def hook_info_cmd(ctx: click.Context, token: str) -> None:
    """
    Show hook details.

    Args:
        TOKEN: Hook token (format: run_id:hook_id)

    Examples:

        pyworkflow hooks info run_abc123:hook_approval_1
    """
    # Get context data
    config = ctx.obj["config"]
    output = ctx.obj["output"]
    storage_type = ctx.obj["storage_type"]
    storage_path = ctx.obj["storage_path"]

    # Create storage backend
    storage = create_storage(storage_type, storage_path, config)

    # Get hook by token
    try:
        hook = await storage.get_hook_by_token(token)

        if not hook:
            print_error(f"Hook not found: {token}")
            raise click.Abort()

        # Format output
        if output == "json":
            data = {
                "token": hook.token,
                "hook_id": hook.hook_id,
                "run_id": hook.run_id,
                "name": hook.name,
                "status": hook.status.value,
                "created_at": hook.created_at.isoformat() if hook.created_at else None,
                "expires_at": hook.expires_at.isoformat() if hook.expires_at else None,
                "received_at": hook.received_at.isoformat() if hook.received_at else None,
                "payload": json.loads(hook.payload) if hook.payload else None,
                "payload_schema": json.loads(hook.payload_schema) if hook.payload_schema else None,
            }
            format_json(data)

        else:  # table or plain (use key-value format)
            data = {
                "Token": hook.token,
                "Hook ID": hook.hook_id,
                "Run ID": hook.run_id,
                "Name": hook.name or "-",
                "Status": hook.status.value,
                "Created": hook.created_at.strftime("%Y-%m-%d %H:%M:%S")
                if hook.created_at
                else "-",
                "Expires": hook.expires_at.strftime("%Y-%m-%d %H:%M:%S")
                if hook.expires_at
                else "-",
                "Received": hook.received_at.strftime("%Y-%m-%d %H:%M:%S")
                if hook.received_at
                else "-",
            }

            # Show payload if received
            if hook.payload:
                try:
                    payload = json.loads(hook.payload)
                    data["Payload"] = json.dumps(payload, indent=2)
                except json.JSONDecodeError:
                    data["Payload"] = hook.payload

            # Show schema summary if available
            if hook.payload_schema:
                try:
                    schema = json.loads(hook.payload_schema)
                    fields = list(schema.get("properties", {}).keys())
                    required = schema.get("required", [])
                    data["Schema Fields"] = ", ".join(
                        f"{f}*" if f in required else f for f in fields
                    )
                except json.JSONDecodeError:
                    data["Schema Fields"] = "Invalid schema"

            format_key_value(data, title=f"Hook: {token}")

    except click.Abort:
        raise
    except Exception as e:
        print_error(f"Failed to get hook info: {e}")
        if ctx.obj["verbose"]:
            raise
        raise click.Abort()


@hooks.command(name="run")
@click.argument("run_id")
@click.pass_context
@async_command
async def hooks_by_run_cmd(ctx: click.Context, run_id: str) -> None:
    """
    Show all hooks for a specific workflow run.

    Args:
        RUN_ID: Workflow run ID

    Examples:

        pyworkflow hooks run run_9b7d9218ebe341ca
    """
    # Get context data
    config = ctx.obj["config"]
    output = ctx.obj["output"]
    storage_type = ctx.obj["storage_type"]
    storage_path = ctx.obj["storage_path"]

    # Create storage backend
    storage = create_storage(storage_type, storage_path, config)

    try:
        # Get all hooks for this run
        hooks_list = await storage.list_hooks(run_id=run_id)

        if not hooks_list:
            print_info(f"No hooks found for run: {run_id}")
            return

        # Format output
        if output == "json":
            data = {
                "run_id": run_id,
                "hook_count": len(hooks_list),
                "hooks": [
                    {
                        "token": hook.token,
                        "hook_id": hook.hook_id,
                        "name": hook.name,
                        "status": hook.status.value,
                        "created_at": hook.created_at.isoformat() if hook.created_at else None,
                        "expires_at": hook.expires_at.isoformat() if hook.expires_at else None,
                        "received_at": hook.received_at.isoformat() if hook.received_at else None,
                        "payload": json.loads(hook.payload) if hook.payload else None,
                        "has_schema": hook.payload_schema is not None,
                    }
                    for hook in hooks_list
                ],
            }
            format_json(data)

        else:  # table or plain
            print(f"\n{Colors.PRIMARY}{Colors.bold(f'Hooks for Run: {run_id}')}{RESET}")
            print(f"{DIM}{'─' * 60}{RESET}")
            print(f"Total hooks: {len(hooks_list)}\n")

            for i, hook in enumerate(hooks_list, 1):
                # Status color
                status_color = {
                    "pending": Colors.YELLOW,
                    "received": Colors.GREEN,
                    "expired": Colors.RED,
                    "disposed": Colors.GRAY,
                }.get(hook.status.value, "")

                print(f"{Colors.bold(f'{i}. {hook.name or hook.hook_id}')}")
                print(f"   Token: {hook.token}")
                print(f"   Status: {status_color}{hook.status.value}{RESET}")
                print(
                    f"   Created: {hook.created_at.strftime('%Y-%m-%d %H:%M:%S') if hook.created_at else '-'}"
                )

                if hook.expires_at:
                    print(f"   Expires: {hook.expires_at.strftime('%Y-%m-%d %H:%M:%S')}")

                if hook.received_at:
                    print(f"   Received: {hook.received_at.strftime('%Y-%m-%d %H:%M:%S')}")

                # Show payload if received
                if hook.payload:
                    try:
                        payload = json.loads(hook.payload)
                        print(f"   Payload: {json.dumps(payload)}")
                    except json.JSONDecodeError:
                        print(f"   Payload: {hook.payload}")

                # Show schema fields if available
                if hook.payload_schema:
                    try:
                        schema = json.loads(hook.payload_schema)
                        fields = list(schema.get("properties", {}).keys())
                        required = schema.get("required", [])
                        fields_str = ", ".join(f"{f}*" if f in required else f for f in fields)
                        print(f"   Schema: {fields_str}")
                    except json.JSONDecodeError:
                        pass

                print()  # Blank line between hooks

    except Exception as e:
        print_error(f"Failed to get hooks for run: {e}")
        if ctx.obj["verbose"]:
            raise
        raise click.Abort()


@hooks.command(name="resume")
@click.argument("token", required=False)
@click.option(
    "--payload",
    "-p",
    help="JSON payload to send (skip interactive prompt)",
)
@click.option(
    "--payload-file",
    "-f",
    type=click.Path(exists=True),
    help="Read payload from JSON file",
)
@click.pass_context
@async_command
async def resume_hook_cmd(
    ctx: click.Context,
    token: str | None,
    payload: str | None,
    payload_file: str | None,
) -> None:
    """
    Resume a pending hook with payload.

    When run without arguments, displays an interactive flow:
    1. Select a pending hook from the list
    2. Enter values for each payload field (based on schema)

    Args:
        TOKEN: Hook token (optional, will prompt if not provided)

    Examples:

        # Interactive mode - select hook and enter payload
        pyworkflow hooks resume

        # Direct mode with inline payload
        pyworkflow hooks resume run_abc123:hook_approval_1 --payload '{"approved": true}'

        # Direct mode with payload from file
        pyworkflow hooks resume run_abc123:hook_approval_1 --payload-file payload.json
    """
    # Get context data
    config = ctx.obj["config"]
    output = ctx.obj["output"]
    storage_type = ctx.obj["storage_type"]
    storage_path = ctx.obj["storage_path"]

    # Create storage backend
    storage = create_storage(storage_type, storage_path, config)

    try:
        # Step 1: Select hook if not provided
        if not token:
            print_breadcrumb(["hook", "payload"], 0)
            token = await _select_pending_hook_async(storage)
            if not token:
                raise click.Abort()

        # Get hook details (for schema)
        hook = await storage.get_hook_by_token(token)
        if not hook:
            print_error(f"Hook not found: {token}")
            raise click.Abort()

        if hook.status != HookStatus.PENDING:
            print_error(f"Hook is not pending (status: {hook.status.value})")
            raise click.Abort()

        # Step 2: Get payload
        if payload_file:
            with open(payload_file) as f:
                payload_data = json.load(f)
        elif payload:
            try:
                payload_data = json.loads(payload)
            except json.JSONDecodeError as e:
                print_error(f"Invalid JSON payload: {e}")
                raise click.Abort()
        else:
            # Interactive mode - prompt for payload fields
            print_breadcrumb(["hook", "payload"], 1)
            payload_data = await _prompt_for_payload_async(hook)
            print()  # Add spacing after prompts

        # Resume the hook
        from pyworkflow.primitives.resume_hook import resume_hook

        result = await resume_hook(token, payload_data, storage=storage)

        # Output result
        if output == "json":
            format_json(
                {
                    "run_id": result.run_id,
                    "hook_id": result.hook_id,
                    "status": result.status,
                }
            )
        else:
            print_success(f"Hook resumed: {result.hook_id}")
            print_info(f"Run ID: {result.run_id}")
            print_info(f"Payload: {json.dumps(payload_data)}")

    except click.Abort:
        raise
    except Exception as e:
        print_error(f"Failed to resume hook: {e}")
        if ctx.obj["verbose"]:
            raise
        raise click.Abort()
