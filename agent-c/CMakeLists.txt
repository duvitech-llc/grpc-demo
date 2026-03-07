cmake_minimum_required(VERSION 3.16)

project(telemetry_agent_c
    VERSION 1.0.0
    DESCRIPTION "C Telemetry Agent for gRPC telemetry service"
    LANGUAGES C
)

# Set C standard
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

# Build type
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

# Optimization flags
if(CMAKE_BUILD_TYPE STREQUAL "Release")
    if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
        add_compile_options(-O3 -DNDEBUG)
    endif()
elseif(CMAKE_BUILD_TYPE STREQUAL "Debug")
    if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
        add_compile_options(-g -O0 -DDEBUG)
    endif()
endif()

# Find Protobuf
find_package(Protobuf REQUIRED)
message(STATUS "Found Protobuf: ${Protobuf_VERSION} at ${Protobuf_INCLUDE_DIRS}")

# Create protobuf headers
# Proto file is in parent directory (grpc-demo/proto)
set(PROTO_FILE "${CMAKE_SOURCE_DIR}/../proto/telemetry.proto")
set(PROTO_INCLUDE_DIR "${CMAKE_CURRENT_BINARY_DIR}/proto")
set(PROTO_FILES "telemetry.proto")

protobuf_generate_cpp(PROTO_SRCS PROTO_INCLUDES
    "${PROTO_FILE}"
)
message(STATUS "Generated protobuf files in: ${PROTO_INCLUDE_DIR}")

# Add include directories
include_directories(${Protobuf_INCLUDE_DIRS})
include_directories(${PROTO_INCLUDE_DIR})

# Create executable
add_executable(telemetry_agent
    telemetry_agent.c
    ${PROTO_SRCS}
)

# Link protobuf libraries
target_link_libraries(telemetry_agent
    protobuf::libprotobuf
    protobuf::libprotobuf-lite
)

# Enable shared libraries support (if needed for dynamic protobuf)
set_target_properties(telemetry_agent PROPERTIES
    CXX_STANDARD 14
    CXX_STANDARD_REQUIRED ON
)

# Install target
install(TARGETS telemetry_agent
    DESTINATION bin
)

# Install headers
install(FILES telemetry_agent.h
    DESTINATION include/agent-c
)

# Print build summary
message(STATUS "")
message(STATUS "========================================")
message(STATUS "Telemetry Agent C Build Configuration")
message(STATUS "========================================")
message(STATUS "Build Type: ${CMAKE_BUILD_TYPE}")
message(STATUS "C Compiler: ${CMAKE_C_COMPILER_ID} ${CMAKE_C_COMPILER_VERSION}")
message(STATUS "C Standard: ${CMAKE_C_STANDARD}")
message(STATUS "Proto Version: ${Protobuf_VERSION}")
message(STATUS "Install Prefix: ${CMAKE_INSTALL_PREFIX}")
message(STATUS "========================================")
message(STATUS "")