from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Union, List
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status, Security
from fastapi.security import OAuth2PasswordBearer, SecurityScopes
from auth.models import TokenData, User, UserInDB
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Secret key for JWT
SECRET_KEY = os.getenv("SECRET_KEY", "a-very-long-secret-key-that-should-be-in-env-vars")
# JWT Algorithm
ALGORITHM = "HS256"
# Token expiration time
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 scheme for token validation
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="api/v1/auth/token",
    scopes={
        "users:read": "Read information about users",
        "users:write": "Create, update, and delete users",
        "alphas:read": "Read information about trading alphas",
        "alphas:write": "Create, update, and delete trading alphas",
        "backtest:read": "View backtest results",
        "backtest:write": "Run backtests",
        "forward:read": "View forward test results",
        "forward:write": "Run forward tests",
    }
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password"""
    return pwd_context.hash(password)


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token"""
    to_encode = data.copy()
    
    # Set expiration time
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    
    # Create JWT token
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


async def get_current_user(
    security_scopes: SecurityScopes, 
    token: str = Depends(oauth2_scheme),
    user_db = None  # This will be injected in auth_router.py
):
    """Get the current authenticated user from JWT token"""
    # Set authentication value based on scopes
    authenticate_value = f'Bearer scope="{security_scopes.scope_str}"' if security_scopes.scopes else "Bearer"
    
    # Define the credentials exception that will be raised for invalid tokens
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": authenticate_value},
    )
    
    try:
        # Decode token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # Extract critical information
        username = payload.get("sub")
        user_id = payload.get("user_id")
        token_scopes = payload.get("scopes", [])
        
        # Validate essential token data
        if not username or not user_id:
            raise credentials_exception
            
        # Get user from database directly using ID (more efficient)
        user = await user_db.get_user(user_id)
        if not user:
            raise credentials_exception
            
        # Check if user is disabled
        if user.get("disabled"):
            raise HTTPException(status_code=400, detail="Inactive user")
        
        # Verify token scopes
        for scope in security_scopes.scopes:
            if scope not in token_scopes:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Not enough permissions. Required: {scope}",
                    headers={"WWW-Authenticate": authenticate_value},
                )
        
        return user
        
    except JWTError:
        raise credentials_exception


async def get_current_active_user(
    current_user: Dict[str, Any] = Security(get_current_user, scopes=[])
) -> Dict[str, Any]:
    """Get current user and ensure they are active"""
    if current_user.get("disabled"):
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user 