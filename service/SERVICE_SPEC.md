# Telemetry Service — Specification Document

## Overview

The Telemetry Service is a Python-based gRPC server that receives telemetry packets from one or more agents, validates and processes the data, and logs all transaction timing and throughput metrics. It is designed to handle concurrent connections from both C and Python agents simultaneously.

---

## Responsibilities

1. Listen for incoming gRPC connections on a configurable host/port
2. Accept `TelemetryPacket` messages via unary and streaming RPCs
3. Validate incoming packet fields
4. Record receive timestamps and compute processing time and throughput
5. Write structured transaction logs to a configurable log directory
6. Return `AckResponse` messages with server-side timestamps
7. Expose a session summary at shutdown

---

## Proto Definition

### File: `proto/telemetry.proto`

```protobuf
syntax = "proto3";

package telemetry;

// ── Messages ──────────────────────────────────────────────────────────────

message ImuData {
  float accel_x = 1;   // m/s²
  float accel_y = 2;
  float accel_z = 3;
  float gyro_x  = 4;   // rad/s
  float gyro_y  = 5;
  float gyro_z  = 6;
  float mag_x   = 7;   // µT
  float mag_y   = 8;
  float mag_z   = 9;
}

message GpsData {
  double latitude  = 1;  // degrees
  double longitude = 2;  // degrees
  double altitude  = 3;  // meters
}

message TelemetryPacket {
  string   device_id        = 1;
  uint64   sequence_number  = 2;
  uint64   timestamp_ms     = 3;  // Unix epoch ms
  float    temperature      = 4;  // °C
  GpsData  gps              = 5;
  ImuData  imu              = 6;
}

message AckResponse {
  uint64 sequence_number   = 1;
  uint64 server_timestamp  = 2;  // Unix epoch ms
  bool   success           = 3;
  string message           = 4;
}

// ── Service ───────────────────────────────────────────────────────────────

service TelemetryService {
  // Single packet transmission
  rpc SendTelemetry (TelemetryPacket) returns (AckResponse);

  // Client streams multiple packets; server acks at end
  rpc StreamTelemetry (stream TelemetryPacket) returns (AckResponse);
}
```

---

## Service Architecture

```
┌──────────────────────────────────────────────────────┐
│                  TelemetryServicer                   │
│                                                      │
│  SendTelemetry()      StreamTelemetry()              │
│       │                      │                       │
│       ▼                      ▼                       │
│  PacketValidator        StreamHandler                │
│       │                      │                       │
│       └──────────┬───────────┘                       │
│                  ▼                                    │
│          TransactionLogger                           │
│                  │                                    │
│                  ▼                                    │
│           logs/<date>.log                            │
└──────────────────────────────────────────────────────┘
```

---

## RPC Method Specifications

### `SendTelemetry` (Unary)

**Request:** `TelemetryPacket`
**Response:** `AckResponse`

**Behavior:**
1. Record `receive_time` immediately upon entry
2. Validate all required fields
3. Log the transaction with timing
4. Return `AckResponse` with `server_timestamp` and `success=true`

**Timing:**
```
processing_time_ms = ack_send_time - receive_time
```

---

### `StreamTelemetry` (Client Streaming)

**Request:** `stream TelemetryPacket`
**Response:** `AckResponse`

**Behavior:**
1. Record `stream_start_time` on first packet
2. Iterate over all incoming packets, logging each
3. After stream ends, compute aggregate stats
4. Return a single `AckResponse` with total packet count and success status

**Timing:**
```
stream_duration_ms  = stream_end_time - stream_start_time
avg_packet_rate     = total_packets / stream_duration_s  (packets/sec)
total_throughput    = total_bytes / stream_duration_s / 1024  (KB/s)
```

---

## Transaction Logging

### Log Format

```
[TIMESTAMP] [LEVEL] [DEVICE_ID] [SEQ] [EVENT] key=value ...
```

### Logged Events

| Event | Fields Logged |
|---|---|
| `SERVICE_START` | host, port, timestamp |
| `PACKET_RECEIVED` | seq, device_id, receive_time_ms, payload_bytes |
| `PACKET_PROCESSED` | seq, device_id, proc_time_ms, throughput_kbps |
| `PACKET_INVALID` | seq, device_id, reason |
| `STREAM_START` | device_id, stream_id |
| `STREAM_END` | device_id, stream_id, total_packets, total_bytes, duration_ms, avg_throughput_kbps |
| `SERVICE_STOP` | total_packets_served, uptime_s |

### Log File Naming
```
logs/service_<YYYYMMDD_HHMMSS>.log
```

