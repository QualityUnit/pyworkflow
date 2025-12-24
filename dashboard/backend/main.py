"""CLI entry point for the dashboard backend server."""

import uvicorn
from app.config import settings


def main():
    """Run the dashboard backend server."""
    uvicorn.run(
        "app.server:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
