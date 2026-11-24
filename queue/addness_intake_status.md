# Addness intake status

- **status:** blocked: addness auth
- **runner:** `windows-main`
- **updated:** 2026-11-24T15:23:09Z
- **detail:** true,"num_turns":1,"subtype":"success","api_error_status":429,"api_error_type":"rate_limit_error","api_error_origin":"first_party","api_error":"usage_limit_reached","result":"You've hit your 5-hour limit · resets 4am (Etc/GMT-9)","type":"result","duration_ms":807,"uuid":"4d765cfd-61bd-4ffa-8d21-8517f25df605","queued_turn_count":0,"result_index":0,"credential_expires_at":"2026-12-13T11:48:44.642Z"}

**Owner action needed:** re-authenticate the Addness MCP connection in Claude Code on the runner PC (`claude` → `/mcp` → addness → authenticate). The runner keeps polling and resumes automatically.
