# Flask Load Testing Application - Vision

**Purpose**: A load/capacity testing application for validating platform performance, observability, and scalability.

## Overview

This application will evolve from a simple "Hello World" to a comprehensive load testing target that demonstrates real-world platform capabilities under various workload conditions.

## Core Objectives

### 1. Load Testing Target
Provide endpoints that simulate realistic application workloads to test platform behavior under different load conditions.

### 2. Observability Demonstration
Instrument the application to showcase platform monitoring capabilities including metrics, logging, and tracing.

### 3. Performance Validation
Enable measurement of platform performance characteristics, scaling behavior, resource efficiency, and cost per request.

## Key Use Cases

- **Platform Learning**: Understand Kubernetes resource management, auto-scaling, and monitoring
- **Infrastructure Validation**: Test ALB distribution, EKS stability, and spot instance handling under load
- **Cost Optimization**: Measure cost per request and evaluate different scaling strategies
- **Production Readiness**: Demonstrate monitoring, alerting, and incident response capabilities

## Success Criteria

- Measurable performance baselines
- Clear observability signals (metrics, logs, traces)
- Documented scaling behavior
- Cost-per-request analysis
- Repeatable load testing scenarios

---

## What the Harness provides

- CPU and memory load endpoints, blocking and sustained
- Prometheus metrics and health endpoints
- OpenAPI documentation at `/apidocs`
- A dashboard for triggering load and watching the cluster respond

See [APPLICATION-ROADMAP.md](./APPLICATION-ROADMAP.md) for the endpoint
reference, metrics, deployment notes, and how to replace the Harness with your
own application.
