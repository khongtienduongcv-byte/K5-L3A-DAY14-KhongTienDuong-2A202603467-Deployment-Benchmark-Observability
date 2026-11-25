# Deployment Information

## Public URL
https://k5-l3a-day14-khongtienduong-2a202603467-deployme-production.up.railway.app

## Platform
Railway (Docker multi-stage build from `/06-lab-complete` + Railway managed Redis)

## Test Commands

### 1. Liveness & Readiness Checks (`GET /health` & `GET /ready`)
```bash
BASE="https://k5-l3a-day14-khongtienduong-2a202603467-deployme-production.up.railway.app"

curl -sS "$BASE/health"
# Expected (200 OK): {"status":"ok","uptime_seconds":...,"environment":"production"}

curl -sS "$BASE/ready"
# Expected (200 OK): {"status":"ready","redis":"connected"}
```

### 2. Authentication Check — Without API Key (`POST /ask` → `401`)
```bash
curl -sS -i -X POST "$BASE/ask" \
  -H "Content-Type: application/json" \
  -d '{"question": "Hello"}'
# Expected: HTTP/2 401 — {"detail":"Invalid or missing API key"}
```

### 3. Authenticated Agent Request (`POST /ask` with `X-API-Key` → `200`)
```bash
curl -sS -X POST "$BASE/ask" \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "Hello"}'
# Expected (200 OK): {"question":"Hello","answer":"...","usage":{"input_tokens":...,"output_tokens":...,"cost_usd":...}}
```

### 4. CP6 Self-Test Summary (HTTP Status Codes Only)
```bash
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"                                                                                               # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"                                                                                                # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'                            # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'  # 200
```

## Environment Variables Set (on Railway Dashboard — Not Hardcoded in Repo)
- `AGENT_API_KEY` (secret API key configured on Railway service variables)
- `REDIS_URL` (`${{Redis.REDIS_URL}}` linked to the Railway Redis service)
- `ENVIRONMENT` (`production`)
- `RATE_LIMIT_PER_MINUTE` (`10`)
- `DAILY_BUDGET_USD` (`10.0`)
- `MONTHLY_BUDGET_USD` (`50.0`)
- `PORT` (injected automatically by Railway)

## Screenshots
- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
