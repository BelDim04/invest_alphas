from fastapi import APIRouter, Depends
from typing import List
from datetime import datetime
from schema.models import Instrument, BacktestRequest, BacktestResult
from service.backtest_service import BacktestService
from client.tinkoff_client import TinkoffClient
from storage.redis_storage import RedisStorage
from utils.decorators import handle_errors

# Create single instances of our services
_tinkoff_client = TinkoffClient()
_redis_storage = RedisStorage()
_backtest_service = BacktestService(tinkoff_client=_tinkoff_client, redis_storage=_redis_storage)

def get_backtest_service():
    """Dependency provider for BacktestService"""
    return _backtest_service

router = APIRouter(prefix="/api/v1", tags=["backtest"])

@router.get("/instruments", response_model=List[Instrument])
@handle_errors
async def get_instruments(service: BacktestService = Depends(get_backtest_service)):
    """Get available instruments for backtesting"""
    return await service.get_instruments()

@router.post("/backtest", response_model=dict)
@handle_errors
async def backtest_alpha(request: BacktestRequest, service: BacktestService = Depends(get_backtest_service)):
    """Run backtest for selected instruments"""
    return await service.run_backtest(request) 