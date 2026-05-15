# Command Reference

All Python and CLI commands should run through:

```bash
conda run -n ashare-research-lab ...
```

Install the repo in editable mode:

```bash
conda run -n ashare-research-lab python -m pip install -e .
```

Run the Phase 4 service locally:

```bash
conda run -n ashare-research-lab ashare serve --service-config configs/service.yaml
```

Dry-run the configured fixture workflow:

```bash
conda run -n ashare-research-lab ashare service-workflow --service-config configs/service.yaml --name phase4-fixture-research --dry-run
```

Dry-run the scheduler once:

```bash
conda run -n ashare-research-lab ashare service-scheduler --service-config configs/service.yaml --once --name phase4-fixture-research --dry-run
```

Run the full test suite:

```bash
conda run -n ashare-research-lab pytest -q
```
