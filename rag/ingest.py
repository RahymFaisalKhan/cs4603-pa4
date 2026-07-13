"""Corpus ingestion into Databricks Vector Search (Task 0.3).

Run inside a Databricks notebook with Spark, ai_parse_document, and ai_prep_search.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value or "<" in value:
        raise OSError(f"Set {name} to a real value before running ingestion")
    return value


def build_chunks_table(spark, volume_path: str, chunks_table: str) -> None:
    # read_files requires a literal path in Databricks SQL. Escape quotes before
    # interpolation; ai_prep_search then converts parsed elements into chunks.
    escaped_path = volume_path.replace("'", "''")
    spark.sql(
        f"""
        CREATE OR REPLACE TABLE {chunks_table}
        TBLPROPERTIES (delta.enableChangeDataFeed = true)
        AS
        WITH parsed AS (
          SELECT path, ai_parse_document(content, map('version', '2.0')) AS doc
          FROM read_files('{escaped_path}', format => 'binaryFile')
        ), prepared AS (
          SELECT path, ai_prep_search(doc) AS chunks FROM parsed
        )
        SELECT
          coalesce(chunk.value:chunk_id::STRING, uuid()) AS chunk_id,
          chunk.value:chunk_to_retrieve::STRING AS chunk_to_retrieve,
          chunk.value:chunk_to_embed::STRING AS chunk_to_embed,
          regexp_extract(path, '[^/]+$', 0) AS source,
          coalesce(
            try_cast(chunk.value:pages[0].page_id AS INT) + 1,
            try_cast(chunk.value:metadata.page_number AS INT),
            try_cast(chunk.value:metadata.page AS INT),
            0
          ) AS page
        FROM prepared,
        LATERAL variant_explode(prepared.chunks) AS root,
        LATERAL variant_explode(root.value:contents) AS chunk
        WHERE root.key = 'document'
          AND chunk.value:chunk_to_retrieve IS NOT NULL
          AND trim(chunk.value:chunk_to_retrieve::STRING) <> ''
          AND chunk.value:chunk_to_embed IS NOT NULL
          AND trim(chunk.value:chunk_to_embed::STRING) <> ''
        """
    )


def create_index() -> None:
    from databricks.vector_search.client import VectorSearchClient

    endpoint = _require("VECTOR_SEARCH_ENDPOINT")
    index = _require("VECTOR_SEARCH_INDEX")
    source = _require("SOURCE_TABLE")
    embeddings = os.environ.get("EMBEDDINGS_ENDPOINT", "databricks-gte-large-en")
    client = VectorSearchClient()
    try:
        client.get_endpoint(endpoint)
    except Exception:  # SDK exception types vary across vector-search releases.
        client.create_endpoint(name=endpoint, endpoint_type="STANDARD")
    client.wait_for_endpoint(endpoint)
    try:
        handle = client.get_index(endpoint_name=endpoint, index_name=index)
        handle.sync()
    except Exception:
        handle = client.create_delta_sync_index(
            endpoint_name=endpoint,
            index_name=index,
            source_table_name=source,
            pipeline_type="TRIGGERED",
            primary_key="chunk_id",
            embedding_source_column="chunk_to_embed",
            embedding_model_endpoint_name=embeddings,
        )
    handle.wait_until_ready()


def ingest(spark, volume_path: str) -> None:
    """Build the configured chunk table and create/sync its Vector Search index."""
    table = _require("SOURCE_TABLE")
    build_chunks_table(spark, volume_path, table)
    create_index()
