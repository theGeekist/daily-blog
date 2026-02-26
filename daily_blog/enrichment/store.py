import sqlite3


def init_enrichment_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS enrichment_sources (
            topic_id TEXT NOT NULL,
            query_terms_json TEXT NOT NULL,
            domain TEXT NOT NULL,
            url TEXT NOT NULL,
            stance TEXT NOT NULL,
            credibility_guess TEXT NOT NULL,
            fetched_ok INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (topic_id, url)
        )
        """
    )
    conn.commit()


def init_discussion_receipts_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS discussion_receipts (
            topic_id TEXT NOT NULL,
            source_url TEXT NOT NULL,
            platform TEXT NOT NULL,
            query_used TEXT NOT NULL,
            receipt_text TEXT NOT NULL,
            comment_count INTEGER NOT NULL,
            problem_statements_json TEXT NOT NULL,
            solution_statements_json TEXT NOT NULL,
            model_route_used TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (topic_id, source_url)
        )
        """
    )
    conn.commit()


def enrichment_has_model_route(conn: sqlite3.Connection) -> bool:
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(enrichment_sources)").fetchall()
        if len(row) > 1
    }
    return "model_route_used" in columns


def topic_clusters_has_normalized_label(conn: sqlite3.Connection) -> bool:
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(topic_clusters)").fetchall()
        if len(row) > 1
    }
    return "normalized_topic_label" in columns


def upsert_enrichment_source(
    conn: sqlite3.Connection,
    has_model_route_column: bool,
    topic_id: str,
    query_terms_json: str,
    source: dict[str, str | int],
    now: str,
    model_route_used: str,
) -> None:
    if has_model_route_column:
        conn.execute(
            """
            INSERT OR REPLACE INTO enrichment_sources (
                topic_id, query_terms_json, domain, url, stance,
                credibility_guess, fetched_ok, created_at, model_route_used
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                topic_id,
                query_terms_json,
                source["domain"],
                source["url"],
                source["stance"],
                source["credibility_guess"],
                source["fetched_ok"],
                now,
                model_route_used,
            ),
        )
        return

    conn.execute(
        """
        INSERT OR REPLACE INTO enrichment_sources (
            topic_id, query_terms_json, domain, url, stance,
            credibility_guess, fetched_ok, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            topic_id,
            query_terms_json,
            source["domain"],
            source["url"],
            source["stance"],
            source["credibility_guess"],
            source["fetched_ok"],
            now,
        ),
    )


def upsert_discussion_receipt(
    conn: sqlite3.Connection,
    *,
    topic_id: str,
    source_url: str,
    platform: str,
    query_used: str,
    receipt_text: str,
    comment_count: int,
    problem_statements_json: str,
    solution_statements_json: str,
    model_route_used: str,
    now: str,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO discussion_receipts (
            topic_id, source_url, platform, query_used, receipt_text, comment_count,
            problem_statements_json, solution_statements_json, model_route_used, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            topic_id,
            source_url,
            platform,
            query_used,
            receipt_text,
            comment_count,
            problem_statements_json,
            solution_statements_json,
            model_route_used,
            now,
        ),
    )
