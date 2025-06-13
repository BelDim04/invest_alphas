import asyncio
import logging
from datetime import datetime, timezone, date, timedelta
from typing import List, Dict, Any, Optional
import signal
import sys

from client.tinkoff_client import TinkoffClient
from storage.db import Database
from service.forward_test_service import ForwardTestService
from auth.db import UserDB

logger = logging.getLogger(__name__)

class ForwardTestExecutor:
    def __init__(self):
        db = Database()  # Create base database instance
        self.db = db  # For forward test operations
        self.user_db = UserDB(db)  # Create UserDB with the same database connection
        self.running = True
        self.active_services: Dict[int, ForwardTestService] = {}
        
    async def initialize(self):
        """Initialize the executor service"""
        await self.db.connect()
        await self.user_db.init_tables()
        # Set up signal handlers
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, self.handle_shutdown)
            
    def handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully"""
        logger.info("Received shutdown signal, stopping all forward tests...")
        self.running = False
        
    async def cleanup(self):
        """Cleanup resources before shutdown"""
        await self.db.close()
        
    async def get_active_forward_tests(self) -> List[Dict[str, Any]]:
        """Get all active forward tests from database"""
        return await self.db.get_all_active_forward_tests()
        
    async def start_forward_test(self, forward_test: Dict[str, Any]) -> ForwardTestService:
        """Start a single forward test"""
        try:
            logger.info(f"Starting forward test {forward_test['id']}")
            forward_test_id = forward_test['id']
            account_id = forward_test['account_id']
            alpha = forward_test['alpha']
            figis = [f['figi'] for f in forward_test['figis']]
            user_id = forward_test['user_id']
            
            # Get user's token and create client
            user_token = await self.user_db.get_tinkoff_token(user_id)
            if not user_token:
                raise ValueError(f"No token found for user {user_id}")
            
            client = TinkoffClient(token=user_token)
            
            service = ForwardTestService(
                forward_test_id=forward_test_id,
                account_id=account_id,
                target_stocks=figis,
                tinkoff_client=client,
                start_date=forward_test['datetime_start'],
                expression=alpha,
                trade_on_weekends=forward_test.get('trade_on_weekends', False)
            )
            
            return service
            
        except Exception as e:
            logger.error(f"Error starting forward test {forward_test_id}: {e}")
            raise
                
    async def execute_iteration(self):
        """Execute one iteration for all active forward tests"""
        logger.info("Executing iteration for all active forward tests")

        active_tests = await self.get_active_forward_tests()
        current_date = datetime.now(timezone.utc).date()
        
        for test in active_tests:
            logger.info(f"Executing iteration for test {test['id']}")
            forward_test_id = test['id']
            
            # Check if it's within trading hours (10:00 - 18:45 Moscow time)
            now = datetime.now(timezone.utc) + timedelta(hours=3)  # UTC+3 for Moscow
            is_trading_time = 10 <= now.hour < 18 or (now.hour == 18 and now.minute <= 45)
            is_weekday = now.weekday() < 5
            
            # Get service or create new one
            service = self.active_services.get(forward_test_id)
            if not service:
                try:
                    service = await self.start_forward_test(test)
                    await service.initialize()
                    self.active_services[forward_test_id] = service
                except Exception as e:
                    logger.error(f"Error starting service for test {forward_test_id}: {e}")
                    continue
                    
            try:
                if is_trading_time and (is_weekday or test['trade_on_weekends']):
                    # Execute trading iteration
                    await service.get_current_positions()
                    await service.get_historical_data()
                    alpha_signals = service.calculate_alpha_signals()
                    logger.info(f"Alpha signals for test {forward_test_id}: {alpha_signals}")
                    await service.execute_trades(alpha_signals)
                    
                    # Update last execution date
                    await self.db.update_last_execution_date(forward_test_id, current_date)
                    logger.info(f"Executed iteration for test {forward_test_id}")
                    
            except Exception as e:
                logger.error(f"Error in forward test {forward_test_id} iteration: {e}")
                # Remove service on error to force reinitialization next time
                self.active_services.pop(forward_test_id, None)
                
    async def run(self):
        """Main execution loop"""
        logger.info("Starting forward test executor service")
        
        while self.running:
            try:
                await self.execute_iteration()
                # Sleep for 5 minutes before next iteration
                logger.info("Sleeping for 5 minutes before next iteration")
                await asyncio.sleep(300)
            except Exception as e:
                logger.error(f"Error in main execution loop: {e}")
                await asyncio.sleep(60)
                
        await self.cleanup()

async def main():
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Initialize executor
    executor = ForwardTestExecutor()
    
    try:
        await executor.initialize()
        await executor.run()
    except Exception as e:
        logger.error(f"Fatal error in executor service: {e}")
        sys.exit(1)
    finally:
        await executor.cleanup()

if __name__ == "__main__":
    asyncio.run(main()) 