from .async_class import AsyncClass

class AsyncSingleton(AsyncClass):
    """
    A class that can only be instantiated once.
    All subsequent calls will return the same instance.
    Uses the singleton pattern, and the async class pattern
    """
    _instance = None

    @classmethod
    async def create(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = cls(async_creation=True)
            await cls._instance.__create__(*args, **kwargs)
        return cls._instance
