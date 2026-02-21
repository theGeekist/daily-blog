# Documentation Index

This docs set is organized into three layers:

- `docs/operator/`: practical day-to-day guides for running and tuning the pipeline
- `docs/developer/`: technical documentation for contributors and maintainers
- `docs/internal/`: design notes and historical planning docs

## Operator Documentation

Recommended reading order for operators:

1. `docs/operator/01-quickstart.md` - Setup and first run
2. `docs/operator/02-pipeline-map.md` - Stage-by-stage data flow
3. `docs/operator/03-outputs-and-decisions.md` - Understanding outputs
4. `docs/operator/04-configuration-and-models.md` - Configuration guidance
5. `docs/operator/05-operations.md` - Production operations guide
6. `docs/operator/06-troubleshooting.md` - Common issues and solutions

## Developer Documentation

For contributors and maintainers:

1. `docs/developer/01-architecture.md` - System architecture and data flow
2. `docs/developer/02-api-reference.md` - Core API documentation
3. `docs/developer/03-database-schema.md` - Complete database reference
4. `docs/developer/04-configuration-reference.md` - Detailed config reference
5. `docs/developer/05-testing-guide.md` - Testing philosophy and how-to
6. `docs/developer/06-extending-the-pipeline.md` - Adding new stages and features

See also: `docs/developer/README.md` for full developer documentation index.

Optional: local docs viewer

```bash
python3 scripts/docs_viewer.py
```

Then open:

- `http://127.0.0.1:8765/docs/viewer/index.html`

Operational dashboards:

- `http://127.0.0.1:8877/docs/viewer/dashboard.html`
- `http://127.0.0.1:8877/docs/viewer/settings.html`