### Sample Log Output
```
[2024-01-15 10:23:01.450] [INFO]  [SERVICE]        [--]  SERVICE_START    host=0.0.0.0 port=50051
[2024-01-15 10:23:01.455] [INFO]  [agent-py-001]   [1]   PACKET_RECEIVED  receive_time=1705315381455 payload_bytes=312
[2024-01-15 10:23:01.456] [INFO]  [agent-py-001]   [1]   PACKET_PROCESSED proc_time_ms=0.91 throughput_kbps=273.4
[2024-01-15 10:23:01.460] [INFO]  [agent-c-001]    [1]   PACKET_RECEIVED  receive_time=1705315381460 payload_bytes=308
[2024-01-15 10:23:01.461] [INFO]  [agent-c-001]    [1]   PACKET_PROCESSED proc_time_ms=0.84 throughput_kbps=291.7
```

---

## Throughput Calculation

```
payload_bytes    = len(serialized TelemetryPacket in bytes)
proc_time_ms     = time from receive to ack dispatch
throughput_kbps  = (payload_bytes * 1000) / proc_time_ms / 1024
```

For streaming sessions:
```
total_bytes      = sum of all packet payload sizes
stream_duration  = last_packet_time - first_packet_time  (seconds)
throughput_kbps  = total_bytes / stream_duration / 1024
```

---

## Packet Validation Rules

| Field | Validation Rule |
|---|---|
| `device_id` | Non-empty string, max 64 chars |
| `sequence_number` | > 0 |
| `timestamp_ms` | > 0, not more than 60s in the future |
| `temperature` | -100.0 to +200.0 °C |
| `latitude` | -90.0 to +90.0 |
| `longitude` | -180.0 to +180.0 |
| `altitude` | -500.0 to +50000.0 meters |
| IMU fields | All 9 axes must be present (non-NaN) |

Invalid packets receive `AckResponse(success=false, message="<reason>")` and are logged as `PACKET_INVALID`.

---

## Service Implementation

### File: `service/telemetry_service.py`

### Dependencies
```
grpcio>=1.60.0
grpcio-tools>=1.60.0
protobuf>=4.25.0
```

### Key Classes

#### `TelemetryServicer`
```python
class TelemetryServicer(telemetry_pb2_grpc.TelemetryServiceServicer):
    def __init__(self, log_dir: str)
    def SendTelemetry(self, request: TelemetryPacket,
                      context) -> AckResponse
    def StreamTelemetry(self, request_iterator,
                        context) -> AckResponse
```

#### `PacketValidator`
```python
class PacketValidator:
    @staticmethod
    def validate(packet: TelemetryPacket) -> tuple[bool, str]
```

#### `TransactionLogger`
```python
class TransactionLogger:
    def __init__(self, log_dir: str)
    def log_received(self, packet, payload_bytes: int) -> float
    def log_processed(self, packet, receive_time: float,
                      payload_bytes: int) -> None
    def log_invalid(self, packet, reason: str) -> None
    def log_stream_summary(self, device_id: str, stream_id: str,
                           total_packets: int, total_bytes: int,
                           duration_ms: float) -> None
    def write_service_summary(self) -> None
```

### Server Startup
```python
def serve(host="0.0.0.0", port=50051, log_dir="./logs",
          max_workers=10):
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=max_workers)
    )
    telemetry_pb2_grpc.add_TelemetryServiceServicer_to_server(
        TelemetryServicer(log_dir=log_dir), server
    )
    server.add_insecure_port(f"{host}:{port}")
    server.start()
    server.wait_for_termination()
```

---

## Configuration

| Parameter | Default | Description |
|---|---|---|
| `--host` | `0.0.0.0` | Bind address |
| `--port` | `50051` | gRPC listen port |
| `--log-dir` | `./logs` | Log output directory |
| `--max-workers` | `10` | Thread pool size for concurrent connections |

---

## Concurrency Model

The service uses Python's `ThreadPoolExecutor` via the gRPC server framework. Each incoming RPC call is handled in a separate thread. The `TransactionLogger` uses a thread-safe queue and a dedicated writer thread to avoid I/O contention in logs.

```
Thread Pool (max_workers=10)
  ├── Thread 1 → handles agent-py-001 SendTelemetry
  ├── Thread 2 → handles agent-c-001 SendTelemetry
  └── ...

Logger Thread (dedicated)
  └── Drains log queue → writes to log file
```

---

## Session Summary Output

At shutdown (SIGINT/SIGTERM), the service prints and logs:

```
========== SERVICE SESSION SUMMARY ==========
Uptime              : 120.3 seconds
Total Packets       : 1,842
Total Bytes Received: 574,704 bytes
Unique Devices      : 3
Avg Processing Time : 0.87 ms
Min Processing Time : 0.41 ms
Max Processing Time : 3.12 ms
Avg Throughput      : 287.6 KB/s
Invalid Packets     : 2
==============================================
```

---

## Security Considerations (Future)

| Feature | Status | Notes |
|---|---|---|
| TLS/mTLS | Planned | Use `grpc.ssl_server_credentials()` |
| Token Auth | Planned | gRPC metadata interceptor |
| Rate Limiting | Planned | Per-device packet rate cap |
| Input Sanitization | Implemented | Via `PacketValidator` |