DM# gRPC Telemetry System

## Overview

This project demonstrates a gRPC-based telemetry data pipeline where agents (written in C or Python) stream sensor data — **temperature**, **GPS location**, and **9-axis IMU data** — to a Python-based gRPC service. The system includes full transaction logging with timing and throughput measurements on both the agent and service sides.

---

## Architecture

```
┌─────────────────────┐         gRPC / HTTP/2         ┌──────────────────────┐
│   Telemetry Agent   │  ─────────────────────────►   │  Telemetry Service   │
│  (C or Python)      │   TelemetryPacket (protobuf)   │  (Python gRPC Server)│
│                     │  ◄─────────────────────────    │                      │
│  - Sends packets    │       AckResponse              │  - Receives packets  │
│  - Logs tx timing   │                                │  - Logs rx timing    │
│  - Calc throughput  │                                │  - Calc throughput   │
└─────────────────────┘                                └──────────────────────┘
```

### Components

| Component | Language | Description |
|---|---|---|
| `telemetry.proto` | Protobuf | Shared service/message definitions |
| `agent_c/` | C | C-based telemetry agent |
| `agent_python/` | Python | Python-based telemetry agent |
| `service/` | Python | gRPC telemetry service (server) |

---

## Data Schema

Each telemetry packet contains:

- **Temperature** — float (°C)
- **GPS** — latitude, longitude, altitude (doubles)
- **IMU (9-axis)**
  - Accelerometer: X, Y, Z (m/s²)
  - Gyroscope: X, Y, Z (rad/s)
  - Magnetometer: X, Y, Z (µT)
- **Timestamp** — Unix epoch (milliseconds)
- **Device ID** — string identifier

---

## Project Structure

```
grpc-telemetry/
├── README.md
├── proto/
│   └── telemetry.proto
├── service/
│   ├── telemetry_service.py
│   ├── requirements.txt
│   └── logs/
├── agent_python/
│   ├── telemetry_agent.py
│   ├── requirements.txt
│   └── logs/
└── agent_c/
    ├── telemetry_agent.c
    ├── CMakeLists.txt
    └── logs/
```

---

## Prerequisites

### All Platforms
- Protocol Buffers compiler: `protoc` v3.x+
- Python 3.9+

### Python (Service + Python Agent)
```bash
pip install grpcio grpcio-tools protobuf
```

### C Agent
- `grpc` C core library
- `protobuf-c` library
- `cmake` 3.15+
- `pkg-config`

On Ubuntu/Debian:
```bash
sudo apt install libgrpc-dev libprotobuf-c-dev cmake pkg-config
```

On macOS (Homebrew):
```bash
brew install grpc protobuf-c cmake pkg-config
```

---

## Setup

### 1. Generate Protobuf Code

**Python (service + agent):**
```bash
cd proto/
python -m grpc_tools.protoc \
  -I. \
  --python_out=../service/ \
  --grpc_python_out=../service/ \
  telemetry.proto

python -m grpc_tools.protoc \
  -I. \
  --python_out=../agent_python/ \
  --grpc_python_out=../agent_python/ \
  telemetry.proto
```

**C Agent:**
```bash
cd proto/
protoc-c --c_out=../agent_c/ telemetry.proto
```

### 2. Build the C Agent
```bash
cd agent_c/
mkdir build && cd build
cmake ..
make
```

---

## Running the System

### Step 1 — Start the Service
```bash
cd service/
python telemetry_service.py
```
The service listens on `0.0.0.0:50051` by default.

### Step 2 — Run the Python Agent
```bash
cd agent_python/
python telemetry_agent.py --host localhost --port 50051 --device-id agent-py-001 --packets 100
```

### Step 3 — Run the C Agent
```bash
cd agent_c/build/
./telemetry_agent --host localhost --port 50051 --device-id agent-c-001 --packets 100
```

---

## Logging & Throughput

Both the agent and service write structured logs to their respective `logs/` directories.

### Agent Log Sample
```
[2024-01-15 10:23:01.452] [INFO] Sending packet seq=1 device=agent-py-001
[2024-01-15 10:23:01.461] [INFO] ACK received seq=1 | RTT=8.74ms | bytes=312 | throughput=284.7 KB/s
```

### Service Log Sample
```
[2024-01-15 10:23:01.455] [INFO] Received packet seq=1 device=agent-py-001
[2024-01-15 10:23:01.456] [INFO] Processed seq=1 | proc_time=0.91ms | payload=312 bytes
```

### Metrics Captured

| Metric | Agent | Service |
|---|---|---|
| Packet send timestamp | ✓ | — |
| Round-trip time (RTT) | ✓ | — |
| Receive timestamp | — | ✓ |
| Processing time | — | ✓ |
| Payload size (bytes) | ✓ | ✓ |
| Throughput (KB/s) | ✓ | ✓ |
| Sequence number | ✓ | ✓ |

---

## Configuration

| Parameter | Default | Description |
|---|---|---|
| `--host` | `localhost` | Service hostname or IP |
| `--port` | `50051` | Service gRPC port |
| `--device-id` | `agent-001` | Unique agent identifier |
| `--packets` | `100` | Number of packets to send |
| `--interval` | `0.1` | Seconds between packets |
| `--log-dir` | `./logs` | Log output directory |

---

## Proto Definition Summary

```protobuf
service TelemetryService {
  rpc SendTelemetry (TelemetryPacket) returns (AckResponse);
  rpc StreamTelemetry (stream TelemetryPacket) returns (AckResponse);
}
```

---

## License

MIT License. See `LICENSE` for details.