from functools import wraps
from fastapi import HTTPException
from typing import Callable, Any, Optional
from datetime import datetime, timedelta
import json
import logging
import traceback

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def handle_errors(func: Callable) -> Callable:
    @wraps(func)
    async def wrapper(*args, **kwargs) -> Any:
        try:
            return await func(*args, **kwargs)
        except HTTPException as e:
            # Pass through HTTP exceptions (like 400 Bad Request) without changing them
            logger.error(f"HTTP exception in {func.__name__}: {e.status_code}: {e.detail}")
            raise
        except ValueError as e:
            logger.error(f"Validation error in {func.__name__}: {str(e)}\n{traceback.format_exc()}")
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Unexpected error in {func.__name__}: {str(e)}\n{traceback.format_exc()}")
            raise HTTPException(status_code=500, detail="Internal server error")
    return wrapper
