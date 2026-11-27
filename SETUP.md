Run WAHA in detached mode (-d) without --rm, using the same ./sessions folder path so your existing QR login is preserved:

Bash
```
docker run -d --restart unless-stopped --platform linux/amd64 -p 127.0.0.1:3000:3000 \
  -e WAHA_API_KEY=secret123 \
  -e WAHA_DASHBOARD_USERNAME=admin \
  -e WAHA_DASHBOARD_PASSWORD=admin \
  -e WHATSAPP_RESTART_ALL_SESSIONS=True \
  -v "$(pwd)/sessions:/app/.sessions" \
  --name waha devlikeapro/waha
```
Verification: Run `docker ps` —waha appears with status Up, and you can safely close your terminal window.

3
Confirm the session auto-restores in WORKING state
Browser / API
Wait ~10 seconds for WAHA to boot, then open `http://localhost:3000/dashboard` (or check via ```curl -H "X-Api-Key: secret123" http://localhost:3000/api/sessions```). Because ```WHATSAPP_RESTART_ALL_SESSIONS=True``` and ./sessions are mounted, WAHA automatically reconnects your session without a new QR scan.
Verification: The default session status shows ```WORKING```.