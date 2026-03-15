# IRIS Home Assistant Integration

Custom Home Assistant integration for IRIS.

This repository contains the HACS-compatible integration root:

- `custom_components/iris/`
- `tests/`
- `pyproject.toml`

## Scope

The integration is server-driven:

- bootstrap, catalog, dashboard and state snapshots come from the IRIS backend
- runtime updates flow over WebSocket
- Home Assistant materializes entities and the managed IRIS dashboard from backend schema

## Local Development

```bash
uv sync --group dev
uv run ruff check custom_components tests
uv run pytest tests -q
```

## Repository Layout

```text
custom_components/iris/  # integration package
tests/                   # pytest-homeassistant-custom-component suite
pyproject.toml           # isolated HA dev environment
```

## Compatibility

- Protocol version: `1`
- Backend version: `2026.03.15+`
- Integration version: `0.1.0`

Main IRIS repository: `git@github.com:Mesteriis/iris.git`
