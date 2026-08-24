
class SolutionOutput(BaseModel):
    """Output from student solution, required format for evaluation.
    This is the JSON structure your agent must produce and write to
    solution.json.
    The moulinette validates this against task correctness and
    metrics limits.
    """
    task_id: str = Field(..., description="Task identifier (MBPP
    task_id as string, or SWE-bench instance_id)")
    benchmark: str = Field(..., description="Benchmark type: 'mbpp' \
    or 'swebench'")
    success: bool = Field(..., description="Whether the agent \
    believes it solved the task")
    solution: str = Field(..., description="For MBPP: the Python \
    function code. For SWE-bench: the git patch (diff)")
    iterations: int = Field(..., description="Number of agent loop \
    iterations used")
    total_requests: int = Field(..., description="Total number of LLM \
    API requests made (including retries)")
    total_input_tokens: int = Field(..., description="Sum of \
    input_tokens across all steps")
    total_output_tokens: int = Field(..., description="Sum of \
    output_tokens across all steps")
    total_time_seconds: float = Field(..., description="Wall-clock \
    time from agent start to finish")
    steps: List[StepMetrics] = Field(default_factory=list,
    description="Per-step metrics, one entry per agent iteration")
    system_prompt: str = Field(default="", description="Full system \
    prompt sent to the LLM (for provenance checking)")
    error: Optional[str] = Field(default=None, description="Error \
    message if the agent failed (None if successful)")
    timestamp: str = Field(default_factory=lambda: datetime.now().
    isoformat(), description="ISO 8601 timestamp of when the \
    solution was produced")
