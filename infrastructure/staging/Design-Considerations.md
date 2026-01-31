# EKS Cluster Design Considerations

This document covers the architectural decisions, cost optimization strategies, and lessons learned during the development of our private EKS cluster infrastructure.

## Architecture Evolution

### Initial Design Attempts

Our infrastructure went through several iterations before settling on the current hybrid approach:

#### 1. VPC Endpoints Only (Failed)
**Approach**: Fully private setup with comprehensive VPC endpoints for all AWS services.
**Result**: Failed due to Session Manager bootstrap issues.
**Problem**: Session Manager couldn't download packages when using VPC endpoints only.
**Error**: `Cannot find a valid baseurl for repo: amzn2-core/2/x86_64`
**Lesson**: VPC endpoints don't provide comprehensive internet replacement for package repositories.

#### 2. Single AZ Setup (Failed)
**Approach**: Attempted single AZ configuration to reduce costs.
**Result**: Failed due to EKS requirements.
**Error**: `InvalidParameterException: Subnets specified must be in at least two different AZs`
**Lesson**: EKS requires minimum two AZs for high availability, no exceptions.

#### 3. Hybrid Approach (Current Solution)
**Approach**: NAT Gateway + S3 VPC Endpoint + Public Session Manager.
**Result**: Successful deployment with balanced cost and functionality.

### Current Architecture Components

```
Internet Gateway
    ├── Public Subnet (10.0.101.0/24)
    │   └── Session Manager (t3.micro) + ALB
    ├── Private Subnet 1 (10.0.1.0/24) - eu-west-2a
    │   └── EKS Worker Node (t3.small)
    └── Private Subnet 2 (10.0.2.0/24) - eu-west-2b
        └── Available for scaling

NAT Gateway (in public subnet)
    └── Provides internet access for private subnets

S3 VPC Gateway Endpoint
    └── Cost-free access to S3 from private subnets

EKS Cluster (Private API endpoint)
    └── Accessible only within VPC
```

## NAT Gateway vs VPC Endpoints Analysis

### When to Prefer NAT Gateway

**Use NAT Gateway when:**
- Applications require general internet access for package downloads, API calls, external services
- Workloads need access to third-party registries (Docker Hub, npm, pip, etc.)
- Development/testing environments where flexibility is important
- Cost of NAT Gateway ($45.60/month + data) is acceptable vs VPC endpoint complexity

**Advantages:**
- Universal internet access for all services
- Simplifies connectivity - no need to create specific endpoints
- Better for dynamic/unpredictable internet requirements
- Easier troubleshooting - standard internet routing

### When to Prefer VPC Endpoints

**Use VPC Endpoints when:**
- High data transfer costs through NAT Gateway (>1GB+ monthly)
- Strict security requirements (no internet access)
- Well-defined, limited set of AWS services required
- Production environments with predictable AWS API usage patterns

**Advantages:**
- Lower costs for high-volume AWS API calls
- Enhanced security (no internet routing)
- Better performance for AWS service calls
- Compliance requirements for private-only connectivity

### Cost Analysis: NAT Gateway vs VPC Endpoints

#### NAT Gateway Costs
- **Base Cost**: $45.60/month (always)
- **Data Processing**: $0.045/GB processed
- **Break-even**: ~1GB of data transfer

#### VPC Endpoints Costs
- **Interface Endpoints**: $7.30/month per endpoint
- **Data Processing**: $0.01/GB processed
- **Gateway Endpoints**: Free (S3, DynamoDB)

**Example Scenario**: Application using ECR, SSM, EC2, S3
- **NAT Gateway**: $45.60 + data costs
- **VPC Endpoints**: $21.90/month (3 interface endpoints) + S3 free + data costs

## Technical Issues and Solutions

### 1. EKS Add-on Dependency Management

**Problem**: Chicken-and-egg scenario where all add-ons waited for healthy nodes, but nodes couldn't become healthy without VPC CNI.

**Solution**: Implemented staged dependencies:
```hcl
# Stage 1: Critical add-ons (no dependencies)
resource "aws_eks_addon" "vpc_cni" {
  cluster_name = module.eks.cluster_name
  addon_name   = "vpc-cni"
}

# Stage 2: Non-critical add-ons (depend on node group completion)  
resource "aws_eks_addon" "coredns" {
  cluster_name = module.eks.cluster_name
  addon_name   = "coredns"
  depends_on = [module.eks]
}
```

**Key Discovery**: CoreDNS is NOT required for node health - nodes can be Ready without DNS resolution.

### 2. CoreDNS Scheduling Issues

**Problem**: CoreDNS pods failed to schedule on t3.micro instances due to insufficient pod capacity.
**Instance Capacity**: t3.micro = 4-11 pods, t3.small = 11-17 pods

