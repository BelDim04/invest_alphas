# expression_parser.py
import ast
import operator as op
import numpy as np
import pandas as pd

class Expression:
    def evaluate(self, context: dict):
        raise NotImplementedError

class Const(Expression):
    def __init__(self, value):
        self.value = value
    def evaluate(self, context):
        return self.value

class Var(Expression):
    def __init__(self, name):
        self.name = name
    def evaluate(self, context):
        if self.name in context:
            return context[self.name]
        else:
            raise ValueError(f"Unknown variable: {self.name}")

class Func(Expression):
    def __init__(self, name, args):
        self.name = name
        self.args = args
    def evaluate(self, context):
        eval_args = [arg.evaluate(context) for arg in self.args]
        x = eval_args[0] if eval_args else None

        # Базовые функции
        if self.name == 'abs':
            return np.abs(x)
        elif self.name == 'sign':
            return np.sign(x)
        elif self.name == 'log':
            return np.log(x)
        elif self.name == 'rank':
            return pd.Series(x).rank(pct=True) - 0.5
        elif self.name == 'delay':
            k = int(eval_args[1])
            return pd.Series(x).shift(k)
        elif self.name == 'delta':
            k = int(eval_args[1])
            return pd.Series(x).diff(k)

        # Добавленные функции
        elif self.name == 'scale':
            series_x = pd.Series(x)
            return (series_x - series_x.mean()) / series_x.std()
        elif self.name == 'signedpower':
            exp = eval_args[1]
            return np.sign(x) * (np.abs(x) ** exp)
        elif self.name == 'ternary':
            cond = eval_args[0]
            true_val = eval_args[1]
            false_val = eval_args[2]
            cond_series = pd.Series(cond).astype(bool)
            idx = cond_series.index if hasattr(cond_series, 'index') else None
            x_series = pd.Series(true_val, index=idx)
            y_series = pd.Series(false_val, index=idx)
            return x_series.where(cond_series, y_series)
        elif self.name == 'correlation':
            y = eval_args[1]; n = int(eval_args[2])
            series_x = pd.Series(x); series_y = pd.Series(y)
            return series_x.rolling(n).corr(series_y)
        elif self.name == 'covariance':
            y = eval_args[1]; n = int(eval_args[2])
            series_x = pd.Series(x); series_y = pd.Series(y)
            return series_x.rolling(n).cov(series_y)
        elif self.name == 'ts_argmax':
            n = int(eval_args[1])
            series_x = pd.Series(x)
            return series_x.rolling(n).apply(lambda s: np.nanargmax(s.values) if not np.isnan(s.values).all() else np.nan, raw=False)
        elif self.name == 'ts_argmin':
            n = int(eval_args[1])
            series_x = pd.Series(x)
            return series_x.rolling(n).apply(lambda s: np.nanargmin(s.values) if not np.isnan(s.values).all() else np.nan, raw=False)
        elif self.name == 'sum':
            n = int(eval_args[1])
            series_x = pd.Series(x)
            return series_x.rolling(n).sum()
        elif self.name == 'product':
            n = int(eval_args[1])
            series_x = pd.Series(x)
            return series_x.rolling(n).apply(lambda s: np.prod(s.values) if not np.isnan(s.values).all() else np.nan, raw=False)
        elif self.name == 'stddev':
            n = int(eval_args[1])
            series_x = pd.Series(x)
            return series_x.rolling(n).std(ddof=0)
        elif self.name == 'mean':
            n = int(eval_args[1])
            series_x = pd.Series(x)
            return series_x.rolling(n).mean()
        elif self.name == 'min':
            n = int(eval_args[1])
            series_x = pd.Series(x)
            return series_x.rolling(n).min()
        elif self.name == 'max':
            n = int(eval_args[1])
            series_x = pd.Series(x)
            return series_x.rolling(n).max()
        elif self.name == 'indneutralize':
            series_x = pd.Series(x)
            if len(eval_args) > 1:
                group = pd.Series(eval_args[1])
                result = series_x.copy()
                for grp in group.unique():
                    mask = (group == grp)
                    result.loc[mask] = result.loc[mask] - series_x.loc[mask].mean()
                return result
            else:
                return series_x - series_x.mean()
        else:
            raise ValueError(f"Unknown function: {self.name}")

class BinOp(Expression):
    ops = {
        ast.Add: op.add,
        ast.Sub: op.sub,
        ast.Mult: op.mul,
        ast.Div: op.truediv,
        ast.Pow: op.pow
    }
    def __init__(self, left, right, op_node):
        self.left = left
        self.right = right
        self.op = self.ops[type(op_node)]
    def evaluate(self, context):
        return self.op(self.left.evaluate(context), self.right.evaluate(context))

class UnaryOp(Expression):
    def __init__(self, operand, op_node):
        self.operand = operand
        self.op = op_node
    def evaluate(self, context):
        val = self.operand.evaluate(context)
        if isinstance(self.op, ast.UAdd):
            return +val
        elif isinstance(self.op, ast.USub):
            return -val
        else:
            raise ValueError("Unsupported unary operator")

class Compare(Expression):
    # Операторы сравнения
    ops = {
        ast.Gt: op.gt,
        ast.Lt: op.lt,
        ast.GtE: op.ge,
        ast.LtE: op.le,
        ast.Eq: op.eq,
        ast.NotEq: op.ne
    }
    def __init__(self, left, right, op_node):
        self.left = left
        self.right = right
        self.op = self.ops[type(op_node)]
    def evaluate(self, context):
        return self.op(self.left.evaluate(context), self.right.evaluate(context))

class ExpressionParser:
    def parse(self, text: str) -> Expression:
        node = ast.parse(text, mode='eval').body
        return self._parse_node(node)

    def _parse_node(self, node):
        if isinstance(node, ast.Constant):
            return Const(node.value)
        elif isinstance(node, ast.Name):
            return Var(node.id)
        elif isinstance(node, ast.BinOp):
            left = self._parse_node(node.left)
            right = self._parse_node(node.right)
            return BinOp(left, right, node.op)
        elif isinstance(node, ast.UnaryOp):
            operand = self._parse_node(node.operand)
            return UnaryOp(operand, node.op)
        elif isinstance(node, ast.Compare):
            if len(node.ops) != 1 or len(node.comparators) != 1:
                raise ValueError("Chained comparisons not supported")
            left = self._parse_node(node.left)
            right = self._parse_node(node.comparators[0])
            return Compare(left, right, node.ops[0])
        elif isinstance(node, ast.Call):
            func_name = node.func.id
            args = [self._parse_node(arg) for arg in node.args]
            return Func(func_name, args)
        else:
            raise ValueError(f"Unsupported expression: {ast.dump(node)}")
