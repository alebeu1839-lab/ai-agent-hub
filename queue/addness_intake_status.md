# Addness intake status

- **status:** blocked: addness auth
- **runner:** `windows-myaddness`
- **updated:** 2026-11-24T00:34:41Z
- **detail:** true,"num_turns":1,"subtype":"success","api_error_status":429,"api_error_type":"rate_limit_error","api_error_origin":"first_party","api_error":"usage_limit_reached","result":"You've hit your 5-hour limit · resets 1pm (Etc/GMT-9)","type":"result","duration_ms":790,"uuid":"2065879f-1316-4e3d-9a7f-e02cee4ebdf1","queued_turn_count":0,"result_index":0,"credential_expires_at":"2026-12-13T11:48:44.642Z"}

**Owner action needed:** re-authenticate the Addness MCP connection in Claude Code on the runner PC (`claude` → `/mcp` → addness → authenticate). The runner keeps polling and resumes automatically.
