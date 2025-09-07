import asyncio

class JitterBuffer:
    def __init__(self, maxsize=100, prebuffer_size=10):
        self.prebuffer_size = prebuffer_size
        self.queue = asyncio.Queue(maxsize)
        self._buffering = True
        self._buffer_event = asyncio.Event()
        self._check_lock = asyncio.Lock()

    async def put(self, item):
        await self.queue.put(item)
        async with self._check_lock:
            if self._buffering and self.queue.qsize() >= self.prebuffer_size:
                self._buffering = False
                self._buffer_event.set()

    async def get(self):
        while True:
            if self._buffering:
                await self._buffer_event.wait()
            item = await self.queue.get()
            if self.queue.empty():
                async with self._check_lock:
                    self._buffering = True
                    self._buffer_event.clear()
            return item

    def get_nowait(self):
        if self.queue.empty():
            raise asyncio.QueueEmpty
        loop = asyncio.get_running_loop()
        return loop.run_until_complete(self.get())

    def put_nowait(self, item):
        loop = asyncio.get_running_loop()
        loop.run_until_complete(self.put(item))

    def empty(self):
        return self.queue.empty()

    def full(self):
        return self.queue.full()

    def qsize(self):
        return self.queue.qsize()

