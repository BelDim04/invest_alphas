from fastapi import APIRouter, Depends, HTTPException, Query, Security
from typing import Dict, Any
from datetime import datetime, timezone
import asyncio
import logging
from schema.models import ForwardTestRequest
from service.forward_test_service import ForwardTestService
from client.tinkoff_client import TinkoffClient
from utils.decorators import handle_errors
from utils.auth_deps import create_auth_client_dependency

# Configure logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/forward", tags=["forward"])

# Store active forward test services
_forward_test_services: Dict[str, ForwardTestService] = {}

# Create authenticated client dependencies with appropriate scopes
get_auth_tinkoff_client_write = create_auth_client_dependency(scopes=["forward:write"])
get_auth_tinkoff_client_read = create_auth_client_dependency(scopes=["forward:read"])

# Dependency injection
def get_forward_test_service(account_id: str) -> ForwardTestService:
    """Dependency provider for ForwardTestService by account ID"""
    if account_id not in _forward_test_services:
        raise HTTPException(status_code=404, detail=f"No forward test service found for account {account_id}")
    return _forward_test_services[account_id]

@router.post("/start")
@handle_errors
async def start_forward_test(
    request: ForwardTestRequest,
    client: TinkoffClient = Depends(get_auth_tinkoff_client_write)
):
    """Start forward testing for selected instruments"""
    # Create new sandbox account
    account_id = await client.create_sandbox_account()
    
    # Create and initialize service
    service = ForwardTestService(
        account_id=account_id,
        target_stocks=request.instruments,
        tinkoff_client=client
    )
    
    # Initialize and start the service
    await service.initialize()
    service.start_date = datetime.now(timezone.utc)
    _forward_test_services[account_id] = service
    
    # Start the service in the background
    asyncio.create_task(service.run())
    
    return {"status": "started", "account_id": account_id}

@router.post("/stop")
@handle_errors
async def stop_forward_test(
    account_id: str = Query(..., description="ID of the account to stop forward testing"),
    client: TinkoffClient = Depends(get_auth_tinkoff_client_write)
):
    """Stop forward testing for an account"""
    service = get_forward_test_service(account_id)
    service.is_running = False
    
    # Close sandbox account
    await client.close_sandbox_account(account_id)
    
    # Remove service from tracking
    del _forward_test_services[account_id]
    
    return {"status": "stopped", "account_id": account_id}

@router.get("/history/{account_id}")
@handle_errors
async def get_forward_test_history(
    account_id: str, 
    service: ForwardTestService = Depends(get_forward_test_service),
    client: TinkoffClient = Depends(get_auth_tinkoff_client_read)
):
    """Get portfolio value history for a forward test"""
    # Get history from start date to now
    from_date = service.start_date
    to_date = datetime.now(timezone.utc)
    
    history = await client.get_portfolio_value_history(account_id, from_date, to_date)
    
    # Convert to list of dicts for JSON serialization
    history_list = [
        {
            'timestamp': date.strftime('%Y-%m-%d %H:%M:%S'),
            'value': row['value'],
            'cash': row['cash'],
            'positions': row['positions']
        }
        for date, row in history.iterrows()
    ]
    
    return {
        'account_id': account_id,
        'history': history_list
    } 