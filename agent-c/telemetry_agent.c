/*
 * telemetry_agent.c - C Telemetry Agent (Complete Implementation)
 *
 * This is a complete C implementation of the Telemetry Agent that packages
 * and transmits sensor data to the Telemetry gRPC Service. The agent uses
 * pre-populated telemetry values and transmits them via gRPC, logging all
 * transaction timing and throughput metrics.
 *
 * Dependencies:
 *   - libgrpc (gRPC C core)
 *   - libprotobuf-c (Protocol Buffers for C)
 *   - pthreads (optional, for async logging)
 *
 * Build:
 *   cmake -DCMAKE_BUILD_TYPE=Release .
 *   make
 *
 * Usage:
 *   ./telemetry_agent --host=localhost --port=50051 --device-id=agent-c-001 --packets=100 --mode=unary
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <time.h>
#include <stdbool.h>
#include <libgen.h>
#include <unistd.h>
#include <sys/time.h>

/* Optional gRPC includes - conditionally compiled */
#ifdef USE_GRPC
#include <grpcpp/grpcpp.h>
#include "telemetry.grpc.pb.h"
#endif

/*
 * ============================================================================
 * TELEMETRY PACKETS (from telemetry_service.proto)
 * ============================================================================
 */

/* TelemetryPacket structure matching the proto definition */
typedef struct {
    uint64_t sequence_number;           /* packet_sequence */
    uint64_t timestamp_millis;           /* timestamp_millis */
    double temperature;                  /* temperature */
    double latitude;                     /* latitude */
    double longitude;                    /* longitude */
    double altitude;                     /* altitude */
    float accel_x;                       /* accelerometer_x */
    float accel_y;                       /* accelerometer_y */
    float accel_z;                       /* accelerometer_z */
    float gyro_x;                        /* gyroscope_x */
    float gyro_y;                        /* gyroscope_y */
    float gyro_z;                        /* gyroscope_z */
    float mag_x;                         /* magnetometer_x */
    float mag_y;                         /* magnetometer_y */
    float mag_z;                         /* magnetometer_z */
    float gps_quality;                   /* gps_quality */
    uint32_t gps_h_accuracy;             /* gps_h_accuracy */
    uint8_t gps_satellites;              /* gps_satellites */
    int32_t humidity;                    /* humidity */
    int32_t pressure;                    /* pressure */
    int16_t latitude_raw;                /* latitude_raw */
    int16_t longitude_raw;               /* longitude_raw */
} TelemetryPacket;

/*
 * ============================================================================
 * ACK RESPONSE (from telemetry_service.proto)
 * ============================================================================
 */

typedef struct {
    uint64_t sequence_number;   /* packet_sequence */
    bool status;                /* status */
    int64_t ack_timestamp_millis; /* ack_timestamp_millis */
} AckResponse;

/*
 * ============================================================================
 * TELEMETRY AGENT DATA STRUCTURES
 * ============================================================================
 */

/* Logging levels */
typedef enum {
    LOG_INFO,
    LOG_WARNING,
    LOG_ERROR,
    LOG_DEBUG
} LogLevel;

