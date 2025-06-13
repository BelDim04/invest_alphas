import os
import asyncpg
from typing import List, Optional, Dict, Any
from fastapi import Depends
import datetime

class Database:
    def __init__(self):
        self.pool = None
        self._min_size = 2  # Minimum number of connections
        self._max_size = 10  # Maximum number of connections
        self._connection_timeout = 30.0  # Connection timeout in seconds
        self._command_timeout = 60.0  # Command timeout in seconds

    async def connect(self):
        if self.pool is None:
            self.pool = await asyncpg.create_pool(
                user=os.getenv('POSTGRES_USER'),
                password=os.getenv('POSTGRES_PASSWORD'),
                database=os.getenv('POSTGRES_DB'),
                host=os.getenv('POSTGRES_HOST'),
                port=os.getenv('POSTGRES_PORT'),
                min_size=self._min_size,
                max_size=self._max_size,
                timeout=self._connection_timeout,
                command_timeout=self._command_timeout,
                server_settings={
                    'application_name': 'invest_alphas',
                    'statement_timeout': str(int(self._command_timeout * 1000))  # Convert to milliseconds
                }
            )
            await self._init_db()
            
    async def _recreate_tables(self):
        """Force recreation of all tables with new schema"""
        async with self.pool.acquire() as conn:
            # Drop tables in reverse order to avoid foreign key constraint issues
            await conn.execute('''
                DROP TABLE IF EXISTS forward_test_figis CASCADE;
                DROP TABLE IF EXISTS forward_tests CASCADE;
                DROP TABLE IF EXISTS alphas CASCADE;
                DROP TABLE IF EXISTS figis CASCADE;
            ''')
            await self._init_db()

    async def _init_db(self):
        async with self.pool.acquire() as conn:
            # First ensure users table exists (defined in auth/db.py but referenced here)
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(50) UNIQUE NOT NULL,
                    email VARCHAR(100) UNIQUE NOT NULL,
                    full_name VARCHAR(100),
                    hashed_password VARCHAR(255) NOT NULL,
                    disabled BOOLEAN DEFAULT FALSE,
                    tinkoff_token VARCHAR(1000),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS alphas (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    alpha TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS figis (
                    id SERIAL PRIMARY KEY,
                    figi TEXT NOT NULL UNIQUE,
                    ticker TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS forward_tests (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                    account_id TEXT NOT NULL,
                    alpha_id INTEGER NOT NULL REFERENCES alphas(id) ON DELETE RESTRICT,
                    datetime_start TIMESTAMP NOT NULL,
                    datetime_end TIMESTAMP,
                    is_running BOOLEAN DEFAULT TRUE,
                    last_execution_date DATE,
                    trade_on_weekends BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, account_id)
                );

                CREATE TABLE IF NOT EXISTS forward_test_figis (
                    forward_test_id INTEGER REFERENCES forward_tests(id) ON DELETE CASCADE,
                    figi_id INTEGER REFERENCES figis(id) ON DELETE RESTRICT,
                    PRIMARY KEY (forward_test_id, figi_id)
                );
            ''')

    async def create_alpha(self, user_id: int, alpha: str) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                'INSERT INTO alphas (user_id, alpha) VALUES ($1, $2) RETURNING id',
                user_id, alpha
            )

    async def get_alpha(self, alpha_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT id, user_id, alpha, created_at FROM alphas WHERE id = $1 AND user_id = $2',
                alpha_id, user_id
            )
            return dict(row) if row else None

    async def get_all_alphas(self, user_id: int) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                'SELECT id, user_id, alpha, created_at FROM alphas WHERE user_id = $1 ORDER BY created_at DESC',
                user_id
            )
            return [dict(row) for row in rows]

    async def update_alpha(self, alpha_id: int, user_id: int, alpha: str) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                'UPDATE alphas SET alpha = $1 WHERE id = $2 AND user_id = $3',
                alpha, alpha_id, user_id
            )
            return result.split()[-1] == '1'

    async def delete_alpha(self, alpha_id: int, user_id: int) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                'DELETE FROM alphas WHERE id = $1 AND user_id = $2',
                alpha_id, user_id
            )
            return result.split()[-1] == '1'

    # FIGI related methods
    async def upsert_figi(self, figi: str, ticker: str) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval('''
                INSERT INTO figis (figi, ticker)
                VALUES ($1, $2)
                ON CONFLICT (figi) 
                DO UPDATE SET ticker = EXCLUDED.ticker
                RETURNING id
            ''', figi, ticker)

    async def get_figi_by_id(self, figi_id: int) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('SELECT * FROM figis WHERE id = $1', figi_id)
            return dict(row) if row else None

    # Forward test related methods
    async def create_forward_test(self, user_id: int, account_id: str, alpha_id: int, figi_ids: List[int], trade_on_weekends: bool = False) -> int:
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                # Create forward test entry
                forward_test_id = await conn.fetchval('''
                    INSERT INTO forward_tests (user_id, account_id, alpha_id, datetime_start, trade_on_weekends)
                    VALUES ($1, $2, $3, CURRENT_TIMESTAMP, $4)
                    RETURNING id
                ''', user_id, account_id, alpha_id, trade_on_weekends)

                # Create forward test FIGI connections
                await conn.executemany('''
                    INSERT INTO forward_test_figis (forward_test_id, figi_id)
                    VALUES ($1, $2)
                ''', [(forward_test_id, figi_id) for figi_id in figi_ids])

                return forward_test_id

    async def get_forward_test(self, forward_test_id: int) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            # Get forward test data
            test_row = await conn.fetchrow('''
                SELECT ft.*, array_agg(f.*) as figis
                FROM forward_tests ft
                LEFT JOIN forward_test_figis ftf ON ft.id = ftf.forward_test_id
                LEFT JOIN figis f ON ftf.figi_id = f.id
                WHERE ft.id = $1
                GROUP BY ft.id
            ''', forward_test_id)
            return dict(test_row) if test_row else None

    async def get_user_forward_tests(self, user_id: int, only_running: bool = False) -> List[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT ft.*, array_agg(f.*) as figis
                FROM forward_tests ft
                LEFT JOIN forward_test_figis ftf ON ft.id = ftf.forward_test_id
                LEFT JOIN figis f ON ftf.figi_id = f.id
                WHERE ft.user_id = $1
                AND ($2 = FALSE OR ft.is_running = TRUE)
                GROUP BY ft.id
                ORDER BY ft.datetime_start DESC
            ''', user_id, only_running)
            return [dict(row) for row in rows]

    async def stop_forward_test(self, forward_test_id: int) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute('''
                UPDATE forward_tests 
                SET datetime_end = CURRENT_TIMESTAMP, is_running = FALSE
                WHERE id = $1 AND datetime_end IS NULL
            ''', forward_test_id)
            return result.split()[-1] == '1'

    async def get_active_forward_test_by_account(self, user_id: int, account_id: str) -> Optional[Dict[str, Any]]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT ft.*, array_agg(f.*) as figis
                FROM forward_tests ft
                LEFT JOIN forward_test_figis ftf ON ft.id = ftf.forward_test_id
                LEFT JOIN figis f ON ftf.figi_id = f.id
                WHERE ft.user_id = $1 AND ft.account_id = $2 AND ft.is_running = TRUE
                GROUP BY ft.id
            ''', user_id, account_id)
            return dict(row) if row else None

    async def get_all_active_forward_tests(self) -> List[Dict[str, Any]]:
        """Get all active forward tests with their alphas and figis that haven't been executed today"""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT 
                    ft.*,
                    a.alpha,
                    array_agg(f.*) as figis
                FROM forward_tests ft
                JOIN alphas a ON ft.alpha_id = a.id
                LEFT JOIN forward_test_figis ftf ON ft.id = ftf.forward_test_id
                LEFT JOIN figis f ON ftf.figi_id = f.id
                WHERE ft.is_running = TRUE
                AND ft.datetime_end IS NULL
                AND (ft.last_execution_date IS NULL OR ft.last_execution_date < CURRENT_DATE)
                GROUP BY ft.id, a.alpha
                ORDER BY ft.datetime_start DESC
            ''')
            return [dict(row) for row in rows]

    async def update_last_execution_date(self, forward_test_id: int, execution_date: datetime.date) -> bool:
        """Update the last execution date for a forward test"""
        async with self.pool.acquire() as conn:
            result = await conn.execute('''
                UPDATE forward_tests 
                SET last_execution_date = $1
                WHERE id = $2
            ''', execution_date, forward_test_id)
            return result.split()[-1] == '1'

    async def close(self):
        """Close all pool connections"""
        if self.pool:
            await self.pool.close()

# Create global database instance for use in dependency functions
db = Database()

# Dependency to get database instance
async def get_db():
    """Dependency provider for the Database instance"""
    await db.connect()  # Ensure database is connected
    return db 