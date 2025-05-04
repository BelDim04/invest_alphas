import pandas as pd
import numpy as np

def calculate_alpha1(stock_data: pd.DataFrame) -> pd.Series:
    """Calculate alpha1 signal for a single stock"""
    returns = stock_data['close'].pct_change()

    returns_stddev = returns.rolling(window=20, closed='left').std()
    
    power_term = np.where(returns < 0, 
                         returns_stddev, 
                         stock_data['close'])
    signed_power = np.sign(power_term) * (np.abs(power_term) ** 2)
    
    ts_argmax = pd.Series(signed_power).rolling(5, closed='left').apply(np.argmax)
    
    # Calculate alpha using current data
    alpha = ts_argmax.rank(pct=True) - 0.5
    
    return alpha

def neutralize_weights(weights: pd.Series) -> pd.Series:
    """Neutralize weights to make sum = 0 and scale absolute values to sum to 1"""
    # Demean to make sum = 0
    weights = weights.sub(weights.mean(axis=1), axis=0)
    
    # Scale so absolute values sum to 1
    abs_sum = weights.abs().sum(axis=1)
    weights = weights.div(abs_sum, axis=0)
    
    return weights 