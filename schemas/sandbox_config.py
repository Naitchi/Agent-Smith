from typing import List
from pydantic import BaseModel, Field


class SandboxConfig(BaseModel):
    """Sandbox configuration for student solutions.
    Uses allowlist approach: only imports in authorized_imports are allowed.
    Everything else is blocked by default.
    """

    max_execution_time_seconds: int = 30
    max_memory_mb: int = 512
    max_output_length: int = 10000
    max_open_files: int = 256
    max_processes: int = 4096
    allowed_directories: List[str] = Field(
        default_factory=lambda: ["/testbed", "/tmp/agent"]
    )

    authorized_imports: List[str] = Field(
        default_factory=lambda: [
            "math",
            "math.*",
            "random",
            "datetime",
            "datetime.*",
            "time",
            "itertools",
            "functools",
            "collections",
            "collections.*",
            "operator",
            "string",
            "re",
            "json",
            "json.*",
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
            "typing.*",
            "cmath",
        ]
    )
    authorized_builtins: List[str] = Field(
        default_factory=lambda: [
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
            "__import__",
            "open",
            "__build_class__",
        ]
    )
    authorized_attributes: List[str] = Field(
        default_factory=lambda: [
            "__doc__",
            "__name__",
            "__module__",
            "__annotations__",
        ]
    )
