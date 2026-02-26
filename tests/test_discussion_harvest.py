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
        self.assertIsNotNone(receipt)
        if receipt is None:
            return
        self.assertEqual(receipt["platform"], "reddit")
        self.assertEqual(receipt["comment_count"], 2)
        comments = json.loads(str(receipt["comments_json"]))
        self.assertEqual(len(comments), 2)

    @patch("daily_blog.enrichment.discussion._http_get_json")
    def test_harvest_hn_discussion_and_edge_cases(self, mock_get_json) -> None:
        def _fake_get_json(url: str, timeout_seconds: int, user_agent: str) -> object | None:
            del timeout_seconds, user_agent
            if "item/12345.json" in url:
                return {"id": 12345, "title": "HN thread", "kids": [2001, 2002]}
            if "item/2001.json" in url:
                return {"id": 2001, "type": "comment", "text": "Problem signal", "kids": [3001]}
            if "item/2002.json" in url:
                return {"id": 2002, "type": "comment", "text": "Solution signal"}
            if "item/3001.json" in url:
                return {"id": 3001, "type": "comment", "text": "Nested detail"}
            return None

        mock_get_json.side_effect = _fake_get_json
        receipt = discussion._harvest_hn_discussion(
            url="https://news.ycombinator.com/item?id=12345",
            timeout_seconds=5,
            user_agent="ua",
            max_comments=10,
        )
        self.assertIsNotNone(receipt)
        if receipt is None:
            return
        self.assertEqual(receipt["platform"], "hackernews")
        self.assertEqual(receipt["comment_count"], 3)
        comments = json.loads(str(receipt["comments_json"]))
        self.assertEqual(len(comments), 3)

        # Empty comments path: root item exists but has no kids.
        mock_get_json.side_effect = lambda url, timeout_seconds, user_agent: (  # noqa: ARG005
            {"id": 12345, "title": "HN thread", "kids": []} if "item/12345.json" in url else None
        )
        empty_receipt = discussion._harvest_hn_discussion(
            url="https://news.ycombinator.com/item?id=12345",
            timeout_seconds=5,
            user_agent="ua",
            max_comments=10,
        )
        self.assertIsNone(empty_receipt)

        # Malformed/None payload path.
        mock_get_json.side_effect = lambda url, timeout_seconds, user_agent: None  # noqa: ARG005
        none_receipt = discussion._harvest_hn_discussion(
            url="https://news.ycombinator.com/item?id=12345",
            timeout_seconds=5,
            user_agent="ua",
            max_comments=10,
        )
        self.assertIsNone(none_receipt)


if __name__ == "__main__":
    unittest.main()
