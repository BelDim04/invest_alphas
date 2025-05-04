from typing import List, Dict, Any
from datetime import datetime, timedelta, timezone
import pandas as pd
import numpy as np
import vectorbt as vbt
from vectorbt.portfolio.enums import SizeType

from client.tinkoff_client import TinkoffClient
from schema.models import BacktestRequest, Instrument
from tinkoff.invest.schemas import RealExchange
from utils.alpha_calculator import calculate_alpha1, neutralize_weights

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

        # Calculate alpha signals
        alpha_signals = self._calculate_alpha_signals(prices_data)
        #alpha_signals = neutralize_weights(alpha_signals)

        # Create portfolio
        prices = pd.DataFrame({
            name: data['close']
            for name, data in prices_data.items()
        })

        portfolio = vbt.Portfolio.from_orders(
            prices,
            alpha_signals,
            size_type=SizeType.Percent,
            init_cash=1000000,  # Initial capital
            fees=0.001,         # 0.1% trading fee
            freq='1D',          # Daily data
        )

        # Generate portfolio statistics
        stats = portfolio.stats()
        print(stats)

        return {
            "statistics": stats.to_dict()
        }

    def _calculate_alpha_signals(self, stock_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Calculate alpha signals for each stock"""
        alpha_signals = {}
        
        for stock_name, df in stock_data.items():
            alpha_signals[stock_name] = calculate_alpha1(df)
        
        print(alpha_signals)
        return pd.DataFrame(alpha_signals)
