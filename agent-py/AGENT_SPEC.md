# Telemetry Agent — Specification Document

## Overview

The Telemetry Agent is responsible for packaging and transmitting sensor data to the Telemetry gRPC Service. Two reference implementations are provided:

- **C Agent** — for embedded/resource-constrained environments
- **Python Agent** — for rapid prototyping and higher-level integration

The agent does **not** collect sensor data itself. It accepts pre-populated telemetry values and transmits them via gRPC, logging all transaction timing and throughput metrics.

---

## Responsibilities

1. Construct a `TelemetryPacket` protobuf message from provided sensor values
2. Establish and maintain a gRPC channel to the Telemetry Service
3. Transmit packets using either unary RPC or client-side streaming RPC
4. Record send/receive timestamps and compute RTT and throughput
5. Write structured transaction logs to a configurable log directory
6. Handle connection errors and retry with exponential backoff

---

## Telemetry Packet Fields

| Field | Type | Unit | Description |
|---|---|---|---|
| `device_id` | string | — | Unique identifier for the agent/device |
| `sequence_number` | uint64 | — | Monotonically increasing packet counter |
| `timestamp_ms` | uint64 | ms | Unix epoch timestamp at packet creation |
| `temperature` | float | °C | Ambient or sensor temperature |
| `latitude` | double | degrees | GPS latitude (-90 to +90) |
| `longitude` | double | degrees | GPS longitude (-180 to +180) |
| `altitude` | double | meters | GPS altitude above sea level |
| `accel_x` | float | m/s² | Accelerometer X-axis |
| `accel_y` | float | m/s² | Accelerometer Y-axis |
| `accel_z` | float | m/s² | Accelerometer Z-axis |
| `gyro_x` | float | rad/s | Gyroscope X-axis |
| `gyro_y` | float | rad/s | Gyroscope Y-axis |
| `gyro_z` | float | rad/s | Gyroscope Z-axis |
| `mag_x` | float | µT | Magnetometer X-axis |
| `mag_y` | float | µT | Magnetometer Y-axis |
| `mag_z` | float | µT | Magnetometer Z-axis |

---

## gRPC Service Methods Used

### Unary RPC — `SendTelemetry`
- Sends a single `TelemetryPacket`
- Receives an `AckResponse` with server-side timestamp
- Used for low-frequency or one-shot transmissions

### Client Streaming RPC — `StreamTelemetry`
- Sends a stream of `TelemetryPacket` messages
- Receives a single `AckResponse` at the end of the stream
- Used for high-frequency burst transmissions

---

## Transaction Logging

### Log Format
Each log entry is a structured line with the following fields:

```
[TIMESTAMP] [LEVEL] [SEQ] [EVENT] key=value key=value ...
```

### Logged Events

| Event | Fields Logged |
|---|---|
| `PACKET_CREATED` | seq, device_id, timestamp_ms, payload_bytes |
| `SEND_START` | seq, send_time_ms |
| `ACK_RECEIVED` | seq, ack_time_ms, rtt_ms, throughput_kbps |
| `SEND_ERROR` | seq, error_code, error_message |
| `RETRY` | seq, attempt, backoff_ms |
| `SESSION_SUMMARY` | total_packets, total_bytes, avg_rtt_ms, avg_throughput_kbps, duration_s |

### Throughput Calculation

```
payload_bytes = serialized protobuf message size in bytes
rtt_ms        = ack_receive_time - send_start_time  (milliseconds)
throughput     = (payload_bytes * 2 * 1000) / rtt_ms / 1024  (KB/s)
               = round-trip bytes / RTT converted to KB/s
```

### Log File Naming
```
logs/agent_<device_id>_<YYYYMMDD_HHMMSS>.log
```

---

## Python Agent

### File: `agent_python/telemetry_agent.py`

### Dependencies
```
grpcio>=1.60.0
grpcio-tools>=1.60.0
protobuf>=4.25.0
```

### CLI Arguments

| Argument | Default | Description |
|---|---|---|
| `--host` | `localhost` | gRPC service host |
| `--port` | `50051` | gRPC service port |
| `--device-id` | `agent-py-001` | Device identifier |
| `--packets` | `100` | Number of packets to send |
| `--interval` | `0.1` | Delay between packets (seconds) |
| `--mode` | `unary` | `unary` or `stream` |
| `--log-dir` | `./logs` | Log output directory |

### Key Classes

