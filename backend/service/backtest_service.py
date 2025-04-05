from typing import List, Dict, Any
from datetime import datetime, timedelta, timezone
import pandas as pd
import numpy as np
import vectorbt as vbt
from vectorbt.portfolio.enums import SizeType

from client.tinkoff_client import TinkoffClient
from storage.redis_storage import RedisStorage
from schema.models import BacktestRequest, Instrument
from tinkoff.invest.schemas import RealExchange

class BacktestService:
    def __init__(self):
        self.storage = RedisStorage()
        self.tinkoff_client = TinkoffClient()

    async def get_instruments(self) -> List[Instrument]:
        """Get all MOEX instruments"""
        cached_instruments = await self.storage.get_instruments()
        if cached_instruments:
            return [i for i in cached_instruments if i.real_exchange == RealExchange.REAL_EXCHANGE_MOEX]
        
        instruments = self.tinkoff_client.get_instruments()
        await self.storage.set_instruments(instruments)
        return [i for i in instruments if i.real_exchange == RealExchange.REAL_EXCHANGE_MOEX]

    async def run_backtest(self, request: BacktestRequest) -> Dict[str, Any]:
        """Run backtest for selected instruments"""
        # Get historical data for each instrument
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=365*5)  # 5 years of data
        
        prices_data = {}
        for ticker in request.instruments:
            figi = self.tinkoff_client.get_figi_by_ticker(ticker)
            data = self.tinkoff_client.get_stock_data(figi, start_date, end_date)
            prices_data[ticker] = data

        # Calculate alpha signals
        alpha_signals = self._calculate_alpha_signals(prices_data)
        # alpha_signals = self._neutralize_weights(alpha_signals)

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

        return {
            "statistics": stats.to_dict()
        }

    def _calculate_alpha_signals(self, stock_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """Calculate alpha signals for each stock"""
        alpha_signals = {}
        
        for stock_name, df in stock_data.items():
            returns = df['close'].pct_change()
            returns_stddev = returns.rolling(window=20).std()
            
            power_term = np.where(returns < 0, 
                                returns_stddev, 
                                df['close'])
            signed_power = np.sign(power_term) * (np.abs(power_term) ** 2)
            
            ts_argmax = pd.Series(signed_power).rolling(5).apply(np.argmax)
            alpha = ts_argmax.rank(pct=True) - 0.5
            
            alpha_signals[stock_name] = alpha
        
        return pd.DataFrame(alpha_signals)

    def _neutralize_weights(self, weights: pd.DataFrame) -> pd.DataFrame:
        """Neutralize weights to make sum = 0 and scale absolute values to sum to 1"""
        # Demean to make sum = 0
        weights = weights.sub(weights.mean(axis=1), axis=0)
        
        # Scale so absolute values sum to 1
        abs_sum = weights.abs().sum(axis=1)
        weights = weights.div(abs_sum, axis=0)
        
        return weights 