# Day 14 Lab - Mission Answers

> Mọi output dưới đây lấy từ lệnh đã chạy trên máy (Ubuntu 24.04 WSL2 + Docker Desktop).

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns trong `01-localhost-vs-production/develop/app.py`
1. API key và `DATABASE_URL` (kèm mật khẩu) hardcode trong code (dòng 17-18) → lộ khi push GitHub.
2. Không có config management: `DEBUG = True`, `MAX_TOKENS = 500` viết cứng (dòng 21-22).
3. Dùng `print()` thay vì logging, và còn in cả secret ra log (`print(f"[DEBUG] Using key: ...")`, dòng 34).
4. Không có endpoint `/health` → platform không biết khi nào cần restart.
5. Port cố định `8000`, không đọc biến `PORT` (dòng 52).
6. `host="localhost"` → trong container/cloud không nhận được kết nối từ bên ngoài (dòng 51).
7. `reload=True` (chế độ debug) bật cứng; không có xử lý SIGTERM/graceful shutdown.

### Exercise 1.2: Chạy bản develop
```
$ curl -i -X POST "http://127.0.0.1:18000/ask?question=Hello"
HTTP/1.1 200 OK
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}
```
(Chạy ở cổng 18000 vì cổng 8000 trên máy đang bị chương trình khác chiếm.)

### Exercise 1.3: Bảng so sánh
| Feature | Develop | Production | Tại sao quan trọng? |
|---|---|---|---|
| Config | Hardcode trong code | Đọc từ biến môi trường qua `config.py` (`settings`) | Đổi giữa dev/staging/prod mà không sửa code, không commit secret |
| Secrets | `OPENAI_API_KEY = "sk-..."` trong code | `os.getenv("OPENAI_API_KEY")`, `.env` nằm trong `.gitignore` | Tránh lộ key khi push repo |
| Port / host | Cố định `8000`, `localhost` | `PORT` từ env, host `0.0.0.0` | Railway/Render inject `PORT`; container cần bind `0.0.0.0` |
| Health check | Không có | `GET /health` (liveness) và `GET /ready` (readiness) | Platform restart khi chết, load balancer chỉ gửi traffic khi sẵn sàng |
| Logging | `print()` (lộ cả secret) | JSON log, không log secret | Dễ parse/tìm kiếm, an toàn |
| Shutdown | Tắt đột ngột | Lifespan + xử lý SIGTERM, hoàn thành request đang chạy | Không mất request của người dùng khi deploy/scale |

Bản production gọi thật:
```
$ curl -i http://127.0.0.1:18000/health
HTTP/1.1 200 OK
{"status":"ok","uptime_seconds":1.1,"version":"1.0.0","environment":"development",...}
```

## Part 2: Docker

### Exercise 2.1: Câu hỏi về `02-docker/develop/Dockerfile`
1. Base image: `python:3.11` (bản đầy đủ, nặng).
2. Working directory: `/app`.
3. `COPY requirements.txt` trước `COPY app.py`: để Docker cache layer `pip install`; chỉ cài lại dependencies khi `requirements.txt` đổi, còn sửa code thì dùng lại cache.
4. `CMD` là lệnh mặc định, có thể bị ghi đè khi `docker run <image> <lệnh khác>`; `ENTRYPOINT` là lệnh cố định của container (tham số chạy thêm được nối vào sau).

### Exercise 2.2: Build và chạy bản develop
```
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
$ docker run -p 18000:8000 my-agent:develop
$ curl -i http://127.0.0.1:18000/health
{"status":"ok","uptime_seconds":0.6,"container":true}
$ curl -i -X POST "http://127.0.0.1:18000/ask?question=What%20is%20Docker"
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
```

### Exercise 2.3: Multi-stage build
- Stage 1 (`builder`, `python:3.11-slim`): cài `gcc`, `libpq-dev` và `pip install --user` các dependencies.
- Stage 2 (`runtime`, `python:3.11-slim`): chỉ copy `/root/.local` (packages đã cài) và source; tạo user non-root `appuser`, có `HEALTHCHECK`.
- Image nhỏ hơn vì runtime không chứa compiler, build tools, apt cache; base là `slim` thay vì bản đầy đủ.

Kích thước đo bằng `docker image inspect`:
- Develop: **1667.77 MB** (1,667,771,716 bytes) — `docker images` hiển thị 1.67GB
- Production (multi-stage): **239.82 MB** (239,815,363 bytes) — `docker images` hiển thị 240MB
- Chênh lệch: **giảm 85.62%**

