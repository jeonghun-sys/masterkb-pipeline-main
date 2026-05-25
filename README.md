# KB Pipeline

Python backend for collecting CLASS101 KB source data from Slack, Event/Promotion,
and DocBuilder sources, then normalizing it with OCR/LLM and upserting it into
NocoDB.

## Scope

- Collect parent Slack threads created on or after 2026-04-01 00:00 KST.
- Collect active Event/Promotion records that start on or after 2026-04-01 00:00 KST.
- Collect published DocBuilder documents from 2026-04-01 onward.
- Normalize every stored record with LLM-friendly structured output.
- Store source tracking fields for safe backfill and incremental runs.

## Local Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
cp .env.example .env
```

`PIPELINE_WEBHOOK_TOKEN` is optional locally. Set it in Railway and send the same
value as `X-Pipeline-Token` from n8n when calling write-capable endpoints.

## Run

```bash
.venv/bin/kb-pipeline health
.venv/bin/kb-pipeline run --mode smoke --write-mode dry-run --source slack --limit 1
.venv/bin/uvicorn kb_pipeline.main:app --reload
```

The first safe production path is:

1. `smoke` with `dry-run`
2. `smoke` with `write`
3. small batch by source
4. full `backfill`
5. scheduled `incremental`
