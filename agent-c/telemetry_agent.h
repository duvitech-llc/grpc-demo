/*
 * telemetry_agent.h - C Telemetry Agent Header
 *
 * Telemetry Agent for embedded/resource-constrained environments.
 * Packages sensor data into gRPC TelemetryPacket messages and sends them
 * to the Telemetry Service using either unary RPC or client streaming RPC.
 */

#ifndef TELEMETRY_AGENT_H
#define TELEMETRY_AGENT_H

#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <grpc/grpc.h>
#include <grpc/impl/codegen/grpc_types.h>

/* Maximum packet size */
#define MAX_PACKET_SIZE 4096

/* Default retry settings */
#define DEFAULT_RETRY_COUNT 5
#define DEFAULT_BACKOFF_MS 100
#define DEFAULT_TIMEOUT_SEC 5

/* Log level options */
typedef enum {
    LOG_DEBUG = 0,
    LOG_INFO,
    LOG_WARNING,
    LOG_ERROR
} LogLevel;

/* Log entry structure */
typedef struct {
    char timestamp[32];
    LogLevel level;
    int sequence;
    const char *event_type;
    char message[256];
} LogEntry;

/* Transaction record for successful transmissions */
typedef struct {
    uint64_t seq;
    uint64_t send_time_ms;
    uint64_t ack_time_ms;
    double rtt_ms;
    double throughput_kbps;
    bool success;
} TransactionRecord;

/* Agent state */
typedef struct {
    grpc_channel *channel;
    grpc_status_code channel_status;
    
    char device_id[64];
    
    uint64_t sequence_number;
    
    FILE *log_file;
    
    TransactionRecord *records;
    int record_count;
    int total_bytes;
    int total_errors;
    
    double avg_rtt_ms;
    double min_rtt_ms;
    double max_rtt_ms;
    double avg_throughput_kbps;
    double duration_s;
    
    LogLevel log_level;
    
    int retry_count;
    int backoff_ms;
    int timeout_sec;
    
    int mode;  /* 0 = unary, 1 = stream */
    
    /* Callback for custom logging */
    void (*log_callback)(const LogEntry *entry);
} TelemetryAgent;

/* Function declarations */

/* Initialize the telemetry agent */
int agent_init(TelemetryAgent *agent, const char *host,
               int port, const char *device_id, const char *log_dir);

/* Connect to the gRPC service */
int agent_connect(TelemetryAgent *agent);

/* Disconnect and cleanup */
void agent_close(TelemetryAgent *agent);

/* Build a telemetry packet from sensor data */
int agent_build_packet(TelemetryAgent *agent, uint64_t seq,
                       float temperature, double latitude, double longitude,
                       double altitude,
                       float accel_x, float accel_y, float accel_z,
                       float gyro_x, float gyro_y, float gyro_z,
                       float mag_x, float mag_y, float mag_z,
                       uint64_t timestamp_ms,
                       Telemetry__TelemetryPacket **packet_out);

/* Send a single packet via unary RPC */
int agent_send_packet(TelemetryAgent *agent, Telemetry__TelemetryPacket *packet);

/* Send multiple packets via client streaming RPC */
int agent_send_stream(TelemetryAgent *agent, Telemetry__TelemetryPacket **packets, int count);

/* Log transaction metrics */
void agent_log_transaction(TelemetryAgent *agent, uint64_t seq,
                           double rtt_ms, size_t payload_bytes);

/* Get session summary */
void agent_get_summary(TelemetryAgent *agent, char *buffer, size_t buffer_size);

/* Set log level */
void agent_set_log_level(TelemetryAgent *agent, LogLevel level);

/* Set retry configuration */
void agent_set_retry_count(TelemetryAgent *agent, int count);
void agent_set_backoff_ms(TelemetryAgent *agent, int ms);
void agent_set_timeout_sec(TelemetryAgent *agent, int sec);

/* Set transmission mode */
void agent_set_mode(TelemetryAgent *agent, int mode);

/* Get current sequence number */
uint64_t agent_get_sequence(TelemetryAgent *agent);

/* Increment sequence number */
void agent_increment_sequence(TelemetryAgent *agent);

/* Reset agent state */
void agent_reset(TelemetryAgent *agent);

#endif /* TELEMETRY_AGENT_H */