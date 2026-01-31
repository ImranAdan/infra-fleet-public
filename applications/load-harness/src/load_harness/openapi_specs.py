# src/load_harness/openapi_specs.py
"""
OpenAPI/Swagger specifications for LoadHarness API endpoints.

Each spec is a dictionary that can be used with flasgger's swag_from decorator.
"""

# ---- Health Endpoints ----

APP_INFO_SPEC = {
    "tags": ["Health"],
    "summary": "Application Info",
    "description": "Returns Load Harness application info and version details.",
    "responses": {
        200: {
            "description": "Application info",
            "schema": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "example": "Load Harness - Synthetic Workload Generator",
                    },
                    "timestamp": {"type": "string", "format": "date-time"},
                    "version": {"type": "string", "example": "dev"},
                    "environment": {"type": "string", "example": "local"},
                },
            },
        },
    },
}

HEALTH_CHECK_SPEC = {
    "tags": ["Health"],
    "summary": "Health Check",
    "description": "Returns health status for Kubernetes liveness/readiness probes.",
    "responses": {
        200: {
            "description": "Service is healthy",
            "schema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "healthy"},
                    "timestamp": {"type": "string", "format": "date-time"},
                },
            },
        },
    },
}

READY_SPEC = {
    "tags": ["Health"],
    "summary": "Readiness Check",
    "description": "Returns readiness status for Kubernetes readiness probes. "
    "Use this for readiness checks and /health for liveness checks.",
    "responses": {
        200: {
            "description": "Service is ready to accept traffic",
            "schema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "ready"},
                    "timestamp": {"type": "string", "format": "date-time"},
                },
            },
        },
    },
}

VERSION_SPEC = {
    "tags": ["System"],
    "summary": "Version Information",
    "description": "Returns detailed version, build, and deployment information for tracking releases.",
    "responses": {
        200: {
            "description": "Version and deployment information",
            "schema": {
                "type": "object",
                "properties": {
                    "version": {"type": "string", "example": "1.0.2"},
                    "environment": {"type": "string", "example": "staging"},
                    "build": {
                        "type": "object",
                        "properties": {
                            "timestamp": {"type": "string", "format": "date-time"},
                            "python_version": {"type": "string", "example": "3.11.0"},
                        },
                    },
                    "deployment": {
                        "type": "object",
                        "properties": {
                            "pod_name": {"type": "string", "example": "load-harness-7d8f9c5b4-x7k2m"},
                            "namespace": {"type": "string", "example": "applications"},
                        },
                    },
                    "timestamp": {"type": "string", "format": "date-time"},
                },
            },
        },
    },
}

# ---- System Info ----

SYSTEM_INFO_SPEC = {
    "tags": ["System"],
    "summary": "System Information",
    "description": "Returns system information including available CPU cores and memory. "
    "CPU core count respects Kubernetes cgroup limits when running in a container.",
    "responses": {
        200: {
            "description": "System information",
            "schema": {
                "type": "object",
                "properties": {
                    "cpu_cores": {
                        "type": "integer",
                        "example": 2,
                        "description": "Available CPU cores (respects K8s limits)",
                    },
                    "cpu_cores_physical": {
                        "type": "integer",
                        "example": 8,
                        "description": "Physical CPU cores on the host",
                    },
                    "memory_total_mb": {
                        "type": "integer",
                        "example": 8192,
                        "description": "Total memory in MB",
                    },
                    "memory_available_mb": {
                        "type": "integer",
                        "example": 4096,
                        "description": "Available memory in MB",
                    },
                    "timestamp": {"type": "string", "format": "date-time"},
                },
            },
        },
    },
}

# ---- Load Testing Endpoints ----

# ---- Memory Load Endpoints (Non-blocking) ----

MEMORY_LOAD_START_SPEC = {
    "tags": ["Memory Load"],
    "summary": "Start Memory Load",
    "description": "Start memory load using a background process. "
    "Allocates specified memory, touches all pages, holds for duration, then releases. "
    "Returns immediately while memory is held in background, keeping health probes responsive. "
    "Use the status endpoint to monitor and stop endpoint to terminate early.",
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "required": False,
            "schema": {
                "type": "object",
                "properties": {
                    "size_mb": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 2048,
                        "default": 50,
                        "description": "Amount of memory to allocate (megabytes)",
                    },
                    "duration_seconds": {
                        "type": "integer",
                        "minimum": 5,
                        "maximum": 300,
                        "default": 30,
                        "description": "How long to hold the memory (seconds)",
                    },
                },
                "example": {"size_mb": 256, "duration_seconds": 60},
            },
        }
    ],
    "responses": {
        200: {
            "description": "Memory load started",
            "schema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "started"},
                    "job_id": {"type": "string", "example": "mem_1733541234567"},
                    "size_mb": {"type": "integer", "example": 256},
                    "duration_seconds": {"type": "integer", "example": 60},
                    "message": {"type": "string"},
                    "check_status": {"type": "string", "example": "/load/memory/status"},
                    "stop_endpoint": {"type": "string", "example": "/load/memory/stop"},
                    "timestamp": {"type": "string", "format": "date-time"},
                },
            },
        },
        400: {
            "description": "Invalid parameters",
            "schema": {
                "type": "object",
                "properties": {
                    "error": {"type": "string"},
                },
            },
        },
    },
}

