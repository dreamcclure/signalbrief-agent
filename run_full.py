import time, nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

PATCH = '''import time as _t, openai as _oai
from openai._base_client import SyncAPIClient as _SC
if not getattr(_SC, "_gl_patched", False):
    _orig = _SC.request
    def _retry(self, *a, **k):
        last = None
        for _i in range(8):
            try:
                return _orig(self, *a, **k)
            except _oai.AuthenticationError as e:
                last = e; _t.sleep(1.5)
        raise last
    _SC.request = _retry
    _SC._gl_patched = True
'''

path = "research_agent_fullcode.ipynb"
nb = nbformat.read(path, as_version=4)

# Inject the retry patch as a temporary first cell (removed after execution)
nb.cells.insert(0, nbformat.v4.new_code_cell(PATCH))

client = NotebookClient(nb, timeout=3600, kernel_name="p3venv")
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
                if ("401" in str(e) or "AuthenticationError" in str(e)) and attempt < 2:
                    print(f"[{index:>3}] cell-level 401, retrying...", flush=True)
                    time.sleep(3)
                    continue
                print(f"[{index:>3}] ERROR in: {label}", flush=True)
                raise
        print(f"[{index:>3}] {time.time()-t0:6.1f}s  {label}", flush=True)

# Remove the injected patch cell and renumber execution counts cleanly
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
