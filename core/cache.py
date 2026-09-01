import threading
from cachetools import TTLCache

cache = TTLCache(maxsize=400, ttl=600)
cache_lock = threading.Lock()

scrape_cache = TTLCache(maxsize=200, ttl=3600)
scrape_cache_lock = threading.Lock()
