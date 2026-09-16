"""Sandbox package: isolated execution of LLM-generated Python code.

Re-exports `Sandbox`, the class satisfying
`schemas.contract_model.SandboxProtocol` (`execute`, `get_manual`, `close`)
that the agent loop is built against.
"""

from .core import Sandbox

__all__ = ["Sandbox"]
