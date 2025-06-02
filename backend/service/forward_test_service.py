import asyncio
import logging
from datetime import datetime, timedelta, timezone
import pandas as pd
from typing import Dict, List, Optional

from client.tinkoff_client import TinkoffClient
from utils.alpha_calculator import calculate_alpha1, neutralize_weights
from tinkoff.invest import (
    CandleInterval,
    OrderDirection,
    OrderType,
    Quotation,
    SecurityTradingStatus,
    MoneyValue,
)
from tinkoff.invest.schemas import InstrumentStatus, InstrumentExchangeType
from schema.models import Instrument
from utils.expression_parser import ExpressionParser


logger = logging.getLogger(__name__)

class ForwardTestService:
    
    def __init__(self, account_id: str, target_stocks: List[str], tinkoff_client: Optional[TinkoffClient] = None,
                 expression: Optional[str] = None):
        self.account_id = account_id
        self.target_stocks = target_stocks
        self.client = tinkoff_client or TinkoffClient()
        self.positions = {}
        self.prices_data = {}
        self.total_value = 0
        self.portfolio_task = None
        self.positions_task = None
        self.is_running = False
        self.target_instruments: Dict[str, Instrument] = {}
        self.start_date = self.client.account_creation_date
        self.expression = expression
        self.last_execution_date = None  # Track the date of last execution


    async def initialize(self):
        """Initialize the service and get necessary data"""
        # Get instruments and verify all target stocks exist
        instruments = await self.client.get_instruments()
        self.target_instruments = {
            i.ticker: i for i in instruments 
            if i.ticker in self.target_stocks
        }
        
        if len(self.target_instruments) != len(self.target_stocks):
            missing = set(self.target_stocks) - set(self.target_instruments.keys())
            raise ValueError(f"Some target stocks not found: {missing}")
        
        logger.info(f"Tracking stocks: {list(self.target_instruments.keys())}")

    async def get_current_positions(self):
        """Get current positions in the account"""
        portfolio = await self.client.get_portfolio(self.account_id)
        self.positions = {
            position.figi: position.quantity.units 
            for position in portfolio.positions
        }
        self.total_value = portfolio.total_amount_portfolio.units + portfolio.total_amount_portfolio.nano / 1e9
        logger.info(f"Current positions: {self.positions}")
        logger.info(f"Total portfolio value: {self.total_value:.2f} RUB")
        return self.positions

    async def get_historical_data(self, days_back: int = 30):
        """Get historical data for target stocks"""
        end_date = datetime.now(timezone.utc)
        start_date = self.start_date
        
        for instrument in self.target_instruments.values():
            try:
                data = await self.client.get_stock_data(
                    figi=instrument.figi,
                    from_date=start_date - timedelta(days=days_back),
                    to_date=end_date,
                    interval=CandleInterval.CANDLE_INTERVAL_DAY
                )
                self.prices_data[instrument.ticker] = data
                logger.info(f"Retrieved {len(data)} daily candles for {instrument.ticker}")
            except Exception as e:
                logger.error(f"Error getting data for {instrument.ticker}: {e}")

    def calculate_alpha_signals(self) -> Dict[str, float]:
        """Calculate alpha signals for all stocks"""
        alpha_signals = {}

        if self.expression:
            parser = ExpressionParser()
            expr = parser.parse(self.expression)

            for ticker, df in self.prices_data.items():
                context = {col: df[col] for col in df.columns if col != 'time'}
                series = expr.evaluate(context)
                alpha_signals[ticker] = series.iloc[-1]
        else:
            for ticker, df in self.prices_data.items():
                alpha = calculate_alpha1(df)
                alpha_signals[ticker] = alpha.iloc[-1]

        # Convert to DataFrame and neutralize
        alpha_df = pd.DataFrame([alpha_signals])
        neutralized_alpha = neutralize_weights(alpha_df).iloc[0]
        
        return neutralized_alpha.to_dict()

    async def execute_trades(self, alpha_signals: Dict[str, float]):
        """Execute trades based on alpha signals"""
        logger.info("Starting trade execution with signals:")
        for ticker, signal in alpha_signals.items():
            if signal == None:
                continue
            logger.info(f"{ticker}: signal={signal:.4f}, current_position={self.positions.get(self.target_instruments[ticker].figi, 0)}")
        
        # Calculate base position size (10% of initial balance)
        current_portfolio = await self.client.get_portfolio(self.account_id)
        current_value = current_portfolio.total_amount_portfolio.units + current_portfolio.total_amount_portfolio.nano / 1e9
        base_position_size = current_value * 0.95
        
        # Prepare trade actions
        trade_actions = []
        for ticker, signal in alpha_signals.items():
            if signal == None:
                continue
            instrument = self.target_instruments[ticker]
            current_position = self.positions.get(instrument.figi, 0)
            
            # Get current price from historical data
            if ticker not in self.prices_data or self.prices_data[ticker].empty:
                logger.error(f"No price data available for {ticker}")
                continue
                
            current_price = self.prices_data[ticker]['close'].iloc[-1]
            
            # Calculate target position value based on signal
            target_value = base_position_size * signal
            
            # Convert to number of lots
            target_lots = round(target_value / (current_price * instrument.lot_size))
            
            # Calculate position change needed (in lots)
            position_change = target_lots - (current_position // instrument.lot_size)
            
            trade_actions.append({
                'ticker': ticker,
                'instrument': instrument,
                'position_change': position_change,
                'signal': signal,
                'target_value': target_value,
                'current_price': current_price
            })
        
        # Execute all sell orders first
        for action in trade_actions:
            if action['position_change'] < 0:
                try:
                    await self.client.post_order(
                        account_id=self.account_id,
                        figi=action['instrument'].figi,
                        quantity=abs(action['position_change']),
                        direction=OrderDirection.ORDER_DIRECTION_SELL,
                        order_type=OrderType.ORDER_TYPE_MARKET
                    )
                    logger.info(f"Executed SELL order for {action['ticker']}: {abs(action['position_change'])} lots ({abs(action['position_change']) * action['instrument'].lot_size} shares) (signal: {action['signal']:.4f}, target_value: {action['target_value']:.2f} RUB, price: {action['current_price']:.2f} RUB)")
                except Exception as e:
                    logger.error(f"Failed to execute SELL order for {action['ticker']}: {str(e)}")
        
        # Execute all buy orders after sells
        for action in trade_actions:
            if action['position_change'] > 0:
                try:
                    await self.client.post_order(
                        account_id=self.account_id,
                        figi=action['instrument'].figi,
                        quantity=action['position_change'],
                        direction=OrderDirection.ORDER_DIRECTION_BUY,
                        order_type=OrderType.ORDER_TYPE_MARKET
                    )
                    logger.info(f"Executed BUY order for {action['ticker']}: {action['position_change']} lots ({action['position_change'] * action['instrument'].lot_size} shares) (signal: {action['signal']:.4f}, target_value: {action['target_value']:.2f} RUB, price: {action['current_price']:.2f} RUB)")
                except Exception as e:
                    logger.error(f"Failed to execute BUY order for {action['ticker']}: {str(e)}")

    async def run(self):
        """Main execution loop - runs once per day during trading hours"""
        self.is_running = True
        logger.info(f"Starting forward test service for account {self.account_id}")
        
        while self.is_running:
            try:
                # Get current time in Moscow timezone (MOEX trading hours)
                now = datetime.now(timezone.utc) + timedelta(hours=3)  # UTC+3 for Moscow
                current_date = now.date()
                
                # Check if we already executed today
                if self.last_execution_date == current_date:
                    logger.debug(f"Already executed trades for {current_date}, waiting for next trading day")
                    await asyncio.sleep(300)  # Check every 5 minutes
                    continue
                
                # Check if it's a weekday and within trading hours (10:00 - 18:45 Moscow time)
                if now.weekday() < 5 and 10 <= now.hour < 18 or (now.hour == 18 and now.minute <= 45):
                    logger.info(f"Starting daily execution for {current_date}")
                    
                    # Get current positions
                    await self.get_current_positions()
                    
                    # Get historical data
                    await self.get_historical_data()
                    
                    # Calculate alpha signals
                    alpha_signals = self.calculate_alpha_signals()
                    logger.info(f"Daily alpha signals: {alpha_signals}")
                    
                    # Execute trades
                    await self.execute_trades(alpha_signals)
                    
                    # Mark execution as completed for today
                    self.last_execution_date = current_date
                    logger.info(f"Daily execution completed for {current_date}, next execution will be on next trading day")
                else:
                    logger.debug(f"Outside trading hours on {current_date}, waiting for next check")
                
                await asyncio.sleep(300)  # Check every 5 minutes
                
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                await asyncio.sleep(60)  # On error, wait for 1 minute before retrying
        
        logger.info(f"Stopping forward test service for account {self.account_id}") 