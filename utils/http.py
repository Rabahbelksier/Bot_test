import requests
from requests.adapters import HTTPAdapter

_http_session = requests.Session()
_adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=0)
_http_session.mount('http://', _adapter)
_http_session.mount('https://', _adapter)
_http_session.headers.update({'Connection': 'keep-alive'})
