# Testing Guide

This document describes the testing philosophy, structure, and how to write tests for the daily-blog pipeline.

## Test Philosophy

The daily-blog testing approach follows these principles:

1. **Determinism**: Tests use fixed inputs and avoid external API calls
2. **Stage Isolation**: Each test validates one stage independently
3. **Fast Feedback**: Unit tests should run in seconds, not minutes
4. **Realistic Data**: Fixtures mirror production data structure
5. **No LLM Dependencies**: Tests mock or use deterministic outputs

---

## Test Structure

### Directory Layout

```
tests/
├── test_ingest.py              # RSS feed ingestion tests
├── test_scoring_baseline.py    # Scoring calculation tests
├── test_extract_claims.py      # Claim extraction tests
├── test_lift_topics.py         # Topic clustering tests
├── test_enrich_topics.py       # Evidence enrichment tests
├── test_generate_editorial.py  # Editorial generation tests
├── test_pipeline_stages.py     # End-to-end integration tests
├── test_e2e_deterministic.py   # Full pipeline E2E tests
├── test_normalize_topics.py    # Topic normalization tests
├── utils/                      # Test fixtures and helpers
└── create_fixture_db.py        # Database fixture creation
```

### Test Categories

| Category | Tests | Purpose |
|----------|-------|---------|
| **Unit** | test_*.py (individual stages) | Validate single stage behavior |
| **Integration** | test_pipeline_stages.py | Validate stage interactions |
| **E2E** | test_e2e_deterministic.py | Validate full pipeline |
| **Baseline** | test_scoring_baseline.py | Validate scoring calculations |

---

## Running Tests

### All Tests

```bash
make test
# or
python3 -m unittest discover -s tests
```

### Specific Test File

```bash
python3 -m unittest tests.test_ingest
# or
python3 -m unittest tests/test_ingest.py
```

### Specific Test Method

```bash
python3 -m unittest tests.test_ingest.TestIngest.test_upsert_mentions
```

### With Coverage

```bash
python3 -m pytest --cov=. tests/
# or
coverage run -m unittest discover -s tests
coverage report
```

---

## Test Fixtures

### Database Fixtures

Located in `tests/utils/` and created via `create_fixture_db.py`:

```python
# Create a temporary test database
import sqlite3
import tempfile

def get_test_db():
    """Return a temporary SQLite database for testing."""
    db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    conn = sqlite3.connect(db.name)
    return conn, db.name
```

### Sample Fixtures

The pipeline uses **minimal, realistic fixtures** for testing:

```python
# Sample mention fixture
MENTION_FIXTURE = {
    "entry_id": "test-entry-1",
    "source": "test",
    "feed_url": "https://example.com/feed",
    "title": "Test Entry",
    "url": "https://example.com/test",
    "published": "2026-01-01T00:00:00Z",
    "summary": "Test summary",
    "fetched_at": "2026-01-01T00:00:00Z"
}
```

---

## Writing New Tests

### Basic Test Template

```python
import unittest
import sqlite3
import tempfile
from pathlib import Path

class TestNewFeature(unittest.TestCase):
    def setUp(self):
        """Create a fresh database for each test."""
        self.db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.conn = sqlite3.connect(self.db.name)
        # Initialize required tables
        self.init_tables()

    def tearDown(self):
        """Clean up database after each test."""
        self.conn.close()
        Path(self.db.name).unlink()

    def test_expected_behavior(self):
        """Test that feature behaves as expected."""
        # Arrange: Set up test data
        input_data = {...}

        # Act: Execute the function
        result = function_under_test(self.conn, input_data)

        # Assert: Verify expected outcome
        self.assertEqual(result["expected_key"], "expected_value")

    def test_error_handling(self):
        """Test that errors are handled correctly."""
        with self.assertRaises(ValueError):
            function_under_test(self.conn, invalid_input)
```

### Testing Pipeline Stages

When testing a pipeline stage:

```python
def test_stage_output_schema(self):
    """Test that stage produces expected schema."""
    # Arrange: Create required input tables
    self.conn.execute("""
        INSERT INTO mentions (entry_id, source, feed_url, title, url, published, summary, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, ("test-id", "test", "https://example.com/feed", "Test", "https://example.com", "2026-01-01T00:00:00Z", "Summary", "2026-01-01T00:00:00Z"))

    # Act: Run the stage
    from ingest_rss import main
    main()  # Will use test database via environment variable

    # Assert: Check output table exists and has expected data
    rows = self.conn.execute("SELECT * FROM mentions").fetchall()
    self.assertGreater(len(rows), 0)
```

