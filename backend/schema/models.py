from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel
from tinkoff.invest.schemas import RealExchange

class Instrument(BaseModel):
    figi: str
    ticker: str
    name: str
    currency: str
    real_exchange: RealExchange
    liquidity_flag: Optional[bool] = None
    basic_asset: Optional[str] = None

class BacktestRequest(BaseModel):
    instruments: List[str]
    start_date: datetime
    end_date: datetime

class BacktestResult(BaseModel):
    instrument: str
    start_date: datetime
    end_date: datetime
    pnl: float
    sharpe_ratio: float

class BacktestResponse(BaseModel):
    results: List[BacktestResult]

class Error(BaseModel):
    error: str
    message: str 