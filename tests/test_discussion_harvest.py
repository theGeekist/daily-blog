import json
import unittest
from unittest.mock import patch

from daily_blog.enrichment import discussion


class TestDiscussionHarvest(unittest.TestCase):
    def test_extract_reddit_post_id(self) -> None:
        self.assertEqual(
            discussion._extract_reddit_post_id(
                "https://www.reddit.com/r/Python/comments/abc123/sample_post/"
            ),
            "abc123",
        )
        self.assertEqual(discussion._extract_reddit_post_id("https://example.com/post"), "")

    def test_extract_hn_item_id(self) -> None:
        self.assertEqual(
            discussion._extract_hn_item_id("https://news.ycombinator.com/item?id=12345"),
            "12345",
        )
        self.assertEqual(discussion._extract_hn_item_id("https://example.com/item?id=12345"), "")

    @patch("daily_blog.enrichment.discussion._http_get_json")
    def test_harvest_reddit_discussion(self, mock_get_json) -> None:
        mock_get_json.return_value = [
            {"data": {"children": [{"data": {"title": "A post", "subreddit": "Python"}}]}},
            {
                "data": {
                    "children": [
                        {"data": {"id": "c1", "score": 10, "body": "Problem with setup."}},
                        {"data": {"id": "c2", "score": 6, "body": "Use a virtualenv."}},
                    ]
                }
            },
        ]
        receipt = discussion._harvest_reddit_discussion(
            url="https://www.reddit.com/r/Python/comments/abc123/sample_post/",
            timeout_seconds=5,
            user_agent="ua",
            max_comments=10,
        )
        assert receipt is not None
        self.assertEqual(receipt["platform"], "reddit")
        self.assertEqual(receipt["comment_count"], 2)
        comments = json.loads(str(receipt["comments_json"]))
        self.assertEqual(len(comments), 2)


if __name__ == "__main__":
    unittest.main()
