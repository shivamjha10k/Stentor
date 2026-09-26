"""
Knowledge base seeding service.
Reads curated JSON files from knowledge/ directory,
embeds each document using OpenAI, and upserts into knowledge_embeddings.

Run ONCE via POST /api/v1/knowledge/seed before the pipeline is operational.
"""

import json
import os
import logging
from pathlib import Path

from app.services.embedding import embed_text
from app.db.queries import upsert_knowledge_doc, get_knowledge_count

logger = logging.getLogger("rag.seeding")


# Map filenames to their expected categories
KNOWLEDGE_FILES = {
    "fraud_patterns.json": "fraud_pattern",
    "compliance_rules.json": "compliance",
    "risk_heuristics.json": "risk_heuristic",
}


def seed_knowledge_base() -> dict:
    """
    Read all knowledge JSON files, embed each document, and upsert into DB.

    Returns:
        {
            "seeded": True,
            "documents_processed": 16,
            "by_category": { "fraud_pattern": 6, "compliance": 5, "risk_heuristic": 5 },
            "total_in_db": 16
        }
    """
    knowledge_dir = Path(__file__).parent.parent.parent / "knowledge"

    if not knowledge_dir.exists():
        raise RuntimeError(f"Knowledge directory not found: {knowledge_dir}")

    logger.info(f"Seeding from {knowledge_dir}")

    documents_processed = 0
    by_category = {}
    errors = []

    for filename, expected_category in KNOWLEDGE_FILES.items():
        filepath = knowledge_dir / filename

        if not filepath.exists():
            logger.warning(f"File not found: {filename}")
            errors.append(f"File not found: {filename}")
            continue

        with open(filepath, "r", encoding="utf-8") as f:
            docs = json.load(f)

        logger.info(f"Processing {filename} ({len(docs)} docs)")

        category_count = 0

        for doc in docs:
            doc_id = doc["doc_id"]
            category = doc.get("category", expected_category)
            title = doc["title"]
            content = doc["content"]
            metadata = doc.get("metadata", {})

            logger.info(f"  [{doc_id}] {title}")

            # Embed the content (this is what gets searched against)
            try:
                embedding = embed_text(content)
            except Exception as e:
                logger.error(f"Embedding failed for {doc_id}: {str(e)}")
                errors.append(f"Embedding failed for {doc_id}: {str(e)}")
                continue

            # Upsert into knowledge_embeddings
            try:
                upsert_knowledge_doc(
                    doc_id=doc_id,
                    category=category,
                    title=title,
                    content=content,
                    embedding=embedding,
                    metadata=metadata,
                )
            except Exception as e:
                logger.error(f"Upsert failed for {doc_id}: {str(e)}")
                errors.append(f"Upsert failed for {doc_id}: {str(e)}")
                continue

            category_count += 1
            documents_processed += 1

        by_category[expected_category] = category_count

    total_in_db = get_knowledge_count()
    logger.info(f"Seeding complete | {documents_processed} docs | {total_in_db} in DB")

    result = {
        "seeded": True,
        "documents_processed": documents_processed,
        "by_category": by_category,
        "total_in_db": total_in_db,
    }

    if errors:
        result["errors"] = errors

    return result