### Testing with Mocked LLM Responses

For stages that use `call_model()`, mock the responses:

```python
from unittest.mock import patch

def test_claims_extraction(self):
    """Test claim extraction with mocked LLM."""
    mock_response = {
        "content": {
            "claims": [
                {
                    "headline": "Test claim",
                    "who_cares": "Test audience",
                    "problem_pressure": "Test problem",
                    "proposed_solution": "Test solution",
                    "evidence_type": "anecdote",
                    "sources": ["https://example.com"]
                }
            ]
        },
        "model_used": "test-model"
    }

    with patch('orchestrator_utils.call_model', return_value=mock_response):
        from extract_claims import main
        main()

    # Verify claims were stored correctly
    claims = self.conn.execute("SELECT * FROM claims").fetchall()
    self.assertEqual(len(claims), 1)
```

---

## Test Examples

### Example 1: Ingest RSS Tests

```python
class TestIngest(unittest.TestCase):
    def test_upsert_mentions(self):
        """Test that mentions are upserted correctly."""
        from ingest_rss import upsert_mentions, Mention

        mentions = [
            Mention(
                entry_id="test-1",
                source="test",
                feed_url="https://example.com/feed",
                title="Test",
                url="https://example.com/test",
                published="2026-01-01T00:00:00Z",
                summary="Summary",
                fetched_at="2026-01-01T00:00:00Z"
            )
        ]

        count = upsert_mentions(self.conn, mentions)
        self.assertEqual(count, 1)

        # Verify insertion
        row = self.conn.execute("SELECT * FROM mentions WHERE entry_id = ?", ("test-1",)).fetchone()
        self.assertIsNotNone(row)

    def test_duplicate_handling(self):
        """Test that duplicate mentions are ignored."""
        # Insert same mention twice
        mentions = [same_mention, same_mention]
        count = upsert_mentions(self.conn, mentions)
        self.assertEqual(count, 1)  # Only one inserted
```

### Example 2: Scoring Tests

```python
class TestScoring(unittest.TestCase):
    def test_novelty_calculation(self):
        """Test that novelty scores are calculated correctly."""
        # Test novel content (first_seen_at = today)
        novel_days = 3
        self.assertTrue(is_novel("2026-01-01", "2026-01-01", novel_days))

    def test_composite_score(self):
        """Test that final score is weighted correctly."""
        scores = {
            "novelty": 1.0,
            "recency": 0.6,
            "corroboration": 0.8,
            "source_diversity": 0.5,
            "actionability": 0.7
        }
        weights = {
            "novelty": 0.3,
            "recency": 0.2,
            "corroboration": 0.2,
            "source_diversity": 0.15,
            "actionability": 0.15
        }

        final = calculate_final_score(scores, weights)
        expected = (
            1.0 * 0.3 + 0.6 * 0.2 + 0.8 * 0.2 +
            0.5 * 0.15 + 0.7 * 0.15
        )
        self.assertAlmostEqual(final, expected, places=2)
```

### Example 3: Database Schema Tests

```python
class TestDatabaseSchema(unittest.TestCase):
    def test_mentions_table_columns(self):
        """Test that mentions table has required columns."""
        from ingest_rss import init_db
        init_db(self.conn)

        columns = [
            row[1] for row in
            self.conn.execute("PRAGMA table_info(mentions)").fetchall()
        ]

        required = [
            "entry_id", "source", "feed_url", "title",
            "url", "published", "summary", "fetched_at"
        ]
        for col in required:
            self.assertIn(col, columns)

    def test_primary_keys(self):
        """Test that primary keys are correctly defined."""
        # Check mentions PK
        pk = self.conn.execute("""
            SELECT sql FROM sqlite_master
            WHERE type='table' AND name='mentions'
        """).fetchone()[0]
        self.assertIn("PRIMARY KEY", pk)
```

---

## Integration Testing

### test_pipeline_stages.py

Tests the interaction between stages:

```python
class TestPipelineStages(unittest.TestCase):
    def test_full_pipeline_flow(self):
        """Test that data flows correctly through all stages."""
        # 1. Ingest
        from ingest_rss import main as ingest_main
        ingest_main()

        # 2. Score
        from score_rss import main as score_main
        score_main()

        # 3. Extract claims
        from extract_claims import main as extract_main
        extract_main()

        # Verify all stages completed
        mention_count = self.conn.execute("SELECT COUNT(*) FROM mentions").fetchone()[0]
        self.assertGreater(mention_count, 0)

        claim_count = self.conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        self.assertGreater(claim_count, 0)
```

