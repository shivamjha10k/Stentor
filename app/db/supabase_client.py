"""
Supabase client — lazy singleton.
Initializes the connection using SUPABASE_URL and SUPABASE_KEY from .env.
Only connects when first called (not at import time).
"""

import os
import logging
from supabase import create_client, Client

logger = logging.getLogger("rag.db")

_client: Client | None = None


def get_supabase_client() -> Client:
    """
    Return the Supabase client singleton.
    Creates the client on first call, reuses it after that.
    """
    global _client
    if _client is not None:
        return _client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")

    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_KEY must be set in .env file. "
            "Get these from your Supabase project → Settings → API."
        )

    logger.info("Connecting to Supabase...")
    _client = create_client(url, key)
    logger.info("Supabase connected")
    return _client
