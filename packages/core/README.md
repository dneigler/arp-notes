# arp-notes-core

The server half of arp-notes (`import arp_notes`). A host app builds one typed
`arp_notes.config.HostConfig`, mounts `arp_notes.fastapi.build_routers(cfg)` and registers
`arp_notes.mcp.TOOLS`. See the repository `PROTOCOL.md` for the wire contract.

Every module exists as a stub until the lane that owns it lands (contract K§7).

## MCP tools (`arp_notes.mcp`)

`mcp.TOOLS` is the 13 notes tools of PROTOCOL.md A.3, then the 4 hygiene tools (K§6.3). Each is a
`ToolSpec(name, description, input_schema, handler, writes)`. `handler(cfg, user_id, **args)`
validates `args` against `input_schema`, calls the same core function the REST route uses, and
returns a JSON-ready dict. A failure comes back as the REST error body (`{"error": "not_found"}`),
and bad arguments as `{"error": "invalid_arguments", "detail": [...]}`. Read tools carry the
hygiene block (K§6.2); `get_note` cuts the body at 20,000 characters (`truncated: true`).

Three ways to wire them, depending on the host:

1. **A FastMCP server that can call the core in process** (`fastmcp` or the `mcp` SDK):

   ```python
   from arp_notes import mcp

   mcp.register_fastmcp(app, cfg)  # blocking handlers run in a worker thread
   mcp.register_fastmcp(app, cfg, wrap=my_wrapper)  # or choose how: wrap(run) -> run2
   ```

   Each call resolves the caller with `cfg.principal.current_user_id(request)`; `request` is the
   HTTP request when the server exposes one, else `None`. `run(user_id, tool_name, args)` is the
   function `wrap` receives; return a callable with the same arguments (sync or async). `wrap`
   must not register anything itself.

2. **A FastMCP server whose tools call REST** (PT's `mcp_host.py` and `api_call`). Generate the
   wrappers from `mcp.REST_BINDINGS` instead of writing them by hand:

   ```python
   for tool in mcp.TOOLS:
       req = mcp.rest_request(tool.name, args)  # -> (method, path, params, json)
       api_call(req.method, req.path, params=req.params, json=req.json)
   ```

   `get_note` then needs `mcp.truncate_body(result)` on the response.

3. **A hand-maintained registry** (PT keeps one in three files: the MCP server's handlers, the
   in-process registry with its `READ_TOOLS` / `WRITE_TOOLS`, and the FastMCP host, with a parity
   test on the names). Iterate `mcp.TOOLS` in each file rather than copying names:
   `[s.name for s in mcp.TOOLS if not s.writes]` is the read list and `... if s.writes` the write
   list, `s.handler(cfg, user_id, **args)` is the in-process body and `s.input_schema` is the
   registered schema. When the core adds a tool the parity test then fails in one place only.

`update_note` clears `person`, `note_date` and `place` with an empty string (FastMCP cannot tell
an omitted argument from a null one). `create_note` takes `source_system: "llm"` and a
`source_doc_id` to make a retry return the existing note.
