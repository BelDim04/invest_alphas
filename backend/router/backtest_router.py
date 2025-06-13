from fastapi import APIRouter, Depends, HTTPException, Security
from typing import List, Dict, Any
from schema.models import BacktestRequest
from service.backtest_service import BacktestService
from service.alpha_service import AlphaService
from client.tinkoff_client import TinkoffClient
from utils.decorators import handle_errors
from auth.router import get_current_user_with_db
from utils.auth_deps import create_auth_client_dependency
from storage.db import Database, get_db

router = APIRouter(prefix="/api/v1/backtest", tags=["backtest"])

# Create authenticated client dependency with write scope
get_auth_tinkoff_client = create_auth_client_dependency(scopes=["backtest:write"])

# Dependency injection
def get_backtest_service(
    client: TinkoffClient = Depends(get_auth_tinkoff_client)
) -> BacktestService:
    """Dependency provider for BacktestService"""
    return BacktestService(tinkoff_client=client)

def get_alpha_service(db: Database = Depends(get_db)) -> AlphaService:
    """Dependency provider for AlphaService"""
    return AlphaService(db=db)

@router.post("/")
@handle_errors
async def backtest_alpha(
    request: BacktestRequest, 
    service: BacktestService = Depends(get_backtest_service),
    alpha_service: AlphaService = Depends(get_alpha_service),
    current_user: Dict[str, Any] = Security(get_current_user_with_db, scopes=["backtest:write"])
):
    """Run backtest for selected instruments"""
    # Load the alpha expression
    alpha = await alpha_service.get_alpha(request.alpha_id, current_user["id"])
    if not alpha:
        raise HTTPException(status_code=404, detail=f"Alpha with id {request.alpha_id} not found")
    
    if request.commission_percent is None or request.commission_percent < 0:
        raise HTTPException(status_code=400, detail="Commission percent must be a positive number")
    
    # Create a new request with the alpha expression
    request_dict = request.dict()
    request_dict['expression'] = alpha['alpha']
    return await service.run_backtest(request_dict) 