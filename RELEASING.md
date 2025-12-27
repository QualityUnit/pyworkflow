# Release Process

This document describes how to release a new version of PyWorkflow to PyPI.

## Prerequisites

- Maintainer access to the GitHub repository
- PyPI trusted publisher configured (see setup below)
- Clean working directory (all changes committed)

## Release Checklist

### 1. Prepare Release

```bash
# Ensure you're on main branch with latest changes
git checkout main
git pull origin main

# Run full test suite locally
pip install -e ".[dev]"
pytest tests/ -v

# Check code quality
ruff check .
ruff format --check .
mypy pyworkflow
```

### 2. Update Version

Update version in THREE places (must match):

1. **pyproject.toml** (line 7):
   ```toml
   version = "0.2.0"
   ```

2. **pyworkflow/__init__.py** (line 32):
   ```python
   __version__ = "0.2.0"
   ```

3. Commit version bump:
   ```bash
   git add pyproject.toml pyworkflow/__init__.py
   git commit -m "chore: bump version to 0.2.0"
   git push origin main
   ```

### 3. Create Release Tag

```bash
# Create annotated tag
git tag -a v0.2.0 -m "Release v0.2.0"

# Push tag to trigger release workflow
git push origin v0.2.0
```

### 4. Monitor Release Workflow

The GitHub Actions workflow will automatically:

1. ✅ Verify version consistency
2. ✅ Build wheel and sdist
3. ✅ Test installation on Python 3.11, 3.12, 3.13
4. ✅ Run full test suite
5. ✅ Publish to TestPyPI
6. ⏸️ Wait for approval (pypi environment)
7. ✅ Publish to production PyPI
8. ✅ Create GitHub release with artifacts

**Monitor at:** `https://github.com/QualityUnit/pyworkflow/actions`

### 5. Approve Production Release

1. Go to the workflow run
2. Review TestPyPI publication
3. Test installation from TestPyPI:
   ```bash
   pip install --index-url https://test.pypi.org/simple/ \
               --extra-index-url https://pypi.org/simple/ \
               pyworkflow-engine==0.2.0
   ```
4. Click "Review deployments" → Approve `pypi` environment

### 6. Verify Release

```bash
# Wait ~5 minutes for PyPI propagation

# Test installation
pip install pyworkflow-engine==0.2.0
python -c "import pyworkflow; print(pyworkflow.__version__)"

# Test extras
pip install pyworkflow-engine[all]==0.2.0
```

Visit release pages:
- PyPI: https://pypi.org/project/pyworkflow-engine/0.2.0/
- GitHub: https://github.com/QualityUnit/pyworkflow/releases/tag/v0.2.0

---

## Version Numbering

