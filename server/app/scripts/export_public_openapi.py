"""Export the deterministic public v1 OpenAPI contract for web clients."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Schema export never performs live provider calls, but composition imports
# validate that provider configuration exists. Stable sentinels keep export
# deterministic without reading developer secrets.
os.environ.setdefault("DEEPSEEK_API_KEY", "openapi-export")
os.environ.setdefault("STRIPE_API_KEY", "sk_openapi_export")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_openapi_export")
os.environ.setdefault("STRIPE_MONTHLY_PRICE_ID", "price_openapi_monthly")
os.environ.setdefault("STRIPE_YEARLY_PRICE_ID", "price_openapi_yearly")

from app.main import app

PUBLIC_PREFIX = "/api/v1"
OUTPUT = Path(__file__).resolve().parents[2] / "openapi" / "public-v1.json"


def public_openapi_schema() -> dict[str, Any]:
    schema = app.openapi()
    schema["paths"] = {
        path: schema["paths"][path]
        for path in sorted(schema.get("paths", {}))
        if path.startswith(PUBLIC_PREFIX)
    }
    return schema


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(public_openapi_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