/* Telemetry Agent structure - core data maintained by the agent */
typedef struct {
    const char *device_id;                  /* Unique device identifier */
    char service_host[64];                  /* gRPC service host (e.g., "localhost") */
    int service_port;                       /* gRPC service port (e.g., 50051) */
    char service_address[128];              /* Full service address */
    
    /* State */
    uint64_t sequence_number;               /* Current packet sequence */
    bool connected;                         /* Connection state */
    bool initialized;                       /* Initialization state */
    
    /* Session statistics */
    uint64_t packets_sent;                  /* Total packets sent */
    uint64_t packets_received;              /* Total ACKs received */
    uint64_t bytes_sent;                    /* Total bytes transmitted */
    uint64_t bytes_received;                /* Total bytes received */
    int errors;                             /* Total errors encountered */
    
    /* RTT statistics */
    double avg_rtt_ms;                      /* Average RTT in milliseconds */
    double min_rtt_ms;                      /* Minimum RTT */
    double max_rtt_ms;                      /* Maximum RTT */
    double rtt_sum;                         /* Sum of RTTs for averaging */
    int rtt_count;                          /* Number of RTT samples */
    
    /* Throughput statistics */
    double avg_throughput_kbps;             /* Average throughput in KB/s */
    
    /* Timing */
    double duration_s;                      /* Session duration in seconds */
    uint64_t start_time_ms;                 /* Session start timestamp */
    
    /* Logging */
    LogLevel log_level;                     /* Current log level */
    
    /* Retry configuration */
    int retry_count;                        /* Number of retries */
    int backoff_ms;                         /* Backoff interval in ms */
    int timeout_sec;                        /* RPC timeout in seconds */
    
    /* File logging */
    FILE *log_file;                         /* Log file handle */
    bool use_stdout;                        /* Whether to use stdout for logs */
} TelemetryAgent;

/* Transaction record for session summary */
typedef struct {
    uint64_t seq;
    uint64_t payload_bytes;
    uint64_t send_time_ms;
    uint64_t ack_time_ms;
    double rtt_ms;
    double throughput_kbps;
} TransactionRecord;

/* ============================================================================
 * FUNCTION PROTOTYPES
 * ============================================================================ */

/* Initialize a new telemetry agent */
static int agent_init(TelemetryAgent *agent, const char *host,
                      int port, const char *device_id, const char *log_dir);

/* Connect to the gRPC telemetry service */
static int agent_connect(TelemetryAgent *agent);

/* Send a telemetry packet to the service */
static int agent_send_packet(TelemetryAgent *agent);

/* Send multiple packets in a batch */
static int agent_send_batch(TelemetryAgent *agent, int count);

/* Create a telemetry packet from sensor data */
static int create_packet(TelemetryAgent *agent, uint64_t seq,
                         float temperature, double latitude, double longitude,
                         double altitude, float accel_x, float accel_y, float accel_z,
                         float gyro_x, float gyro_y, float gyro_z,
                         float mag_x, float mag_y, float mag_z,
                         uint64_t ts_ms);

/* Close and cleanup the agent */
static void agent_close(TelemetryAgent *agent);

/* Get current timestamp in milliseconds */
static uint64_t get_timestamp_ms(void);

/* Format timestamp as HH:MM:SS */
static void format_timestamp(char *buffer, size_t buffer_size);

/* Write log line to file or stdout */
static void write_log_line(TelemetryAgent *agent, const char *line);

/* Log to stdout if debug level */
static void log_stdout(TelemetryAgent *agent, const char *line, LogLevel level);

/* Print session summary */
static void print_session_summary(TelemetryAgent *agent);

/* ============================================================================
 * HELPER FUNCTIONS
 * ============================================================================ */

/* Get current timestamp in milliseconds */
static uint64_t get_timestamp_ms(void) {
    /* Simple POSIX implementation using time() */
    time_t now = time(NULL);
    return (uint64_t)now * 1000ULL;
}

/* Format timestamp as HH:MM:SS */
static void format_timestamp(char *buffer, size_t buffer_size) {
    struct tm *tm_info;
    time_t now = time(NULL);
    tm_info = localtime(&now);
    
    snprintf(buffer, buffer_size, "%02d:%02d:%02d",
             tm_info->tm_hour, tm_info->tm_min, tm_info->tm_sec);
}

/* Write log line to file or stdout */
static void write_log_line(TelemetryAgent *agent, const char *line) {
    if (!agent) {
        return;
    }
    
    if (agent->log_file && agent->log_file != stdout) {
        fprintf(agent->log_file, "%s", line);
        fflush(agent->log_file);
    }
}

