from fastapi import APIRouter, Depends, HTTPException, Security
from typing import List, Dict, Any
from schema.models import BacktestRequest
from service.backtest_service import BacktestService
from client.tinkoff_client import get_tinkoff_client, TinkoffClient
from utils.decorators import handle_errors
from auth.router import get_current_user_with_db
from utils.auth_deps import create_auth_client_dependency

router = APIRouter(prefix="/api/v1/backtest", tags=["backtest"])

# Create authenticated client dependency with write scope
get_auth_tinkoff_client = create_auth_client_dependency(scopes=["backtest:write"])

# Dependency injection
def get_backtest_service(
    client: TinkoffClient = Depends(get_auth_tinkoff_client)
):
    """Dependency provider for BacktestService"""
    return BacktestService(tinkoff_client=client)

@router.post("/", response_model=dict)
@handle_errors
async def backtest_alpha(
    request: BacktestRequest, 
    service: BacktestService = Depends(get_backtest_service)
):
    """Run backtest for selected instruments"""
    return await service.run_backtest(request) 