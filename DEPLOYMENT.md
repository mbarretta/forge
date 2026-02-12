# FORGE Deployment Guide

Complete guide for deploying FORGE to production.

## Quick Reference

```bash
# Local development
uv sync
uv run forge

# Docker (production images)
docker compose -f docker-compose.prod.yml up

# Kubernetes
helm install forge ./deploy/helm/forge -f deploy/helm/forge/values.prod.yaml
```

## Architecture Overview

```
                                   ┌─────────────┐
                                   │   Ingress   │
                                   └──────┬──────┘
                                          │
                         ┌────────────────┼────────────────┐
                         │                │                │
                    ┌────▼────┐      ┌────▼────┐     ┌────▼────┐
                    │   UI    │      │   API   │     │  API    │
                    │ (nginx) │      │ (uvicorn)│     │(replica)│
                    └─────────┘      └────┬────┘     └────┬────┘
                                          │                │
                                     ┌────▼────────────────▼────┐
                                     │        Redis             │
                                     │     (job queue)          │
                                     └────┬────────────────┬────┘
                                          │                │
                                     ┌────▼────┐      ┌────▼────┐
                                     │ Worker  │      │ Worker  │
                                     │  (ARQ)  │      │  (ARQ)  │
                                     └─────────┘      └─────────┘
```

## Deployment Modes

### 1. Local Development

**Use when:** Developing plugins or working on FORGE itself

```bash
# Install dependencies
uv sync

# Run CLI
uv run forge hello --name "Test"

# Run API + Worker (requires Redis)
docker run -d -p 6379:6379 redis:7-alpine
uv run forge serve &
uv run arq forge_api.worker.WorkerSettings &

# Run UI
cd packages/forge-ui && npm run dev
```

**Pros:** Fast iteration, easy debugging
**Cons:** Not production-ready, manual setup

### 2. Docker Compose (Local)

**Use when:** Testing full stack locally or simple deployments

```bash
# Development images (faster builds)
docker compose up

# Production images (Chainguard base)
docker compose -f docker-compose.prod.yml up --build
```

**Pros:** Full stack, realistic environment
**Cons:** Not scalable, single host only

### 3. Kubernetes (Production)

**Use when:** Production deployments, high availability needed

```bash
# Install to staging
helm install forge ./deploy/helm/forge \
  --namespace forge-staging \
  --create-namespace

# Install to production
helm install forge ./deploy/helm/forge \
  -f deploy/helm/forge/values.prod.yaml \
  --namespace forge-prod \
  --create-namespace
```

**Pros:** Scalable, HA, production-grade
**Cons:** Requires K8s cluster, more complex

## Kubernetes Deployment

### Prerequisites

1. **Kubernetes cluster** (1.24+)
2. **kubectl** configured
3. **Helm** installed (3.8+)
4. **Container registry** access (`cgr.dev/chainguard-private`)
5. **Redis** (in-cluster or external)
6. **Ingress controller** (nginx recommended)
7. **Cert-manager** (for TLS, optional)

### Step 1: Create Namespace

```bash
kubectl create namespace forge-prod
```

### Step 2: Container Registry Access

```bash
kubectl create secret docker-registry chainguard-registry \
  --docker-server=cgr.dev/chainguard-private \
  --docker-username=$REGISTRY_USER \
  --docker-password=$REGISTRY_TOKEN \
  --namespace forge-prod
```

### Step 3: Configure Values

Create `values.custom.yaml`:

```yaml
image:
  registry: cgr.dev/chainguard-private
  pullSecrets:
    - name: chainguard-registry

api:
  replicas: 3
  autoscaling:
    enabled: true
    maxReplicas: 10

worker:
  replicas: 5
  autoscaling:
    enabled: true
    maxReplicas: 20

redis:
  external:
    enabled: true
    url: "redis://prod-redis.database.svc.cluster.local:6379"

ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - host: forge.yourdomain.com
      paths:
        - path: /api
          pathType: Prefix
          service: api
        - path: /
          pathType: Prefix
          service: ui
  tls:
    - secretName: forge-tls
      hosts:
        - forge.yourdomain.com
```

### Step 4: Install Helm Chart

```bash
helm install forge ./deploy/helm/forge \
  -f values.custom.yaml \
  --namespace forge-prod
```

### Step 5: Verify Deployment

```bash
# Check pods
kubectl get pods -n forge-prod

# Check services
kubectl get svc -n forge-prod

# Check ingress
kubectl get ingress -n forge-prod

# View logs
kubectl logs -n forge-prod deployment/forge-api
kubectl logs -n forge-prod deployment/forge-worker
```

### Step 6: Access FORGE

```bash
# Get ingress URL
kubectl get ingress forge -n forge-prod

# Or port-forward for testing
kubectl port-forward -n forge-prod svc/forge-api 8080:80
```

## Scaling

### Manual Scaling

```bash
# Scale API replicas
kubectl scale deployment forge-api --replicas=5 -n forge-prod

# Scale workers
kubectl scale deployment forge-worker --replicas=10 -n forge-prod
```

