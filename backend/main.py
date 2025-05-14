from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from router.router import router as common_router
from router.alpha_router import router as alpha_router
from router.backtest_router import router as backtest_router
from router.forward_test_router import router as forward_test_router
from auth.router import router as auth_router
from storage.db import db
from auth.utils import create_initial_admin

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup - connect to database
    await db.connect()
    
    # Initialize auth system
    await create_initial_admin()
    
    yield
    
    # Shutdown - close database connection
    await db.close()

app = FastAPI(
    title="Investment Alphas Backtesting API",
    description="API for backtesting trading alphas",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://localhost"],  # Only allow HTTPS
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Include all routers directly
app.include_router(common_router)
app.include_router(auth_router)
app.include_router(alpha_router)
app.include_router(backtest_router)
app.include_router(forward_test_router)

@app.get("/")
async def root():
    return {"message": "Investment Alphas Backtesting API"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 