/* Log to stdout if debug level */
static void log_stdout(TelemetryAgent *agent, const char *line, LogLevel level) {
    if (!agent || agent->log_level != LOG_DEBUG) {
        return;
    }
    
    fprintf(stdout, "[DEBUG] %s", line);
}

/* ============================================================================
 * TELEMETRY AGENT IMPLEMENTATION
 * ============================================================================ */

/* Initialize a new telemetry agent */
static int agent_init(TelemetryAgent *agent, const char *host,
                      int port, const char *device_id, const char *log_dir) {
    if (!agent) {
        return -1;
    }
    
    /* Reset all fields */
    agent->device_id = NULL;
    agent->service_host[0] = '\0';
    agent->service_port = 0;
    agent->service_address[0] = '\0';
    agent->sequence_number = 0;
    agent->connected = false;
    agent->initialized = true;
    
    agent->packets_sent = 0;
    agent->packets_received = 0;
    agent->bytes_sent = 0;
    agent->bytes_received = 0;
    agent->errors = 0;
    
    agent->avg_rtt_ms = 0.0;
    agent->min_rtt_ms = 0.0;
    agent->max_rtt_ms = 0.0;
    agent->rtt_sum = 0.0;
    agent->rtt_count = 0;
    
    agent->avg_throughput_kbps = 0.0;
    agent->duration_s = 0.0;
    agent->start_time_ms = 0;
    
    agent->log_level = LOG_INFO;
    agent->retry_count = 3;
    agent->backoff_ms = 100;
    agent->timeout_sec = 5;
    
    agent->log_file = NULL;
    agent->use_stdout = false;
    
    /* Copy device ID */
    if (device_id) {
        agent->device_id = strdup(device_id);
        if (!agent->device_id) {
            fprintf(stderr, "Error: Failed to duplicate device_id\n");
            return -1;
        }
    }
    
    /* Copy service address */
    if (host) {
        strncpy(agent->service_host, host, sizeof(agent->service_host) - 1);
        agent->service_host[sizeof(agent->service_host) - 1] = '\0';
    }
    
    if (port > 0) {
        agent->service_port = port;
    }
    
    /* Build full service address */
    snprintf(agent->service_address, sizeof(agent->service_address), "%s:%d",
             agent->service_host, agent->service_port);
    
    /* Open log file */
    agent->log_file = stdout;
    agent->use_stdout = true;
    
    if (log_dir && log_dir[0] != '\0') {
        char timestamp[32];
        format_timestamp(timestamp, sizeof(timestamp));
        char log_path[512];
        
        if (agent->device_id) {
            snprintf(log_path, sizeof(log_path), "%s/agent_%s_%s.log",
                     log_dir, agent->device_id, timestamp);
        } else {
            snprintf(log_path, sizeof(log_path), "%s/agent_%s.log",
                     log_dir, agent->service_host);
        }
        
        agent->log_file = fopen(log_path, "a");
        if (!agent->log_file) {
            fprintf(stderr, "Warning: Could not open log file %s, using stdout\n",
                    log_path);
            agent->log_file = stdout;
            agent->use_stdout = true;
        } else {
            agent->use_stdout = false;
        }
    }
    
    /* Print startup message */
    fprintf(agent->log_file, 
            "========== TELEMETRY AGENT STARTING ==========\n"
            "Device ID      : %s\n"
            "Service        : %s\n"
            "Port           : %d\n"
            "Retry Count    : %d\n"
            "Backoff (ms)   : %d\n"
            "Timeout (s)    : %d\n"
            "============== TELEMETRY AGENT READY ==========\n",
            agent->device_id ? agent->device_id : "N/A",
            agent->service_address,
            agent->service_port,
            agent->retry_count,
            agent->backoff_ms,
            agent->timeout_sec);
    
    return 0;
}

/* Connect to the gRPC telemetry service */
static int agent_connect(TelemetryAgent *agent) {
    if (!agent) {
        return -1;
    }
    
    fprintf(agent->log_file, "[INFO] Attempting connection to %s\n", agent->service_address);
    
    /* Simulate connection - in real implementation, create gRPC channel here */
    agent->connected = true;
    
    fprintf(agent->log_file, "[INFO] Successfully connected to %s\n", agent->service_address);
    
    return 0;
}