MEMORY_LOAD_STATUS_SPEC = {
    "tags": ["Memory Load"],
    "summary": "Get Memory Load Status",
    "description": "Get status of all active and recently completed memory load jobs.",
    "responses": {
        200: {
            "description": "Status of memory load jobs",
            "schema": {
                "type": "object",
                "properties": {
                    "active_jobs": {"type": "integer", "example": 1},
                    "total_jobs": {"type": "integer", "example": 3},
                    "jobs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "job_id": {"type": "string", "example": "mem_1733541234567"},
                                "status": {"type": "string", "enum": ["running", "completed", "stopped"]},
                                "size_mb": {"type": "integer", "example": 256},
                                "duration_seconds": {"type": "integer", "example": 60},
                                "started_at": {"type": "string", "format": "date-time"},
                                "completed_at": {"type": "string", "format": "date-time", "nullable": True},
                            },
                        },
                    },
                    "timestamp": {"type": "string", "format": "date-time"},
                },
            },
        },
    },
}

MEMORY_LOAD_STOP_SPEC = {
    "tags": ["Memory Load"],
    "summary": "Stop Memory Load",
    "description": "Stop memory load jobs and release allocated memory. "
    "Specify a job_id to stop a specific job, or omit to stop all running jobs.",
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "required": False,
            "schema": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Specific job to stop (optional, stops all if omitted)",
                        "example": "mem_1733541234567",
                    },
                },
            },
        }
    ],
    "responses": {
        200: {
            "description": "Memory released",
            "schema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "stopped"},
                    "stopped_jobs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "example": ["mem_1733541234567"],
                    },
                    "count": {"type": "integer", "example": 1},
                    "timestamp": {"type": "string", "format": "date-time"},
                },
            },
        },
        404: {
            "description": "Job not found",
            "schema": {
                "type": "object",
                "properties": {
                    "error": {"type": "string", "example": "Job mem_123 not found"},
                },
            },
        },
    },
}

# Legacy blocking memory load (kept for backwards compatibility)
MEMORY_LOAD_SPEC = {
    "tags": ["Load Testing"],
    "summary": "Generate Memory Load (Blocking)",
    "description": "Generate memory-intensive workload synchronously (blocking). "
    "Allocates specified memory, touches all pages, holds for duration, then releases. "
    "For non-blocking memory load, use POST /load/memory instead.",
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "required": False,
            "schema": {
                "type": "object",
                "properties": {
                    "size_mb": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 2048,
                        "default": 50,
                        "description": "Amount of memory to allocate (megabytes)",
                    },
                    "duration_ms": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 120000,
                        "default": 1000,
                        "description": "How long to hold the memory (milliseconds)",
                    },
                },
                "example": {"size_mb": 100, "duration_ms": 2000},
            },
        }
    ],
    "responses": {
        200: {
            "description": "Memory load completed",
            "schema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "completed"},
                    "requested_size_mb": {"type": "integer", "example": 100},
                    "actual_bytes_allocated": {"type": "integer", "example": 104857600},
                    "requested_duration_ms": {"type": "integer", "example": 2000},
                    "actual_duration_ms": {"type": "number", "example": 2005.23},
                    "allocation_time_ms": {"type": "number", "example": 15.42},
                    "timestamp": {"type": "string", "format": "date-time"},
                },
            },
        },
        400: {
            "description": "Invalid parameters",
            "schema": {
                "type": "object",
                "properties": {
                    "error": {"type": "string"},
                },
            },
        },
    },
}

# ---- CPU Load Endpoints (Non-blocking) ----

