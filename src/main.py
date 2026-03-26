import asyncio
from viam.module.module import Module

try:
    from models.printer import Printer  # noqa: F401
except ModuleNotFoundError:
    from .models.printer import Printer  # noqa: F401


if __name__ == '__main__':
    asyncio.run(Module.run_from_registry())
