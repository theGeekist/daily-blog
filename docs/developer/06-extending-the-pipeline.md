# Extending the Pipeline

This document describes how to extend the daily-blog pipeline with new stages, custom scoring rules, and model integrations.

## Overview

The pipeline is designed for extensibility:

1. **Stages are independent**: Add new stages without modifying existing ones
2. **Configuration-driven**: Change behavior via config files
3. **LLM-agnostic**: Use any model that provides a CLI interface
4. **Stateful**: SQLite database maintains all intermediate results

---

## Adding a New Pipeline Stage

### Step 1: Create the Stage Module

Create a new Python file (e.g., `my_new_stage.py`):

```python
#!/usr/bin/env python3
"""Custom stage description."""

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import sqlite3

logger = logging.getLogger(__name__)

# Constants
DB_PATH = Path("data/daily-blog.db")
STAGE_NAME = "my_new_stage"


def init_table(conn: sqlite3.Connection) -> None:
    """Initialize the output table for this stage."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS my_output (
            id TEXT PRIMARY KEY,
            input_data TEXT NOT NULL,
            processed_result TEXT NOT NULL,
            model_route_used TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def process_item(item: dict) -> dict:
    """Process a single item. Implement your logic here."""
    # Example: Transform the input data
    result = {
        "id": hashlib.sha256(item["input"].encode()).hexdigest()[:20],
        "processed": item["input"].upper()  # Your processing logic
    }
    return result


def main() -> None:
    """Main entry point for the stage."""
    logging.basicConfig(level=logging.INFO)
    logger.info("Starting %s stage", STAGE_NAME)

    conn = sqlite3.connect(DB_PATH)
    init_table(conn)

    # Read from previous stage
    rows = conn.execute("SELECT * FROM previous_stage_table").fetchall()
    logger.info("Found %d rows to process", len(rows))

    processed = 0
    for row in rows:
        # Convert row to dict
        item = dict(zip([c[0] for c in conn.description], row))

        # Process the item
        result = process_item(item)

        # Store result
        conn.execute(
            """
            INSERT INTO my_output (id, input_data, processed_result, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (result["id"], json.dumps(item), json.dumps(result), datetime.now(timezone.utc).isoformat())
        )
        processed += 1

    conn.commit()
    logger.info("Processed %d items", processed)


if __name__ == "__main__":
    main()
```

### Step 2: Add Model Routing

Add your stage to `config/model-routing.json`:

```json
{
  "existing_stage": {...},
  "my_new_stage": {
    "primary": "ollama:qwen2.5:7b",
    "fallback": "gemini-3-pro"
  }
}
```

### Step 3: Register in Orchestrator

Add to `run_pipeline.py`:

```python
# Import your stage
import my_new_stage

# Add to STAGES list
STAGES = [
    ("ingest", ingest_rss.main),
    ("score", score_rss.main),
    # ... existing stages ...
    ("my_new_stage", my_new_stage.main),
]
```

### Step 4: Test Your Stage

```python
# tests/test_my_new_stage.py
import unittest
import sqlite3
import tempfile

class TestMyNewStage(unittest.TestCase):
    def setUp(self):
        self.db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.conn = sqlite3.connect(self.db.name)
        from my_new_stage import init_table
        init_table(self.conn)

    def tearDown(self):
        self.conn.close()
        Path(self.db.name).unlink()

    def test_process_item(self):
        """Test item processing logic."""
        from my_new_stage import process_item

        result = process_item({"input": "test"})
        self.assertEqual(result["processed"], "TEST")
```

### Step 5: Run the Stage

```bash
# Run individually
python3 my_new_stage.py

# Or via full pipeline
python3 run_pipeline.py
```

---

## Using LLMs in Your Stage

### Basic LLM Call

```python
from orchestrator_utils import call_model

def my_llm_function(input_text: str) -> dict:
    """Call LLM with input text."""
    result = call_model(
        stage_name="my_new_stage",
        prompt=f"Process this: {input_text}",
        schema={
            "type": "object",
            "required": ["output"],
            "properties": {
                "output": {"type": "string"}
            }
        }
    )
    return result["content"]
```

### Advanced: Streaming/Batch Processing

```python
def process_batch(items: list[dict]) -> list[dict]:
    """Process multiple items efficiently."""
    results = []

    # Process in batches to avoid overwhelming the LLM
    batch_size = 10
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]

        # Create batch prompt
        prompt = json.dumps({"items": batch})

        result = call_model(
            stage_name="my_new_stage",
            prompt=prompt,
            schema={
                "type": "object",
                "required": ["results"],
                "properties": {
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["id", "processed"]
                        }
                    }
                }
            }
        )
        results.extend(result["content"]["results"])

    return results
```