---

## End-to-End Testing

### E2E Test Template

```python
class TestE2E(unittest.TestCase):
    def test_full_pipeline_with_output(self):
        """Test complete pipeline and verify outputs."""
        # Run full pipeline
        from run_pipeline import main
        main()

        # Verify database state
        tables = [
            "mentions", "canonical_items", "candidate_scores",
            "claims", "topic_clusters", "claim_topic_map",
            "enrichment_sources", "editorial_candidates"
        ]
        for table in tables:
            count = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            self.assertGreater(count, 0, f"Table {table} is empty")

        # Verify output files exist
        from pathlib import Path
        self.assertTrue(Path("data/daily_board.md").exists())
        self.assertTrue(Path("data/top_outlines.md").exists())
        self.assertTrue(Path("data/research_pack.json").exists())
```

---

## Test Coverage

### Current Coverage

The pipeline currently has good coverage for:
- RSS ingestion and normalization
- Scoring calculations
- Topic lifting and clustering
- Editorial generation

### Coverage Targets

| Component | Target Coverage | Current Status |
|-----------|-----------------|----------------|
| Core pipeline modules | 80%+ | Good |
| orchestrator_utils.py | 90%+ | Needs work |
| Individual stages | 70%+ | Good |
| Error paths | 60%+ | Needs work |

### Running Coverage Report

```bash
# Install coverage
pip install coverage

# Run tests with coverage
coverage run -m unittest discover -s tests

# Generate report
coverage report
coverage html  # Opens HTML report
```

---

## Debugging Tests

### Verbose Output

```bash
python3 -m unittest tests.test_ingest -v
```

### Debugging Single Test

```python
def test_failing_test(self):
    import pdb; pdb.set_trace()  # Set breakpoint
    # ... test code
```

### Logging During Tests

```python
import logging
logging.basicConfig(level=logging.DEBUG)

class TestWithLogging(unittest.TestCase):
    def test_with_logs(self):
        # Logs will appear during test run
        pass
```

---

## Testing Best Practices

1. **Isolation**: Each test should be independent
2. **Speed**: Keep tests fast—avoid real network calls
3. **Clarity**: Test names should describe what they test
4. **Maintenance**: Update tests when code changes
5. **Fixtures**: Use realistic but minimal test data
6. **Asserts**: Be specific about expected outcomes

---

## Common Test Patterns

### Testing with Temporary Files

```python
def test_with_temp_file(self):
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        f.write("test content")
        temp_path = f.name

    try:
        # Use temp_path in test
        result = process_file(temp_path)
        self.assertIsNotNone(result)
    finally:
        Path(temp_path).unlink()
```

### Testing Database Migrations

```python
def test_migration_adds_column(self):
    """Test that a migration adds a new column."""
    # Create old schema
    self.conn.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY)")

    # Run migration
    migrate_add_new_column(self.conn)

    # Verify column exists
    columns = [row[1] for row in self.conn.execute("PRAGMA table_info(test_table)").fetchall()]
    self.assertIn("new_column", columns)
```

### Testing Error Handling

```python
def test_invalid_input_raises_error(self):
    """Test that invalid input raises appropriate error."""
    with self.assertRaises(ValueError) as context:
        process_invalid_input(None)

    self.assertIn("cannot be None", str(context.exception))
```

---

## Continuous Integration

### Pre-commit Hooks

The project uses pre-commit hooks for automatic quality checks:

```bash
# Install hooks
.venv/bin/pre-commit install

# Hooks run automatically on git commit
# Or run manually:
pre-commit run --all-files
```

### CI Configuration

Tests are designed to run in CI/CD environments:
- No external dependencies (LLMs mocked)
- Fast execution (< 2 minutes)
- Clear failure messages

---

## Test Maintenance

### When to Update Tests

- After adding new features
- After fixing bugs
- After changing database schema
- After modifying configuration structure

### Test Smell Detection

**Signs tests need refactoring:**
- Tests take > 1 second each
- Tests depend on each other
- Tests have complex setup
- Tests test implementation details

**Refactoring approach:**
- Extract common setup to `setUp()`
- Use fixtures for complex data
- Split large tests into smaller units
- Mock external dependencies
