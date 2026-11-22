# Addness intake status

- **status:** blocked: addness auth
- **runner:** `windows-main`
- **updated:** 2026-11-22T05:58:44Z
- **detail:** turns":1,"subtype":"success","api_error_status":429,"api_error_type":"rate_limit_error","api_error_origin":"first_party","api_error":"usage_limit_reached","result":"You've hit your weekly limit · resets Nov 23, 10pm (Etc/GMT-9)","type":"result","duration_ms":3867,"uuid":"1148feeb-0d49-4581-84ce-25a2085e67f6","queued_turn_count":0,"result_index":0,"credential_expires_at":"2026-12-13T11:48:44.808Z"}

**Owner action needed:** re-authenticate the Addness MCP connection in Claude Code on the runner PC (`claude` → `/mcp` → addness → authenticate). The runner keeps polling and resumes automatically.