### Error Handling

```python
from orchestrator_utils import ModelCallError

def safe_llm_call(input_data: dict) -> dict | None:
    """Call LLM with fallback handling."""
    try:
        result = call_model(
            stage_name="my_new_stage",
            prompt=json.dumps(input_data),
            schema={...}
        )
        return result["content"]
    except ModelCallError as e:
        logger.error("LLM call failed: %s", e)
        # Return default value or re-raise
        return None
```

---

## Adding Custom Scoring Rules

### Modify rules-engine.json

Add a new scoring dimension:

```json
{
  "weights": {
    "existing_dimension": 0.2,
    "my_custom_score": 0.15,
    "another_dimension": 0.3
  }
}
```

### Implement Scoring Logic

In your stage module:

```python
def calculate_custom_score(item: dict) -> float:
    """Calculate custom score for an item."""
    score = 0.0

    # Example: Score based on title length
    title_length = len(item.get("title", ""))
    if 50 <= title_length <= 100:
        score = 1.0
    elif title_length > 100:
        score = 0.7
    else:
        score = 0.3

    return score


def apply_scoring_rules(item: dict, rules: dict) -> dict:
    """Apply all scoring rules to an item."""
    scores = {
        "my_custom_score": calculate_custom_score(item),
        # ... other scores
    }

    # Calculate final weighted score
    weights = rules["weights"]
    final_score = sum(
        scores.get(key, 0) * weight
        for key, weight in weights.items()
    )

    return {
        **scores,
        "final_score": final_score
    }
```

---

## Integrating a New LLM Provider

### Step 1: Ensure CLI Compatibility

Your LLM tool must support:

```bash
# Basic interface expected
tool run -m MODEL_NAME "prompt"

# Or for ollama-style
ollama run MODEL_NAME "prompt"
```

### Step 2: Add Model Resolution

Update `orchestrator_utils.py` `_resolve_cli()` function:

```python
def _resolve_cli(model_name: str) -> tuple[str, str]:
    # Existing cases...
    if model_name.startswith("your-tool:"):
        return "your-tool", model_name.split(":", 1)[1]

    # Default
    return "opencode", model_name
```

### Step 3: Add Command Format

Update `_run_model_cli()` function:

```python
def _run_model_cli(model_name: str, prompt: str) -> str:
    cli_tool, cli_model = _resolve_cli(model_name)

    if cli_tool == "your-tool":
        command = [cli_tool, "run", "-m", cli_model, "--json", prompt]
    # ... existing cases ...
```

### Step 4: Test Integration

```bash
# Test CLI directly
your-tool run -m your-model "test prompt"

# Test via orchestrator
python3 -c "
from orchestrator_utils import call_model
result = call_model('test_stage', 'test')
print(result)
"
```

---

## Adding Database Migrations

### For New Tables

```python
def init_my_new_table(conn: sqlite3.Connection) -> None:
    """Initialize new table with migration support."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS my_new_table (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )

    # Check for migrations
    columns = {
        row[1] for row in
        conn.execute("PRAGMA table_info(my_new_table)").fetchall()
    }

    if "new_column" not in columns:
        conn.execute(
            "ALTER TABLE my_new_table ADD COLUMN new_column TEXT NOT NULL DEFAULT ''"
        )

    conn.commit()
```

### For Schema Changes

```python
def migrate_add_new_column(conn: sqlite3.Connection) -> None:
    """Add new column to existing table."""
    columns = {
        row[1] for row in
        conn.execute("PRAGMA table_info(existing_table)").fetchall()
    }

    if "new_column" not in columns:
        logger.info("Adding new_column to existing_table")
        conn.execute(
            "ALTER TABLE existing_table ADD COLUMN new_column TEXT"
        )
        conn.commit()
```

---

## Custom Data Outputs

### Writing Markdown Files

```python
def write_markdown_report(data: list[dict], output_path: Path) -> None:
    """Generate a Markdown report from data."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        f.write("# My Custom Report\n\n")

        for item in data:
            f.write(f"## {item['title']}\n\n")
            f.write(f"{item['content']}\n\n")
```

### Writing JSON Files

```python
def write_json_report(data: dict, output_path: Path) -> None:
    """Generate a JSON report."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
```

---

## Adding Configuration Options

### 1. Define Config Schema

