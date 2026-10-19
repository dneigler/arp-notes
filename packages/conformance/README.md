# arp-notes-conformance

Black-box conformance kit (ADR §9.3): it drives any implementation over HTTP (A.2) and MCP (A.3),
so any stack can prove compliance. A host runs it in CI:

```python
from arp_notes_conformance import suite

suite(app=app, token=TOKEN)  # in-process ASGI
suite(base_url="https://...", token=TOKEN)  # any stack, over the wire
```

Stubs until C7a (ga-mxal.14) and C7b (ga-mxal.38) land.
