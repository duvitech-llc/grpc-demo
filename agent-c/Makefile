.PHONY: all clean build help

help:
	@echo "Usage: make [TARGET]"
	@echo ""
	@echo "Targets:"
	@echo "  all     - Build the telemetry agent (default)"
	@echo "  build   - Build the telemetry agent"
	@echo "  clean   - Remove build artifacts"
	@echo ""
	@echo "Build options:"
	@echo "  make BUILD_TYPE=Debug    - Debug build (default: Release)"
	@echo "  make CFLAGS='-Wall'      - Enable warnings"
	@echo ""

all: build

build:
	cmake -S . -B build \
		-DCMAKE_BUILD_TYPE=Release \
		-DCMAKE_C_STANDARD=11 \
		-DCMAKE_C_FLAGS="${CFLAGS:-}" && \
	cmake --build build --target telemetry_agent

clean:
	rm -rf build