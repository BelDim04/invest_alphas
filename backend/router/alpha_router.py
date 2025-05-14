from fastapi import APIRouter, Depends, Security
from schema.models import AlphaCreate, AlphaUpdate, AlphaResponse, AlphaListResponse
from service.alpha_service import AlphaService
from storage.db import get_db, Database
from auth.router import get_current_user_with_db
from typing import Dict, Any

router = APIRouter(prefix="/api/v1/alphas", tags=["alphas"])

# Dependency injection
def get_alpha_service(db: Database = Depends(get_db)):
    """Dependency provider for AlphaService"""
    return AlphaService(db=db)

@router.post("/", response_model=AlphaResponse)
async def create_alpha(
    alpha: AlphaCreate, 
    service: AlphaService = Depends(get_alpha_service),
    current_user: Dict[str, Any] = Security(get_current_user_with_db, scopes=["alphas:write"])
):
    return await service.create_alpha(alpha.alpha)

@router.get("/", response_model=AlphaListResponse)
async def get_all_alphas(
    service: AlphaService = Depends(get_alpha_service),
    current_user: Dict[str, Any] = Security(get_current_user_with_db, scopes=["alphas:read"])
):
    alphas = await service.get_all_alphas()
    return AlphaListResponse(alphas=alphas)

@router.get("/{alpha_id}", response_model=AlphaResponse)
async def get_alpha(
    alpha_id: int, 
    service: AlphaService = Depends(get_alpha_service),
    current_user: Dict[str, Any] = Security(get_current_user_with_db, scopes=["alphas:read"])
):
    return await service.get_alpha(alpha_id)

@router.put("/{alpha_id}", response_model=AlphaResponse)
async def update_alpha(
    alpha_id: int, 
    alpha: AlphaUpdate, 
    service: AlphaService = Depends(get_alpha_service),
    current_user: Dict[str, Any] = Security(get_current_user_with_db, scopes=["alphas:write"])
):
    return await service.update_alpha(alpha_id, alpha.alpha)

@router.delete("/{alpha_id}", response_model=AlphaResponse)
async def delete_alpha(
    alpha_id: int, 
    service: AlphaService = Depends(get_alpha_service),
    current_user: Dict[str, Any] = Security(get_current_user_with_db, scopes=["alphas:write"])
):
    return await service.delete_alpha(alpha_id) 