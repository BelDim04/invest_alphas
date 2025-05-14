from typing import Optional, List, Dict, Any
from datetime import datetime
from storage.db import get_db, Database
from auth.models import UserCreate, UserInDB, UserUpdate
from auth.security import get_password_hash, verify_password
import base64
import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from fastapi import Depends

# Load or generate encryption key for API tokens
# In production, this should be stored in a secure key management service
def get_encryption_key():
    key_env = os.getenv("API_KEY_ENCRYPTION_KEY")
    if not key_env:
        # Generate a key derived from SECRET_KEY for development
        # In production, use a proper key management solution
        secret = os.getenv("SECRET_KEY", "fallback-secret-key-not-for-production")
        salt = b'api_token_salt'  # In production, store this securely
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(secret.encode()))
    else:
        key = key_env.encode()
    return key

# Initialize Fernet cipher with the key
encryption_key = get_encryption_key()
cipher = Fernet(encryption_key)

# Functions to encrypt and decrypt API tokens
def encrypt_token(token: str) -> str:
    """Encrypt an API token before storing it in the database"""
    if not token:
        return None
    return cipher.encrypt(token.encode()).decode()

def decrypt_token(encrypted_token: str) -> str:
    """Decrypt an API token retrieved from the database"""
    if not encrypted_token:
        return None
    return cipher.decrypt(encrypted_token.encode()).decode()


class UserDB:
    def __init__(self, db: Database):
        self.db = db

    async def init_tables(self):
        """Initialize the users table if it doesn't exist"""
        async with self.db.pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(50) UNIQUE NOT NULL,
                    email VARCHAR(100) UNIQUE NOT NULL,
                    full_name VARCHAR(100),
                    hashed_password VARCHAR(255) NOT NULL,
                    disabled BOOLEAN DEFAULT FALSE,
                    tinkoff_token VARCHAR(1000),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

    async def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Get a user by username"""
        async with self.db.pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT id, username, email, full_name, hashed_password, disabled, created_at FROM users WHERE username = $1',
                username
            )
            if not row:
                return None
            return dict(row)

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get a user by email"""
        async with self.db.pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT id, username, email, full_name, hashed_password, disabled, created_at FROM users WHERE email = $1',
                email
            )
            if not row:
                return None
            return dict(row)

    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get a user by ID"""
        async with self.db.pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT id, username, email, full_name, hashed_password, disabled, created_at FROM users WHERE id = $1',
                user_id
            )
            if not row:
                return None
            return dict(row)

    async def get_tinkoff_token(self, user_id: int) -> Optional[str]:
        """
        Get the Tinkoff API token for a user.
        This is the only method that should access the token directly.
        
        Args:
            user_id: User ID to get token for
            
        Returns:
            str: Decrypted token if exists, None otherwise
        """
        async with self.db.pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT tinkoff_token FROM users WHERE id = $1',
                user_id
            )
            if not row or not row['tinkoff_token']:
                return None
            return decrypt_token(row['tinkoff_token'])

    async def create_user(self, user: UserCreate) -> Dict[str, Any]:
        """Create a new user"""
        hashed_password = get_password_hash(user.password)
        
        # Encrypt token if provided
        encrypted_token = encrypt_token(user.tinkoff_token) if user.tinkoff_token else None
        
        async with self.db.pool.acquire() as conn:
            user_id = await conn.fetchval(
                '''
                INSERT INTO users (username, email, full_name, hashed_password, tinkoff_token)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                ''',
                user.username,
                user.email,
                user.full_name,
                hashed_password,
                encrypted_token
            )
            
            return await self.get_user(user_id)

    async def update_user(self, user_id: int, user_update: UserUpdate) -> Dict[str, Any]:
        """Update a user"""
        # Get current user
        current_user = await self.get_user(user_id)
        if not current_user:
            return None

        # Build update query dynamically
        query_parts = []
        params = []
        param_index = 1

        if user_update.username is not None:
            query_parts.append(f"username = ${param_index}")
            params.append(user_update.username)
            param_index += 1

        if user_update.email is not None:
            query_parts.append(f"email = ${param_index}")
            params.append(user_update.email)
            param_index += 1

        if user_update.full_name is not None:
            query_parts.append(f"full_name = ${param_index}")
            params.append(user_update.full_name)
            param_index += 1

        if user_update.disabled is not None:
            query_parts.append(f"disabled = ${param_index}")
            params.append(user_update.disabled)
            param_index += 1

        if user_update.password is not None:
            query_parts.append(f"hashed_password = ${param_index}")
            params.append(get_password_hash(user_update.password))
            param_index += 1
            
        if user_update.tinkoff_token is not None:
            query_parts.append(f"tinkoff_token = ${param_index}")
            # Encrypt the token before storing
            encrypted_token = encrypt_token(user_update.tinkoff_token)
            params.append(encrypted_token)
            param_index += 1

        if not query_parts:
            return current_user  # No updates to perform

        # Add user_id to params
        params.append(user_id)

        # Build final query
        update_query = f"UPDATE users SET {', '.join(query_parts)} WHERE id = ${param_index} RETURNING id"

        # Execute update
        async with self.db.pool.acquire() as conn:
            await conn.execute(update_query, *params)
            return await self.get_user(user_id)

    async def delete_user(self, user_id: int) -> bool:
        """Delete a user"""
        async with self.db.pool.acquire() as conn:
            result = await conn.execute(
                'DELETE FROM users WHERE id = $1',
                user_id
            )
            return result.split()[-1] == '1'

    async def authenticate_user(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """Authenticate a user with username and password"""
        user = await self.get_user_by_username(username)
        
        if not user:
            return None
        
        if not verify_password(password, user["hashed_password"]):
            return None
            
        return user

    async def list_users(self) -> List[Dict[str, Any]]:
        """List all users"""
        async with self.db.pool.acquire() as conn:
            rows = await conn.fetch(
                'SELECT id, username, email, full_name, disabled, created_at FROM users ORDER BY created_at DESC'
            )
            return [dict(row) for row in rows] 

# Dependency for UserDB
def get_user_db(db: Database = Depends(get_db)):
    """User DB dependency"""
    return UserDB(db)
