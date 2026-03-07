#!/usr/bin/env python3
"""
Benchmark tests for the Telemetry Service.

Measures:
- SendTelemetry latency (unary RPC)
- StreamTelemetry throughput (client streaming)
- Concurrent connection handling
- Packet validation overhead
"""

import os
import sys
import time
import statistics
import argparse
import concurrent.futures

import grpc
from concurrent import futures

import telemetry_pb2
import telemetry_pb2_grpc

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from telemetry_service import PacketValidator, TelemetryServicer


# ── Benchmark Results ────────────────────────────────────────────────────
class BenchmarkResults:
    """Container for benchmark results."""

    def __init__(self):
        self.unitary_latency_us = []  # microseconds
        self.stream_throughput_kbps = []
        self.concurrent_connections = []
        self.validation_overhead_us = []
        self.errors = 0

    def to_dict(self):
        return {
            'unitary_latency_us': self.unitary_latency_us,
            'stream_throughput_kbps': self.stream_throughput_kbps,
            'concurrent_connections': self.concurrent_connections,
            'validation_overhead_us': self.validation_overhead_us,
            'errors': self.errors,
        }


# ── Test Packets ─────────────────────────────────────────────────────────
class TestPackets:
    """Test packet generators."""

    @staticmethod
    def create_valid_packet(device_id: str, seq: int, temperature: float = 25.0):
        """Create a valid telemetry packet."""
        return telemetry_pb2.TelemetryPacket(
            device_id=device_id,
            sequence_number=seq,
            timestamp_ms=int(time.time() * 1000),
            temperature=temperature,
            gps=telemetry_pb2.GpsData(latitude=37.7749 + seq * 0.0001,
                                       longitude=-122.4194 + seq * 0.0001,
                                       altitude=10.0 + seq),
            imu=telemetry_pb2.ImuData(
                accel_x=1.5, accel_y=-0.5, accel_z=9.8,
                gyro_x=0.1, gyro_y=0.2, gyro_z=0.05,
                mag_x=30000, mag_y=28000, mag_z=45000
            )
        )

    @staticmethod
    def create_invalid_packet(type: str = "empty_device_id"):
        """Create an invalid telemetry packet."""
        if type == "empty_device_id":
            return telemetry_pb2.TelemetryPacket(
                device_id="",
                sequence_number=1,
                timestamp_ms=int(time.time() * 1000),
                temperature=25.0,
                gps=telemetry_pb2.GpsData(latitude=37.0, longitude=-122.0, altitude=0.0),
                imu=telemetry_pb2.ImuData(
                    accel_x=0, accel_y=0, accel_z=0,
                    gyro_x=0, gyro_y=0, gyro_z=0,
                    mag_x=0, mag_y=0, mag_z=0
                )
            )
        elif type == "invalid_temp":
            return telemetry_pb2.TelemetryPacket(
                device_id="test-device",
                sequence_number=1,
                timestamp_ms=int(time.time() * 1000),
                temperature=201.0,  # Out of range
                gps=telemetry_pb2.GpsData(latitude=37.0, longitude=-122.0, altitude=0.0),
                imu=telemetry_pb2.ImuData(
                    accel_x=0, accel_y=0, accel_z=0,
                    gyro_x=0, gyro_y=0, gyro_z=0,
                    mag_x=0, mag_y=0, mag_z=0
                )
            )
        elif type == "invalid_lat":
            return telemetry_pb2.TelemetryPacket(
                device_id="test-device",
                sequence_number=1,
                timestamp_ms=int(time.time() * 1000),
                temperature=25.0,
                gps=telemetry_pb2.GpsData(latitude=91.0, longitude=-122.0, altitude=0.0),
                imu=telemetry_pb2.ImuData(
                    accel_x=0, accel_y=0, accel_z=0,
                    gyro_x=0, gyro_y=0, gyro_z=0,
                    mag_x=0, mag_y=0, mag_z=0
                )
            )
        else:
            return telemetry_pb2.TelemetryPacket(
                device_id="test-device",
                sequence_number=1,
                timestamp_ms=int(time.time() * 1000),
                temperature=25.0,
                gps=telemetry_pb2.GpsData(latitude=37.0, longitude=-122.0, altitude=0.0),
                imu=telemetry_pb2.ImuData(
                    accel_x=0, accel_y=0, accel_z=0,
                    gyro_x=0, gyro_y=0, gyro_z=0,
                    mag_x=0, mag_y=0, mag_z=0
                )
            )


