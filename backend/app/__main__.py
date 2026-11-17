"""`python -m app` starts the API server. Host and port come from the config."""

import uvicorn

from .config import get_config


def main() -> None:
    config = get_config()
    uvicorn.run("app.main:create_app", factory=True, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
