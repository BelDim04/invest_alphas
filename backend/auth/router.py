from fastapi import APIRouter, Depends, HTTPException, status, Security, BackgroundTasks
from fastapi.security import OAuth2PasswordRequestForm
from typing import List, Optional, Dict, Any
from datetime import timedelta
from functools import partial
from pydantic import BaseModel

from storage.db import get_db, Database
from auth.db import UserDB, get_user_db
from auth.models import User, UserCreate, UserUpdate, Token
from auth.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    get_current_user,
    get_current_active_user,
    oauth2_scheme,
    SecurityScopes
)
from utils.decorators import handle_errors
from client.client_cache import clear_client_cache
from client.tinkoff_client import AsyncSandboxClient

# Create auth router
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# Model for Tinkoff token update
class TinkoffTokenUpdate(BaseModel):
    token: str

# Create a dependency to properly inject UserDB into get_current_user
async def get_current_user_with_db(
    security_scopes: SecurityScopes, 
    token: str = Depends(oauth2_scheme),
    user_db: UserDB = Depends(get_user_db)
):
    """Get current user with UserDB dependency properly injected"""
    return await get_current_user(security_scopes, token, user_db)

# Login endpoint
@router.post("/token", response_model=Token)
@handle_errors
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    user_db: UserDB = Depends(get_user_db)
):
    """Authenticate user and return JWT token"""
    # Check if user exists and password is correct
    user = await user_db.authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Check if user is active
    if user.get("disabled"):
        raise HTTPException(status_code=400, detail="Inactive user")
    
    # Create token data with scopes
    # For simplicity, all users get all scopes
    # In a real app, you would store and retrieve user-specific scopes
    scopes = form_data.scopes if form_data.scopes else [
        "users:read", "alphas:read", "alphas:write", 
        "backtest:read", "backtest:write", 
        "forward:read", "forward:write"
    ]
    
    # Add admin scope if the user is an admin (username 'admin' for demo)
    if user.get("username") == "admin":
        scopes.append("users:write")
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={
            "sub": user["username"],
            "user_id": user["id"],
            "scopes": scopes
        },
        expires_delta=access_token_expires,
    )
    
    return {"access_token": access_token, "token_type": "bearer"}

# Registration endpoint
@router.post("/register", response_model=dict)
@handle_errors
async def register_new_user(
    user: UserCreate, 
    user_db: UserDB = Depends(get_user_db),
    background_tasks: BackgroundTasks = None
):
    """Register a new user"""
    # Check if username already exists
    db_user = await user_db.get_user_by_username(user.username)
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    # Check if email already exists
    db_user = await user_db.get_user_by_email(user.email)
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Create user
    user_data = await user_db.create_user(user)
    
    # In a real app, you would send a verification email here
    # background_tasks.add_task(send_verification_email, user.email)
    
    return {
        "message": "User created successfully",
        "user_id": user_data["id"]
    }

# Get current user info
@router.get("/me", response_model=dict)
@handle_errors
async def read_users_me(
    current_user: Dict[str, Any] = Security(
        get_current_user_with_db, 
        scopes=["users:read"]
    )
):
    """Get current user info"""
    # Remove sensitive information
    if "hashed_password" in current_user:
        del current_user["hashed_password"]
    
    return current_user

# Update current user
@router.put("/me", response_model=dict)
@handle_errors
async def update_user_me(
    user_update: UserUpdate,
    current_user: Dict[str, Any] = Security(
        get_current_user_with_db, 
        scopes=["users:read"]
    ),
    user_db: UserDB = Depends(get_user_db)
):
    """Update current user info"""
    # Update user
    updated_user = await user_db.update_user(current_user["id"], user_update)
    
    # Remove sensitive information
    if "hashed_password" in updated_user:
        del updated_user["hashed_password"]
    
    return updated_user

# Admin: List all users
@router.get("/users", response_model=List[dict])
@handle_errors
async def list_users(
    current_user: Dict[str, Any] = Security(
        get_current_user_with_db, 
        scopes=["users:write"]
    ),
    user_db: UserDB = Depends(get_user_db)
):
    """List all users (admin only)"""
    users = await user_db.list_users()
    return users

# Admin: Get user by ID
@router.get("/users/{user_id}", response_model=dict)
@handle_errors
async def get_user(
    user_id: int,
    current_user: Dict[str, Any] = Security(
        get_current_user_with_db, 
        scopes=["users:write"]
    ),
    user_db: UserDB = Depends(get_user_db)
):
    """Get user by ID (admin only)"""
    user = await user_db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Remove sensitive information
    if "hashed_password" in user:
        del user["hashed_password"]
    
    return user

# Admin: Update any user
@router.put("/users/{user_id}", response_model=dict)
@handle_errors
async def update_user(
    user_id: int,
    user_update: UserUpdate,
    current_user: Dict[str, Any] = Security(
        get_current_user_with_db, 
        scopes=["users:write"]
    ),
    user_db: UserDB = Depends(get_user_db)
):
    """Update any user (admin only)"""
    # Check if user exists
    user = await user_db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Update user
    updated_user = await user_db.update_user(user_id, user_update)
    
    # Remove sensitive information
    if "hashed_password" in updated_user:
        del updated_user["hashed_password"]
    
    return updated_user

# Admin: Delete user
@router.delete("/users/{user_id}", response_model=dict)
@handle_errors
async def delete_user(
    user_id: int,
    current_user: Dict[str, Any] = Security(
        get_current_user_with_db, 
        scopes=["users:write"]
    ),
    user_db: UserDB = Depends(get_user_db)
):
    """Delete a user (admin only)"""
    # Check if user exists
    user = await user_db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Delete user
    success = await user_db.delete_user(user_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete user")
    
    return {"message": "User deleted successfully"}

# Update Tinkoff API token
@router.post("/tinkoff", response_model=dict)
@handle_errors
async def update_tinkoff_token(
    token_update: TinkoffTokenUpdate,
    current_user: Dict[str, Any] = Security(get_current_user_with_db, scopes=[]),
    user_db: UserDB = Depends(get_user_db)
):
    """Update the Tinkoff API token for the current user"""
    # Validate token by making a test API call
    try:
        async with AsyncSandboxClient(token_update.token) as client:
            # Try to get accounts as a simple validation
            await client.users.get_accounts()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid Tinkoff API token: {str(e)}"
        )
    
    # Create a UserUpdate object with just the token field
    user_update = UserUpdate(tinkoff_token=token_update.token)
    
    # Update the user
    updated_user = await user_db.update_user(current_user["id"], user_update)
    
    # Check if update was successful
    if not updated_user:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update Tinkoff token"
        )
    
    # Clear the client cache for this user
    clear_client_cache(current_user["id"])
    
    return {"message": "Tinkoff API token updated successfully"} 