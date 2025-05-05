import asyncio
import logging
from datetime import datetime, timezone, timedelta
import pandas as pd
from typing import Dict, List, Optional, Any
import os
from tinkoff.invest import CandleInterval, OrderDirection, OrderType, MoneyValue
from tinkoff.invest.schemas import InstrumentExchangeType, RealExchange, PortfolioResponse, PostOrderResponse, OperationState
from tinkoff.invest import InstrumentStatus
from tinkoff.invest.sandbox.async_client import AsyncSandboxClient
from fastapi import Depends, HTTPException, status, Security

from schema.models import Instrument
from auth.security import SecurityScopes
from client.client_cache import get_client_from_cache, add_client_to_cache

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class TinkoffClient:
    def __init__(self, token: str):
        """
        Initialize TinkoffClient with a user-specific token.
        
        Args:
            token: User-specific Tinkoff API token.
        """
        if not token:
            raise ValueError("Tinkoff API token is required")
        self.token = token
        self._ticker_to_figi: Dict[str, str] = {}
        self._instruments: List[Instrument] = []
        self._instruments_loaded = False

    async def close_all_sandbox_accounts(self):
        """Close all existing sandbox accounts"""
        async with AsyncSandboxClient(self.token) as client:
            try:
                # Get all sandbox accounts
                accounts = await client.sandbox.get_sandbox_accounts()
                logger.info(f"Found {len(accounts.accounts)} sandbox accounts")

                # Close all sandbox accounts
                for account in accounts.accounts:
                    await client.sandbox.close_sandbox_account(account_id=account.id)
                    logger.info(f"Closed sandbox account: {account.id}")
            except Exception as e:
                logger.error(f"Error closing sandbox accounts: {str(e)}")
                raise

    async def create_sandbox_account(self, initial_balance: float = 1000000.0) -> str:
        """Create a new sandbox account with initial balance"""
        # First close all existing sandbox accounts
        await self.close_all_sandbox_accounts()
        
        async with AsyncSandboxClient(self.token) as client:
            # Create new sandbox account
            account = await client.sandbox.open_sandbox_account()
            account_id = account.account_id
            logger.info(f"Created new sandbox account: {account_id}")
            
            # Add initial balance
            await client.sandbox.sandbox_pay_in(
                account_id=account_id,
                amount=MoneyValue(units=int(initial_balance), nano=0, currency="rub")
            )
            
            return account_id

    async def close_sandbox_account(self, account_id: str):
        """Close a sandbox account"""
        async with AsyncSandboxClient(self.token) as client:
            await client.sandbox.close_sandbox_account(account_id=account_id)

    async def get_instruments(self, force_refresh: bool = False) -> List[Instrument]:
        """Get all instruments, with caching"""
        if not force_refresh and self._instruments_loaded:
            return self._instruments
            
        async with AsyncSandboxClient(self.token) as client:
            shares = (await client.instruments.shares(
                instrument_status=InstrumentStatus.INSTRUMENT_STATUS_BASE,
                instrument_exchange=InstrumentExchangeType.INSTRUMENT_EXCHANGE_UNSPECIFIED
            )).instruments

            futures = (await client.instruments.futures(
                instrument_status=InstrumentStatus.INSTRUMENT_STATUS_BASE,
                instrument_exchange=InstrumentExchangeType.INSTRUMENT_EXCHANGE_UNSPECIFIED
            )).instruments

            # Combine shares and futures
            instruments = shares + futures

            # Update ticker to FIGI mapping
            self._ticker_to_figi = {
                instrument.ticker: instrument.figi
                for instrument in instruments
            }

            # Cache instruments
            self._instruments = [
                Instrument(
                    figi=instrument.figi,
                    ticker=instrument.ticker,
                    name=instrument.name,
                    currency=instrument.currency,
                    real_exchange=instrument.real_exchange,
                    liquidity_flag=getattr(instrument, 'liquidity_flag', None),
                    basic_asset=getattr(instrument, 'basic_asset', None),
                    lot_size=instrument.lot
                )
                for instrument in instruments
                if instrument.real_exchange == RealExchange.REAL_EXCHANGE_MOEX
            ]
            self._instruments_loaded = True

            return self._instruments

    async def get_figi_by_ticker(self, ticker: str) -> str:
        """Get FIGI by ticker from the cached mapping"""
        if not self._ticker_to_figi:
            # If mapping is empty, fetch instruments to populate it
            await self.get_instruments()
        
        figi = self._ticker_to_figi.get(ticker)
        if not figi:
            raise ValueError(f"Ticker {ticker} not found")
        return figi

    async def get_stock_data(self, figi: str, from_date: datetime, to_date: datetime, 
                      interval: CandleInterval = CandleInterval.CANDLE_INTERVAL_DAY) -> pd.DataFrame:
        """Get historical stock data for a given FIGI"""
        async with AsyncSandboxClient(self.token) as client:
            candles = await client.market_data.get_candles(
                figi=figi,
                from_=from_date,
                to=to_date,
                interval=interval
            )
            
            df = pd.DataFrame([{
                'time': c.time,
                'open': c.open.units + c.open.nano / 1e9,
                'high': c.high.units + c.high.nano / 1e9,
                'low': c.low.units + c.low.nano / 1e9,
                'close': c.close.units + c.close.nano / 1e9,
                'volume': c.volume
            } for c in candles.candles])
            
            return df

    async def get_portfolio(self, account_id: str) -> PortfolioResponse:
        """Get current portfolio for a specific account"""
        async with AsyncSandboxClient(self.token) as client:
            return await client.sandbox.get_sandbox_portfolio(account_id=account_id)

    async def post_order(self, account_id: str, figi: str, quantity: int, direction: OrderDirection, 
                  order_type: OrderType = OrderType.ORDER_TYPE_MARKET) -> PostOrderResponse:
        """Post a new order for a specific account"""
        async with AsyncSandboxClient(self.token) as client:
            return await client.sandbox.post_sandbox_order(
                figi=figi,
                quantity=quantity,
                direction=direction,
                account_id=account_id,
                order_type=order_type
            )

    async def get_accounts(self) -> List[str]:
        """Get list of available account IDs"""
        async with AsyncSandboxClient(self.token) as client:
            accounts = await client.users.get_accounts()
            if not accounts.accounts:
                raise ValueError("No accounts found")
            return [account.id for account in accounts.accounts]

    async def get_operations(self, account_id: str, from_date: datetime, to_date: datetime):
        """Get operations history for an account"""
        logger.info(f"Getting operations for account {account_id} from {from_date} to {to_date}")
        async with AsyncSandboxClient(self.token) as client:
            operations = await client.operations.get_operations(
                account_id=account_id,
                from_=from_date,
                to=to_date,
                state=OperationState.OPERATION_STATE_EXECUTED
            )
            return operations.operations

    async def get_portfolio_value_history(self, account_id: str, from_date: datetime, to_date: datetime) -> pd.DataFrame:
        """Calculate portfolio value history based on operations and current positions"""
        logger.info(f"Getting portfolio history for account {account_id} from {from_date} to {to_date}")
        
        # Get operations history in chronological order
        operations = await self.get_operations(account_id, from_date, to_date)
        operations = sorted(operations, key=lambda x: x.date)
        logger.info(f"Operations found: {len(operations)}")
        
        # Get all unique FIGIs from operations
        unique_figis = set()
        for op in operations:
            if hasattr(op, 'figi') and op.figi:
                unique_figis.add(op.figi)
        
        # Fetch historical data for all FIGIs at once
        historical_data = {}
        for figi in unique_figis:
            try:
                async with AsyncSandboxClient(self.token) as client:
                    candles = await client.market_data.get_candles(
                        figi=figi,
                        from_=from_date,
                        to=to_date,
                        interval=CandleInterval.CANDLE_INTERVAL_1_MIN
                    )
                if candles.candles:
                    # Create a DataFrame with minute-by-minute prices
                    df = pd.DataFrame([{
                        'time': c.time,
                        'price': c.close.units + c.close.nano / 1e9
                    } for c in candles.candles])
                    df.set_index('time', inplace=True)
                    historical_data[figi] = df
            except Exception as e:
                logger.error(f"Error getting historical data for {figi}: {e}")
                historical_data[figi] = pd.DataFrame()
        
        # Group operations by minute
        operations_by_minute = {}
        for op in operations:
            minute_key = op.date.replace(second=0, microsecond=0)
            if minute_key not in operations_by_minute:
                operations_by_minute[minute_key] = []
            operations_by_minute[minute_key].append(op)
        
        # Initialize empty DataFrame with proper columns
        portfolio_history = pd.DataFrame(columns=['value', 'cash', 'positions'])
        
        # Track portfolio state
        cash = 0.0
        positions = {}  # {figi: quantity}
        
        # Process operations minute by minute
        for minute, ops in sorted(operations_by_minute.items()):
            # Process all operations in this minute
            for op in ops:
                payment = op.payment.units + op.payment.nano / 1e9 if op.payment else 0
                
                # Update cash and positions
                if op.type == 'Пополнение счёта' or op.type == 'Завод денежных средств':
                    cash += abs(payment)
                elif op.type == 'Покупка ЦБ':
                    cash -= abs(payment)
                    positions[op.figi] = positions.get(op.figi, 0) + op.quantity
                elif op.type == 'Продажа ЦБ':
                    cash += abs(payment)
                    positions[op.figi] = positions.get(op.figi, 0) - op.quantity
                elif op.type == 'Удержание комиссии за операцию':
                    cash -= abs(payment)
            
            # Calculate position values using historical data
            position_values = {}
            for figi, quantity in positions.items():
                if quantity != 0 and figi in historical_data:
                    try:
                        # Get the price at this minute
                        price_df = historical_data[figi]
                        if not price_df.empty:
                            # Find the closest price to this minute
                            price = price_df.loc[price_df.index <= minute, 'price'].iloc[-1]
                            position_values[figi] = quantity * price
                    except Exception as e:
                        logger.error(f"Error calculating position value for {figi} at {minute}: {e}")
                        position_values[figi] = 0
            
            # Calculate total portfolio value
            total_value = cash + sum(position_values.values())
            
            # Record portfolio state at this minute
            portfolio_history.loc[minute] = {
                'value': total_value,
                'cash': cash,
                'positions': positions.copy()
            }
        
        # Add current portfolio value
        current_portfolio = await self.get_portfolio(account_id)
        current_value = current_portfolio.total_amount_portfolio.units + current_portfolio.total_amount_portfolio.nano / 1e9
        current_cash = current_portfolio.total_amount_currencies.units + current_portfolio.total_amount_currencies.nano / 1e9
        current_positions = {
            position.figi: position.quantity.units 
            for position in current_portfolio.positions
        }
        
        portfolio_history.loc[to_date] = {
            'value': current_value,
            'cash': current_cash,
            'positions': current_positions
        }
        
        return portfolio_history

