from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone
import pandas as pd
import numpy as np
import vectorbt as vbt
from vectorbt.portfolio.enums import SizeType

from client.tinkoff_client import TinkoffClient
from schema.models import BacktestRequest, Instrument
from tinkoff.invest.schemas import RealExchange
from utils.alpha_calculator import calculate_alpha1, neutralize_weights, compile_formula, SMA, STD, MAX, MIN, SIGN
from storage.db import Database
from fastapi import HTTPException


class BacktestService:
    def __init__(self, tinkoff_client: TinkoffClient = None):
        self.tinkoff_client = tinkoff_client or TinkoffClient()

    async def get_instruments(self) -> List[Instrument]:
        """Get all MOEX instruments"""
        instruments = await self.tinkoff_client.get_instruments()
        return [i for i in instruments if i.real_exchange == RealExchange.REAL_EXCHANGE_MOEX]

    async def run_backtest(self, request: BacktestRequest) -> Dict[str, Any]:
        """Run backtest for selected instruments"""
        # Get historical data for each instrument
        prices_data = {}
        for ticker in request.instruments:
            figi = await self.tinkoff_client.get_figi_by_ticker(ticker)
            data = await self.tinkoff_client.get_stock_data(figi, request.start_date, request.end_date)
            prices_data[ticker] = data

        print(prices_data)

        # Calculate alpha signals for each instrument (choose formula or default)
        alpha_signals = await self._calculate_alpha_signals(prices_data, request.alpha_id)
        # alpha_signals = neutralize_weights(alpha_signals)  # (Optional step for portfolio neutralization)

        # Create price DataFrame (closing prices)
        prices = pd.DataFrame({
            name: data['close']
            for name, data in prices_data.items()
        })

        portfolio = vbt.Portfolio.from_orders(
            prices,
            alpha_signals,
            size_type=SizeType.Percent,
            init_cash=1000000,  # Initial capital
            fees=0.001,  # 0.1% trading fee
            freq='1D',  # Daily frequency
        )

        # Generate portfolio statistics
        stats = portfolio.stats()
        print(stats)

        return {
            "statistics": stats.to_dict()
        }

    async def _calculate_alpha_signals(self, stock_data: Dict[str, pd.DataFrame],
                                       alpha_id: Optional[int] = None) -> pd.DataFrame:
        """Calculate alpha signal series for each stock (use specified formula if provided)."""
        alpha_signals: Dict[str, pd.Series] = {}
        if alpha_id:
            # Fetch the alpha formula from the database
            db = Database()
            await db.connect()
            alpha_entry = await db.get_alpha(alpha_id)
            if not alpha_entry:
                raise HTTPException(status_code=404, detail="Alpha not found")
            formula_str: str = alpha_entry["alpha"]
            # Compile formula once for efficiency
            code_obj = compile_formula(formula_str)
            for stock_name, df in stock_data.items():
                # Prepare environment with series data for the formula
                env = {
                    "open": df.get("open"),  # use .get to handle missing columns safely
                    "high": df.get("high"),
                    "low": df.get("low"),
                    "close": df.get("close"),
                    "volume": df.get("volume"),
                    "returns": None  # will compute below
                }
                # Compute returns series (percentage change of close)
                if env["close"] is not None:
                    env["returns"] = env["close"].pct_change()
                else:
                    env["returns"] = None
                # Add function references to the environment for evaluation
                env.update({"sma": SMA, "std": STD, "max": MAX, "min": MIN, "sign": SIGN, "abs": abs})
                # Evaluate the compiled formula in the restricted environment
                result = eval(code_obj, {"__builtins__": None}, env)
                # If the result is a scalar or numpy array, convert it to a Series to align with dates
                if not isinstance(result, pd.Series):
                    result = pd.Series(result, index=df.index)
                alpha_signals[stock_name] = result
        else:
            # No formula ID provided: default to using the built-in alpha1 formula for all stocks
            for stock_name, df in stock_data.items():
                alpha_signals[stock_name] = calculate_alpha1(df)
        print(alpha_signals)
        return pd.DataFrame(alpha_signals)
