# PyWorkflow Dashboard

A web-based monitoring dashboard for PyWorkflow workflows.

## Structure

```
dashboard/
├── backend/           # FastAPI REST API
│   ├── main.py        # Entry point
│   └── app/           # Application code
│       ├── rest/      # REST routes
│       ├── controllers/
│       ├── services/
│       ├── repositories/
│       └── schemas/
│
└── frontend/          # React + Vite UI
    └── src/
        ├── api/       # API client
        ├── features/  # Feature modules
        ├── hooks/     # React Query hooks
        └── routes/    # Page routes
```

## Quick Start

### Backend

```bash
cd dashboard/backend

# Install dependencies with Poetry
poetry install

# Run the server
poetry run python main.py

# Or use the script
poetry run dashboard
```

The API will be available at `http://localhost:8585`.

API docs: `http://localhost:8585/docs`

### Frontend

```bash
cd dashboard/frontend

# Install dependencies
npm install

# Run development server
npm run dev
```

The UI will be available at `http://localhost:5173`.

## Configuration

### Backend

Environment variables (prefix with `DASHBOARD_`):

| Variable | Default                     | Description |
|----------|-----------------------------|-------------|
| `DASHBOARD_STORAGE_TYPE` | `file`                      | Storage backend type |
| `DASHBOARD_STORAGE_PATH` | `./pyworkflow_data`         | Path for file storage |
| `DASHBOARD_HOST` | `0.0.0.0`                   | Server host |
| `DASHBOARD_PORT` | `8585`                      | Server port |
| `DASHBOARD_CORS_ORIGINS` | `["http://localhost:5173"]` | Allowed CORS origins |

### Frontend

Create `.env` file:

```
VITE_API_URL=http://localhost:8585
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/v1/health` | Health check |
| `GET` | `/api/v1/workflows` | List registered workflows |
| `GET` | `/api/v1/runs` | List workflow runs |
| `GET` | `/api/v1/runs/{run_id}` | Get run details |
| `GET` | `/api/v1/runs/{run_id}/events` | Get run events |
| `GET` | `/api/v1/runs/{run_id}/steps` | Get run steps |
| `GET` | `/api/v1/runs/{run_id}/hooks` | Get run hooks |

## Features

- **Dashboard**: Overview of workflow execution stats
- **Runs List**: Filterable list of all workflow runs
- **Run Detail**: Event timeline, steps, and hooks for each run
- **Workflows List**: All registered workflow definitions
- **Real-time Updates**: Auto-refresh every 5 seconds
- **Dark Mode**: Toggle between light and dark themes
