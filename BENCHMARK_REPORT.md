# Benchmark & Observability Report — Day 14

> Mọi con số dưới đây được trích xuất trực tiếp từ các file `reports/*.json`, `benchmark-results/*.csv`, Prometheus/Jaeger API và ảnh chụp màn hình thực tế trong `screenshots/`.

**Họ tên:** Khong Tien Duong (2A202603467)
**Ngày chạy:** 2026-11-25
**Môi trường:** Windows 11 + Ubuntu 24.04 LTS (WSL2, Python 3.12.3), Docker Desktop 29.9.3 (12 CPUs / 8 GB RAM)

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Với `mock-llm-small` (base 120 ms + jitter 60 ms + retrieval ~20 ms ≈ 180–250 ms), ngưỡng 500 ms đủ dư cho biến động mạng/hàng đợi nhẹ nhưng phát hiện ngay khi hệ thống nghẽn hoặc tỉ lệ tail latency vượt 5%. |
| Error rate `/ask` | < 2.0 % | Mock upstream LLM có tỉ lệ lỗi ngẫu nhiên nền `MOCK_ERROR_RATE=0.01` (1%); đặt SLO < 2% (error budget 2%) cho phép hấp thụ nhiễu upstream bình thường nhưng chặn sự cố suy giảm thật (> 5%). |
| Accuracy trên golden dataset | ≥ 85 % (0 regression) | Agent v2 (có RAG) đạt 91.3% ban đầu và 100% sau khi bổ sung KB; ngưỡng CI ≥ 85% kèm điều kiện `0 regression` chặn mọi thay đổi làm tụt chất lượng câu trả lời đã đúng trước đó. |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

> Bổ sung từ **Exercise 7.1**:
> - Ví dụ 3 loại metric trên `/metrics`: **Counter** (`http_requests_total`, `llm_tokens_total`, `llm_cost_usd_total`), **Gauge** (`agent_in_flight_requests`, `agent_info`), **Histogram** (`http_request_duration_seconds`, `llm_request_duration_seconds`, và metric mới `agent_question_length_chars`).
> - Middleware dùng `route.path` (template `/ask` hoặc `unmatched`) thay vì `request.url.path` thật để chống **cardinality explosion**: nếu bot quét hàng vạn URL ngẫu nhiên (`/wp-admin`, `/.env`, `/xyz123`), mỗi URL tạo một time series riêng làm Prometheus tràn RAM.

### 2.1 Concurrency vs latency (agent v2)

*(Nguồn: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json` — mỗi mức chạy 300 requests)*

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---:|---:|---:|---:|---:|---|
| 1 | 4.27 | 195.3 | 227.0 | 1699.2 | 1.00% (`3/300`) | ✅ PASS |
| 10 | 37.23 | 198.9 | 237.3 | 1699.5 | 1.00% (`3/300`) | ✅ PASS |
| 50 | 36.53 | 785.8 | 4149.2 | 5918.7 | 1.67% (`5/300`) | ❌ FAIL |
| 100 | 37.56 | 1388.2 | 5246.4 | 6018.7 | 1.00% (`3/300`) | ❌ FAIL |

**Nhận xét:** RPS **không** tăng tuyến tính mãi theo concurrency:
- Từ `concurrency = 1` lên `10`, RPS tăng gần tuyến tính (**4.27 → 37.23 req/s**, gấp ~8.7 lần) trong khi `p95` hầu như giữ nguyên (`227.0 → 237.3 ms`), vì `async def ask` giải phóng event loop trong lúc chờ `asyncio.sleep` của LLM call.
- Từ `concurrency = 50` và `100`, throughput chạm trần bão hoà quanh **~36.5–37.6 req/s** của một tiến trình Python đơn lẻ (chi phí xử lý HTTP/JSON, tạo log JSON đồng bộ ra stdout/disk trên mount `/mnt/d`). Theo định luật Little ($L = \lambda \times W$), khi $\lambda$ không tăng thêm được mà số request đồng thời $L$ tăng gấp 5–10 lần, thời gian xếp hàng chờ $W$ phình to khiến `p95` vọt lên **4149.2 ms** và **5246.4 ms**, vi phạm SLO `< 500 ms`.

### 2.2 Tail latency

*(Nguồn: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json` — chạy ở `concurrency = 20`, `300` requests)*

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---:|---:|---:|
| 0 | 225.9 | 344.3 | 393.1 |
| 0.03 (mặc định) | 253.7 | 322.7 | 1715.6 |
| 0.1 | 347.5 | 1698.4 | 1721.9 |

