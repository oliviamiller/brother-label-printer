import asyncio
from viam.module.module import Module
from viam.components.generic import Generic
from models.printer import Printer


if __name__ == '__main__':
    Generic.register_subtype(Printer)
    asyncio.run(Module.run_from_registry())