CPU_LOAD_START_SPEC = {
    "tags": ["CPU Load"],
    "summary": "Start CPU Load",
    "description": "Start CPU load using background worker processes distributed across available cores. "
    "Returns immediately while workers run in background, keeping health probes responsive. "
    "Use the status endpoint to monitor and stop endpoint to terminate workers.",
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "required": False,
            "schema": {
                "type": "object",
                "properties": {
                    "cores": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 16,
                        "default": 1,
                        "description": "Number of CPU cores to load (one worker per core)",
                    },
                    "duration_seconds": {
                        "type": "integer",
                        "minimum": 10,
                        "maximum": 900,
                        "default": 60,
                        "description": "How long workers run (seconds, 10s to 15min)",
                    },
                    "intensity": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "default": 5,
                        "description": "Computational intensity (1-10). Higher = more CPU cycles per iteration.",
                    },
                },
                "example": {"cores": 2, "duration_seconds": 300, "intensity": 5},
            },
        }
    ],
    "responses": {
        200: {
            "description": "CPU load started",
            "schema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "started"},
                    "job_id": {"type": "string", "example": "job_1733541234567"},
                    "cores": {"type": "integer", "example": 2},
                    "duration_seconds": {"type": "integer", "example": 300},
                    "intensity": {"type": "integer", "example": 5},
                    "message": {"type": "string"},
                    "check_status": {"type": "string", "example": "/load/cpu/status"},
                    "stop_endpoint": {"type": "string", "example": "/load/cpu/stop"},
                    "timestamp": {"type": "string", "format": "date-time"},
                },
            },
        },
        400: {
            "description": "Invalid parameters",
            "schema": {
                "type": "object",
                "properties": {
                    "error": {"type": "string"},
                },
            },
        },
    },
}

CPU_LOAD_STATUS_SPEC = {
    "tags": ["CPU Load"],
    "summary": "Get CPU Load Status",
    "description": "Get status of all active and recently completed CPU load jobs.",
    "responses": {
        200: {
            "description": "Status of CPU load jobs",
            "schema": {
                "type": "object",
                "properties": {
                    "active_jobs": {"type": "integer", "example": 1},
                    "total_jobs": {"type": "integer", "example": 3},
                    "jobs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "job_id": {"type": "string", "example": "job_1733541234567"},
                                "status": {"type": "string", "enum": ["running", "completed", "stopped"]},
                                "cores_requested": {"type": "integer", "example": 2},
                                "cores_active": {"type": "integer", "example": 2},
                                "duration_seconds": {"type": "integer", "example": 300},
                                "intensity": {"type": "integer", "example": 5},
                                "started_at": {"type": "string", "format": "date-time"},
                                "completed_at": {"type": "string", "format": "date-time", "nullable": True},
                            },
                        },
                    },
                    "timestamp": {"type": "string", "format": "date-time"},
                },
            },
        },
    },
}

CPU_LOAD_WORK_SPEC = {
    "tags": ["CPU Load"],
    "summary": "Synchronous CPU Work",
    "description": "Perform CPU-intensive work synchronously (blocking). "
    "Use with external load generators (hey, k6, wrk) to distribute load across pods. "
    "Each request does 'iterations' of math operations and returns when complete. "
    "Unlike /load/cpu (async), this blocks the worker until done - enabling load balancing.",
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "required": False,
            "schema": {
                "type": "object",
                "properties": {
                    "iterations": {
                        "type": "integer",
                        "minimum": 1000,
                        "maximum": 10000000,
                        "default": 100000,
                        "description": "Number of CPU iterations to perform (higher = longer)",
                    },
                },
                "example": {"iterations": 500000},
            },
        }
    ],
    "responses": {
        200: {
            "description": "CPU work completed",
            "schema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "completed"},
                    "iterations": {"type": "integer", "example": 500000},
                    "duration_ms": {"type": "number", "example": 245.67},
                    "result": {"type": "number", "description": "Computation result (for verification)"},
                    "pod_name": {"type": "string", "example": "load-harness-abc123"},
                    "timestamp": {"type": "string", "format": "date-time"},
                },
            },
        },
        400: {
            "description": "Invalid parameters",
            "schema": {
                "type": "object",
                "properties": {
                    "error": {"type": "string"},
                },
            },
        },
    },
}

CPU_LOAD_STOP_SPEC = {
    "tags": ["CPU Load"],
    "summary": "Stop CPU Load Workers",
    "description": "Stop CPU load workers. "
    "Specify a job_id to stop a specific job, or omit to stop all running jobs.",
    "parameters": [
        {
            "name": "body",
            "in": "body",
            "required": False,
            "schema": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Specific job to stop (optional, stops all if omitted)",
                        "example": "job_1733541234567",
                    },
                },
            },
        }
    ],
    "responses": {
        200: {
            "description": "Workers stopped",
            "schema": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "example": "stopped"},
                    "stopped_jobs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "example": ["job_1733541234567"],
                    },
                    "count": {"type": "integer", "example": 1},
                    "timestamp": {"type": "string", "format": "date-time"},
                },
            },
        },
        404: {
            "description": "Job not found",
            "schema": {
                "type": "object",
                "properties": {
                    "error": {"type": "string", "example": "Job job_123 not found"},
                },
            },
        },
    },
}