# Dependency injection for tinkoff client with user-specific token
async def get_tinkoff_client(
    current_user: Dict[str, Any] = None,
    user_token: str = None
):
    """
    Dependency provider for the TinkoffClient with user-specific token.
    
    This creates a new client for each user (or reuses an existing one)
    with their specific token. The token is passed securely through the
    dependency chain and is never exposed to the frontend.
    
    Args:
        current_user: Current authenticated user
        user_token: User's Tinkoff API token (retrieved securely from database)
        
    Returns:
        TinkoffClient: Client instance with user's token
        
    Raises:
        HTTPException: If user is not authenticated or token is not set
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
        
    user_id = current_user.get("id")
    
    # Check if user has set their token
    if not user_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tinkoff API token not set. Please set your token in your profile."
        )
    
    # Return cached client if exists
    cached_client = get_client_from_cache(user_id)
    if cached_client:
        return cached_client
    
    # Create a new client instance with the user's token
    try:
        client = TinkoffClient(token=user_token)
        
        # Validate token by making a simple API call
        try:
            # Attempt a simple API call to validate the token
            async with AsyncSandboxClient(user_token) as api_client:
                await api_client.users.get_accounts()
        except Exception as validate_error:
            logger.error(f"Invalid Tinkoff token: {str(validate_error)}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Tinkoff API token. Please check your token and update it in your profile."
            )
            
        # Token is valid, cache the client
        add_client_to_cache(user_id, client)
        return client
    except Exception as e:
        logger.error(f"Error creating Tinkoff client: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error initializing Tinkoff client: {str(e)}"
        )