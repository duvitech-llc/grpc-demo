cmake_minimum_required(VERSION 3.16)

project(telemetry_agent_c
    VERSION 1.0.0
    DESCRIPTION "Telemetry Agent (C only)"
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
# Find Protobuf and gRPC
find_package(Protobuf REQUIRED)
message(STATUS "Found Protobuf: ${Protobuf_VERSION} at ${Protobuf_INCLUDE_DIRS}")
find_package(gRPC CONFIG QUIET)
if (gRPC_FOUND)
    message(STATUS "Found gRPC via config")
else()
    message(STATUS "gRPC CMake config not found; falling back to finding libraries")
    find_library(GRPC_CPP_LIB NAMES grpc++ grpc++_unsecure PATHS /usr/lib /usr/local/lib /usr/lib/x86_64-linux-gnu)
    find_library(GRPC_LIB NAMES grpc PATHS /usr/lib /usr/local/lib /usr/lib/x86_64-linux-gnu)
    if (GRPC_CPP_LIB AND GRPC_LIB)
        message(STATUS "Found gRPC libraries: ${GRPC_CPP_LIB}; ${GRPC_LIB}")
        # Set a local variable to indicate we have gRPC libs
        set(gRPC_FOUND FALSE)
        set(GRPC_LIBS_FOUND TRUE)
    else()
        message(STATUS "gRPC libraries not found; continuing without native gRPC support")
        set(GRPC_LIBS_FOUND FALSE)
        set(gRPC_FOUND FALSE)
    endif()
endif()

# Build the C agent which uses the Python helper script for RPC
message(STATUS "Building C agent (uses Python helper script for RPC)")
add_executable(telemetry_agent
    telemetry_agent.c
)
target_link_libraries(telemetry_agent
    pthread
    m
)
find_package(CURL QUIET)
if (CURL_FOUND)
    target_include_directories(telemetry_agent PRIVATE ${CURL_INCLUDE_DIRS})
    target_link_libraries(telemetry_agent ${CURL_LIBRARIES})
else()
    # Try linking libcurl directly
    target_link_libraries(telemetry_agent curl)
endif()

# No C++ properties required for C-only build

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