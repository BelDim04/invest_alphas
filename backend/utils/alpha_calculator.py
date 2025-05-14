import pandas as pd
import numpy as np
import ast


def calculate_alpha1(stock_data: pd.DataFrame) -> pd.Series:
    """Calculate alpha1 signal for a single stock"""
    returns = stock_data['close'].pct_change()
    returns_stddev = returns.rolling(window=20, closed='left').std()

    power_term = np.where(returns < 0, returns_stddev, stock_data['close'])
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


# Helper functions for formula evaluation
def SMA(series: pd.Series, window: int) -> pd.Series:
    """Rolling mean (Simple Moving Average) over 'window' periods, excluding current period."""
    return series.rolling(window=window, closed='left').mean()


def STD(series: pd.Series, window: int) -> pd.Series:
    """Rolling standard deviation over 'window' periods, excluding current period."""
    return series.rolling(window=window, closed='left').std()


def MAX(series: pd.Series, window: int) -> pd.Series:
    """Rolling maximum over 'window' periods, excluding current period."""
    return series.rolling(window=window, closed='left').max()


def MIN(series: pd.Series, window: int) -> pd.Series:
    """Rolling minimum over 'window' periods, excluding current period."""
    return series.rolling(window=window, closed='left').min()


def SIGN(x):
    """Element-wise sign of the input (returns -1, 0, or 1 for each element)."""
    if isinstance(x, pd.Series):
        # np.sign on a Series returns a numpy array, so wrap it back to a Series:
        return pd.Series(np.sign(x.values), index=x.index)
    else:
        return float(np.sign(x))


class FormulaValidator(ast.NodeVisitor):
    """AST NodeVisitor to validate allowed nodes and names in formula expressions."""
    # Allowed function names and variable names in formulas
    ALLOWED_FUNCS = {"sma", "std", "max", "min", "sign", "abs"}
    ALLOWED_NAMES = {"open", "high", "low", "close", "volume", "returns", "True", "False"}
    ALLOWED_NODE_TYPES = (
        ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp,
        ast.Call, ast.Name, ast.Constant,
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod,
        ast.UAdd, ast.USub, ast.Not,
        ast.And, ast.Or,
        ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
        ast.Load  # context for Name
    )

    def generic_visit(self, node):
        if not isinstance(node, self.ALLOWED_NODE_TYPES):
            raise ValueError(f"Unsupported expression element: {node.__class__.__name__}")
        super().generic_visit(node)

    def visit_Name(self, node: ast.Name):
        if node.id not in self.ALLOWED_NAMES and node.id not in self.ALLOWED_FUNCS:
            raise ValueError(f"Name '{node.id}' is not allowed in formula")
        if not isinstance(node.ctx, ast.Load):
            raise ValueError("Assignment or store operations are not allowed")

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in self.ALLOWED_FUNCS:
            for arg in node.args:
                self.visit(arg)
            for kw in node.keywords:
                self.visit(kw.value)
        else:
            raise ValueError("Function calls are not allowed (or function not recognized)")

    def visit_Attribute(self, node: ast.Attribute):
        raise ValueError("Attribute access is not allowed in formulas")

    def visit_Subscript(self, node: ast.Subscript):
        raise ValueError("Indexing or slicing is not allowed in formulas")

    def visit_Lambda(self, node: ast.Lambda):
        raise ValueError("Lambda expressions are not allowed in formulas")

    def visit_ListComp(self, node: ast.ListComp):
        raise ValueError("Comprehensions are not allowed in formulas")

    def visit_DictComp(self, node: ast.DictComp):
        raise ValueError("Comprehensions are not allowed in formulas")

    def visit_SetComp(self, node: ast.SetComp):
        raise ValueError("Comprehensions are not allowed in formulas")

    def visit_GeneratorExp(self, node: ast.GeneratorExp):
        raise ValueError("Comprehensions are not allowed in formulas")


def validate_formula(formula: str) -> None:
    """Parse and validate an alpha formula. Raises SyntaxError or ValueError if invalid."""
    expr_ast = ast.parse(formula, mode='eval')  # may raise SyntaxError
    FormulaValidator().visit(expr_ast)


def compile_formula(formula: str):
    """Compile an alpha formula into a code object after validation."""
    expr_ast = ast.parse(formula, mode='eval')
    FormulaValidator().visit(expr_ast)
    return compile(expr_ast, "<formula>", "eval")
