"""Dev launcher: starts the backend, serving the built frontend if present."""

import uvicorn

from oral_korean.api.app import create_app
from oral_korean.config import AppConfig


def main() -> None:
    config = AppConfig()
    app = create_app(config)
    print(f"Serving on http://{config.host}:{config.port}")
    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