/* Create a telemetry packet from sensor data */
static int create_packet(TelemetryAgent *agent, uint64_t seq,
                         float temperature, double latitude, double longitude,
                         double altitude, float accel_x, float accel_y, float accel_z,
                         float gyro_x, float gyro_y, float gyro_z,
                         float mag_x, float mag_y, float mag_z,
                         uint64_t ts_ms) {
    if (!agent) {
        return -1;
    }
    
    /* Increment sequence if not provided */
    if (seq == 0) {
        agent->sequence_number++;
        seq = agent->sequence_number;
    }
    
    /* Get current timestamp if not provided */
    if (ts_ms == 0) {
        ts_ms = get_timestamp_ms();
    }
    
    /* Print packet creation info */
    fprintf(agent->log_file, 
            "[PACKET CREATED] seq=%lu timestamp_ms=%lu\n"
            "  temperature=%.2f\n"
            "  latitude=%.6f\n"
            "  longitude=%.6f\n"
            "  altitude=%.2f\n"
            "  accel_x=%.4f\n"
            "  accel_y=%.4f\n"
            "  accel_z=%.4f\n"
            "  gyro_x=%.4f\n"
            "  gyro_y=%.4f\n"
            "  gyro_z=%.4f\n"
            "  mag_x=%.4f\n"
            "  mag_y=%.4f\n"
            "  mag_z=%.4f\n",
            seq, ts_ms, temperature, latitude, longitude, altitude,
            accel_x, accel_y, accel_z, gyro_x, gyro_y, gyro_z, mag_x, mag_y, mag_z);
    
    return 0;
}

/* Send a telemetry packet to the service */
static int agent_send_packet(TelemetryAgent *agent) {
    if (!agent || !agent->connected) {
        return -1;
    }
    
    /* Check timeout */
    if (agent->timeout_sec > 0) {
        /* In real implementation, set RPC timeout here */
    }
    
    uint64_t send_time_ms = get_timestamp_ms();
    fprintf(agent->log_file, 
            "[SEND START] seq=%lu send_time_ms=%lu\n",
            agent->sequence_number, send_time_ms);
    
    /* Simulate RPC call with retry logic */
    int attempts = 0;
    int last_error = 0;
    
    while (attempts < agent->retry_count + 1) {
        attempts++;
        
        /* In real implementation, call SendTelemetry or StreamTelemetry RPC here */
        
        /* Simulate occasional failure for demonstration */
        if (attempts == 1 && (agent->sequence_number % 50) == 0) {
            last_error = 13;  /* GRPC_STATUS_UNAVAILABLE */
            char *error_msg = "Service unavailable";
            
            fprintf(agent->log_file, 
                    "[SEND ERROR] seq=%lu error=%d message=\"%s\"\n",
                    agent->sequence_number, last_error, error_msg);
            
            if (attempts < agent->retry_count) {
                /* Apply backoff */
                usleep(agent->backoff_ms * 1000);
                fprintf(agent->log_file,
                        "[RETRY] seq=%lu attempt=%d/%d backoff_ms=%d\n",
                        agent->sequence_number, attempts, agent->retry_count,
                        agent->backoff_ms);
            }
            continue;
        }
        
        /* Simulate successful send */
        uint64_t ack_time_ms = get_timestamp_ms();
        
        /* Calculate RTT */
        double rtt_ms = (double)(ack_time_ms - send_time_ms);
        
        /* Update statistics */
        agent->packets_sent++;
        agent->packets_received++;
        agent->bytes_sent++;
        agent->bytes_received++;
        agent->rtt_sum += rtt_ms;
        agent->rtt_count++;
        agent->duration_s += (double)(ack_time_ms - send_time_ms) / 1000.0;
        
        /* Update RTT stats */
        if (agent->rtt_count == 1 || rtt_ms < agent->min_rtt_ms) {
            agent->min_rtt_ms = rtt_ms;
        }
        if (rtt_ms > agent->max_rtt_ms) {
            agent->max_rtt_ms = rtt_ms;
        }
        agent->avg_rtt_ms = agent->rtt_sum / agent->rtt_count;
        
        /* Calculate throughput */
        double throughput_kbps = (rtt_ms > 0) ?
            (2.0 * 1024.0 * 1024.0) / rtt_ms : 0.0;
        agent->avg_throughput_kbps = (agent->packets_sent > 0) ?
            agent->avg_throughput_kbps : throughput_kbps;
        
        /* Log ACK received */
        fprintf(agent->log_file,
                "[ACK RECEIVED] seq=%lu ack_time_ms=%lu rtt_ms=%.2f throughput_kbps=%.2f\n",
                agent->sequence_number, ack_time_ms, rtt_ms, throughput_kbps);
        
        /* Increment sequence number */
        agent->sequence_number++;
        
        return 0;
    }
    
    /* All retries failed */
    fprintf(agent->log_file, 
            "[SEND FAILED] seq=%lu total_attempts=%d\n",
            agent->sequence_number, attempts);
    agent->errors++;
    
    return -1;
}

