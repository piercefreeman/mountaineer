"""
Collection of utilities to "crop" python functions to only execute a sub-AST worth
of logic that's required to produce the output value.

"""
import ast
import inspect
from copy import copy
from textwrap import dedent
from typing import Any, Callable

from pydantic import BaseModel

from mountaineer.logging import LOGGER

DependencyGraphType = dict[str, set[str]]


class FunctionCropException(Exception):
    pass


def var_to_synthetic_var(var: str):
    return f"return_synthetic_{var}"


class SyntheticVarInserter(ast.NodeTransformer):
    """
    Extract any expressions in our return statement:

    return {
        "key1": value1 + value2,
    }

    And turn into synthetic variables that we can then easily traverse via a dependency graph:

    synthetic_key1 = value1 + value2
    return {
        "key1": synthetic_key1,
    }

    """

    def __init__(self, known_pydantic_models: list[str]):
        self.known_pydantic_models = known_pydantic_models

    def visit_Return(self, node):
        new_stmts = []

        if isinstance(node.value, ast.Dict):  # Direct dictionary returns
            for i, (key, value) in enumerate(zip(node.value.keys, node.value.values)):
                key_str = key.value if isinstance(key, ast.Constant) else None
                if key_str:
                    assign, synthetic_var_name = self.create_synthetic_assign(
                        key_str, value
                    )
                    new_stmts.append(assign)
                    node.value.values[i] = ast.Name(
                        id=synthetic_var_name, ctx=ast.Load()
                    )

        elif (
            isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and (
                node.value.func.id == "dict"
                or node.value.func.id in self.known_pydantic_models
            )
        ):
            # Handle Pydantic model returns
            # Handle dict() function returns
            for i, keyword in enumerate(node.value.keywords):
                key_str = keyword.arg
                if key_str:
                    assign, synthetic_var_name = self.create_synthetic_assign(
                        key_str, keyword.value
                    )
                    new_stmts.append(assign)
                    node.value.keywords[i].value = ast.Name(
                        id=synthetic_var_name, ctx=ast.Load()
                    )

        else:
            raise FunctionCropException(
                "Unknown return type, can't auto-crop function logic."
            )

        return new_stmts + [node] if new_stmts else node

    def create_synthetic_assign(self, key: str, value: ast.expr):
        """
        Create a synthetic variable assignment statement.
        """
        synthetic_var_name = var_to_synthetic_var(key)
        return ast.Assign(
            targets=[ast.Name(id=synthetic_var_name, ctx=ast.Store())], value=value
        ), synthetic_var_name


class DependencyGraphCreator(ast.NodeVisitor):
    """
    Analyze a function's AST to determine which variables depend on which other variables

    """

    def __init__(self):
        self.graph: DependencyGraphType = {}
        self.current_deps: list[str] = []

    def visit_Assign(self, node):
        # Collect dependencies for the value being assigned
        self.current_deps = []
        self.visit(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                # Update the graph with dependencies for this assignment
                self.graph[target.id] = set(self.current_deps)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load):
            # A variable is being used here, add it to the current dependencies
            self.current_deps.append(node.id)

    def visit_Call(self, node):
        # For simplicity, assume function calls are side-effect free and only depend on
        # their arguments
        for arg in node.args:
            self.visit(arg)


