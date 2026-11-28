# Addness intake status

- **status:** blocked: addness auth
- **runner:** `windows-myaddness`
- **updated:** 2026-11-28T05:39:03Z
- **detail:** turns":1,"subtype":"success","api_error_status":429,"api_error_type":"rate_limit_error","api_error_origin":"first_party","api_error":"usage_limit_reached","result":"You've hit your weekly limit · resets Nov 30, 10pm (Etc/GMT-9)","type":"result","duration_ms":1661,"uuid":"54016b39-bdd4-4e2b-a058-daad5656d858","queued_turn_count":0,"result_index":0,"credential_expires_at":"2026-12-13T11:48:44.642Z"}

**Owner action needed:** re-authenticate the Addness MCP connection in Claude Code on the runner PC (`claude` → `/mcp` → addness → authenticate). The runner keeps polling and resumes automatically.
