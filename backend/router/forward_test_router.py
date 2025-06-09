from fastapi import APIRouter, Depends, HTTPException, Query, Security
from typing import Dict, Any
from datetime import datetime, timezone, timedelta
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
import os
import pandas as pd
import quantstats as qs

# Configure logging
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/forward", tags=["forward"])

# Create authenticated client dependencies with appropriate scopes
get_auth_tinkoff_client_write = create_auth_client_dependency(scopes=["forward:write"])
get_auth_tinkoff_client_read = create_auth_client_dependency(scopes=["forward:read"])

def get_alpha_service(db: Database = Depends(get_db)) -> AlphaService:
    return AlphaService(db=db)

@router.post("/start")
@handle_errors
async def start_forward_test(
    request: ForwardTestRequest,
    client: TinkoffClient = Depends(get_auth_tinkoff_client_write),
    alpha_service: AlphaService = Depends(get_alpha_service),
    db: Database = Depends(get_db),
    current_user: Dict[str, Any] = Security(get_current_user_with_db, scopes=["forward:write"])
):
    """Start forward testing for selected instruments"""
    user_id = current_user["id"]
    
    # Load the alpha expression
    alpha = await alpha_service.get_alpha(request.alpha_id, user_id)
    if not alpha:
        raise HTTPException(status_code=404, detail=f"Alpha with id {request.alpha_id} not found")

    # Create new sandbox account
    account_id = await client.create_sandbox_account()
    
    # Convert tickers to FIGIs and validate them
    figi_ids = []
    figis = []
    
    # Get all available instruments to validate FIGIs
    instruments = await client.get_instruments()
    valid_figis = {i.figi for i in instruments}
    
    for ticker in request.instruments:
        try:
            figi = await client.get_figi_by_ticker(ticker)
            if figi not in valid_figis:
                raise HTTPException(status_code=400, detail=f"FIGI {figi} for ticker {ticker} is not available for trading")
            figis.append(figi)
            # Store FIGI in database
            figi_id = await db.upsert_figi(figi)
            figi_ids.append(figi_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found")
    
    # Create forward test record
    forward_test_id = await db.create_forward_test(
        user_id=user_id,
        account_id=account_id,
        alpha_id=request.alpha_id,
        figi_ids=figi_ids
    )
    
    # Create and initialize service
    service = ForwardTestService(
        forward_test_id=forward_test_id,
        account_id=account_id,
        target_stocks=figis,  # These are now validated FIGIs
        expression=alpha['alpha'],
        tinkoff_client=client,
        db=db,
        trade_on_weekends=request.trade_on_weekends
    )
    
    # Initialize and start the service
    await service.initialize()
    
    # Start the service in the background
    asyncio.create_task(service.run())
    
    return {"status": "started", "account_id": account_id, "forward_test_id": forward_test_id}

@router.post("/stop")
@handle_errors
async def stop_forward_test(
    account_id: str = Query(..., description="ID of the account to stop forward testing"),
    client: TinkoffClient = Depends(get_auth_tinkoff_client_write),
    db: Database = Depends(get_db),
    current_user: Dict[str, Any] = Security(get_current_user_with_db, scopes=["forward:write"])
):
    """Stop forward testing for an account"""
    user_id = current_user["id"]
    
    # Get active forward test for this account
    forward_test = await db.get_active_forward_test_by_account(user_id, account_id)
    if not forward_test:
        raise HTTPException(status_code=404, detail=f"No active forward test found for account {account_id}")
    
    # Stop the forward test in database
    await db.stop_forward_test(forward_test['id'])
    
    # Close sandbox account
    await client.close_sandbox_account(account_id)
    
    return {"status": "stopped", "account_id": account_id, "forward_test_id": forward_test['id']}

@router.get("/history/{account_id}")
@handle_errors
async def get_forward_test_history(
    account_id: str,
    client: TinkoffClient = Depends(get_auth_tinkoff_client_read),
    db: Database = Depends(get_db),
    current_user: Dict[str, Any] = Security(get_current_user_with_db, scopes=["forward:read"])
):
    """Get portfolio value history for a forward test"""
    user_id = current_user["id"]
    
    # Get forward test from database
    forward_test = await db.get_active_forward_test_by_account(user_id, account_id)
    if not forward_test:
        raise HTTPException(status_code=404, detail=f"No forward test found for account {account_id}")

    # Get history from start date to now
    history = await client.get_portfolio_value_history(
        account_id, 
        forward_test['datetime_start'],
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

    # Calculate returns for quantstats
    portfolio_value = history['value']
    
    # Calculate returns
    returns = pd.Series(
        portfolio_value.pct_change().fillna(0),
        index=history.index,
        name='strategy'
    )
    
    report_url = None
    # Only generate report if we have returns data
    if len(returns) > 2 and not returns.empty:
        # Generate quantstats HTML report
        report_filename = f"forward_test_report_{account_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        report_path = os.path.join("static", "reports", report_filename)
        
        # Create reports directory if it doesn't exist
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
            
        qs.reports.html(
            returns=returns,
            output=report_path,
            title=f"Forward Test Report - {forward_test['alpha_id']} {[f['figi'] for f in forward_test['figis']]}",
            download_filename=report_filename
        )
        
        report_url = f"/api/static/reports/{report_filename}"
    
    return {
        'account_id': account_id,
        'forward_test_id': forward_test['id'],
        'history': history_list,
        'report_url': report_url
    }

@router.get("/active")
@handle_errors
async def list_active_forward_tests(
    db: Database = Depends(get_db),
    current_user: Dict[str, Any] = Security(get_current_user_with_db, scopes=["forward:read"])
):
    """List all active forward tests for the current user"""
    user_id = current_user["id"]
    forward_tests = await db.get_user_forward_tests(user_id, only_running=True)
    
    return {
        "active_tests": [{
            "forward_test_id": test['id'],
            "account_id": test['account_id'],
            "status": "running" if test['is_running'] else "stopped",
            "start_date": test['datetime_start'].isoformat(),
            "end_date": test['datetime_end'].isoformat() if test['datetime_end'] else None,
            "instruments": [f['figi'] for f in test['figis']],
            "alpha_id": test['alpha_id']
        } for test in forward_tests]
    } 