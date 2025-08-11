class AsyncClass:
    """
    Base class for all async classes
    Async classes follow the async class pattern.
    They cannot be instantiated directly, but can be created using the create() method.
    The method __create__() is the async __init__ method.
    """
    # async_creation ensures that no developer can accidentally instantiate this class directly
    def __init__(self, async_creation=False, *args, **kwargs):
        if not async_creation:
            raise TypeError(f"Class {self.__class__.__module__}.{self.__class__.__name__} is not intended to be instantiated directly. Use server_instance = await {self.__class__.__name__}.create() instead")

    @classmethod
    async def create(cls, *args, **kwargs):
        f""" 
        Creates a new instance of the class.
        Call this method to create an instance of the class.
        Override __create__ method as an async __init__ method
        The call await {cls.__name__}.create() is synonymous with the synchronous instantiation, {cls.__name__}()
        {cls.__name__}.__create__() is synonymous with {cls.__name__}.__init__()
        They are to be used in the same way as you would use __init__
        """
        klass = cls(async_creation=True)
        return_value = await klass.__create__(*args, **kwargs)
        if return_value is not None:
            raise TypeError(f"__create__ method should return None, not {type(return_value)}")

        return klass

    async def __create__(self, *args, **kwargs):
        f"""
        Async __init__ method.
        Override this method to perform async initialization.
        Called automatically immediately after the class is created.
        The call await {self.__class__.__name__}.create() is synonymous with the synchronous instantiation, {self.__class__.__name__}()
        {self.__class__.__name__}.__create__() is synonymous with {self.__class__.__name__}.__init__()
        They are to be used in the same way as you would use __init__
        """
        pass
