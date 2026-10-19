# arp-notes-core

The server half of arp-notes (`import arp_notes`). A host app builds one typed
`arp_notes.config.HostConfig`, mounts `arp_notes.fastapi.build_routers(cfg)` and registers
`arp_notes.mcp.TOOLS`. See the repository `PROTOCOL.md` for the wire contract.

Every module exists as a stub until the lane that owns it lands (contract K§7).
