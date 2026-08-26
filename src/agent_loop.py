from  __future__ import annotations
import time
from schemas import (LLMProtocole, 
                     SandboxProtocol, 
                     SolutionOutput,
                     StepMetrics)
from .agent.parsing import extract_code


class AgentLoop:
    def __init__(self):
        pass