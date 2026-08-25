from . import run

def __repr__(message: str):
    return f"{message}"

if __name__ == "__main__":
    print(__repr__("bite"))
    print(run("Calcule la somme des nombres premiers < 100."))