**Nhận xét:**
- Chỉ số nhạy nhất với một tỷ lệ nhỏ request chậm là **p99** (và **p95** khi tỷ lệ chậm vượt quá 5%): khi `MOCK_SLOW_RATE` tăng từ `0` lên `0.03` (3% request cộng thêm 1500 ms), `avg` chỉ nhích nhẹ **+27.8 ms** (`225.9 → 253.7 ms`) và `p95` vẫn ở mức thấp (`322.7 ms`), nhưng **p99 nhảy vọt gấp 4.4 lần lên `1715.6 ms`**. Khi tăng lên `0.1` (10% request chậm > ngưỡng 5%), cả **p95 cũng vọt lên `1698.4 ms`** (vi phạm SLO), dù `avg` vẫn chỉ là `347.5 ms` (< 500 ms).
- **SLO tuyệt đối không nên đặt theo average** vì số trung bình cộng làm phẳng và che giấu nhóm người dùng ở đuôi phân phối (tail latency). Nếu đặt SLO `avg < 500 ms`, cả ở mức 10% người dùng phải chờ 1.7 giây hệ thống vẫn báo "xanh", làm trải nghiệm thực tế của khách hàng suy giảm nghiêm trọng mà không hề có cảnh báo.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

*(Nguồn: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json` trên bộ 23 câu `golden_dataset.jsonl`)*

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---:|---:|---:|
| Accuracy | 4.35% (`1/23`) | 91.30% (`21/23`) | 100.00% (`23/23`) |
| Avg tokens / câu | 57.3 | 109.0 | 113.7 |
| Tổng cost (USD) | \$0.000406 | \$0.000760 | \$0.000790 |
| Cost / câu đúng (USD) | \$0.00040635 | \$0.00003619 | \$0.00003436 |
| Quality gate | ❌ FAIL | ✅ PASS | ✅ PASS (`0` regression) |

**Những câu v2 trả lời sai ban đầu và cách bạn sửa:**

| ID | Keyword bị thiếu | Bạn đã sửa gì |
|---|---|---|
| `security-02` | `token`, `hết hạn`, `chữ ký` | Thêm mục từ khoá `["jwt"]` vào `KNOWLEDGE_BASE` trong `utils/mock_llm.py` giải thích sự khác biệt giữa API key cố định và JWT (token có chữ ký số và thời điểm hết hạn). |
| `scaling-03` | `cpu`, `memory`, `custom metrics` | Thêm mục từ khoá `["hpa", "kubernetes", "autoscal"]` vào `KNOWLEDGE_BASE` giải thích cơ chế Kubernetes HPA tự động scale pod theo CPU, memory và custom metrics. |

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2 & Quality Gate CI:**
- **Trade-off:** Agent v2 thêm bước retrieval (RAG, ~20 ms) và chèn tài liệu ngữ cảnh vào prompt nên tiêu tốn lượng token trung bình cao gần gấp đôi v1 (`109.0 → 113.7` tokens so với `57.3` tokens) và tổng chi phí tăng từ `\$0.000406` lên `\$0.000790`. Tuy nhiên, độ chính xác tăng vọt từ **4.35%** lên **100.0%**, giúp **chi phí trên mỗi câu trả lời đúng (`cost_per_correct_usd`) giảm gần 12 lần** (`\$0.00040635` xuống chỉ còn `\$0.00003436`). Đánh đổi thêm ~20 ms latency và gấp đôi token cho hiệu quả kinh tế thực chất cao hơn 12 lần là hoàn toàn xứng đáng.
- **Chặn merge trong CI (`.github/workflows/eval.yml`):** Script `eval/run_eval.py` trả về **exit code `1`** nếu `accuracy < --min-accuracy` hoặc danh sách `regressions` khác rỗng khi đối chiếu `--baseline`. Trong GitHub Actions (`pull_request`), step chạy `python eval/run_eval.py --url http://localhost:8002 --min-accuracy 0.85 --baseline ../../reports/eval_v2.json` sẽ làm fail job ngay khi PR gây regression, chặn nút Merge tự động.

---

## 4. Observability stack (production)

> **Trả lời câu hỏi Exercise 7.4 (khi chạy Locust 30 users, 2 instances):**
> 1. **p95 vs avg:** Trên Grafana / Prometheus, `p95 ≈ 293.8 ms` trong khi `avg ≈ 234.2 ms` (và `p99 ≈ 1.7 s`). Khoảng cách giữa `avg` và các chỉ số phân vị cao phản ánh độ lệch phải của phân phối độ trễ do 3% request rơi vào tail latency.
> 2. **Phân tải theo instance:** Panel *"Requests/s theo instance"* cho thấy Nginx chia tải round-robin gần như đều tuyệt đối giữa 2 container (`2.78 req/s` và `2.71 req/s` khi mới ramp-up, tổng ~18.3 req/s khi ổn định).
> 3. **Input tokens/s > Output tokens/s:** `input` đạt `~422.1 tokens/s` so với `output` `~220.5 tokens/s` vì ở Agent v2, mỗi lần gọi LLM đều gửi kèm `SYSTEM_PROMPT` + đoạn tài liệu truy xuất từ `KNOWLEDGE_BASE` + câu hỏi của user, dài hơn câu trả lời ngắn gọn mà model sinh ra.
> 4. **`curl http://localhost:8080/metrics`:** Trả về **`HTTP/1.1 404 Not Found`** từ `nginx/1.28.3`. Lý do: file `nginx/nginx.conf` cấu hình `location = /metrics { return 404; }` để không lộ thông tin nội bộ hệ thống (lưu lượng, cấu trúc route, phiên bản, chi phí) ra internet; chỉ Prometheus nằm trong mạng nội bộ Docker `obs_net` mới scrape trực tiếp `agent:8000/metrics` qua DNS service discovery.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải (`screenshots/grafana-dashboard.png`)
- [x] Một trace chậm trong Jaeger (`screenshots/jaeger-slow-trace.png`)
- [x] Một trace lỗi trong Jaeger (`screenshots/jaeger-error-trace.png`)
- [x] Trang Alerts của Prometheus với các alert đang **firing** (`screenshots/prometheus-alert-firing.png`)

### 4.2 Thí nghiệm "phá hệ thống"

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.25` (≥ 0.2) | `AgentHighErrorRate` (`for: 1m`) | **92 giây** (~32s cửa sổ rate vượt 5% + 60s `for: 1m`) | Golden Signals — *Error rate* (đỏ > 5%) & *HTTP req/s by status (5xx)* |
| B | `MOCK_SLOW_RATE=0.35` (≥ 0.3) | `AgentHighLatencyP95` (`for: 2m`) | **142 giây** (~22s p95 vượt 1s + 120s `for: 2m`) | Golden Signals — *Latency p95* & biểu đồ *p50 / p95 / p99 / avg* |
| C | `LLM_MODEL=mock-llm-large` | `LLMCostBurnRateHigh` (`for: 2m`) | **147 giây** (tốc độ chi vượt \$2/giờ + 120s `for: 2m`) | Hàng LLM — *Cost USD / giờ* (tăng vọt ~16 lần) & *LLM p95* |
| D | `docker pause k5-day14-observability-agent-2` | `AgentInstanceDown` (`for: 30s`) | **46 giây** (scrape timeout + 30s `for: 30s`) | Golden Signals — *Instances up* (tụt từ 2 xuống 1); Locust ghi nhận lỗi `504` |
| E | `AGENT_VERSION=v1` | **Không có alert chất lượng/lỗi nào firing** | Không firing (sau > 65 giây quan sát, HTTP vẫn 200 OK, nhanh và rẻ hơn) | Hàng LLM — *Retrieval hit ratio* tụt về 0%, *Tokens/s* giảm, bảng *Instances/Version* hiện `v1` |

*(Ghi chú kỹ thuật ở thí nghiệm D: Phải dùng `docker pause` thay vì `docker stop` vì Prometheus khám phá target bằng Docker DNS `dns_sd_configs` — container bị stop sẽ rút khỏi DNS nên biến mất khỏi danh sách target thay vì báo `up == 0`. Ngoài ra, các lỗi `504 Gateway Timeout` khi Nginx chờ container bị pause hết `proxy_read_timeout` không xuất hiện trên panel Error rate của agent vì request chưa từng được agent xử lý xong để tăng counter của agent — cần giám sát thêm metric tầng Load Balancer/Ingress hoặc synthetic probe từ bên ngoài.)*

**Thí nghiệm E không làm alert nào firing. Bạn sẽ phát hiện loại sự cố này trong production bằng cách nào?**

Sự cố suy thoái chất lượng câu trả lời (*silent quality degradation* — đổi nhầm prompt/version làm mất RAG nhưng HTTP vẫn trả `200 OK` rất nhanh) hoàn toàn vô hình trước các alert hạ tầng (CPU, RAM, HTTP 5xx, latency). Để bắt loại sự cố này trong production cần kết hợp 3 lớp:
1. **Trước khi deploy (CI/CD Quality Gate):** Bắt buộc chạy bộ eval tự động trên golden dataset (`run_eval.py --min-accuracy 0.85 --baseline ...`) cho mọi thay đổi code/prompt/config để chặn bản `v1` ngay từ Pull Request.
2. **Metric nghiệp vụ & hành vi đặc thù AI (Domain Signals):** Đặt alert cho sự sụt giảm bất thường của `retrieval_hit_ratio` (ví dụ đang ~90% tụt về 0% khi RAG hỏng), độ dài câu trả lời trung bình, hoặc tỷ lệ người dùng bấm nút 👎 / hỏi lại câu tương tự.
3. **Online Evaluation (LLM-as-a-Judge trên mẫu traffic thật):** Lấy mẫu bất đồng bộ 1–5% hội thoại thực tế trên production để chấm điểm faithfulness/relevance bằng model giám khảo và bắn alert khi điểm chất lượng trung bình trượt khỏi ngưỡng.

### 4.3 Debug bằng trace

Chọn 1 trace chậm nhất tìm được trên Jaeger (`screenshots/jaeger-slow-trace.png`):

- `trace_id`: `93ae5f1fe2f4abe0b78f4e2c3d532c17`
- Tổng thời gian: **1718.3 ms** (`POST /ask`, ghi nhận ở HTTP middleware log là `1717.2 ms`)
- Span chiếm nhiều thời gian nhất: **`chat mock-llm-small`** (**1660.0 ms**, chiếm **96.6%** tổng thời gian request; trong khi bước `agent.retrieve_context` chỉ mất **25.5 ms** ≈ **1.5%**) → Chứng minh nút thắt nằm ở độ trễ phản hồi từ phía upstream LLM chứ không phải code Python hay bước tìm kiếm tài liệu.
- Dòng log tương ứng (grep theo `trace_id` từ `docker compose -p k5-day14-observability logs agent`):

```json
{"ts": "2026-11-25T09:13:21.455216+00:00", "level": "INFO", "service": "observable-agent", "instance": "b8e53ddfe656", "event": "llm_call", "trace_id": "93ae5f1fe2f4abe0b78f4e2c3d532c17", "span_id": "d63130f453bd1fca", "request_id": "fc16c6bb46f6", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 95, "output_tokens": 55, "cost_usd": 4.7e-05, "llm_ms": 1659.6}
{"ts": "2026-11-25T09:13:21.457036+00:00", "level": "INFO", "service": "observable-agent", "instance": "b8e53ddfe656", "event": "http_request", "trace_id": "93ae5f1fe2f4abe0b78f4e2c3d532c17", "span_id": "d63130f453bd1fca", "request_id": "fc16c6bb46f6", "method": "POST", "route": "/ask", "status": 200, "ms": 1717.2}
```

*(Đối chiếu thêm trace lỗi `screenshots/jaeger-error-trace.png` — `trace_id = c7143d28c330baa9b44cdae88543cc1c`:)*
```json
{"ts": "2026-11-25T09:14:34.974125+00:00", "level": "INFO", "service": "observable-agent", "instance": "b8e53ddfe656", "event": "llm_error", "trace_id": "c7143d28c330baa9b44cdae88543cc1c", "span_id": "b9dc65ad2710ca57", "request_id": "33f69e9bcd1f", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, 2 phút)

*(Nguồn: `benchmark-results/scale_1_stats.csv` và `benchmark-results/scale_3_stats.csv` — ghi đầy đủ cả dòng `POST /ask` và dòng `Aggregated`)*

| Số instance | RPS (`POST /ask` / `Aggregated`) | p50 (ms) | p95 (ms) (`/ask` / `Agg`) | p99 (ms) | Failures (`/ask` / `Agg`) |
|---|---:|---:|---:|---:|---:|
| 1 | 59.57 / 65.47 | 200 | 420 / 380 | 1700 | 57 / 7082 (0.80%) · Tổng 57 / 7784 (0.73%) |
| 3 | 59.29 / 65.25 | 200 | 350 / 330 | 1700 | 74 / 7046 (1.05%) · Tổng 74 / 7755 (0.95%) |

**Giải thích kết quả:**
- **Về p95:** Scale từ 1 lên 3 instance giúp giảm `p95` của `/ask` từ **420 ms xuống 350 ms** (`Aggregated` từ **380 ms xuống 330 ms**) và giảm `p99` của `/health` từ `270 ms` xuống `100 ms`, nhờ chia tải xử lý HTTP/JSON/OpenTelemetry span sang 3 event loop riêng biệt, giảm tranh chấp CPU trên mỗi container (mỗi container giới hạn `0.5 CPU`).
- **Vì sao RPS (~59.5 req/s) và p99 (`1700 ms`) gần như không đổi?** Có hai nguyên nhân gốc rễ:
  1. **Trần tải phía client (Locust pacing):** Mỗi user ảo trong `locustfile.py` có thời gian nghỉ `wait_time` giữa các lần gọi (~1.5s) cộng thời gian chờ phản hồi (~0.25s) ≈ 1.75s/vòng; với 100 users, lưu lượng sinh ra đạt trạng thái cân bằng tự nhiên quanh $100 / 1.75 \approx 57\text{–}65\text{ req/s}$, một container async FastAPI đã đủ sức phục vụ mức I/O chờ này.
  2. **Nút thắt thực sự nằm ở Upstream LLM I/O:** Như trace trên Jaeger chỉ rõ, hơn 96% thời gian của mỗi request nằm ở bước chờ phản hồi từ LLM (`~150–200 ms` bình thường và `~1700 ms` khi dính tail latency). Scale ngang số container của Agent chỉ giải quyết nghẽn CPU của tầng ứng dụng, **không thể làm LLM provider trả lời nhanh hơn** — muốn giảm `p99` của LLM phải dùng semantic caching, streaming response, speculative/fallback routing sang model nhanh hơn, hoặc hedging request.

---

## 6. Kết luận

- **3 điều học được về benchmark & observability:**
  1. **Đừng bao giờ tin vào độ trễ trung bình (`average`):** Chỉ 3% request chậm cũng khiến `p99` vọt lên 1.7 giây trong khi `average` trông vẫn hoàn toàn bình thường (~253 ms); SLO bắt buộc phải neo vào `p95`/`p99`.
  2. **Hiệu năng hạ tầng tốt không đồng nghĩa AI trả lời đúng:** Một phiên bản lỗi mất RAG (`v1`) có thể trả HTTP 200 cực nhanh và rẻ trên Grafana nhưng độ chính xác chỉ còn 4.35%. Hệ thống AI bắt buộc phải song hành cả **Observability hạ tầng** lẫn **Eval chất lượng & Cost per correct answer**.
  3. **Liên kết 3 trụ cột Metrics – Traces – Logs qua `trace_id` và kiểm soát Cardinality:** Metrics (Prometheus/Grafana) báo động *khi nào* có bất thường, Traces (Jaeger) khoanh vùng chính xác *span nào* gây chậm (96.6% ở LLM call), và Logs JSON có gắn `trace_id` cho biết chi tiết ngữ cảnh lỗi mà không làm nổ RAM Prometheus vì label cardinality cao.

- **Nếu đưa agent này lên production thật, em sẽ bổ sung thêm metric / alert:**
  1. **Metric & Alert ở tầng API Gateway / Load Balancer (Nginx/Ingress):** Đo `nginx_http_requests_total{status=~"502|504"}` và synthetic blackbox probe từ ngoài internet vào URL public để bắt được lỗi timeout/chết kết nối mà container agent bị treo không tự đếm được.
  2. **Giám sát chất lượng trực tuyến (AI Quality & Guardrails):** Alert khi `retrieval_empty_ratio` (tỷ lệ câu hỏi không tìm thấy tài liệu RAG) vượt ngưỡng, tỷ lệ bị chặn bởi Rate Limit (`429`) / Cost Guard (`402`) tăng đột biến, và điểm chấm bất đồng bộ LLM-as-a-Judge tụt dưới ngưỡng an toàn.
  3. **Multi-window Multi-burn-rate Alert cho Error Budget & Token Budget:** Cảnh báo sớm tốc độ tiêu thụ ngân sách LLM theo từng tenant/API key trước khi chạm trần cứng `402` làm gián đoạn dịch vụ.
