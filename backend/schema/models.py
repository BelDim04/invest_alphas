from datetime import date, datetime
from typing import List, Optional
from pydantic import BaseModel, Field
from tinkoff.invest.schemas import RealExchange

class Instrument(BaseModel):
    figi: str = Field(..., description="Financial Instrument Global Identifier")
    ticker: str = Field(..., description="Trading ticker symbol")
    name: str = Field(..., description="Full name of the instrument")
    currency: str = Field(..., description="Currency of the instrument")
    real_exchange: RealExchange = Field(..., description="Exchange where the instrument is traded")
    liquidity_flag: Optional[bool] = Field(None, description="Flag indicating if the instrument has good liquidity")
    basic_asset: Optional[str] = Field(None, description="Underlying asset for derivative instruments")
    lot_size: int = Field(..., description="Minimum trading lot size")

class BacktestRequest(BaseModel):
    instruments: List[str] = Field(..., description="List of instrument tickers to backtest")
    alpha_id: int = Field(..., description="ID of the alpha to use in backtest")
    start_date: datetime = Field(..., description="Start date for the backtest period")
    end_date: datetime = Field(..., description="End date for the backtest period")
    commission_percent: float = Field(..., description="Commission percentage to apply in calculations")

class BacktestResult(BaseModel):
    instrument: str = Field(..., description="Ticker of the tested instrument")
    start_date: datetime = Field(..., description="Start date of the backtest")
    end_date: datetime = Field(..., description="End date of the backtest")
    pnl: float = Field(..., description="Profit and Loss result")
    sharpe_ratio: float = Field(..., description="Sharpe ratio of the backtest")

class BacktestResponse(BaseModel):
    results: List[BacktestResult] = Field(..., description="List of backtest results")

class ForwardTestRequest(BaseModel):
    instruments: List[str] = Field(..., description="List of instrument tickers to use in forward test")
    alpha_id: int = Field(..., description="ID of the alpha to use in forward test")
    trade_on_weekends: bool = Field(False, description="Whether to trade on weekends")  # Default to False for backward compatibility

class Error(BaseModel):
    error: str = Field(..., description="Error code")
    message: str = Field(..., description="Error message details")

# Alpha-related schemas
class AlphaBase(BaseModel):
    alpha: str = Field(..., description="Alpha expression formula")

class AlphaCreate(AlphaBase):
    pass

class AlphaUpdate(AlphaBase):
    pass

class AlphaResponse(AlphaBase):
    id: int = Field(..., description="Unique identifier of the alpha")
    created_at: datetime = Field(..., description="Timestamp when the alpha was created")

    class Config:
        from_attributes = True

class AlphaListResponse(BaseModel):
    alphas: List[AlphaResponse] = Field(..., description="List of alpha expressions") 