class ASTReducer(ast.NodeTransformer):
    """
    Extract a sub-AST from a given AST, based on a list of needed variables. This will keep
    all variables within `needed_vars` and all non-assigned expressions.

    """

    def __init__(self, needed_vars: set[str], known_pydantic_models: list[str]):
        super().__init__()
        self.needed_vars = needed_vars
        self.known_pydantic_models = known_pydantic_models

    def visit_FunctionDef(self, node: ast.FunctionDef):
        return self.visit_function_common(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        return self.visit_function_common(node)

    def visit_If(self, node):
        # Process the body and orelse parts of the If statement
        node.body = [stmt for stmt in node.body if self.is_needed(stmt)]
        node.orelse = [stmt for stmt in node.orelse if self.is_needed(stmt)]

        # If both body and orelse become empty, exclude the If statement
        if not node.body and not node.orelse:
            return None
        return node

    def visit_function_common(self, node: ast.AsyncFunctionDef | ast.FunctionDef):
        new_body: list[ast.stmt] = []
        for stmt in node.body:
            if isinstance(stmt, ast.If):
                if stmt := self.visit_If(stmt) and stmt:
                    new_body.append(stmt)
            elif self.is_needed(stmt):
                new_body.append(stmt)
            elif isinstance(stmt, ast.Return):
                modified_return = self.modify_return_stmt(stmt)
                if modified_return:
                    new_body.append(modified_return)
        node.body = new_body
        return node

    def is_needed(self, stmt: ast.stmt):
        if isinstance(stmt, ast.Assign):
            return any(
                target.id in self.needed_vars
                for target in stmt.targets
                if isinstance(target, ast.Name)
            )
        elif isinstance(stmt, ast.Expr):
            # For now assume that we need all expressions
            return True
        elif isinstance(stmt, ast.If):
            # Check if the If statement contains needed variables in its body or orelse
            return any(self.is_needed(sub_stmt) for sub_stmt in stmt.body + stmt.orelse)
        return False

    def modify_return_stmt(self, stmt: ast.Return):
        # Prepare the dictionary keys and values based on the model's fields (arguments to the model)
        new_keys: list[ast.Constant] = []
        new_values: list[ast.expr] = []

        if (
            isinstance(stmt.value, ast.Call)
            and hasattr(stmt.value.func, "id")
            and (
                stmt.value.func.id == "dict"  # type: ignore
                or stmt.value.func.id in self.known_pydantic_models  # type: ignore
            )
        ):
            for key, value in zip(
                [ast.Constant(value=arg.arg) for arg in stmt.value.keywords],
                [arg.value for arg in stmt.value.keywords],
            ):
                if isinstance(value, ast.Name) and value.id in self.needed_vars:
                    new_keys.append(key)
                    new_values.append(value)
        elif isinstance(stmt.value, ast.Dict):
            for dict_key, dict_value in zip(stmt.value.keys, stmt.value.values):
                if (
                    isinstance(dict_key, ast.Constant)
                    and isinstance(dict_value, ast.Name)
                    and dict_value.id in self.needed_vars
                ):
                    new_keys.append(dict_key)
                    new_values.append(dict_value)
        return ast.Return(value=ast.Dict(keys=new_keys, values=new_values))  # type: ignore


def reduce_function_to_keys(
    func_ast: ast.Module,
    graph: DependencyGraphType,
    target_keys: list[str],
    known_pydantic_models: list[str],
):
    needed_vars = set(target_keys)
    queue = copy(target_keys)

    while queue:
        current_var = queue.pop()
        if current_var in graph:
            dependencies = graph[current_var]
            for dep in dependencies:
                if dep not in needed_vars:
                    needed_vars.add(dep)
                    queue.append(dep)

    reducer = ASTReducer(needed_vars, known_pydantic_models)
    return reducer.visit(func_ast)


def crop_function_for_return_keys(
    func: Callable, keys: list[str], locals: dict[str, Any] | None = None
):
    """
    Performs static analysis on the given function. Expects this function to either return
    a dictionary or a BaseModel.

    Returns a new synthetic function that always returns a dictionary, just with the subset
    of keys that are specified. Will only perform the computation necessary to directly calculate
    these keys, which saves compute for other non-required functions.

    Known limitations:
        - Only one "return" statement is supported. If you have conditional logic that returns different
            response payloads, this cropping will not work. Instead, have one return payload with multiple
            conditional input variables.

    """
    source = inspect.getsource(func)
    dedented_source = dedent(source)
    tree = ast.parse(dedented_source)

    isolated_namespace = func.__globals__.copy()
    if locals:
        isolated_namespace.update(locals)

    known_pydantic_models = [
        model.__name__
        for model in isolated_namespace.values()
        if inspect.isclass(model) and issubclass(model, BaseModel)
    ]

    # The user is referencing object keys in the resulting payload, refactor these
    # into actual variables
    inserter = SyntheticVarInserter(known_pydantic_models)
    tree = inserter.visit(tree)
    keys = [var_to_synthetic_var(var) for var in keys]

    # Create a dependency graph
    creator = DependencyGraphCreator()
    creator.visit(tree)

    LOGGER.debug(f"Parsed function graph: {creator.graph}")

    # Reduce the function based on the dependency graph
    optimized_tree = reduce_function_to_keys(
        tree, creator.graph, keys, known_pydantic_models
    )

    # Fix line numbers and compile
    optimized_tree = ast.fix_missing_locations(optimized_tree)
    code = compile(optimized_tree, filename="<ast>", mode="exec")

    exec(code, isolated_namespace)

    return isolated_namespace[func.__name__]
