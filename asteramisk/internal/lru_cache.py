from collections import OrderedDict

class LRUCache(OrderedDict):
    """
    LRU (Least Recently Used) cache implementation
    Can be used as a dictionary. e.g. cache = LRUCache()
    """
    def __init__(self, maxsize=1000):
        self.cache = OrderedDict()
        self.maxsize = maxsize

    def __contains__(self, key):
        return key in self.cache

    def __getitem__(self, key):
        return self.cache[key]

    def __setitem__(self, key, value):
        if key in self.cache:
            self.cache.move_to_end(key)

        # Check size
        if len(self.cache) >= self.maxsize:
            self.cache.popitem(last=False)

        # Add to cache
        self.cache[key] = value
