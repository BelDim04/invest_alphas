import logging
from typing import Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Client cache to store TinkoffClient instances by user ID
_client_cache: Dict[int, Any] = {}

# Function to clear client cache for a specific user
def clear_client_cache(user_id: int):
    """
    Clear the cached TinkoffClient for a specific user.
    This should be called when a user updates their token.
    """
    if user_id in _client_cache:
        del _client_cache[user_id]
        logger.info(f"Cleared cached Tinkoff client for user ID {user_id}")
        return True
    return False

# Function to get client from cache
def get_client_from_cache(user_id: int):
    """Get cached client if it exists"""
    return _client_cache.get(user_id)

# Function to add client to cache
def add_client_to_cache(user_id: int, client: Any):
    """Add client to cache"""
    _client_cache[user_id] = client 