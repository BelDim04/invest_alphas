from typing import List, Dict, Any, Callable, Awaitable, Optional
from fastapi import Security, Depends, HTTPException, status
from fastapi.security import SecurityScopes
from client.tinkoff_client import get_tinkoff_client, TinkoffClient
from auth.router import get_current_user_with_db
from auth.db import UserDB, get_user_db

def create_auth_client_dependency(scopes: List[str]) -> Callable:
    """
    Creates a dependency that provides a Tinkoff client with the user's token.
    The token is retrieved securely from the database and passed through the
    dependency chain without being exposed to the frontend.
    
    Args:
        required_scopes: List of required scopes for authentication
        
    Returns:
        Dependency function that provides a Tinkoff client
    """
    async def get_auth_tinkoff_client(
        current_user: dict = Security(get_current_user_with_db, scopes=scopes),
        user_db: UserDB = Depends(get_user_db)
    ):
        """
        Dependency that provides a Tinkoff client with the user's token.
        
        Args:
            current_user: Current authenticated user
            user_db: UserDB instance for token retrieval
            
        Returns:
            TinkoffClient: Client instance with user's token
            
        Raises:
            HTTPException: If user is not authenticated or token is not set
        """
        # Get token securely from database
        user_token = await user_db.get_tinkoff_token(current_user["id"])
        
        # Pass token securely to client
        return await get_tinkoff_client(current_user, user_token)
        
    return get_auth_tinkoff_client 