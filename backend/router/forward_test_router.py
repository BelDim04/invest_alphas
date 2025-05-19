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
from service.alpha_service import AlphaService
from storage.db import Database, get_db
from auth.router import get_current_user_with_db

# Configure logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/forward", tags=["forward"])

# Store active forward test services per user
# user_id -> account_id -> ForwardTestService
_forward_test_services: Dict[int, Dict[str, ForwardTestService]] = {}

# Create authenticated client dependencies with appropriate scopes
get_auth_tinkoff_client_write = create_auth_client_dependency(scopes=["forward:write"])
get_auth_tinkoff_client_read = create_auth_client_dependency(scopes=["forward:read"])

def get_forward_test_service(account_id: str, current_user: Dict[str, Any] = Security(get_current_user_with_db, scopes=["forward:read"])) -> ForwardTestService:
    user_id = current_user["id"]
    if user_id not in _forward_test_services or account_id not in _forward_test_services[user_id]:
        raise HTTPException(status_code=404, detail=f"No forward test service found for account {account_id}")
    return _forward_test_services[user_id][account_id]

def get_alpha_service(db: Database = Depends(get_db)) -> AlphaService:
    return AlphaService(db=db)

@router.post("/start")
@handle_errors
async def start_forward_test(
    request: ForwardTestRequest,
    client: TinkoffClient = Depends(get_auth_tinkoff_client_write),
    alpha_service: AlphaService = Depends(get_alpha_service),
    current_user: Dict[str, Any] = Security(get_current_user_with_db, scopes=["forward:write"])
):
    """Start forward testing for selected instruments"""
    user_id = current_user["id"]
    # Load the alpha expression
    alpha = await alpha_service.get_alpha(request.alpha_id)
    if not alpha:
        raise HTTPException(status_code=404, detail=f"Alpha with id {request.alpha_id} not found")

    # Create new sandbox account
    account_id = await client.create_sandbox_account()
    
    # Create and initialize service
    service = ForwardTestService(
        account_id=account_id,
        target_stocks=request.instruments,
        expression=alpha['alpha'],
        tinkoff_client=client
    )
    
    # Initialize and start the service
    await service.initialize()
    if user_id not in _forward_test_services:
        _forward_test_services[user_id] = {}
    _forward_test_services[user_id][account_id] = service
    
    # Start the service in the background
    asyncio.create_task(service.run())
    
    return {"status": "started", "account_id": account_id}

@router.post("/stop")
@handle_errors
async def stop_forward_test(
    account_id: str = Query(..., description="ID of the account to stop forward testing"),
    client: TinkoffClient = Depends(get_auth_tinkoff_client_write),
    current_user: Dict[str, Any] = Security(get_current_user_with_db, scopes=["forward:write"])
):
    """Stop forward testing for an account"""
    user_id = current_user["id"]
    service = get_forward_test_service(account_id, current_user)
    service.is_running = False
    
    # Close sandbox account
    await client.close_sandbox_account(account_id)
    
    # Remove service from tracking
    del _forward_test_services[user_id][account_id]
    if not _forward_test_services[user_id]:
        del _forward_test_services[user_id]
    
    return {"status": "stopped", "account_id": account_id}

@router.get("/history/{account_id}")
@handle_errors
async def get_forward_test_history(
    account_id: str, 
    service: ForwardTestService = Depends(get_forward_test_service),
    client: TinkoffClient = Depends(get_auth_tinkoff_client_read),
    current_user: Dict[str, Any] = Security(get_current_user_with_db, scopes=["forward:read"])
):
    """Get portfolio value history for a forward test"""
    if not service.start_date:
        raise HTTPException(status_code=400, detail="Forward test has not been started")

    # Get history from original start date to now
    history = await client.get_portfolio_value_history(
        account_id, 
        service.start_date,
        datetime.now(timezone.utc)
    )
    
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

@router.get("/active")
@handle_errors
async def list_active_forward_tests(current_user: Dict[str, Any] = Security(get_current_user_with_db, scopes=["forward:read"])):
    """List all active forward tests for the current user"""
    user_id = current_user["id"]
    active_tests = []
    if user_id in _forward_test_services:
        for account_id, service in _forward_test_services[user_id].items():
            active_tests.append({
                "account_id": account_id,
                "status": "running" if service.is_running else "stopped",
                "start_date": service.start_date.isoformat() if service.start_date else None,
                "instruments": service.target_stocks,
                "alpha_expression": service.expression
            })
    return {"active_tests": active_tests} 