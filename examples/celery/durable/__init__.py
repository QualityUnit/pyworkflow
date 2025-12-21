"""
Celery Durable Workflow Examples

Import all example workflows for use with CLI:
    pyworkflow --module examples.celery.durable worker run
    pyworkflow --module examples.celery.durable workflows list

Note: Individual example files can also be imported directly:
    pyworkflow --module examples.celery.durable.basic_workflow worker run
"""

import importlib
import os
from pathlib import Path

# Dynamically import all workflow modules in this directory
_current_dir = Path(__file__).parent

for file in sorted(_current_dir.glob("*.py")):
    if file.name.startswith("_"):
        continue
    module_name = file.stem
    try:
        importlib.import_module(f".{module_name}", package=__name__)
    except ImportError as e:
        print(f"Warning: Could not import {module_name}: {e}")
