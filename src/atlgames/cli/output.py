"""Output formats for atlg, in the style of gcloud's --format.

Every command builds JSON-compatible data and, optionally, a function that
renders it as Rich tables. ``emit()`` then prints it in the requested format:

- ``table``: Rich tables (the default)
- ``json`` / ``yaml``: the full data
- ``csv``: one row per item, with nested fields flattened to dotted columns
- ``value(FIELD,...)``: tab separated values, one line per item, for scripts
"""
import csv
import json
import re
import sys
from collections.abc import Callable
from collections.abc import Iterable
from typing import Annotated
from typing import Any
from typing import Optional

import typer
from rich.console import Console
from rich.console import RenderableType
from rich.syntax import Syntax
from rich.table import Table

console = Console()
err_console = Console(stderr=True)

FORMATS = ("table", "json", "yaml", "csv")
VALUE_RE = re.compile(r"^value\((?P<fields>.*)\)$")

TableRenderer = Callable[[Any], Iterable[RenderableType]]

# Set by the root command from --format or the profile's format setting.
default_format: str | None = None


def resolve_format(fmt: str | None) -> str:
    """Return the format to use and check it's valid."""
    fmt = (fmt or default_format or "table").strip()
    if fmt in FORMATS or VALUE_RE.match(fmt):
        return fmt
    raise typer.BadParameter(
        f"Unknown format {fmt!r}. Use table, json, yaml, csv or value(FIELD,...).",
        param_hint="'--format'",
    )


def check_format(fmt: str | None) -> str | None:
    """Validate --format before running the command."""
    if fmt is not None:
        resolve_format(fmt)
    return fmt


FormatOption = Annotated[
    Optional[str],
    typer.Option(
        "--format",
        "-f",
        help="Output format: table, json, yaml, csv or value(FIELD,...).",
        show_default=False,
        callback=check_format,
    ),
]


def emit(data: Any, fmt: str | None = None, table: TableRenderer | None = None) -> None:
    """Print data in the requested format."""
    fmt = resolve_format(fmt)
    if fmt == "table":
        for renderable in (table or default_table)(data):
            console.print(renderable)
    elif fmt == "json":
        text = json.dumps(data, indent=2, ensure_ascii=False, default=str)
        if console.is_terminal:
            console.print(Syntax(text, "json", theme="ansi_dark", background_color="default"))
        else:
            sys.stdout.write(text + "\n")
    elif fmt == "yaml":
        try:
            import yaml
        except ImportError:
            raise typer.BadParameter("The yaml format needs PyYAML: pip install pyyaml",
                                     param_hint="'--format'") from None
        sys.stdout.write(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    elif fmt == "csv":
        write_csv(data)
    else:
        fields = [f.strip() for f in VALUE_RE.match(fmt).group("fields").split(",") if f.strip()]
        for row in rows(data):
            sys.stdout.write("\t".join(value_text(get_path(row, f)) for f in fields) + "\n")


def rows(data: Any) -> list:
    """Return data as a list of rows."""
    return data if isinstance(data, list) else [data]


def get_path(data: Any, path: str) -> Any:
    """Return a value by dotted path, such as ``categories[0].title``."""
    for part in re.findall(r"[^.\[\]]+|\[\d+\]", path):
        if part.startswith("["):
            index = int(part[1:-1])
            data = data[index] if isinstance(data, list) and index < len(data) else None
        else:
            data = data.get(part) if isinstance(data, dict) else None
        if data is None:
            return None
    return data


def value_text(value: Any) -> str:
    """Format a value for value() and csv output."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, list) and all(not isinstance(v, (dict, list)) for v in value):
        return ";".join(value_text(v) for v in value)
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def flatten(data: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten nested dicts into dotted keys."""
    if not isinstance(data, dict):
        return {prefix or "value": data}
    flat = {}
    for key, value in data.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flat.update(flatten(value, name))
        else:
            flat[name] = value
    return flat


def write_csv(data: Any) -> None:
    """Write data as CSV, one row per item."""
    flat_rows = [flatten(row) for row in rows(data)]
    columns: list[str] = []
    for row in flat_rows:
        columns.extend(key for key in row if key not in columns)
    writer = csv.writer(sys.stdout)
    writer.writerow(columns)
    for row in flat_rows:
        writer.writerow(value_text(row.get(column)) for column in columns)


def default_table(data: Any) -> Iterable[RenderableType]:
    """Render data without a command-specific table."""
    if isinstance(data, list):
        flat_rows = [flatten(row) for row in data]
        columns: list[str] = []
        for row in flat_rows:
            columns.extend(key for key in row if key not in columns)
        table = Table(header_style="bold")
        for column in columns:
            table.add_column(column)
        for row in flat_rows:
            table.add_row(*(value_text(row.get(column)) for column in columns))
        yield table
    else:
        yield key_value_table(flatten(data) if isinstance(data, dict) else {"value": data})


def key_value_table(data: dict[str, Any], title: str | None = None) -> Table:
    """Render a dict as a two column table."""
    table = Table(title=title, show_header=False, box=None, padding=(0, 2), title_justify="left")
    table.add_column(style="cyan", no_wrap=True)
    table.add_column()
    for key, value in data.items():
        table.add_row(str(key), value_text(value))
    return table
