#!/bin/bash
# Start ngrok + pymol uAgent together
set -e

cd "$(dirname "$0")"

# Safe .env parsing — avoids shell breakage from long JWT values
_env_get() { grep "^${1}=" .env 2>/dev/null | head -1 | cut -d'=' -f2-; }
export PYMOL_AGENT_SEED="${PYMOL_AGENT_SEED:-$(_env_get PYMOL_AGENT_SEED)}"
export AGENTVERSE_API_KEY="${AGENTVERSE_API_KEY:-$(_env_get AGENTVERSE_API_KEY)}"
export PYMOL_AGENT_ADDRESS="${PYMOL_AGENT_ADDRESS:-$(_env_get PYMOL_AGENT_ADDRESS)}"

echo "Starting ngrok tunnel on port 8000..."
ngrok http 8000 --log=stdout > /tmp/ngrok.log 2>&1 &
NGROK_PID=$!

# Wait for ngrok to start and get public URL
echo "Waiting for ngrok URL..."
for i in $(seq 1 15); do
    sleep 1
    NGROK_URL=$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    tunnels = data.get('tunnels', [])
    for t in tunnels:
        if t.get('proto') == 'https':
            print(t['public_url'])
            break
except:
    pass
" 2>/dev/null)
    if [ -n "$NGROK_URL" ]; then
        break
    fi
done

if [ -z "$NGROK_URL" ]; then
    echo "ERROR: Could not get ngrok URL. Is ngrok authenticated?"
    echo "Run: ngrok config add-authtoken YOUR_TOKEN"
    kill $NGROK_PID 2>/dev/null
    exit 1
fi

echo "ngrok URL: $NGROK_URL"
echo "Agent endpoint: $NGROK_URL/submit"

# Update .env with ngrok URL
if grep -q "^NGROK_URL=" .env; then
    sed -i '' "s|^NGROK_URL=.*|NGROK_URL=$NGROK_URL|" .env
else
    echo "NGROK_URL=$NGROK_URL" >> .env
fi

export NGROK_URL

echo ""
echo "========================================="
echo "Agent address: $(python3 -c "
from uagents_core.identity import Identity
import os
seed = os.environ.get('PYMOL_AGENT_SEED','')
if seed:
    print(Identity.from_seed(seed, 0).address)
")"
echo "Endpoint: $NGROK_URL/submit"
echo "========================================="
echo ""
echo "Now go to agentverse.ai → Launch Agent → Connect Agent → uAgents"
echo "Paste endpoint: $NGROK_URL/submit"
echo ""
echo "Starting pymol uAgent..."
python3 -m pymol_uagent.agent

# Cleanup ngrok on exit
kill $NGROK_PID 2>/dev/null
