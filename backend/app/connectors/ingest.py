import csv
import io
import json
from typing import Any, Literal

from app.connectors.schemas import FileIngestResponse

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB


def parse_uploaded_file(
    filename: str,
    content: bytes,
    *,
    max_rows: int = 500,
) -> FileIngestResponse:
    """Parse an uploaded CSV or JSON dataset into normalized record dicts."""
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("Uploaded file exceeds 5 MB maximum limit.")

    try:
        decoded = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Uploaded file must be UTF-8 encoded.") from exc

    lower_name = filename.strip().lower()
    fmt: Literal["csv", "json"]
    records: list[dict[str, Any]] = []

    if lower_name.endswith(".json"):
        fmt = "json"
        try:
            parsed: Any = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON payload: {exc}") from exc

        if isinstance(parsed, dict) and isinstance(parsed.get("records"), list):
            parsed = parsed["records"]
        if not isinstance(parsed, list):
            raise ValueError("JSON upload must contain an array of record objects.")
        for item in parsed[:max_rows]:
            if not isinstance(item, dict):
                raise ValueError("Each item in uploaded JSON array must be an object.")
            records.append(dict(item))
    elif lower_name.endswith(".csv"):
        fmt = "csv"
        reader = csv.DictReader(io.StringIO(decoded))
        if not reader.fieldnames:
            raise ValueError("CSV upload is missing header columns.")
        for idx, row in enumerate(reader):
            if idx >= max_rows:
                break
            records.append({str(k): v for k, v in row.items() if k is not None})
    else:
        raise ValueError("Unsupported file extension; upload a .csv or .json file.")

    if not records:
        raise ValueError("Uploaded file contains no data records.")

    columns: list[str] = []
    seen: set[str] = set()
    for rec in records:
        for col in rec:
            if col not in seen:
                seen.add(col)
                columns.append(col)

    return FileIngestResponse(
        filename=filename,
        format=fmt,
        row_count=len(records),
        columns=columns,
        records=records,
    )