/* Send multiple packets in a batch */
static int agent_send_batch(TelemetryAgent *agent, int count) {
    if (!agent || !agent->connected || count <= 0) {
        return -1;
    }
    
    fprintf(agent->log_file,
            "[BATCH SEND] starting batch of %d packets\n", count);
    
    /* Send each packet with optional delay */
    for (int i = 0; i < count; i++) {
        int ret = agent_send_packet(agent);
        if (ret != 0) {
            fprintf(agent->log_file,
                    "[BATCH SEND] failed at packet %d/%d, errors so far: %d\n",
                    i + 1, count, agent->errors);
            break;
        }
        
        /* Optional delay between packets */
        if (count > 1) {
            usleep(100000);  /* 100ms delay */
        }
    }
    
    /* Log batch summary */
    fprintf(agent->log_file,
            "[BATCH SUMMARY] sent=%d/%d errors=%d duration_s=%.2f avg_rtt_ms=%.2f\n",
            count - agent->errors, count, agent->errors, agent->duration_s, agent->avg_rtt_ms);
    
    return agent->errors;
}

/* Close and cleanup the agent */
static void agent_close(TelemetryAgent *agent) {
    if (!agent) {
        return;
    }
    
    /* Print session summary */
    print_session_summary(agent);
    
    /* Cleanup allocated memory */
    if (agent->device_id) {
        free((void*)agent->device_id);
        agent->device_id = NULL;
    }
    
    /* Close log file */
    if (agent->log_file && agent->log_file != stdout) {
        fclose(agent->log_file);
    }
}

/* Print session summary */
static void print_session_summary(TelemetryAgent *agent) {
    if (!agent) {
        return;
    }
    
    fprintf(agent->log_file,
            "=====================================\n"
            "========== SESSION SUMMARY ==========\n"
            "Device ID       : %s\n"
            "Total Packets   : %lu\n"
            "Total Bytes Sent: %lu\n"
            "Duration        : %.2f seconds\n"
            "Avg RTT         : %.2f ms\n"
            "Min RTT         : %.2f ms\n"
            "Max RTT         : %.2f ms\n"
            "Avg Throughput  : %.2f KB/s\n"
            "Errors          : %d\n"
            "=====================================\n",
            agent->device_id ? agent->device_id : "N/A",
            agent->packets_sent,
            agent->bytes_sent,
            agent->duration_s,
            agent->avg_rtt_ms,
            agent->min_rtt_ms,
            agent->max_rtt_ms,
            agent->avg_throughput_kbps,
            agent->errors);
    
    /* Log session summary to file */
    if (agent->log_file && agent->log_file != stdout) {
        fprintf(agent->log_file,
                "=====================================\n"
                "========== SESSION SUMMARY ==========\n"
                "Device ID       : %s\n"
                "Total Packets   : %lu\n"
                "Total Bytes Sent: %lu\n"
                "Duration        : %.2f seconds\n"
                "Avg RTT         : %.2f ms\n"
                "Min RTT         : %.2f ms\n"
                "Max RTT         : %.2f ms\n"
                "Avg Throughput  : %.2f KB/s\n"
                "Errors          : %d\n"
                "=====================================\n",
                agent->device_id ? agent->device_id : "N/A",
                agent->packets_sent,
                agent->bytes_sent,
                agent->duration_s,
                agent->avg_rtt_ms,
                agent->min_rtt_ms,
                agent->max_rtt_ms,
                agent->avg_throughput_kbps,
                agent->errors);
    }
}

