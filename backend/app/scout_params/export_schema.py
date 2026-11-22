"""Write the JSON Schema for ScoutRequest (for the frontend / other agents).

    uv run python -m app.scout_params.export_schema > scout_request.schema.json
"""

import json
import sys

from .models import ScoutRequest


def main() -> None:
    json.dump(ScoutRequest.model_json_schema(), sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
