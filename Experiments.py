# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:light
#     text_representation:
#       extension: .py
#       format_name: light
#       format_version: '1.5'
#       jupytext_version: 1.16.1
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# +
import ast
import inspect
import functools

def sort_function_calls(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        source = inspect.getsource(func)
        parsed_ast = ast.parse(source)

        main_calls = []
        other_calls = []
        main_instances = set()

        class FunctionCallVisitor(ast.NodeVisitor):
            def visit_Assign(self, node):
                # Check for assignment to a Main instance
                for target in node.targets:
                    if isinstance(node.value, ast.Call) and getattr(node.value.func, 'id', None) == 'Main':
                        main_instances.add(target.id)
                self.generic_visit(node)

            def visit_Call(self, node):
                # Check if the call is on an instance of Main
                if isinstance(node.func, ast.Attribute) and node.func.value.id in main_instances:
                    main_calls.append(ast.unparse(node))
                elif isinstance(node.func, ast.Name) and node.func.id in main_instances:
                    # Direct call like `item()`
                    main_calls.append(ast.unparse(node))
                else:
                    other_calls.append(ast.unparse(node))
                self.generic_visit(node)

        FunctionCallVisitor().visit(parsed_ast)

        print("Calls on 'Main':", main_calls)
        print("Other calls:", other_calls)

        return func(*args, **kwargs)

    return wrapper



# -

class Main:
    def __call__(self, *args, **kwargs):
        pass


@sort_function_calls
def testing():
    item = Main()
    item(whee=True)

    print("TEST")


testing()