### Exercise 2.4: Docker Compose stack (`02-docker/production`)
```
Client → Nginx (port 80) → Agent (port 8000) → Redis (6379)
                                             → Qdrant (6333)
```
Services: `agent`, `redis`, `qdrant`, `nginx`. Chúng giao tiếp qua mạng nội bộ `internal`; chỉ Nginx publish cổng ra ngoài, agent đợi Redis và Qdrant healthy rồi mới khởi động (`depends_on: condition: service_healthy`).

Kết quả test qua Nginx:
```
$ curl -i http://127.0.0.1/health
HTTP/1.1 200 OK  Server: nginx
{"status":"ok","uptime_seconds":1.1,"version":"2.0.0",...}
$ curl -i -X POST http://127.0.0.1/ask -H "Content-Type: application/json" -d '{"question": "Explain microservices"}'
HTTP/1.1 200 OK
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

## Part 3: Cloud Deployment

### Exercise 3.1: Railway Deployment (Agent Part 6 + Redis)
- **Public URL:** https://k5-l3a-day14-khongtienduong-2a202603467-deployme-production.up.railway.app
- **Cấu hình đã đặt trên Railway:** Root Directory = `/06-lab-complete`, kết nối service `Redis` qua `REDIS_URL=${{Redis.REDIS_URL}}`, đặt `AGENT_API_KEY`, `ENVIRONMENT=production`, `RATE_LIMIT_PER_MINUTE=10`, `DAILY_BUDGET_USD=10.0` trong Variables (không hardcode trong repo).
- **Kết quả 4 lệnh tự kiểm CP6:**
  - `GET /health` → `200` (`{"status":"ok","uptime_seconds":...,"environment":"production"}`)
  - `GET /ready` → `200` (`{"status":"ready","redis":"connected"}`)
  - `POST /ask` (không gửi `X-API-Key`) → `401`
  - `POST /ask` (có `X-API-Key` hợp lệ) → `200`
- **Screenshots:**
  - Dashboard kiến trúc (Agent + Redis Online): `screenshots/dashboard.png`
  - Trạng thái service Active: `screenshots/running.png`
  - Kết quả chạy 4 lệnh test: `screenshots/test.png`

### Exercise 3.2: So sánh `railway.toml` và `render.yaml`
| Khía cạnh | `railway.toml` | `render.yaml` | Vì sao khác nhau? |
|---|---|---|---|
| **Phạm vi khai báo** | Cấu hình cho **1 service đơn lẻ** (`[build]` builder/Dockerfile, `[deploy]` startCommand, `healthcheckPath`, restart policy). | **Blueprint (IaC) đa dịch vụ**: khai báo cùng lúc cả web service (`type: web`), database/cache (`type: redis`), `region`, `plan`. | Railway quản lý đa dịch vụ linh hoạt trên Project Canvas/CLI, còn Render hướng tới GitOps khai báo trọn gói hạ tầng trong 1 file. |
| **Biến môi trường & Secret** | Không liệt kê `envVars` trong file; đặt qua Dashboard/CLI và nối dịch vụ bằng biến tham chiếu `${{Redis.REDIS_URL}}`. | Khai báo trực tiếp khối `envVars`, hỗ trợ `generateValue: true` (tự sinh khoá), `sync: false` (nhập tay bảo mật), và `fromService` để lấy `connectionString` của Redis. | Render dùng Blueprint để tự động cấp phát và nối tài nguyên ngay lần đầu sync repo mà không làm lộ secret trong Git. |

### Exercise 3.3: Pipeline CI/CD GCP Cloud Run (`cloudbuild.yaml` & `service.yaml`)
Khi push code lên nhánh `main`, Cloud Build chạy tuần tự 4 bước (`waitFor`): **(1) `test`** cài dependencies và chạy `pytest tests/` trên `python:3.11-slim` để chặn code lỗi từ sớm; **(2) `build`** đóng gói Docker image gắn tag `$COMMIT_SHA` và `latest` kèm `--cache-from` để tận dụng layer cache; **(3) `push`** đẩy toàn bộ image tag lên Container Registry (`gcr.io/$PROJECT_ID/ai-agent`); và **(4) `deploy`** phát hành image đúng mã `$COMMIT_SHA` lên Cloud Run (`asia-southeast1`). Đi kèm đó, `service.yaml` định nghĩa cấu hình Knative cho Cloud Run: giữ `minScale: 1` (tránh cold start), `maxScale: 10` (`containerConcurrency: 80`), giới hạn `1 CPU / 512Mi`, đọc secret an toàn từ Secret Manager (`secretKeyRef`), và giám sát bằng `startupProbe` (`/ready`) cùng `livenessProbe` (`/health`).

## Part 4: API Security

### Exercise 4.1: API Key (`04-api-gateway/develop`, chạy với `AGENT_API_KEY=secret-key-123`)
- Key được kiểm tra trong hàm `verify_api_key` (dependency `Security(APIKeyHeader)`).
- Thiếu key → 401, sai key → 403; muốn rotate key chỉ cần đổi biến môi trường `AGENT_API_KEY` rồi restart.
```
$ curl -i -X POST .../ask -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i -X POST .../ask -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question": "Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

