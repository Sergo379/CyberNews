import sys

import uvicorn

from app.main import app

if __name__ == "__main__":
    if "--migrate" in sys.argv[1:]:
        from .migration import upgrade_schema

        upgrade_schema()
    uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None, access_log=False)
