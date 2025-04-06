from typing import List, Dict, Optional
import os
from datetime import datetime, timezone
from tinkoff.invest import AsyncClient, CandleInterval
from tinkoff.invest.schemas import InstrumentExchangeType, RealExchange
from tinkoff.invest import InstrumentStatus
import pandas as pd

from schema.models import Instrument

class TinkoffClient:
    def __init__(self):
        self.token = os.getenv("TINKOFF_TOKEN")
        if not self.token:
            raise ValueError("TINKOFF_TOKEN environment variable is not set")
        self._ticker_to_figi: Dict[str, str] = {}

    async def get_instruments(self) -> List[Instrument]:
        async with AsyncClient(self.token) as client:
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

            return [
                Instrument(
                    figi=instrument.figi,
                    ticker=instrument.ticker,
                    name=instrument.name,
                    currency=instrument.currency,
                    real_exchange=instrument.real_exchange,
                    liquidity_flag=getattr(instrument, 'liquidity_flag', None),
                    basic_asset=getattr(instrument, 'basic_asset', None)
                )
                for instrument in instruments
                if instrument.real_exchange == RealExchange.REAL_EXCHANGE_MOEX
            ]

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
        async with AsyncClient(self.token) as client:
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