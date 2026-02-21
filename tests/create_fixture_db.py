import sqlite3
from pathlib import Path


def create_fixture_db(db_path: Path):
    conn = sqlite3.connect(db_path)

    # Mentions
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mentions (
            entry_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            feed_url TEXT NOT NULL,
            title TEXT,
            url TEXT,
            published TEXT,
            summary TEXT,
            fetched_at TEXT NOT NULL
        )
        """
    )

    mentions = [
        (
            "m1",
            "reddit.com",
            "https://www.reddit.com/r/programming/hot.rss",
            "How to improve build reliability",
            "https://example.com/a",
            "2026-02-17T08:00:00+00:00",
            "A practical guide with workflow steps",
            "2026-02-17T08:05:00+00:00",
        ),
        (
            "m2",
            "reddit.com",
            "https://www.reddit.com/r/MachineLearning/new.rss",
            "LLM model release notes",
            "https://example.com/b",
            "2026-02-17T07:00:00+00:00",
            "Research update and benchmark results",
            "2026-02-17T07:05:00+00:00",
        ),
        (
            "m3",
            "github.com",
            "https://github.com/trending",
            "New React framework for high performance",
            "https://github.com/example/react-fast",
            "2026-02-17T09:00:00+00:00",
            "A new framework that optimizes rendering",
            "2026-02-17T09:05:00+00:00",
        ),
    ]

    conn.executemany(
        """
        INSERT OR REPLACE INTO mentions (
            entry_id, source, feed_url, title, url, published, summary, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        mentions,
    )

    conn.commit()
    conn.close()
    print(f"Fixture DB created at {db_path}")


if __name__ == "__main__":
    create_fixture_db(Path("tests/fixture.db"))