**Solution**: Upgraded worker nodes from t3.micro to t3.small for reliable CoreDNS scheduling.
**Cost Impact**: Additional $8.76/month per node.

### 3. Session Manager Internet Access

**Problem**: Session Manager in private subnet couldn't download kubectl and AWS CLI when using VPC endpoints only.

**Solutions Evaluated**:
1. **VPC Endpoints for YUM repositories** - Not feasible (too many endpoints required)
2. **Pre-built AMI with tools** - Increases maintenance overhead
3. **Public subnet placement** - Chosen solution

**Final Solution**: Place Session Manager in public subnet with direct internet access while maintaining SSM security.

## Cost Optimization Strategies

### Actual Costs (November 2025)

**Achieved**: ~$36-41/month (38% uptime pattern)

| Component | Cost (When Running) | Actual Monthly | Optimization |
|-----------|---------------------|----------------|--------------|
| EKS Control Plane | $72/month | ~$27-31 | Prorated by uptime (38%) |
| t3.small (Worker Node) | $17.52/month | ~$5 | Spot instance (~70% savings) + prorated |
| NAT Gateway | $45.60/month | ~$10-12 | Prorated by uptime |
| S3 VPC Endpoint | $0 | $0 | Gateway type (free) |
| Session Manager | ~~$8.76~~ | $0 | **DISABLED** |
| **Total** | **~$135/month** | **~$36-41/month** | **73% reduction** |

**Key Cost Drivers Ranked by Impact**:
1. **Version Management** - $1,656/year savings (Kubernetes 1.32 vs extended support)
2. **Operational Discipline** - 38% uptime pattern via nightly destruction
3. **Spot Instances** - 70% savings on EC2 costs
4. **Session Manager Disabled** - $0 vs $8-10/month
5. **Slim Flux** - Minimal resource overhead

### Operational Cost Optimization (Highest Impact)

#### Automated Nightly Destruction
**Implementation**: GitHub Actions workflow at 1 AM UTC
- **Impact**: 73% cost reduction ($135/month → $36-41/month)
- **Uptime pattern**: ~38% (278 hours in November 2025)
- **Workflow**: `.github/workflows/nightly-destroy.yml`
  - Multi-job design with 5 phases
  - Hybrid cleanup approach (Kubernetes + AWS tag-based)
  - Idempotency support
  - Automatic issue creation on failure

**Hybrid Cleanup Approach**:
- **Phase 1**: Kubernetes-native cleanup (delete Ingress → ALB controller cleans ALBs)
- **Phase 2**: AWS tag-based cleanup (query by tags when cluster destroyed)
- **Phase 3**: Verification (ensure no orphaned ENIs/ALBs blocking VPC deletion)
- **Phase 4**: Terraform destroy
- **Phase 5**: Final idempotency check

See `docs/implementation-summary-hybrid-cleanup.md` for technical details.

#### Version Management (Biggest Absolute Savings)
**Current**: Kubernetes 1.32 (standard support until ~March 2026)
- **Savings**: $1,656/year vs extended support (6× pricing: $0.60/hr vs $0.10/hr)
- **Action**: Quarterly version checks, upgrade before extended support starts
- **Next upgrade**: Target February 2026 → Kubernetes 1.33

See `docs/COST-OPTIMIZATION-GUIDE.md` for comprehensive analysis.

### Infrastructure Optimization Opportunities

#### 1. Data Transfer Optimization
- Monitor NAT Gateway data usage
- Consider VPC endpoints if sustained >1GB monthly transfer
- Use S3 VPC endpoint for artifact storage (already implemented)

#### 2. Instance Right-Sizing
- **Worker Nodes**: t3.small minimum for reliable CoreDNS (11+ pod capacity)
- **Spot instances**: Already implemented (~70% EC2 savings)
- **Scaling**: Can add more spot nodes as needed

#### 3. Network Architecture
- Current single NAT Gateway saves ~$45.60/month vs multi-AZ NAT
- S3 Gateway endpoint eliminates S3 data transfer costs
- Public ALB placement (when needed) avoids internal load balancer costs

## Full Stack Planning

### Future Application Architecture

**Target Stack**:
- **Web Applications**: React/Vue frontend, Node.js/Python backend
- **Observability**: Datadog or Splunk for monitoring and logging  
- **CI/CD**: GitHub Actions + GitOps (ArgoCD/Flux)
- **Data Storage**: RDS for persistent data, ElastiCache for caching

### Integration Considerations

#### 1. Application Load Balancer (ALB)
```hcl
# Future ALB configuration for public application access
# Deploy in public subnet for internet-facing applications
subnet_ids = module.vpc.public_subnets
```

