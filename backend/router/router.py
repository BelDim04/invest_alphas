from fastapi import APIRouter, Depends, Security
from typing import List, Dict, Any

from schema.models import Instrument
from client.tinkoff_client import TinkoffClient
from service.backtest_service import BacktestService
from utils.decorators import handle_errors
from utils.auth_deps import create_auth_client_dependency

# Main router with common endpoints
router = APIRouter(prefix="/api/v1", tags=["common"])

# Create authenticated client dependency with read scope
get_auth_tinkoff_client = create_auth_client_dependency(scopes=["backtest:read"])

# Dependency injection for services used in common endpoints
def get_backtest_service(
    client: TinkoffClient = Depends(get_auth_tinkoff_client)
):
    """Dependency provider for BacktestService"""
    return BacktestService(tinkoff_client=client)

@router.get("/instruments", response_model=List[Instrument])
@handle_errors
async def get_instruments(
    service: BacktestService = Depends(get_backtest_service)
):
    """Get available instruments for trading"""
    return await service.get_instruments() 