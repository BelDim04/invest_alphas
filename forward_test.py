import asyncio
import logging
from datetime import datetime, timedelta, timezone
import numpy as np
import pandas as pd
from dotenv import load_dotenv
import os
from tinkoff.invest import (
    CandleInterval,
    OrderDirection,
    OrderType,
    Quotation,
    SecurityTradingStatus,
    MoneyValue,
)
from tinkoff.invest.sandbox.async_client import AsyncSandboxClient
from tinkoff.invest.schemas import InstrumentStatus, InstrumentExchangeType, PortfolioStreamResponse, PositionsStreamResponse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ForwardTestService:
    INITIAL_BALANCE = 1000000  # Initial balance in RUB
    
    def __init__(self, token: str, target_stocks: list):
        self.token = token
        self.target_stocks = target_stocks
        self.ticker_to_figi = {}
        self.ticker_to_lot = {}  # Store lot size for each instrument
        self.account_id = None
        self.client = None
        self.positions = {}
        self.prices_data = {}
        self.total_value = 0
        self.portfolio_task = None
        self.positions_task = None
        self.is_running = False
        self.start_date = None  # Add start_date attribute

    async def initialize(self):
        """Initialize the service and get necessary data"""
        # Close all existing sandbox accounts
        accounts = await self.client.sandbox.get_sandbox_accounts()
        for account in accounts.accounts:
            logger.info(f"Closing existing sandbox account: {account.id}")
            await self.client.sandbox.close_sandbox_account(account_id=account.id)
        
        # Create new sandbox account
        logger.info("Creating new sandbox account...")
        account = await self.client.sandbox.open_sandbox_account()
        self.account_id = account.account_id
        self.start_date = datetime.now(timezone.utc)  # Set start_date when account is created
        logger.info(f"Created new sandbox account: {self.account_id}")
        
        # Add initial balance
        await self.client.sandbox.sandbox_pay_in(
            account_id=self.account_id,
            amount=MoneyValue(units=self.INITIAL_BALANCE, nano=0, currency="rub")
        )
        logger.info(f"Added initial {self.INITIAL_BALANCE} RUB to sandbox account")
        
        # Get instruments and create ticker to FIGI mapping
        instruments = await self.client.instruments.shares(
            instrument_status=InstrumentStatus.INSTRUMENT_STATUS_BASE,
            instrument_exchange=InstrumentExchangeType.INSTRUMENT_EXCHANGE_UNSPECIFIED
        )
        self.ticker_to_figi = {
            instrument.ticker: instrument.figi 
            for instrument in instruments.instruments
            if instrument.ticker in self.target_stocks
        }
        
        # Store lot sizes
        self.ticker_to_lot = {
            instrument.ticker: instrument.lot 
            for instrument in instruments.instruments
            if instrument.ticker in self.target_stocks
        }
        
        logger.info(f"Tracking stocks: {self.ticker_to_figi}")
        logger.info(f"Lot sizes: {self.ticker_to_lot}")

    async def get_current_positions(self):
        """Get current positions in the account"""
        portfolio = await self.client.sandbox.get_sandbox_portfolio(account_id=self.account_id)
        self.positions = {
            position.figi: position.quantity.units 
            for position in portfolio.positions
        }
        logger.info(f"Current positions: {self.positions}")
        return self.positions

    async def get_historical_data(self, days_back: int = 1):
        """Get historical data for target stocks"""
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days_back)
        
        # Calculate chunk size based on candle interval
        # For 1-minute candles, we can request up to 1 day at a time
        chunk_days = 1
        chunk_size = timedelta(days=chunk_days)
        
        for ticker, figi in self.ticker_to_figi.items():
            current_start = start_date
            all_candles = []
            
            while current_start < end_date:
                current_end = min(current_start + chunk_size, end_date)
                
                try:
                    candles = await self.client.market_data.get_candles(
                        figi=figi,
                        from_=current_start,
                        to=current_end,
                        interval=CandleInterval.CANDLE_INTERVAL_1_MIN
                    )
                    all_candles.extend(candles.candles)
                    logger.info(f"Retrieved candles for {ticker} from {current_start} to {current_end}")
                    
                except Exception as e:
                    logger.error(f"Error getting candles for {ticker}: {e}")
                    break
                
                current_start = current_end
                # Add a small delay between requests to avoid rate limiting
                await asyncio.sleep(0.1)
            
            # Convert all candles to DataFrame
            df = pd.DataFrame([{
                'time': c.time,
                'open': self.quotation_to_float(c.open),
                'high': self.quotation_to_float(c.high),
                'low': self.quotation_to_float(c.low),
                'close': self.quotation_to_float(c.close),
                'volume': c.volume
            } for c in all_candles])
            
            self.prices_data[ticker] = df
            logger.info(f"Retrieved total {len(df)} candles for {ticker}")

    def neutralize_weights(self, weights: pd.Series) -> pd.Series:
        """Neutralize alpha weights to make them market neutral"""
        # Demean to make sum = 0
        weights = weights - weights.mean()
        
        # Scale so absolute values sum to 1
        abs_sum = weights.abs().sum()
        if abs_sum > 0:
            weights = weights / abs_sum
            
        return weights

    def calculate_alpha1(self):
        """Calculate alpha1 signals for all stocks"""
        alpha_signals = {}
        
        for stock_name, df in self.prices_data.items():
            returns = df['close'].pct_change()
            returns_stddev = returns.rolling(window=20).std()
            
            power_term = np.where(returns < 0, 
                                returns_stddev, 
                                df['close'])
            signed_power = np.sign(power_term) * (np.abs(power_term) ** 2)
            
            ts_argmax = pd.Series(signed_power).rolling(5).apply(np.argmax)
            alpha = ts_argmax.rank(pct=True) - 0.5
            
            alpha_signals[stock_name] = alpha.iloc[-1]  # Get latest signal
        
        # Convert to Series and neutralize
        alpha_series = pd.Series(alpha_signals)
        neutralized_alpha = self.neutralize_weights(alpha_series)
        
        return neutralized_alpha.to_dict()

    async def execute_trades(self, alpha_signals: dict):
        """Execute trades based on alpha signals"""
        logger.info("Starting trade execution with signals:")
        for ticker, signal in alpha_signals.items():
            logger.info(f"{ticker}: signal={signal:.4f}, current_position={self.positions.get(self.ticker_to_figi[ticker], 0)}")
        
        # Calculate base position size (10% of initial balance)
        base_position_size = self.INITIAL_BALANCE * 0.1
        
        for ticker, signal in alpha_signals.items():
            figi = self.ticker_to_figi[ticker]
            lot_size = self.ticker_to_lot[ticker]
            current_position = self.positions.get(figi, 0)
            
            # Get current price from historical data
            if ticker not in self.prices_data or self.prices_data[ticker].empty:
                logger.error(f"No price data available for {ticker}")
                continue
                
            current_price = self.prices_data[ticker]['close'].iloc[-1]
            
            # Calculate target position value based on signal
            target_value = base_position_size * signal
            
            # Convert to number of lots
            target_lots = round(target_value / (current_price * lot_size))
            
            # Calculate position change needed (in lots)
            position_change = target_lots - (current_position // lot_size)
            
            if position_change > 0:
                # Buy order
                try:
                    await self.client.sandbox.post_sandbox_order(
                        figi=figi,
                        quantity=position_change,  # This is in lots
                        direction=OrderDirection.ORDER_DIRECTION_BUY,
                        account_id=self.account_id,
                        order_type=OrderType.ORDER_TYPE_MARKET
                    )
                    logger.info(f"Executed BUY order for {ticker}: {position_change} lots ({position_change * lot_size} shares) (signal: {signal:.4f}, target_value: {target_value:.2f} RUB, price: {current_price:.2f} RUB)")
                except Exception as e:
                    logger.error(f"Failed to execute BUY order for {ticker}: {str(e)}")
            elif position_change < 0:
                # Sell order
                try:
                    await self.client.sandbox.post_sandbox_order(
                        figi=figi,
                        quantity=abs(position_change),  # This is in lots
                        direction=OrderDirection.ORDER_DIRECTION_SELL,
                        account_id=self.account_id,
                        order_type=OrderType.ORDER_TYPE_MARKET
                    )
                    logger.info(f"Executed SELL order for {ticker}: {abs(position_change)} lots ({abs(position_change) * lot_size} shares) (signal: {signal:.4f}, target_value: {target_value:.2f} RUB, price: {current_price:.2f} RUB)")
                except Exception as e:
                    logger.error(f"Failed to execute SELL order for {ticker}: {str(e)}")

    @staticmethod
    def quotation_to_float(quotation: Quotation) -> float:
        """Convert Tinkoff Quotation to float"""
        return float(quotation.units + quotation.nano / 1e9)

    async def start_streams(self):
        """Start portfolio and positions streams"""
        logger.info("Starting portfolio and positions streams...")
        self.is_running = True
        
        # Start processing streams
        self.portfolio_task = asyncio.create_task(self._process_portfolio_stream())
        self.positions_task = asyncio.create_task(self._process_positions_stream())
        logger.info("Streams started successfully")

    async def _process_portfolio_stream(self):
        """Process portfolio stream updates"""
        try:
            logger.info("Starting portfolio stream processing...")
            async for response in self.client.operations_stream.portfolio_stream(
                accounts=[self.account_id],
                ping_delay_ms=60000
            ):
                if not self.is_running:
                    break
                    
                # Handle subscription status
                if hasattr(response, 'subscriptions') and response.subscriptions:
                    if hasattr(response.subscriptions, 'accounts') and response.subscriptions.accounts:
                        for account in response.subscriptions.accounts:
                            if account and hasattr(account, 'account_id') and hasattr(account, 'subscription_status'):
                                logger.info(f"Portfolio subscription status for {account.account_id}: {account.subscription_status}")
                    if hasattr(response.subscriptions, 'stream_id'):
                        logger.info(f"Portfolio stream ID: {response.subscriptions.stream_id}")
                    continue
                    
                if (hasattr(response, 'portfolio') and response.portfolio and 
                    hasattr(response.portfolio, 'total_amount_portfolio') and 
                    response.portfolio.total_amount_portfolio):
                    self.total_value = response.portfolio.total_amount_portfolio.units + response.portfolio.total_amount_portfolio.nano / 1e9
                    logger.info(f"Portfolio update: {self.total_value:.2f} RUB")
                    
                    # Update positions from portfolio response
                    if hasattr(response.portfolio, 'positions'):
                        self.positions = {
                            pos.figi: int(pos.quantity.units)
                            for pos in response.portfolio.positions
                            if pos and hasattr(pos, 'figi') and hasattr(pos, 'quantity') and hasattr(pos.quantity, 'units')
                        }
                        logger.info(f"Positions update from portfolio: {self.positions}")

        except asyncio.CancelledError:
            logger.info("Portfolio stream cancelled")
        except Exception as e:
            logger.error(f"Error in portfolio stream: {e}")
            logger.exception("Detailed portfolio stream error:")  # This will log the full traceback
        finally:
            logger.info("Portfolio stream processing ended")

    async def _process_positions_stream(self):
        """Process positions stream updates"""
        try:
            logger.info("Starting positions stream processing...")
            async for response in self.client.operations_stream.positions_stream(
                accounts=[self.account_id],
                with_initial_positions=True
            ):
                if not self.is_running:
                    break
                    
                # Handle subscription status
                if hasattr(response, 'subscriptions') and response.subscriptions:
                    if hasattr(response.subscriptions, 'accounts') and response.subscriptions.accounts:
                        for account in response.subscriptions.accounts:
                            if account and hasattr(account, 'account_id') and hasattr(account, 'subscription_status'):
                                logger.info(f"Positions subscription status for {account.account_id}: {account.subscription_status}")
                    if hasattr(response.subscriptions, 'stream_id'):
                        logger.info(f"Positions stream ID: {response.subscriptions.stream_id}")
                    continue
                    
                if hasattr(response, 'position') and response.position:
                    position_data = response.position
                    if hasattr(position_data, 'securities') and position_data.securities:
                        self.positions = {
                            position.figi: int(position.balance)
                            for position in position_data.securities
                            if position and hasattr(position, 'figi') and hasattr(position, 'balance')
                        }
                        logger.info(f"Positions update from stream: {self.positions}")

        except asyncio.CancelledError:
            logger.info("Positions stream cancelled")
        except Exception as e:
            logger.error(f"Error in positions stream: {e}")
            logger.exception("Detailed positions stream error:")  # This will log the full traceback
        finally:
            logger.info("Positions stream processing ended")

    async def run(self):
        """Main execution loop"""
        async with AsyncSandboxClient(self.token) as client:
            self.client = client
            await self.initialize()
            await self.start_streams()
            
            while True:
                try:
                    # Get and log portfolio value
                    portfolio = await self.client.sandbox.get_sandbox_portfolio(account_id=self.account_id)
                    total_value = portfolio.total_amount_portfolio.units + portfolio.total_amount_portfolio.nano / 1e9
                    logger.info(f"Current portfolio value: {total_value:.2f} RUB")
                    
                    # Get current positions
                    await self.get_current_positions()
                    
                    # Get historical data
                    await self.get_historical_data()
                    
                    # Calculate alpha signals
                    alpha_signals = self.calculate_alpha1()
                    logger.info(f"Alpha signals: {alpha_signals}")
                    
                    # Execute trades
                    await self.execute_trades(alpha_signals)
                    
                    # Wait for next iteration
                    await asyncio.sleep(60)  # Check every minute
                    
                except Exception as e:
                    logger.error(f"Error in main loop: {e}")
                    await asyncio.sleep(60)

    async def close(self):
        """Close streams and cleanup"""
        logger.info("Shutting down streams...")
        self.is_running = False
        
        if self.portfolio_task:
            self.portfolio_task.cancel()
            try:
                await self.portfolio_task
            except asyncio.CancelledError:
                pass
            
        if self.positions_task:
            self.positions_task.cancel()
            try:
                await self.positions_task
            except asyncio.CancelledError:
                pass
            
        logger.info("Streams shut down successfully")
