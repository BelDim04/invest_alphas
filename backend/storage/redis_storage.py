import json
import os
from typing import List, Optional
import redis.asyncio as redis
from schema.models import Instrument

class RedisStorage:
    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://redis")
        self.redis = redis.from_url(self.redis_url)
        self.instruments_key = "instruments"
        self.cache_timeout = 300  # 5 minutes

    async def get_instruments(self) -> Optional[List[Instrument]]:
        data = await self.redis.get(self.instruments_key)
        if not data:
            return None
            
        try:
            instruments_list = json.loads(data)
            return [Instrument(**instrument) for instrument in instruments_list]
        except (json.JSONDecodeError, ValueError) as e:
            raise ValueError(f"Invalid instrument data in cache: {str(e)}")

    async def set_instruments(self, instruments: List[Instrument]) -> None:
        try:
            data = json.dumps([instrument.dict() for instrument in instruments])
            await self.redis.setex(self.instruments_key, self.cache_timeout, data)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Failed to serialize instruments: {str(e)}")
