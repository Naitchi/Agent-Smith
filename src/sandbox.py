from ..schemas.contract_model import ExecutionResult


class Sandbox:

    def execute(self, code: str) -> ExecutionResult:
        raise NotImplementedError("Sandbox.execute is not implemented yet")
