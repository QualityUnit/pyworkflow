"""
Celery Durable Workflow - Dynamic Code Execution Example

This example demonstrates executing dynamically generated workflow code
on distributed Celery workers.

Dynamic workflows are ideal for:
- No-code workflow builders that generate Python at runtime
- AI agents that write workflow code
- Template-based workflow generation
- Multi-tenant workflow customization

The workflow_code parameter allows sending Python source code that gets
executed on workers, enabling truly dynamic workflow creation.

Prerequisites:
    1. Start Redis: docker run -d -p 6379:6379 redis:7-alpine
    2. Start worker: pyworkflow --module examples.celery.durable.workflows.dynamic_workflows worker run

Run with CLI:
    pyworkflow --module examples.celery.durable.workflows.dynamic_workflows workflows run dynamic_data_pipeline \\
        --arg source=api --arg destination=warehouse

Check status:
    pyworkflow runs list
    pyworkflow runs status <run_id>
"""

from pyworkflow import step, workflow


# --- Pre-defined steps that dynamic workflows can use ---
@step(name="dyn_fetch_data")
async def fetch_data(source: str) -> dict:
    """Fetch data from a source."""
    print(f"[Step] Fetching data from {source}...")
    return {"source": source, "records": 100, "data": ["item1", "item2", "item3"]}


@step(name="dyn_transform_data")
async def transform_data(data: dict) -> dict:
    """Transform the fetched data."""
    print(f"[Step] Transforming {data['records']} records...")
    return {**data, "transformed": True, "records": len(data.get("data", []))}


@step(name="dyn_validate_data")
async def validate_data(data: dict) -> dict:
    """Validate the transformed data."""
    print(f"[Step] Validating data...")
    is_valid = data.get("records", 0) > 0 and data.get("transformed", False)
    return {**data, "valid": is_valid}


@step(name="dyn_load_data")
async def load_data(data: dict, destination: str) -> dict:
    """Load data to destination."""
    print(f"[Step] Loading {data['records']} records to {destination}...")
    return {**data, "destination": destination, "loaded": True}


# --- Pre-defined workflow that uses steps ---
@workflow(tags=["celery", "durable", "dynamic"])
async def dynamic_data_pipeline(source: str, destination: str) -> dict:
    """
    Data pipeline workflow that can be customized dynamically.

    This workflow demonstrates a typical ETL pattern:
    1. Fetch data from source
    2. Transform the data
    3. Validate the transformed data
    4. Load data to destination

    In a real application, the workflow code could be generated
    dynamically based on user configuration.
    """
    data = await fetch_data(source)
    data = await transform_data(data)
    data = await validate_data(data)
    result = await load_data(data, destination)
    return result


# --- Example dynamic workflow code templates ---

# Template 1: Simple data processing
SIMPLE_PROCESSING_TEMPLATE = '''
@workflow(name="dynamic_simple_process")
async def dynamic_simple_process(input_value: str):
    """Dynamically generated simple processing workflow."""
    result = input_value.upper()
    return {"processed": result}
'''

# Template 2: Conditional processing based on data type
CONDITIONAL_PROCESSING_TEMPLATE = '''
@step(name="dynamic_detect_type")
async def dynamic_detect_type(data: str) -> str:
    """Detect the type of input data."""
    if data.isdigit():
        return "numeric"
    elif data.isalpha():
        return "text"
    else:
        return "mixed"

@step(name="dynamic_process_numeric")
async def dynamic_process_numeric(data: str) -> dict:
    """Process numeric data."""
    return {"type": "numeric", "value": int(data), "squared": int(data) ** 2}

@step(name="dynamic_process_text")
async def dynamic_process_text(data: str) -> dict:
    """Process text data."""
    return {"type": "text", "value": data, "upper": data.upper(), "length": len(data)}

@step(name="dynamic_process_mixed")
async def dynamic_process_mixed(data: str) -> dict:
    """Process mixed data."""
    return {"type": "mixed", "value": data, "cleaned": "".join(c for c in data if c.isalnum())}

@workflow(name="dynamic_conditional_process")
async def dynamic_conditional_process(data: str):
    """Conditionally process data based on its type."""
    data_type = await dynamic_detect_type(data)

    if data_type == "numeric":
        result = await dynamic_process_numeric(data)
    elif data_type == "text":
        result = await dynamic_process_text(data)
    else:
        result = await dynamic_process_mixed(data)

    return result
'''

# Template 3: Parallel-style processing with multiple steps
BATCH_PROCESSING_TEMPLATE = '''
@step(name="dynamic_chunk")
async def dynamic_chunk(data: list, chunk_size: int) -> list:
    """Split data into chunks."""
    return [data[i:i + chunk_size] for i in range(0, len(data), chunk_size)]

@step(name="dynamic_process_chunk")
async def dynamic_process_chunk(chunk: list) -> list:
    """Process a single chunk."""
    return [item.upper() if isinstance(item, str) else item for item in chunk]

@step(name="dynamic_merge")
async def dynamic_merge(chunks: list) -> list:
    """Merge processed chunks."""
    result = []
    for chunk in chunks:
        result.extend(chunk)
    return result

@workflow(name="dynamic_batch_process")
async def dynamic_batch_process(data: list, chunk_size: int = 2):
    """Process data in batches."""
    chunks = await dynamic_chunk(data, chunk_size)

    processed_chunks = []
    for chunk in chunks:
        processed = await dynamic_process_chunk(chunk)
        processed_chunks.append(processed)

    result = await dynamic_merge(processed_chunks)
    return result
'''


def get_workflow_templates() -> dict:
    """Get available dynamic workflow templates."""
    return {
        "simple": SIMPLE_PROCESSING_TEMPLATE,
        "conditional": CONDITIONAL_PROCESSING_TEMPLATE,
        "batch": BATCH_PROCESSING_TEMPLATE,
    }


async def main() -> None:
    """Run the dynamic workflow example."""
    import argparse

    import pyworkflow

    parser = argparse.ArgumentParser(description="Dynamic Data Pipeline Workflow")
    parser.add_argument("--source", default="api", help="Data source")
    parser.add_argument("--destination", default="warehouse", help="Data destination")
    args = parser.parse_args()

    print(f"Starting dynamic data pipeline: {args.source} -> {args.destination}")
    run_id = await pyworkflow.start(dynamic_data_pipeline, args.source, args.destination)
    print(f"Workflow started with run_id: {run_id}")
    print(f"\nCheck status: pyworkflow runs status {run_id}")

    print("\n--- Available Dynamic Workflow Templates ---")
    for name, code in get_workflow_templates().items():
        lines = code.strip().split("\n")
        print(f"  {name}: {lines[0][:50]}...")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
