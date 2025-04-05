from fastapi import APIRouter, Depends
from typing import List
from datetime import datetime
from schema.models import Instrument, BacktestRequest, BacktestResult
from service.backtest_service import BacktestService
from utils.decorators import handle_errors

router = APIRouter(prefix="/api/v1", tags=["backtest"])

@router.get("/instruments", response_model=List[Instrument])
@handle_errors
async def get_instruments(service: BacktestService = Depends()):
    """Get available instruments for backtesting"""
    return await service.get_instruments()

@router.post("/backtest", response_model=dict)
@handle_errors
async def backtest_alpha(request: BacktestRequest, service: BacktestService = Depends()):
    """Run backtest for selected instruments"""
    return await service.run_backtest(request) 