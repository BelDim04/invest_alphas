from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime


class UserBase(BaseModel):
    email: EmailStr
    username: str
    full_name: Optional[str] = None
    disabled: Optional[bool] = False
    tinkoff_token: Optional[str] = None


class UserCreate(UserBase):
    password: str = Field(..., min_length=8)


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    username: Optional[str] = None
    full_name: Optional[str] = None
    disabled: Optional[bool] = None
    password: Optional[str] = Field(None, min_length=8)
    tinkoff_token: Optional[str] = None


class UserInDB(UserBase):
    id: int
    hashed_password: str
    created_at: datetime


class User(UserBase):
    id: int
    created_at: datetime

    class Config:
        orm_mode = True


class Token(BaseModel):
    access_token: str
    token_type: str


# This class is kept for backward compatibility and documentation purposes
# It represents the structure of JWT token data
class TokenData(BaseModel):
    username: str
    user_id: int
    scopes: List[str] = [] 