#### `TelemetryAgent`
```python
class TelemetryAgent:
    def __init__(self, host, port, device_id, log_dir)
    def connect(self) -> None
    def build_packet(self, seq, sensor_data: dict) -> TelemetryPacket
    def send_unary(self, packet: TelemetryPacket) -> TransactionRecord
    def send_stream(self, packets: List[TelemetryPacket]) -> TransactionRecord
    def close(self) -> None
```

#### `TransactionLogger`
```python
class TransactionLogger:
    def __init__(self, device_id, log_dir)
    def log_send_start(self, seq, payload_bytes) -> float
    def log_ack_received(self, seq, send_time, payload_bytes) -> None
    def log_error(self, seq, error) -> None
    def write_session_summary(self, records: List[TransactionRecord]) -> None
```

### Sample Usage
```python
agent = TelemetryAgent(host="localhost", port=50051,
                       device_id="agent-py-001", log_dir="./logs")
agent.connect()

sensor_data = {
    "temperature": 23.5,
    "latitude": 37.7749, "longitude": -122.4194, "altitude": 15.0,
    "accel_x": 0.01, "accel_y": -0.02, "accel_z": 9.81,
    "gyro_x": 0.001, "gyro_y": 0.002, "gyro_z": -0.001,
    "mag_x": 25.3, "mag_y": -10.1, "mag_z": 42.7
}

for seq in range(1, 101):
    packet = agent.build_packet(seq, sensor_data)
    record = agent.send_unary(packet)

agent.close()
```

---

## C Agent

### File: `agent_c/telemetry_agent.c`

### Dependencies
- `libgrpc` — gRPC C core
- `libprotobuf-c` — Protocol Buffers for C
- `pthreads` — for async logging

### Build System: CMake

```cmake
cmake_minimum_required(VERSION 3.15)
project(telemetry_agent C)
find_package(PkgConfig REQUIRED)
pkg_check_modules(GRPC REQUIRED grpc)
pkg_check_modules(PROTOBUF_C REQUIRED libprotobuf-c)
add_executable(telemetry_agent telemetry_agent.c telemetry.pb-c.c)
target_link_libraries(telemetry_agent ${GRPC_LIBRARIES} ${PROTOBUF_C_LIBRARIES})
```

### CLI Arguments

| Argument | Default | Description |
|---|---|---|
| `--host` | `localhost` | gRPC service host |
| `--port` | `50051` | gRPC service port |
| `--device-id` | `agent-c-001` | Device identifier |
| `--packets` | `100` | Number of packets to send |
| `--interval-ms` | `100` | Delay between packets (ms) |
| `--log-dir` | `./logs` | Log output directory |

### Key Structs and Functions

```c
typedef struct {
    grpc_channel *channel;
    grpc_call    *call;
    char          device_id[64];
    FILE         *log_file;
    uint64_t      seq;
} TelemetryAgent;

int  agent_init(TelemetryAgent *agent, const char *host,
                int port, const char *device_id, const char *log_dir);
int  agent_send_packet(TelemetryAgent *agent, Telemetry__TelemetryPacket *pkt);
void agent_log_transaction(TelemetryAgent *agent, uint64_t seq,
                           double rtt_ms, size_t payload_bytes);
void agent_destroy(TelemetryAgent *agent);
```

### Timing in C

```c
#include <time.h>

struct timespec t_start, t_end;
clock_gettime(CLOCK_MONOTONIC, &t_start);
// ... send packet ...
clock_gettime(CLOCK_MONOTONIC, &t_end);

double rtt_ms = (t_end.tv_sec - t_start.tv_sec) * 1000.0
              + (t_end.tv_nsec - t_start.tv_nsec) / 1e6;
```

---

## Error Handling & Retry Policy

| Condition | Action |
|---|---|
| Connection refused | Retry up to 5 times with exponential backoff (100ms base) |
| Timeout (>5s) | Log error, skip packet, increment error counter |
| Service unavailable | Retry with backoff, log warning |
| Protobuf serialization error | Log error, abort packet, continue |

---

## Session Summary Output

At the end of a run, both agents print and log a summary:

```
========== SESSION SUMMARY ==========
Device ID       : agent-py-001
Total Packets   : 100
Total Bytes Sent: 31,200 bytes
Duration        : 10.42 seconds
Avg RTT         : 8.31 ms
Min RTT         : 6.12 ms
Max RTT         : 14.87 ms
Avg Throughput  : 291.4 KB/s
Errors          : 0
=====================================
```