#### 2. GitOps Integration
**Strategy**: 
- GitHub Actions for CI (build, test, security scanning)
- ArgoCD in EKS cluster for CD (pull-based deployment)
- Separate repository for Kubernetes manifests

**Benefits**:
- Declarative configuration management
- Automatic drift detection and remediation
- Audit trail for all deployments

#### 3. Observability Strategy
**Monitoring**: 
- Datadog agent as DaemonSet for metrics collection
- Application Performance Monitoring (APM) for request tracing
- Custom dashboards for business metrics

**Logging**:
- Fluent Bit for log collection and forwarding
- Structured logging in JSON format
- Log aggregation in Datadog or Splunk

### Security Considerations

#### 1. Network Security
- Private EKS API endpoint (current implementation)
- Network policies for pod-to-pod communication
- Security groups with least-privilege access

#### 2. Identity and Access Management
- EKS Pod Identity for service-to-service authentication
- RBAC for fine-grained Kubernetes permissions
- AWS IAM roles for service accounts (IRSA)

#### 3. Image Security
- ECR vulnerability scanning for container images
- Pod Security Standards enforcement
- Regular security updates for worker node AMIs

## Lessons Learned

### 1. Cost Optimization Priority Order
**Lesson**: Not all optimizations are equal - focus on highest-impact levers first
- **Version management** > operational discipline > infrastructure choices
- Kubernetes 1.32 upgrade saves $1,656/year (highest single lever)
- Nightly destruction discipline saves ~$98/month (operational pattern)
- Infrastructure tweaks (spot, NAT) save ~$10-20/month (helpful but smaller)

### 2. Resource Ownership and Cleanup
**Lesson**: Kubernetes controllers create AWS resources not tracked by Terraform/Flux

**Resource Ownership Chain**:
```
Terraform → VPC, EKS, IAM
    ↓
Flux → Kubernetes manifests
    ↓
ALB Controller → ALBs, ENIs, Security Groups (untracked!)
```

**Solution**: Hybrid cleanup approach
- Try Kubernetes-native cleanup first (delete Ingress → controller cleans up)
- Fall back to AWS tag-based cleanup (query by tags when cluster destroyed)
- Verify no orphaned resources before terraform destroy

**Critical**: ENIs with Elastic IPs prevent Internet Gateway detachment, blocking VPC deletion

### 3. Infrastructure Dependencies
- Always implement staged dependencies for EKS add-ons
- VPC CNI and kube-proxy are critical for node health
- CoreDNS can be deployed after nodes are Ready

### 4. Cost vs Complexity Trade-offs
- VPC endpoints add complexity but can reduce costs for high-traffic scenarios
- NAT Gateway provides simplicity at fixed cost
- Monitor actual usage patterns before over-optimizing
- **Operational discipline beats infrastructure optimization** for cost savings

### 5. Instance Sizing Matters
- t3.micro insufficient for CoreDNS scheduling (4-11 pod capacity)
- t3.small provides reliable pod capacity (11-17 pods)
- Spot instances reduce costs ~70% with minimal risk for dev/learning environments
- Always verify pod limits against workload requirements

### 6. Internet Access Requirements
- Bootstrap scripts require reliable internet access
- VPC endpoints don't replace general internet connectivity
- Hybrid approaches often provide best balance

### 7. EKS Constraints
- Minimum two AZ requirement cannot be circumvented
- Private API endpoints require VPC-based access
- Add-on dependencies must be carefully managed

### 8. Workflow Design for Reliability
**Lesson**: Multi-job workflows provide better visibility and fail-fast behavior
- Single-job workflows hide failure points
- Multi-job design creates visual separation in GitHub UI
- Conditional execution prevents cascade failures
- Idempotency checks critical for automation reliability

## Recommended Next Steps

1. **Monitor Usage Patterns**:
   - Track NAT Gateway data transfer monthly
   - Monitor application internet access requirements
   - Evaluate VPC endpoint migration at 1GB+ sustained transfer

2. **Implement GitOps**:
   - Set up ArgoCD in EKS cluster
   - Create separate manifests repository
   - Implement GitHub Actions CI pipeline

3. **Add Observability**:
   - Deploy monitoring stack (Datadog/Prometheus)
   - Implement structured logging
   - Create application health dashboards

4. **Security Hardening**:
   - Implement Kubernetes Network Policies
   - Add container image scanning
   - Regular security audits and updates

5. **Capacity Planning**:
   - Plan multi-node scaling strategy
   - Evaluate spot instances for cost savings
   - Design auto-scaling policies

---

This architecture provides a solid foundation for production workloads while maintaining cost efficiency and operational simplicity. The hybrid approach balances security, performance, and cost considerations for a sustainable infrastructure platform.