### Auto-scaling

API pods scale based on CPU/memory:

```yaml
api:
  autoscaling:
    enabled: true
    minReplicas: 3
    maxReplicas: 10
    targetCPUUtilization: 70
    targetMemoryUtilization: 80
```

Worker pods scale based on CPU:

```yaml
worker:
  autoscaling:
    enabled: true
    minReplicas: 5
    maxReplicas: 20
    targetCPUUtilization: 70
```

## Monitoring

### Health Checks

All components have health endpoints:

```bash
# API health
curl https://forge.yourdomain.com/healthz

# API readiness
curl https://forge.yourdomain.com/readyz

# UI health
curl https://forge.yourdomain.com/healthz
```

### Metrics

Add Prometheus annotations for scraping:

```yaml
podAnnotations:
  prometheus.io/scrape: "true"
  prometheus.io/port: "8080"
  prometheus.io/path: "/metrics"
```

### Logging

All logs go to stdout/stderr. Collect with:
- **Fluentd/Fluent Bit**
- **Loki**
- **CloudWatch** (AWS)
- **Stackdriver** (GCP)

## Upgrading

### Rolling Update

```bash
# Update image tags
helm upgrade forge ./deploy/helm/forge \
  --set api.image.tag=v1.2.0 \
  --set worker.image.tag=v1.2.0 \
  --set ui.image.tag=v1.2.0 \
  --namespace forge-prod
```

### Rollback

```bash
# View history
helm history forge -n forge-prod

# Rollback to previous
helm rollback forge -n forge-prod

# Rollback to specific revision
helm rollback forge 3 -n forge-prod
```

## Backup & Recovery

### Backup

Redis data (if using persistence):

```bash
kubectl exec -n forge-prod forge-redis-0 -- \
  redis-cli BGSAVE

kubectl cp forge-prod/forge-redis-0:/data/dump.rdb \
  ./backup/dump.rdb
```

### Restore

```bash
kubectl cp ./backup/dump.rdb \
  forge-prod/forge-redis-0:/data/dump.rdb

kubectl rollout restart statefulset forge-redis -n forge-prod
```

## Troubleshooting

### Pods CrashLooping

```bash
# Check pod status
kubectl describe pod <pod-name> -n forge-prod

# View logs
kubectl logs <pod-name> -n forge-prod

# Common issues:
# - Image pull errors → check registry secret
# - OOM killed → increase memory limits
# - Redis connection → verify FORGE_REDIS_URL
```

### Jobs Not Processing

```bash
# Check worker logs
kubectl logs -n forge-prod deployment/forge-worker

# Check Redis connectivity
kubectl exec -n forge-prod deployment/forge-worker -- \
  redis-cli -h forge-redis ping

# Verify ARQ is running
kubectl exec -n forge-prod deployment/forge-worker -- \
  ps aux | grep arq
```

### High Latency

```bash
# Check resource usage
kubectl top pods -n forge-prod

# Check HPA status
kubectl get hpa -n forge-prod

# Increase replicas if needed
helm upgrade forge ./deploy/helm/forge \
  --set api.replicas=10 \
  --namespace forge-prod
```

## Security Best Practices

1. **Use Chainguard images** (minimal, verified, signed)
2. **Non-root containers** (UID 65532)
3. **Read-only root filesystem** (with specific writable mounts)
4. **Network policies** (restrict pod-to-pod communication)
5. **Secret management** (use Kubernetes secrets or external vaults)
6. **RBAC** (least privilege service accounts)
7. **Pod Security Standards** (restricted profile)
8. **TLS everywhere** (ingress, internal if needed)
9. **Image scanning** (Trivy in CI/CD)
10. **Dependency updates** (Dependabot automation)

## Cost Optimization

### Right-sizing Resources

Monitor actual usage and adjust:

```yaml
api:
  resources:
    requests:
      cpu: 100m      # Start small
      memory: 128Mi
    limits:
      cpu: 500m      # Allow bursts
      memory: 256Mi
```

### Cluster Autoscaler

Enable for dynamic node scaling:

```bash
# GKE example
gcloud container clusters update <cluster> \
  --enable-autoscaling \
  --min-nodes 1 \
  --max-nodes 10
```

### Spot/Preemptible Instances

Use for workers (fault-tolerant):

```yaml
worker:
  nodeSelector:
    cloud.google.com/gke-preemptible: "true"
  tolerations:
    - key: cloud.google.com/gke-preemptible
      operator: Equal
      value: "true"
      effect: NoSchedule
```

## Production Checklist

- [ ] Registry authentication configured
- [ ] TLS certificates provisioned
- [ ] External Redis configured (HA)
- [ ] Resource limits set appropriately
- [ ] Autoscaling enabled
- [ ] Monitoring/alerting configured
- [ ] Backup strategy implemented
- [ ] Disaster recovery plan documented
- [ ] Security scanning in CI/CD
- [ ] Load testing completed
- [ ] Runbook created for on-call
