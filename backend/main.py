from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from router.backtest_router import router as backtest_router

app = FastAPI(
    title="Investment Alphas Backtesting API",
    description="API for backtesting trading alphas",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Include routers
app.include_router(backtest_router)

@app.get("/")
async def root():
    return {"message": "Investment Alphas Backtesting API"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 