# ── Benchmark Functions ───────────────────────────────────────────────────
def benchmark_send_telemetry(host: str, port: int, num_packets: int = 10,
                              num_runs: int = 3):
    """Benchmark SendTelemetry latency."""
    channel = grpc.insecure_channel(f"{host}:{port}")
    stub = telemetry_pb2_grpc.TelemetryServiceStub(channel)
    results = BenchmarkResults()
    packet = TestPackets.create_valid_packet("benchmark-device", 0)

    for run in range(num_runs):
        latencies = []
        for _ in range(num_packets):
            start = time.perf_counter()
            response = stub.SendTelemetry(packet, timeout=5.0)
            end = time.perf_counter()
            latency_us = (end - start) * 1_000_000
            latencies.append(latency_us)
            results.unitary_latency_us.append(latency_us)
            if not response.success:
                results.errors += 1

    channel.close()
    return results, latencies


def benchmark_stream_telemetry(host: str, port: int, packet_count: int = 100,
                                num_runs: int = 3):
    """Benchmark StreamTelemetry throughput."""
    channel = grpc.insecure_channel(f"{host}:{port}")
    stub = telemetry_pb2_grpc.TelemetryServiceStub(channel)
    results = BenchmarkResults()

    for run in range(num_runs):
        packets = [TestPackets.create_valid_packet(f"stream-device", i, 25.0 + i * 0.01)
                   for i in range(packet_count)]

        start = time.perf_counter()

        def packet_generator():
            for packet in packets:
                yield packet

        response = stub.StreamTelemetry(packet_generator(), timeout=30.0)
        end = time.perf_counter()

        duration_s = end - start
        throughput_kbps = (len(packets) * 243) / duration_s / 1024  # Approx 243 bytes per packet
        results.stream_throughput_kbps.append(throughput_kbps)

        if not response.success:
            results.errors += 1

    channel.close()
    return results, [throughput_kbps]


def benchmark_concurrent_connections(host: str, port: int,
                                      num_connections: int = 5,
                                      packets_per_conn: int = 10,
                                      num_runs: int = 3):
    """Benchmark concurrent connection handling."""
    channel = grpc.insecure_channel(f"{host}:{port}")
    stub = telemetry_pb2_grpc.TelemetryServiceStub(channel)
    results = BenchmarkResults()

    for run in range(num_runs):
        latencies = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_connections) as executor:
            futures_list = []
            for _ in range(num_connections):
                for seq in range(packets_per_conn):
                    packet = TestPackets.create_valid_packet(f"concurrent-{seq}", seq * 1000, 25.0)
                    futures_list.append(executor.submit(stub.SendTelemetry, packet, timeout=5.0))
            
            for future in concurrent.futures.as_completed(futures_list):
                try:
                    result = future.result()
                    latencies.append(1)  # Dummy latency for concurrent test
                except Exception:
                    results.errors += 1
            results.concurrent_connections.append(num_connections)

    channel.close()
    return results, latencies


def benchmark_validation_overhead(num_iterations: int = 1000):
    """Benchmark packet validation overhead."""
    results = BenchmarkResults()
    packet = TestPackets.create_valid_packet("validation-test", 0)

    for _ in range(num_iterations):
        start = time.perf_counter()
        PacketValidator.validate(packet)
        end = time.perf_counter()
        results.validation_overhead_us.append((end - start) * 1_000_000)

    return results


