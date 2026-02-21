import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path


class TestIngest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "test.db"
        self.feeds_file = self.root / "feeds.txt"
        self.output_jsonl = self.root / "mentions.jsonl"

        # Create a dummy RSS feed file
        self.rss_file = self.root / "test_feed.xml"
        self.rss_file.write_text(
            """<?xml version="1.0" encoding="UTF-8" ?>
<rss version="2.0">
<channel>
 <title>Test Feed</title>
 <item>
  <title>Test Item 1</title>
  <link>https://example.com/1</link>
  <description>Test Description 1</description>
  <guid>guid1</guid>
  <pubDate>Wed, 18 Feb 2026 10:00:00 +0000</pubDate>
 </item>
</channel>
</rss>""",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_ingest_from_local_file_url(self) -> None:
        # Use file:// URL to test ingestion without network
        feed_url = self.rss_file.as_uri()
        self.feeds_file.write_text(feed_url, encoding="utf-8")

        env = {
            **os.environ,
            "FEEDS_FILE": str(self.feeds_file),
            "SQLITE_PATH": str(self.db),
            "OUTPUT_JSONL": str(self.output_jsonl),
            "MAX_ITEMS_PER_FEED": "10",
        }

        proc = subprocess.run(["python3", "ingest_rss.py"], env=env, capture_output=True, text=True)

        self.assertEqual(proc.returncode, 0, msg=proc.stderr + proc.stdout)
        self.assertTrue(self.db.exists())
        self.assertTrue(self.output_jsonl.exists())

        conn = sqlite3.connect(self.db)
        count = conn.execute("SELECT COUNT(*) FROM mentions").fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    def test_ingest_empty_feeds(self) -> None:
        self.feeds_file.write_text("", encoding="utf-8")
        env = {
            **os.environ,
            "FEEDS_FILE": str(self.feeds_file),
            "SQLITE_PATH": str(self.db),
        }
        proc = subprocess.run(["python3", "ingest_rss.py"], env=env, capture_output=True, text=True)
        # Should return 2 as per script logic for no feeds
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
