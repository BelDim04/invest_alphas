from typing import List, Dict, Any
from datetime import datetime, timedelta, timezone
import pandas as pd
import numpy as np
import vectorbt as vbt
from vectorbt.portfolio.enums import SizeType
import quantstats as qs
from utils.expression_parser import ExpressionParser
import io
import base64
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
import seaborn as sns
from io import StringIO
import tempfile
import os

from client.tinkoff_client import TinkoffClient
from schema.models import BacktestRequest, Instrument, BacktestResponse, BacktestResult
from tinkoff.invest.schemas import RealExchange
from utils.alpha_calculator import calculate_alpha1, neutralize_weights


class BacktestService:
    def __init__(self, tinkoff_client: TinkoffClient = None):
        self.tinkoff_client = tinkoff_client or TinkoffClient()
        self.parser = ExpressionParser()

    async def get_instruments(self) -> List[Instrument]:
        """Get all MOEX instruments"""
        instruments = await self.tinkoff_client.get_instruments()
        return [i for i in instruments if i.real_exchange == RealExchange.REAL_EXCHANGE_MOEX]

    async def run_backtest(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Run backtest for selected instruments"""
        if not request.get('expression'):
            raise ValueError("No expression provided")
            
        # Get historical data for all instruments
        portfolio_data = {}
        for ticker in request['instruments']:
            # Get FIGI by ticker
            figi = await self.tinkoff_client.get_figi_by_ticker(ticker)
            if not figi:
                continue
                
            # Get historical data
            data = await self.tinkoff_client.get_stock_data(
                figi,
                request['start_date'],
                request['end_date']
            )
            
            if data is not None:
                # Convert to DataFrame
                df = pd.DataFrame(data)
                df['time'] = pd.to_datetime(df['time']).dt.tz_localize(None)  # Remove timezone info
                df.set_index('time', inplace=True)
                portfolio_data[ticker] = df
        
        if not portfolio_data:
            raise ValueError("No data available for the selected instruments")
            
        # Calculate alpha signals
        signals = self._calculate_alpha_signals(portfolio_data, request['expression'])
        signals = neutralize_weights(signals)
        
        # Create portfolio
        prices = pd.DataFrame({
            name: data['close']
            for name, data in portfolio_data.items()
        })

        portfolio = vbt.Portfolio.from_orders(
            prices,
            signals,
            size_type=SizeType.Percent,
            init_cash=1000000,  # Initial capital
            fees=0.001,         # 0.1% trading fee
            freq='1D',          # Daily data
        )

        # Generate portfolio statistics
        stats = portfolio.stats()
        
        # Generate quantstats HTML report
        report_filename = f"backtest_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        report_path = os.path.join("static", "reports", report_filename)
        
        # Create reports directory if it doesn't exist
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
            
        # Calculate returns for quantstats
        # Get the total portfolio value over time and calculate returns
        portfolio_value = portfolio.value().sum(axis=1)  # Sum across all assets
        returns = pd.Series(
            portfolio_value.pct_change().fillna(0),
            index=portfolio_value.index,
            name='strategy'
        )
        
        # Calculate benchmark returns
        benchmark_returns = pd.Series(
            pd.DataFrame({ticker: data['close'] for ticker, data in portfolio_data.items()}).pct_change().fillna(0).mean(axis=1),
            index=portfolio_data[request['instruments'][0]].index,
            name='benchmark'
        )
            
        qs.reports.html(
            returns=returns,
            benchmark=benchmark_returns,
            benchmark_title="Equal Weight holding",
            output=report_path,
            title=f"Backtest Report - {request.get('expression', 'Alpha Strategy')} {request.get('instruments', '')}",
            download_filename=report_filename
        )
        
        # Generate plots
        plots = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            # Individual ticker plots
            for ticker in request['instruments']:
                fig = portfolio[ticker].plot()
                plot_path = os.path.join(temp_dir, f'{ticker}_plot.png')
                fig.write_image(plot_path)
                with open(plot_path, 'rb') as f:
                    plots[f'{ticker}_plot'] = base64.b64encode(f.read()).decode('utf-8')

        return {
            "statistics": stats.to_dict(),
            "plots": plots,
            "report_url": f"/api/static/reports/{report_filename}"
        }

    def _calculate_alpha_signals(self, portfolio_data: Dict[str, pd.DataFrame], expression: str) -> pd.DataFrame:
        """Calculate alpha signals for all instruments"""
        signals = pd.DataFrame(index=portfolio_data[list(portfolio_data.keys())[0]].index)
        
        for ticker, data in portfolio_data.items():
            context = {
                'close': data['close'],
                'open': data['open'],
                'high': data['high'],
                'low': data['low'],
                'volume': data['volume']
            }
            
            try:
                alpha_expr = self.parser.parse(expression)
                signals[ticker] = alpha_expr.evaluate(context)
            except Exception as e:
                print(f"Error calculating alpha for {ticker}: {e}")
                signals[ticker] = 0
                
        return signals
