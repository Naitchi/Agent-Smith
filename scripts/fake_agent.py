from .fake_sandbox import FakeSandbox

CODE_BLOCKS = [
    # 1. basic execution + stdout
    "print('hello from block 1')\nx = 21",
    # 2. state persistence across execute() calls + final_answer()
    "print(x * 2)\nfinal_answer(x * 2)",
    # 3. should be caught by the security layer (import + FS escape)
    "import os\nprint(os.listdir('/etc'))",
]


def main() -> None:
    sandbox = FakeSandbox()
    try:
        for i, code in enumerate(CODE_BLOCKS, start=1):
            print(f"--- block {i} ---\n{code}\n")
            result = sandbox.execute(code)
            print(result.model_dump_json(indent=2))
            print()
            if result.final_answer is not None:
                print(f"final_answer received: {result.final_answer!r} \
                    — stopping.")
                break
    finally:
        sandbox.close()


if __name__ == "__main__":
    main()
