import time, nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

# Injected temporary first cell: hard per-request timeout + retry on transient proxy failures.
# (Removed after execution, so the submitted notebook stays clean.)
PATCH = '''import time as _t, openai as _oai
from openai._base_client import SyncAPIClient as _SC

_RETRY = (_oai.AuthenticationError, _oai.APITimeoutError, _oai.APIConnectionError,
          _oai.RateLimitError, _oai.InternalServerError)

# 1) Force a 60s timeout on every OpenAI client so a hung proxy request fails fast.
for _name in ("OpenAI", "AsyncOpenAI"):
    _cls = getattr(_oai, _name, None)
    if _cls is not None and not getattr(_cls, "_gl_to", False):
        _orig_init = _cls.__init__
        def _mk(_orig_init):
            def _init(self, *a, **kw):
                kw["timeout"] = 60.0
                kw.setdefault("max_retries", 2)
                return _orig_init(self, *a, **kw)
            return _init
        _cls.__init__ = _mk(_orig_init)
        _cls._gl_to = True

# 2) Retry transient proxy failures (401, timeouts, connection drops, rate limits, 5xx).
if not getattr(_SC, "_gl_patched", False):
    _orig = _SC.request
    def _retry(self, *a, **k):
        last = None
        for _i in range(8):
            try:
                return _orig(self, *a, **k)
            except _RETRY as e:
                last = e; _t.sleep(1.5)
        raise last
    _SC.request = _retry
    _SC._gl_patched = True
'''

path = "research_agent_lowcode.ipynb"
nb = nbformat.read(path, as_version=4)
nb.cells.insert(0, nbformat.v4.new_code_cell(PATCH))

client = NotebookClient(nb, timeout=900, kernel_name="p3venv")
t_start = time.time()
with client.setup_kernel():
    for index, cell in enumerate(nb.cells):
        if cell.cell_type != "code":
            continue
        label = (cell.source.strip().splitlines() or ["(empty)"])[0][:55]
        t0 = time.time()
        for attempt in range(3):
            try:
                client.execute_cell(cell, index)
                break
            except CellExecutionError as e:
                if ("401" in str(e) or "Timeout" in str(e) or "Connection" in str(e)) and attempt < 2:
                    print(f"[{index:>3}] transient error, retrying cell...", flush=True)
                    time.sleep(3)
                    continue
                print(f"[{index:>3}] ERROR in: {label}", flush=True)
                raise
        print(f"[{index:>3}] {time.time()-t0:6.1f}s  {label}", flush=True)

nb.cells.pop(0)
n = 1
for c in nb.cells:
    if c.cell_type == "code":
        c["execution_count"] = n
        for o in c.get("outputs", []):
            if o.get("output_type") == "execute_result":
                o["execution_count"] = n
        n += 1

nbformat.write(nb, path)
print(f"=== EXECUTED AND SAVED in {time.time()-t_start:.0f}s ===", flush=True)