PyWorkflow follows [Semantic Versioning](https://semver.org/):

- **MAJOR** (1.0.0): Breaking changes
- **MINOR** (0.2.0): New features, backward compatible
- **PATCH** (0.1.1): Bug fixes, backward compatible

**Pre-release versions:**
- Alpha: `0.2.0a1`, `0.2.0a2`
- Beta: `0.2.0b1`, `0.2.0b2`
- Release Candidate: `0.2.0rc1`

---

## PyPI Trusted Publishing Setup

**One-time setup** (required before first release):

### Configure PyPI

1. **Production PyPI** (https://pypi.org/manage/account/publishing/):
   - Click "Add a new pending publisher"
   - **PyPI Project Name**: `pyworkflow-engine`
   - **Owner**: `QualityUnit`
   - **Repository**: `pyworkflow`
   - **Workflow name**: `release.yml`
   - **Environment name**: `pypi`

2. **TestPyPI** (https://test.pypi.org/manage/account/publishing/):
   - Same configuration with **Environment name**: `testpypi`

### Configure GitHub Environments

Repository Settings → Environments:

1. **pypi** environment:
   - Required reviewers: Repository maintainers
   - Prevents accidental production releases

2. **testpypi** environment:
   - No restrictions (automatic testing)

**Why Trusted Publishing?**
- No API tokens to manage/rotate
- More secure (OIDC-based, scoped to workflow)
- Recommended by PyPI as best practice

---

## Manual Release (Emergency)

If GitHub Actions fails, manual release:

```bash
# Build package
python -m build

# Check package
twine check dist/*

# Upload to TestPyPI
twine upload --repository testpypi dist/*

# Test from TestPyPI
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ \
            pyworkflow-engine==0.2.0

# Upload to PyPI (CAREFUL!)
twine upload dist/*
```

**Note:** Manual uploads require PyPI API tokens (not recommended).

---

## Troubleshooting

### Version Mismatch Error

```
Version mismatch! pyproject.toml=0.2.0, tag=0.1.9
```

**Fix:** Update version in all three files and recreate tag:
```bash
git tag -d v0.1.9
git push origin :refs/tags/v0.1.9
# Update versions, commit
git tag -a v0.2.0 -m "Release v0.2.0"
git push origin v0.2.0
```

### Package Validation Failed

```
twine check dist/*
```

Common issues:
- Missing README.md
- Invalid RST in long_description
- Missing required metadata

### Test Installation Fails

Check optional dependencies:
```bash
# Should work (core)
pip install pyworkflow-engine

# Should work (extra)
pip install pyworkflow-engine[sqlite]

# Verify imports
python -c "from pyworkflow.storage.file import FileStorageBackend"
```

### Optional Extras Not Working

If optional extras fail to import:
```bash
# Verify the extra was installed
pip show pyworkflow-engine
# Should show dependencies based on extras

# Test specific extras
pip install pyworkflow-engine[postgres]
python -c "from pyworkflow.storage.postgres import PostgresStorageBackend"
```

---

## Post-Release

1. **Update Documentation:**
   - Add release notes to CHANGELOG.md
   - Update version in documentation examples

2. **Announce Release:**
   - GitHub Discussions
   - Project README
   - Social media (if applicable)

3. **Monitor Issues:**
   - Watch for installation issues
   - Check PyPI download stats
   - Monitor GitHub issues

---

## Release History

- **v0.1.0** (TBD): Initial alpha release
  - Core workflow engine
  - File, Memory, SQLite, PostgreSQL storage backends
  - Distributed execution via Celery
  - Event sourcing and auto-recovery
  - Sleep/delay primitives
  - Webhook support
  - Scheduled workflows

---

## Local Build Testing

Before creating a release tag, test the build locally:

```bash
# Clean environment
rm -rf dist/ build/ *.egg-info

# Build package
python -m build

# Verify package contents
tar -tzf dist/pyworkflow_engine-*.tar.gz | less
unzip -l dist/pyworkflow_engine-*.whl | less

# Check with twine
twine check dist/*

# Test installation in isolated environment
python -m venv test_env
source test_env/bin/activate

# Test core installation (should NOT include SQLite/Postgres)
pip install dist/pyworkflow_engine-*-py3-none-any.whl
python -c "import pyworkflow; print(pyworkflow.__version__)"
python -c "from pyworkflow import workflow, step, start"
python -c "from pyworkflow.storage.file import FileStorageBackend"
python -c "from pyworkflow.storage.memory import InMemoryStorageBackend"

# Test that optional backends are NOT available
python -c "
try:
    from pyworkflow.storage.sqlite import SQLiteStorageBackend
    print('ERROR: SQLite should not be available')
    exit(1)
except ImportError:
    print('OK: SQLite not available without extra')
"

# Test with extras
pip uninstall -y pyworkflow-engine
pip install dist/pyworkflow_engine-*-py3-none-any.whl[sqlite]
python -c "from pyworkflow.storage.sqlite import SQLiteStorageBackend; print('OK: SQLite extra works')"

# Test with all extras
pip uninstall -y pyworkflow-engine
pip install dist/pyworkflow_engine-*-py3-none-any.whl[all]
python -c "from pyworkflow.storage.sqlite import SQLiteStorageBackend"
python -c "from pyworkflow.storage.postgres import PostgresStorageBackend"

deactivate
rm -rf test_env
```

---

## Release Workflow Diagram

```
Developer                 GitHub Actions              PyPI
    |                            |                      |
    |--[1. Bump version]-------->|                      |
    |                            |                      |
    |--[2. Create tag]---------->|                      |
    |                            |                      |
    |                    [3. Verify version]            |
    |                            |                      |
    |                    [4. Build package]             |
    |                            |                      |
    |                    [5. Run tests]                 |
    |                            |                      |
    |                    [6. Publish TestPyPI]--------->|
    |                            |                      |
    |<---[7. Request approval]---|                      |
    |                            |                      |
    |---[8. Approve]------------>|                      |
    |                            |                      |
    |                    [9. Publish PyPI]------------->|
    |                            |                      |
    |                    [10. Create GitHub Release]    |
    |                            |                      |
    |<---[11. Release created]---|                      |
```

---

For questions or issues with the release process, open an issue or contact maintainers.
