"""Entry point. Databricks Apps sets DATABRICKS_APP_PORT; locally it defaults to 8000."""

import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run("server.app:app", host="0.0.0.0", port=int(os.environ.get("DATABRICKS_APP_PORT", "8000")),
                proxy_headers=True, forwarded_allow_ips="*")
