from typing import List, Dict, Any, Callable, Awaitable
from fastapi import Security, Depends
from client.tinkoff_client import get_tinkoff_client, TinkoffClient
from auth.router import get_current_user_with_db

def create_auth_client_dependency(scopes: List[str]) -> Callable:
    """
    Creates a dependency function that gets the current user with specified scopes
    and passes it to get_tinkoff_client.
    
    Args:
        scopes: List of required scopes for this dependency
        
    Returns:
        An async function that can be used as a FastAPI dependency
    """
    
    async def get_auth_tinkoff_client(
        current_user: Dict[str, Any] = Security(get_current_user_with_db, scopes=scopes)
    ) -> TinkoffClient:
        """Get authenticated Tinkoff client for the current user with required scopes"""
        return await get_tinkoff_client(current_user)
    
    return get_auth_tinkoff_client 