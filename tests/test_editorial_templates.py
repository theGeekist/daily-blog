import unittest

from daily_blog.editorial.templates import static_editorial_package


class TestEditorialTemplates(unittest.TestCase):
    def test_strategy_templates_produce_distinct_structures(self) -> None:
        ai_outline = static_editorial_package(
            "Artificial Intelligence",
            "Model capability and reliability changes",
            strategy="implementation-guide",
        )["outline_markdown"]
        business_outline = static_editorial_package(
            "Business",
            "Market conditions are shifting",
            strategy="analysis",
        )["outline_markdown"]

        self.assertIn("## Step-by-Step", ai_outline)
        self.assertIn("## Competing Evidence", business_outline)
        self.assertNotEqual(ai_outline, business_outline)


if __name__ == "__main__":
    unittest.main()
