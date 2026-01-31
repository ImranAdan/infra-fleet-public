# GitHub Actions Self-Hosted Runner with all CI dependencies
# Multi-architecture support (amd64/arm64)
#
# Build:
#   docker build -t infra-fleet-runner ops/runner/
#
# Run:
#   docker run -d \
#     -e GITHUB_TOKEN=<your-token> \
#     -e RUNNER_NAME=docker-runner \
#     -v /var/run/docker.sock:/var/run/docker.sock \
#     infra-fleet-runner
#
FROM ubuntu:22.04

# Versions - update as needed
ARG RUNNER_VERSION=2.321.0
ARG TERRAFORM_VERSION=1.9.8
ARG KUBECTL_VERSION=1.32.0
ARG HELM_VERSION=3.16.3
ARG FLUX_VERSION=2.4.0
ARG KUBECONFORM_VERSION=0.6.7
ARG KYVERNO_VERSION=1.13.0
ARG ACTIONLINT_VERSION=1.7.4
ARG TRIVY_VERSION=0.58.0

# Prevent interactive prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install base dependencies
RUN apt-get update && apt-get install -y \
    curl \
    wget \
    git \
    jq \
    unzip \
    zip \
    gnupg \
    lsb-release \
    ca-certificates \
    software-properties-common \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3 \
    python3-pip \
    python3-venv \
    sudo \
    apt-transport-https \
    && rm -rf /var/lib/apt/lists/*

# Install Docker CLI (multi-arch)
RUN ARCH=$(dpkg --print-architecture) \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg \
    && echo "deb [arch=${ARCH} signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# Install AWS CLI v2 (multi-arch)
RUN ARCH=$(uname -m) \
    && if [ "$ARCH" = "aarch64" ]; then AWS_ARCH="aarch64"; else AWS_ARCH="x86_64"; fi \
    && curl -sL "https://awscli.amazonaws.com/awscli-exe-linux-${AWS_ARCH}.zip" -o "awscliv2.zip" \
    && unzip -q awscliv2.zip \
    && ./aws/install \
    && rm -rf aws awscliv2.zip

# Install eksctl (multi-arch)
RUN ARCH=$(uname -m) \
    && if [ "$ARCH" = "aarch64" ]; then EKSCTL_ARCH="arm64"; else EKSCTL_ARCH="amd64"; fi \
    && curl -sLO "https://github.com/eksctl-io/eksctl/releases/latest/download/eksctl_Linux_${EKSCTL_ARCH}.tar.gz" \
    && tar xzf eksctl_Linux_${EKSCTL_ARCH}.tar.gz -C /usr/local/bin \
    && rm eksctl_Linux_${EKSCTL_ARCH}.tar.gz

# Install Terraform (multi-arch)
RUN ARCH=$(uname -m) \
    && if [ "$ARCH" = "aarch64" ]; then TF_ARCH="arm64"; else TF_ARCH="amd64"; fi \
    && curl -sLO "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${TF_ARCH}.zip" \
    && unzip -q terraform_${TERRAFORM_VERSION}_linux_${TF_ARCH}.zip -d /usr/local/bin \
    && rm terraform_${TERRAFORM_VERSION}_linux_${TF_ARCH}.zip

# Install kubectl (multi-arch)
RUN ARCH=$(uname -m) \
    && if [ "$ARCH" = "aarch64" ]; then K8S_ARCH="arm64"; else K8S_ARCH="amd64"; fi \
    && curl -sLO "https://dl.k8s.io/release/v${KUBECTL_VERSION}/bin/linux/${K8S_ARCH}/kubectl" \
    && chmod +x kubectl \
    && mv kubectl /usr/local/bin/

# Install Helm (multi-arch)
RUN ARCH=$(uname -m) \
    && if [ "$ARCH" = "aarch64" ]; then HELM_ARCH="arm64"; else HELM_ARCH="amd64"; fi \
    && curl -sL "https://get.helm.sh/helm-v${HELM_VERSION}-linux-${HELM_ARCH}.tar.gz" | tar xz \
    && mv linux-${HELM_ARCH}/helm /usr/local/bin/ \
    && rm -rf linux-${HELM_ARCH}

# Install Flux CLI (multi-arch)
RUN ARCH=$(uname -m) \
    && if [ "$ARCH" = "aarch64" ]; then FLUX_ARCH="arm64"; else FLUX_ARCH="amd64"; fi \
    && curl -sL "https://github.com/fluxcd/flux2/releases/download/v${FLUX_VERSION}/flux_${FLUX_VERSION}_linux_${FLUX_ARCH}.tar.gz" | tar xz \
    && mv flux /usr/local/bin/

# Install kubeconform (multi-arch)
RUN ARCH=$(uname -m) \
    && if [ "$ARCH" = "aarch64" ]; then KC_ARCH="arm64"; else KC_ARCH="amd64"; fi \
    && curl -sL "https://github.com/yannh/kubeconform/releases/download/v${KUBECONFORM_VERSION}/kubeconform-linux-${KC_ARCH}.tar.gz" | tar xz -C /usr/local/bin

# Install Kyverno CLI (multi-arch)
RUN ARCH=$(uname -m) \
    && if [ "$ARCH" = "aarch64" ]; then KY_ARCH="arm64"; else KY_ARCH="x86_64"; fi \
    && curl -sL "https://github.com/kyverno/kyverno/releases/download/v${KYVERNO_VERSION}/kyverno-cli_v${KYVERNO_VERSION}_linux_${KY_ARCH}.tar.gz" | tar xz -C /usr/local/bin kyverno

# Install actionlint (multi-arch)
RUN ARCH=$(uname -m) \
    && if [ "$ARCH" = "aarch64" ]; then AL_ARCH="arm64"; else AL_ARCH="amd64"; fi \
    && curl -sL "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_linux_${AL_ARCH}.tar.gz" | tar xz -C /usr/local/bin actionlint

# Install Trivy (multi-arch)
RUN ARCH=$(uname -m) \
    && if [ "$ARCH" = "aarch64" ]; then TRIVY_ARCH="ARM64"; else TRIVY_ARCH="64bit"; fi \
    && curl -sL "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-${TRIVY_ARCH}.tar.gz" | tar xz -C /usr/local/bin trivy

# Install GitHub CLI (multi-arch)
RUN ARCH=$(dpkg --print-architecture) \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=${ARCH} signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages for CI (pinned for reproducible builds)
RUN pip3 install --no-cache-dir \
    yamllint==1.35.1 \
    gitlint==0.19.1 \
    pytest==8.3.4

# Create runner user
RUN useradd -m -s /bin/bash runner \
    && usermod -aG sudo runner \
    && echo "runner ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# Add runner to docker group (will be created if mounting docker socket)
RUN groupadd -g 999 docker || true \
    && usermod -aG docker runner || true

# Switch to runner user
USER runner
WORKDIR /home/runner

# Download and extract GitHub Actions runner (multi-arch)
RUN ARCH=$(uname -m) \
    && if [ "$ARCH" = "aarch64" ]; then RUNNER_ARCH="arm64"; else RUNNER_ARCH="x64"; fi \
    && curl -sL "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz" | tar xz

# Copy entrypoint script
COPY --chown=runner:runner entrypoint.sh /home/runner/entrypoint.sh
RUN chmod +x /home/runner/entrypoint.sh

# Environment variables (to be overridden at runtime)
ENV GITHUB_REPOSITORY=your-org/infra-fleet
ENV RUNNER_NAME=docker-runner
ENV RUNNER_LABELS=self-hosted,Linux,docker

ENTRYPOINT ["/home/runner/entrypoint.sh"]
