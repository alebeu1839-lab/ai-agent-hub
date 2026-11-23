# Addness intake status

- **status:** blocked: addness auth
- **runner:** `windows-myaddness`
- **updated:** 2026-11-23T04:36:00Z
- **detail:** rue,"num_turns":1,"subtype":"success","api_error_status":429,"api_error_type":"rate_limit_error","api_error_origin":"first_party","api_error":"usage_limit_reached","result":"You've hit your weekly limit · resets 10pm (Etc/GMT-9)","type":"result","duration_ms":704,"uuid":"dfeefb5e-9ae9-4eb2-b7c8-231245af7745","queued_turn_count":0,"result_index":0,"credential_expires_at":"2026-12-13T11:48:44.642Z"}

**Owner action needed:** re-authenticate the Addness MCP connection in Claude Code on the runner PC (`claude` → `/mcp` → addness → authenticate). The runner keeps polling and resumes automatically.
