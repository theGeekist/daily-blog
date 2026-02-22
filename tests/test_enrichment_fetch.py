import unittest

from daily_blog.enrichment.fetch import _build_search_queries, _prioritize_discovered_urls
from daily_blog.enrichment.helpers import credibility_for_domain


class TestEnrichmentFetch(unittest.TestCase):
    def test_build_search_queries_prefers_specific_terms(self) -> None:
        queries = _build_search_queries(
            topic_label="General Engineering Topics",
            query_terms=["general", "engineering", "observability", "incident", "postmortem"],
        )
        self.assertGreaterEqual(len(queries), 1)
        self.assertIn("observability", queries[0])
        self.assertIn("incident", queries[0])
        self.assertNotIn("general", queries[0])

    def test_prioritize_discovered_urls_non_reddit_first(self) -> None:
        urls = [
            "https://www.reddit.com/r/programming/comments/abc123/thread",
            "https://www.nist.gov/ai/risk-management-framework",
            "https://old.reddit.com/r/technology/comments/xyz987/post",
            "https://www.acm.org/articles/how-teams-scale",
        ]
        prioritized = _prioritize_discovered_urls(urls, limit=4)
        self.assertEqual(len(prioritized), 4)
        self.assertTrue(prioritized[0].startswith("https://www.nist.gov/"))
        self.assertTrue(prioritized[1].startswith("https://www.acm.org/"))


class TestCredibilityForDomain(unittest.TestCase):
    def test_legacy_high_domains(self) -> None:
        for domain in ("nature.com", "ieee.org", "acm.org"):
            with self.subTest(domain=domain):
                self.assertEqual(credibility_for_domain(domain), "high")

    def test_gov_edu_tlds_are_high(self) -> None:
        self.assertEqual(credibility_for_domain("nist.gov"), "high")
        self.assertEqual(credibility_for_domain("mit.edu"), "high")

    def test_new_tech_high_domains(self) -> None:
        for domain in (
            "techcrunch.com",
            "arstechnica.com",
            "wired.com",
            "anthropic.com",
            "openai.com",
            "huggingface.co",
            "bloomberg.com",
            "wsj.com",
            "github.blog",
        ):
            with self.subTest(domain=domain):
                self.assertEqual(credibility_for_domain(domain), "high")

    def test_arxiv_is_now_high(self) -> None:
        # arxiv.org was medium; moved to high in Phase 6
        self.assertEqual(credibility_for_domain("arxiv.org"), "high")

    def test_medium_domains(self) -> None:
        for domain in ("github.com", "reddit.com", "wikipedia.org", "stackexchange.com"):
            with self.subTest(domain=domain):
                self.assertEqual(credibility_for_domain(domain), "medium")

    def test_org_tld_is_medium(self) -> None:
        self.assertEqual(credibility_for_domain("someproject.org"), "medium")

    def test_unknown_domain_is_low(self) -> None:
        self.assertEqual(credibility_for_domain("randomsite.io"), "low")

    def test_url_path_upgrade_requires_trusted_domain(self) -> None:
        # Strict mode: avoid false positive credibility inflation on arbitrary domains.
        # Path hints only upgrade trusted domains (.edu/.gov/.org or explicit allowlist highs).
        for path in ("/papers/", "/research/", "/publications/", "/docs/"):
            url = f"https://somecompany.com{path}my-paper"
            with self.subTest(path=path):
                self.assertEqual(credibility_for_domain("somecompany.com", url), "low")

    def test_url_path_upgrade_for_trusted_tlds(self) -> None:
        for domain in ("mit.edu", "nist.gov", "example.org"):
            for path in ("/papers/", "/research/", "/publications/", "/docs/"):
                url = f"https://{domain}{path}resource"
                with self.subTest(domain=domain, path=path):
                    self.assertEqual(credibility_for_domain(domain, url), "high")

    def test_url_path_upgrade_for_allowlisted_high_domain(self) -> None:
        domain = "anthropic.com"
        for path in ("/papers/", "/research/", "/publications/", "/docs/"):
            url = f"https://{domain}{path}note"
            with self.subTest(path=path):
                self.assertEqual(credibility_for_domain(domain, url), "high")

    def test_url_path_upgrade_uses_path_not_query(self) -> None:
        url = "https://randomsite.com/?next=/docs/paper"
        self.assertEqual(credibility_for_domain("randomsite.com", url), "low")

    def test_url_path_upgrade_does_not_downgrade_existing_high(self) -> None:
        # High domains stay high regardless
        self.assertEqual(credibility_for_domain("nature.com", "https://nature.com/article"), "high")

    def test_no_url_uses_domain_only(self) -> None:
        self.assertEqual(credibility_for_domain("github.com"), "medium")
        self.assertEqual(credibility_for_domain("github.com", ""), "medium")


if __name__ == "__main__":
    unittest.main()
