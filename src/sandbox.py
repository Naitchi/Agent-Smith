from multiprocessing import Process, Queue
from typing import Any, Dict
import resource
import ast

from schemas import ExecutionResult
from schemas import SandboxConfig


class Sandbox(SandboxConfig):
    def __init__(self, config: SandboxConfig = SandboxConfig()) -> None:
        self.config = config
        self._state: Dict[str, Any] = {}

    # TODO refactor: to lower Cognitive complexity
    def _is_code_safe(self, code: str) -> bool:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return False

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module not in self._ALLOWED_IMPORTS
            ):
                return False
            elif isinstance(node, ast.Call) and (
                (
                    isinstance(node.func, ast.Name)
                    and node.func.id not in self._ALLOWED_BUILTINS
                )
                or (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr not in self._ALLOWED_ATTRIBUTES
                )
            ):
                return False
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name not in self._ALLOWED_IMPORTS:
                        return False
        return True

    def _worker(
        self, code: str, state: Dict[str, Any], queue: Queue[ExecutionResult]
    ) -> None:
        limit_bytes = self.config.max_memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))

        try:
            exec(code, state)
        except MemoryError:
            queue.put(ExecutionResult(error="Memory limit exceeded."))
        except Exception as e:
            queue.put(ExecutionResult(error=str(e)))
        else:
            queue.put(ExecutionResult())

    def execute(self, code: str) -> ExecutionResult:
        q: Queue[ExecutionResult] = Queue()
        p = Process(target=self._worker, args=(code, self._state, q))

        if not self._is_code_safe(code):
            return ExecutionResult(
                error="Code contains disallowed operations."
            )
        p.start()
        p.join(timeout=self.config.max_execution_time_seconds)
        if p.is_alive():
            p.terminate()
            return ExecutionResult(error="Execution timed out.")
        return q.get()

    _ALLOWED_BUILTINS = {
        "bool",
        "int",
        "float",
        "complex",
        "str",
        "bytes",
        "bytearray",
        "list",
        "tuple",
        "dict",
        "set",
        "frozenset",
        "slice",
        "range",
        "object",
        "type",
        "isinstance",
        "issubclass",
        "callable",
        "iter",
        "next",
        "enumerate",
        "zip",
        "map",
        "filter",
        "reversed",
        "sorted",
        "sum",
        "min",
        "max",
        "all",
        "any",
        "len",
        "abs",
        "round",
        "divmod",
        "pow",
        "repr",
        "format",
        "ascii",
        "chr",
        "ord",
        "bin",
        "oct",
        "hex",
        "hash",
        "super",
        "property",
        "staticmethod",
        "classmethod",
        "print",
        "Exception",
        "BaseException",
        "ValueError",
        "TypeError",
        "KeyError",
        "IndexError",
        "StopIteration",
        "StopAsyncIteration",
        "RuntimeError",
        "AttributeError",
        "NotImplementedError",
        "ImportError",
        "ModuleNotFoundError",
        "NameError",
        "ZeroDivisionError",
        "ArithmeticError",
        "OverflowError",
        "OSError",
        "FileNotFoundError",
        "PermissionError",
        "TimeoutError",
        "MemoryError",
        "RecursionError",
        "AssertionError",
        "LookupError",
        "UnicodeError",
        "GeneratorExit",
        "KeyboardInterrupt",
        "SystemExit",
    }

    _ALLOWED_ATTRIBUTES = {
        "__class__",
        "__bases__",
        "__base__",
        "__mro__",
        "__subclasses__",
        "__globals__",
        "__reduce__",
        "__reduce_ex__",
        "__init_subclass__",
        "__init__",
        "__new__",
        "__call__",
        "__str__",
        "__repr__",
        "__format__",
        "__sizeof__",
        "__dir__",
        "__doc__",
        "__module__",
        "__annotations__",
        "__kwdefaults__",
        "__defaults__",
        "__code__",
        "__closure__",
        "__func__",
        "__self__",
        "__dict__",
        "__weakref__",
        "__slots__",
        "__getattribute__",
    }

    _ALLOWED_IMPORTS = {
        "math",
        "random",
        "datetime",
        "time",
        "itertools",
        "functools",
        "collections",
        "operator",
        "string",
        "re",
        "json",
        "decimal",
        "fractions",
        "statistics",
        "heapq",
        "bisect",
        "array",
        "copy",
        "types",
        "weakref",
        "enum",
        "contextlib",
        "abc",
        "typing",
    }
