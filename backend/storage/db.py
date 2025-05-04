import os
import asyncpg
from typing import List, Optional, Dict, Any
from fastapi import Depends

class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        if self.pool is None:
            self.pool = await asyncpg.create_pool(
                user=os.getenv('POSTGRES_USER'),
                password=os.getenv('POSTGRES_PASSWORD'),
                database=os.getenv('POSTGRES_DB'),
                host=os.getenv('POSTGRES_HOST'),
                port=os.getenv('POSTGRES_PORT')
            )
            await self._init_db()

    async def _init_db(self):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS alphas (
                    id SERIAL PRIMARY KEY,
                    alpha TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

    async def create_alpha(self, alpha: str) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                'INSERT INTO alphas (alpha) VALUES ($1) RETURNING id',
                alpha
            )

    async def get_alpha(self, alpha_id: int) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT id, alpha, created_at FROM alphas WHERE id = $1',
                alpha_id
            )
            return dict(row) if row else None

    async def get_all_alphas(self) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                'SELECT id, alpha, created_at FROM alphas ORDER BY created_at DESC'
            )
            return [dict(row) for row in rows]

    async def update_alpha(self, alpha_id: int, alpha: str) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                'UPDATE alphas SET alpha = $1 WHERE id = $2',
                alpha, alpha_id
            )
            return result.split()[-1] == '1'

    async def delete_alpha(self, alpha_id: int) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                'DELETE FROM alphas WHERE id = $1',
                alpha_id
            )
            return result.split()[-1] == '1'

    async def close(self):
        if self.pool:
            await self.pool.close()

# Create global database instance for use in dependency functions
db = Database()

# Dependency to get database instance
async def get_db():
    """Dependency provider for the Database instance"""
    return db 