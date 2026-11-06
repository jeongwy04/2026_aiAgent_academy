"""Regenerate the checked-in OpenAPI contract from FastAPI."""
import json
from pathlib import Path

from app.main import app

path = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"
path.parent.mkdir(exist_ok=True)
path.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n")
print(path)