```python
from pathlib import Path
import json

def load_my_config(path: Path) -> dict:
    """Load configuration for my stage."""
    default = {
        "enabled": True,
        "batch_size": 10,
        "threshold": 0.5
    }

    if not path.exists():
        return default

    loaded = json.loads(path.read_text(encoding="utf-8"))
    return {**default, **loaded}  # Merge with defaults
```

### 2. Add to Config File

```json
// config/rules-engine.json
{
  "my_stage": {
    "enabled": true,
    "batch_size": 10,
    "threshold": 0.5
  }
}
```

### 3. Use in Stage

```python
CONFIG_PATH = Path("config/rules-engine.json")

def main():
    config = load_my_config(CONFIG_PATH)
    if not config["enabled"]:
        logger.info("Stage disabled, skipping")
        return

    batch_size = config["batch_size"]
    # ... use config
```

---

## Adding Prompt Templates

### Create prompts.json

```json
{
  "my_new_stage": {
    "template": "You are a specialized assistant.\n\nContext: {context}\n\nTask: {prompt}",
    "prefix": "IMPORTANT: Follow these guidelines:",
    "suffix": "Return only valid JSON response."
  }
}
```

### Template Variables

Your stage can pass variables to templates:

```python
def build_prompt(context: str, task: str) -> str:
    """Build prompt with template variables."""
    # This will be used by orchestrator_utils._apply_prompt_overrides()
    # The template must include {prompt} for the base prompt
    return json.dumps({
        "context": context,
        "prompt": task  # This becomes {prompt} in template
    })
```

---

## Performance Optimization

### Batch Processing

```python
def process_in_batches(items: list[dict], batch_size: int = 100) -> None:
    """Process items in batches for better performance."""
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        logger.info("Processing batch %d (%d items)", i // batch_size, len(batch))
        process_batch(batch)
```

### Parallel Processing

```python
from concurrent.futures import ThreadPoolExecutor

def process_parallel(items: list[dict], max_workers: int = 4) -> list[dict]:
    """Process items in parallel."""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(process_item, items))
    return results
```

### Database Optimization

```python
# Use transactions for bulk inserts
def bulk_insert(conn: sqlite3.Connection, items: list[dict]) -> None:
    """Insert multiple items efficiently."""
    conn.execute("BEGIN TRANSACTION")
    try:
        for item in items:
            conn.execute("INSERT INTO ...", (...))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
```

---

## Testing Your Extensions

### Unit Tests

```python
# tests/test_my_extension.py
import unittest

class TestMyExtension(unittest.TestCase):
    def test_processing_logic(self):
        """Test core processing logic."""
        from my_new_stage import process_item
        result = process_item({"input": "test"})
        self.assertEqual(result["output"], "expected")

    def test_scoring(self):
        """Test scoring calculation."""
        from my_new_stage import calculate_custom_score
        score = calculate_custom_score({"title": "A" * 75})
        self.assertEqual(score, 1.0)
```

### Integration Tests

```python
def test_stage_integration(self):
    """Test stage in pipeline context."""
    from my_new_stage import main
    main()

    # Verify output table exists and has data
    count = self.conn.execute("SELECT COUNT(*) FROM my_output").fetchone()[0]
    self.assertGreater(count, 0)
```

---

## Best Practices for Extensions

1. **Idempotency**: Re-running should produce same results
2. **Logging**: Log important events and errors
3. **Error Handling**: Gracefully handle failures
4. **Configuration**: Make behavior configurable
5. **Testing**: Write tests for new functionality
6. **Documentation**: Document new stages and features
7. **Database**: Use proper migrations for schema changes
8. **Performance**: Consider batch processing for large datasets

---

## Common Extension Patterns

### Filter Stage

```python
def filter_items(items: list[dict]) -> list[dict]:
    """Filter items based on criteria."""
    return [
        item for item in items
        if meets_criteria(item)
    ]
```

### Transform Stage

```python
def transform_items(items: list[dict]) -> list[dict]:
    """Transform item structure."""
    return [
        {
            "old_field": item["field"],
            "new_field": transform(item["field"])
        }
        for item in items
    ]
```

### Enrichment Stage

```python
def enrich_items(items: list[dict]) -> list[dict]:
    """Add additional data to items."""
    return [
        {**item, "enriched_data": fetch_external_data(item["id"])}
        for item in items
    ]
```

### Aggregation Stage

```python
def aggregate_items(items: list[dict]) -> dict:
    """Aggregate items into summary."""
    return {
        "count": len(items),
        "by_category": group_by_category(items),
        "metrics": calculate_metrics(items)
    }
```