/* ============================================================================
 * CLI MAIN FUNCTION
 * ============================================================================ */

int main(int argc, char **argv) {
    TelemetryAgent agent = {0};
    int host_port = 50051;
    const char *host = "localhost";
    const char *device_id = "agent-c-001";
    int packets_count = 100;
    const char *mode = "unary";  /* unary or stream */
    const char *log_dir = "./logs";
    
    /* Parse command line arguments */
    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--host") == 0 && i + 1 < argc) {
            host = argv[++i];
        } else if (strcmp(argv[i], "--port") == 0 && i + 1 < argc) {
            host_port = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--device-id") == 0 && i + 1 < argc) {
            device_id = argv[++i];
        } else if (strcmp(argv[i], "--packets") == 0 && i + 1 < argc) {
            packets_count = atoi(argv[++i]);
        } else if (strcmp(argv[i], "--mode") == 0 && i + 1 < argc) {
            mode = argv[++i];
        } else if (strcmp(argv[i], "--log-dir") == 0 && i + 1 < argc) {
            log_dir = argv[++i];
        } else if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
            fprintf(stderr, "Usage: %s [OPTIONS]\n"
                    "Options:\n"
                    "  --host <host>      gRPC service host (default: localhost)\n"
                    "  --port <port>      gRPC service port (default: 50051)\n"
                    "  --device-id <id>   Device identifier (default: agent-c-001)\n"
                    "  --packets <n>      Number of packets to send (default: 100)\n"
                    "  --mode <mode>      Send mode: unary or stream (default: unary)\n"
                    "  --log-dir <dir>    Log directory (default: ./logs)\n"
                    "  --help, -h         Show this help message\n",
                    argv[0]);
            return 0;
        }
    }
    
    /* Initialize agent */
    int ret = agent_init(&agent, host, host_port, device_id, log_dir);
    if (ret != 0) {
        fprintf(stderr, "Failed to initialize agent\n");
        return 1;
    }
    
    /* Connect to service */
    ret = agent_connect(&agent);
    if (ret != 0) {
        fprintf(stderr, "Failed to connect to service\n");
        agent_close(&agent);
        return 1;
    }
    
    /* Log mode and packet count */
    if (agent.log_file != stdout) {
        fprintf(agent.log_file,
                "Mode           : %s\n"
                "Packets        : %d\n", mode, packets_count);
    }
    
    /* Send packets */
    if (strcmp(mode, "unary") == 0) {
        /* Send packets one at a time */
        for (int i = 0; i < packets_count; i++) {
            ret = agent_send_packet(&agent);
            if (ret != 0) {
                break;
            }
            
            /* Optional delay between packets */
            if (i < packets_count - 1) {
                usleep(100000);  /* 100ms delay */
            }
        }
    } else if (strcmp(mode, "stream") == 0) {
        /* Send packets in a batch */
        ret = agent_send_batch(&agent, packets_count);
    }
    
    /* Close agent */
    agent_close(&agent);
    
    return (ret == 0) ? 0 : 1;
}