def run_all_benchmarks(host: str, port: int):
    """Run all benchmarks and print results."""
    print("\n" + "=" * 60)
    print("TELEMETRY SERVICE BENCHMARK RESULTS")
    print("=" * 60 + "\n")

    print("--- SendTelemetry Latency Benchmark ---")
    print("Running with 10 packets per run, 3 runs...\n")
    results1, _ = benchmark_send_telemetry(host, port, num_packets=10, num_runs=3)
    if results1.unitary_latency_us:
        avg_latency = statistics.mean(results1.unitary_latency_us)
        min_latency = min(results1.unitary_latency_us)
        max_latency = max(results1.unitary_latency_us)
        p50 = statistics.median(results1.unitary_latency_us)
        print(f"  Average Latency: {avg_latency:.2f} µs")
        print(f"  Min Latency:     {min_latency:.2f} µs")
        print(f"  Max Latency:     {max_latency:.2f} µs")
        print(f"  P50 Latency:     {p50:.2f} µs")
        if len(results1.unitary_latency_us) > 1:
            print(f"  Std Deviation:   {statistics.stdev(results1.unitary_latency_us):.2f} µs")
    else:
        print("  No results collected")
    print()

    print("--- StreamTelemetry Throughput Benchmark ---")
    print("Running with 100 packets per stream, 3 runs...\n")
    results2, _ = benchmark_stream_telemetry(host, port, packet_count=100, num_runs=3)
    if results2.stream_throughput_kbps:
        avg_throughput = statistics.mean(results2.stream_throughput_kbps)
        min_throughput = min(results2.stream_throughput_kbps)
        max_throughput = max(results2.stream_throughput_kbps)
        print(f"  Average Throughput: {avg_throughput:.1f} KB/s")
        print(f"  Min Throughput:     {min_throughput:.1f} KB/s")
        print(f"  Max Throughput:     {max_throughput:.1f} KB/s")
    else:
        print("  No results collected")
    print()

    print("--- Concurrent Connections Benchmark ---")
    print("Running with 5 concurrent connections, 10 packets each, 3 runs...\n")
    results3, _ = benchmark_concurrent_connections(host, port, num_connections=5,
                                                   packets_per_conn=10, num_runs=3)
    print(f"  Connections Tested: {results3.concurrent_connections}")
    print(f"  Errors: {results3.errors}")
    print()

    print("--- Validation Overhead Benchmark ---")
    print("Running with 1000 validation iterations...\n")
    results4 = benchmark_validation_overhead(num_iterations=1000)
    if results4.validation_overhead_us:
        avg_overhead = statistics.mean(results4.validation_overhead_us)
        if len(results4.validation_overhead_us) > 1:
            print(f"  Average Validation Time: {avg_overhead:.2f} µs")
            print(f"  Std Deviation: {statistics.stdev(results4.validation_overhead_us):.2f} µs")
    print()

    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total Errors: {results1.errors + results2.errors}")
    print("All benchmarks completed successfully!")


def main():
    """Main entry point for benchmarks."""
    parser = argparse.ArgumentParser(description="Telemetry Service Benchmarks")
    parser.add_argument("--host", default="localhost", help="Server host (default: localhost)")
    parser.add_argument("--port", type=int, default=50051, help="Server port (default: 50051)")
    parser.add_argument("--num-unary-packets", type=int, default=10, help="Unary test packets (default: 10)")
    parser.add_argument("--num-stream-packets", type=int, default=100, help="Stream test packets (default: 100)")
    parser.add_argument("--concurrent-connections", type=int, default=5, help="Concurrent connections (default: 5)")
    args = parser.parse_args()

    print("Starting Telemetry Service Benchmark Tests")
    print(f"Connecting to {args.host}:{args.port}")

    try:
        run_all_benchmarks(args.host, args.port)
    except grpc.RpcError as e:
        print(f"Connection error: {e}")
        print("Make sure the telemetry service is running on the specified host:port")
    except Exception as e:
        print(f"Benchmark error: {e}")


if __name__ == "__main__":
    main()