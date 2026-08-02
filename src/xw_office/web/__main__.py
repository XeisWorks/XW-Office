"""Start the Content Studio web service locally or on Railway."""
from __future__ import annotations

import os

import uvicorn


def main() -> None:
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("xw_office.web.app:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
