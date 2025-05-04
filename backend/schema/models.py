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
    lot_size: int

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

class ForwardTestRequest(BaseModel):
    instruments: List[str]

class Error(BaseModel):
    error: str
    message: str

# Alpha-related schemas
class AlphaBase(BaseModel):
    alpha: str

class AlphaCreate(AlphaBase):
    pass

class AlphaUpdate(AlphaBase):
    pass

class AlphaResponse(AlphaBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True

class AlphaListResponse(BaseModel):
    alphas: List[AlphaResponse] 