### Exercise 4.2: JWT (`04-api-gateway/production`, tài khoản `student` / `demo123`)
Luồng: `POST /auth/token` → server ký JWT (HS256, hết hạn 60 phút) → client gửi `Authorization: Bearer <token>` → server xác minh chữ ký, không cần tra database.
```
$ curl -i -X POST .../ask -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 401 Unauthorized
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

$ curl -i -X POST .../ask -H "Authorization: Bearer <TOKEN-đã-che>" -H "Content-Type: application/json" -d '{"question": "Explain JWT"}'
HTTP/1.1 200 OK
{"question":"Explain JWT","answer":"...","usage":{"requests_remaining":9,"budget_remaining_usd":1.6e-05}}
```

### Exercise 4.3: Rate limiting
- Thuật toán: **sliding window counter** (deque timestamp mỗi user, cửa sổ 60 giây).
- Giới hạn: user 10 request/phút, admin 100 request/phút. Admin "bypass" bằng cách dùng tier `rate_limiter_admin` (role `admin`).
- Gọi 11 lần liên tiếp bằng cùng một token, request thứ 11:
```
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
retry-after: 59
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

### Exercise 4.4: Cost guard
Cách làm: mỗi request cộng chi phí token (input/output nhân giá/1K token) vào bộ đếm; trước khi gọi LLM kiểm tra tổng đã chi, nếu `>= ngân sách` thì trả **402**. Bản bài mẫu lưu trong bộ nhớ; bản Part 6 của mình (`06-lab-complete/app/cost_guard.py`) lưu trong **Redis** bằng `INCRBYFLOAT` với key theo ngày (`cost:daily:YYYY-MM-DD`) và theo tháng, có `EXPIRE` để tự reset, nên mọi worker/instance dùng chung và không mất khi restart. Rate limit bảo vệ tốc độ gọi, cost guard bảo vệ tiền; cần cả hai vì vài request đắt (prompt dài) vẫn có thể đốt ngân sách dù chưa chạm rate limit.

## Part 5: Scaling & Reliability

### Exercise 5.1: Health và readiness (`05-scaling-reliability/develop`)
```
GET /health → 200 {"status":"ok","uptime_seconds":1.1,"version":"1.0.0",...}
GET /ready  → 200 {"ready":true,"in_flight_requests":1}
```
- `/health` (liveness): process còn sống không; fail thì platform restart container.
- `/ready` (readiness): sẵn sàng nhận traffic chưa; fail (503) thì load balancer ngừng gửi traffic nhưng không restart.

### Exercise 5.2: Graceful shutdown
Gửi một request `/ask` rồi `kill -TERM` ngay: request vẫn trả `200 OK`, server log:
```
INFO:     Shutting down
INFO:     Waiting for application shutdown.
... INFO 🔄 Graceful shutdown initiated...
... INFO ✅ Shutdown complete
INFO:     Finished server process
... INFO Received signal 15 — uvicorn will handle graceful shutdown
```

### Exercise 5.3: Stateless
State (session, history) lưu trong Redis (`session:<id>`, TTL 1 giờ), không để trong RAM của process, vì khi scale mỗi instance có bộ nhớ riêng; request kế tiếp có thể rơi vào instance khác.

### Exercise 5.4: Load balancing (`docker compose -p k5-day14-scaling up -d --build --scale agent=3`)
3 container `agent` + `redis` + `nginx` (cổng 8080) đều chạy `healthy`; Nginx chia request qua 3 instance.

### Exercise 5.5: `python test_stateless.py`
```
Request 1: [instance-42961f]
Request 2: [instance-d1d30d]
Request 3: [instance-42961f]
Request 4: [instance-eadef1]
Request 5: [instance-d1d30d]
Instances used: {'instance-42961f', 'instance-d1d30d', 'instance-eadef1'}
✅ All requests served despite different instances!
Total messages: 10  (5 user + 5 assistant)
✅ Session history preserved across all instances via Redis!
```
Giải thích: 5 request trong cùng một session đi qua 3 instance khác nhau nhưng lịch sử vẫn đủ 10 tin nhắn vì cả 3 instance đọc/ghi chung Redis.

## Part 6: Final Project

Kết quả chạy đầy đủ `python check_production_ready.py --public-url https://k5-l3a-day14-khongtienduong-2a202603467-deployme-production.up.railway.app` trong `06-lab-complete/` trên Ubuntu 24.04 WSL2 + Docker Desktop:

```text
================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 44/44 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

## AI log

Theo quy định tại `RULES.md` mục 1, dưới đây là nhật ký sử dụng trợ lý AI (Antigravity) trong quá trình làm bài:

1. **Tìm hiểu cấu trúc đề bài & lưu ý riêng của lớp K5**
   - *Hỏi gì:* Nhờ tổng hợp yêu cầu từ các file `.md` (`README.md`, `RULES.md`, `RUBRIC.md`, `CHECKPOINTS.md`, `SUBMISSION.md`, `06-lab-complete/README.md`) và kiểm tra môi trường máy tính.
   - *Nhận gì:* Danh sách 11 lưu ý riêng của lớp K5 (đặc biệt yêu cầu chạy trên Linux/WSL2 `os.name == 'posix'` để kiểm tra `SIGTERM`, cờ `-p` cho Docker Compose, deploy thẳng `06-lab-complete/`) và hướng dẫn cài Ubuntu 24.04 WSL2 tích hợp Docker Desktop.
   - *Tự sửa & tự kiểm tra:* Đã kiểm tra `python -c "import os; print(os.name)"` trả về `posix` và `docker run --rm hello-world` chạy thành công từ trong WSL2.

2. **Hoàn thiện mã nguồn Part 6 (`06-lab-complete/`)**
   - *Hỏi gì:* Gợi ý triển khai các mục `TODO` trong `app/config.py`, `app/redis_client.py`, `app/auth.py`, `app/rate_limiter.py`, `app/cost_guard.py`, `app/main.py`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml` theo đúng bảng Hợp đồng.
   - *Nhận gì:* Thiết kế kết nối Redis lazy (không ping khi import để container vẫn sống khi chưa có Redis), `APIKeyHeader(auto_error=False)` trả đúng mã `401`, Lua script sliding window 60s trên Redis Sorted Set cho rate limit (`429` + `Retry-After`), `INCRBYFLOAT` theo ngày/tháng cho cost guard (`402`), `JsonFormatter` cho structured logging, nối chuỗi `signal.SIGTERM` bên trong `lifespan` của FastAPI, và multi-stage `Dockerfile` dùng `/opt/venv` với user non-root `appuser` (`exec uvicorn ... --port ${PORT:-8000}`).
   - *Tự sửa & tự kiểm tra:* Chạy trực tiếp `python check_production_ready.py` (không sửa file chấm) trên WSL2 + Docker, xác minh từng hạng mục runtime (restart vẫn giữ 429, tắt Redis `/ready` trả 503 còn `/health` trả 200, `docker stop` thoát mã 0 sau 1.5s, image 273 MB < 500 MB) đạt `PASS 12/12`.

3. **Sửa lỗi môi trường Part 7 & bổ sung `KNOWLEDGE_BASE`**
   - *Hỏi gì:* Thêm metric Histogram `agent_question_length_chars` (Ex 7.1), bổ sung tài liệu còn thiếu vào `KNOWLEDGE_BASE` (Ex 7.3), viết workflow CI `.github/workflows/eval.yml`, và xử lý lỗi `ModuleNotFoundError: No module named 'uvicorn'` khi build container `06-lab-complete/benchmark-observability/production/Dockerfile`.
   - *Nhận gì:* Thêm 2 entry về Kubernetes HPA (`scaling-03`) và JWT vs API key (`security-02`) vào `utils/mock_llm.py` (không sửa `golden_dataset.jsonl`), đồng thời thêm `ENV PYTHONUSERBASE=/home/agent/.local` vào `production/Dockerfile` do builder cài gói bằng `pip install --user` ở `/root/.local` rồi copy sang user `agent`.
   - *Tự sửa & tự kiểm tra:* Chạy thật toàn bộ lệnh `load_test.py`, `eval/run_eval.py` (đạt `23/23 = 100%`, `0 regression`), Locust headless (`scale_1`, `scale_3`), kịch bản Chaos trên Prometheus/Grafana/Jaeger và kiểm chứng mọi số liệu trong `BENCHMARK_REPORT.md` khớp chính xác với các file JSON/CSV đã xuất.
