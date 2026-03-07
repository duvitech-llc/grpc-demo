sudo # Telemetry Agent — Specification Document

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

### File: `agent-c/telemetry_agent.c`

### Dependencies
- `libgrpc` — gRPC C core  
- `libprotobuf-c` — Protocol Buffers for C  
- `pthreads` — for async logging (optional)  

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
    const char *device_id;           /* Unique device identifier */
    char service_host[64];           /* gRPC service host */
    int service_port;                /* gRPC service port */
    uint64_t sequence_number;        /* Current packet sequence */
    bool connected;                  /* Connection state */
    uint64_t packets_sent;           /* Total packets sent */
    uint64_t packets_received;       /* Total ACKs received */
    uint64_t bytes_sent;             /* Total bytes transmitted */
    uint64_t bytes_received;         /* Total bytes received */
    int errors;                      /* Total errors */
    double duration_s;               /* Session duration */
} TelemetryAgent;

int  agent_init(TelemetryAgent *agent, const char *host,
                int port, const char *device_id, const char *log_dir);
int  agent_connect(TelemetryAgent *agent);
TelemetryPacket agent_create_packet(float temperature, double latitude, double longitude,
                                     double altitude, float accel_x, float accel_y, float accel_z,
                                     float gyro_x, float gyro_y, float gyro_z,
                                     float mag_x, float mag_y, float mag_z,
                                     uint64_t ts_ms);
int  agent_send_packet(TelemetryAgent *agent, const TelemetryPacket *packet, size_t packet_size);
int  agent_send_batch(TelemetryAgent *agent, const TelemetryPacket *packets,
                      size_t *packet_sizes, int count);
void agent_close(TelemetryAgent *agent);
```

### Data Structures

The C agent uses the following structures to represent telemetry data:

```c
typedef struct {
    uint64_t sequence_number;
    uint64_t timestamp_millis;
    double temperature;
    double latitude;
    double longitude;
    double altitude;
    float accel_x;
    float accel_y;
    float accel_z;
    float gyro_x;
    float gyro_y;
    float gyro_z;
    float mag_x;
    float mag_y;
    float mag_z;
    float gps_quality;
    uint32_t gps_h_accuracy;
    uint8_t gps_satellites;
    int32_t humidity;
    int32_t pressure;
    int16_t latitude_raw;
    int16_t longitude_raw;
} TelemetryPacket;

typedef struct {
    uint64_t sequence_number;
    bool status;
    int64_t ack_timestamp_millis;
} AckResponse;
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

### Usage Example

```c
#include "telemetry_agent.h"

int main(int argc, char **argv) {
    TelemetryAgent agent = {0};
    
    /* Initialize agent */
    if (agent_init(&agent, "localhost", 50051, "agent-c-001", "./logs") != 0) {
        return 1;
    }
    
    /* Connect to service */
    if (agent_connect(&agent) != 0) {
        agent_close(&agent);
        return 1;
    }
    
    /* Create and send packets */
    TelemetryPacket packet;
    packet.temperature = 23.5;
    packet.latitude = 37.7749;
    packet.longitude = -122.4194;
    packet.altitude = 15.0;
    packet.accel_x = 0.01;
    packet.accel_y = -0.02;
    packet.accel_z = 9.81;
    packet.gyro_x = 0.001;
    packet.gyro_y = 0.002;
    packet.gyro_z = -0.001;
    packet.mag_x = 25.3;
    packet.mag_y = -10.1;
    packet.mag_z = 42.7;
    
    uint64_t now = get_timestamp_ms();
    uint8_t *packet_data;
    size_t packet_size;
    
    int ret = create_packet(&agent, 1, packet.temperature, packet.latitude, 
                            packet.longitude, packet.altitude,
                            packet.accel_x, packet.accel_y, packet.accel_z,
                            packet.gyro_x, packet.gyro_y, packet.gyro_z,
                            packet.mag_x, packet.mag_y, packet.mag_z,
                            now, &packet_data, &packet_size);
    
    if (ret == 0) {
        int send_ret = agent_send_packet(&agent, &packet, packet_size);
        if (send_ret != 0) {
            fprintf(stderr, "Error sending packet\n");
        }
    }
    
    /* Cleanup */
    agent_close(&agent);
    
    return 0;
}
```

---

## Error Handling & Retry Policy
### Retry Configuration

The C agent includes built-in retry configuration for connection failures:

- **Retry Count**: 3 attempts
- **Backoff Interval**: 100ms
- **Timeout**: 5 seconds per RPC call

The agent tracks the following error conditions:

| Condition | Action |
|---|---|
| Connection refused | Retry up to 3 times with exponential backoff (100ms base) |
| Timeout (>5s) | Log error, skip packet, increment error counter |
| Service unavailable | Retry with backoff, log warning |
| Protobuf serialization error | Log error, abort packet, continue |


| Condition | Action |
|---|---|
| Connection refused | Retry up to 5 times with exponential backoff (100ms base) |
```
```
```
=====================================
```