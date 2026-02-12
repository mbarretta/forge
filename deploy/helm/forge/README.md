# FORGE Helm Chart

This Helm chart deploys FORGE (Chainguard Field Engineering Toolkit) to Kubernetes.

## Prerequisites

- Kubernetes 1.24+
- Helm 3.8+
- Access to `cgr.dev/chainguard-private` registry
- Redis (in-cluster or external)

## Installation

### Quick Start (Development)

```bash
# Install with default values
helm install forge ./deploy/helm/forge

# Or from repository root
helm install forge ./deploy/helm/forge --namespace forge --create-namespace
```

### Production Deployment

```bash
# Install with production values
helm install forge ./deploy/helm/forge \
  -f deploy/helm/forge/values.prod.yaml \
  --namespace forge-prod \
  --create-namespace
```

### Custom Configuration

```bash
# Override specific values
helm install forge ./deploy/helm/forge \
  --set api.replicas=5 \
  --set worker.autoscaling.maxReplicas=30 \
  --set ingress.hosts[0].host=forge.example.com
```

## Configuration

### Image Registry Authentication

Create a secret for pulling from Chainguard private registry:

```bash
kubectl create secret docker-registry chainguard-registry \
  --docker-server=cgr.dev/chainguard-private \
  --docker-username=<username> \
  --docker-password=<password> \
  --namespace forge
```

Then set in values:

```yaml
image:
  pullSecrets:
    - name: chainguard-registry
```

### External Redis

To use an external Redis instance:

```yaml
redis:
  external:
    enabled: true
    url: "redis://my-redis.database.svc.cluster.local:6379"
```

### Autoscaling

API server autoscaling:

```yaml
api:
  autoscaling:
    enabled: true
    minReplicas: 3
    maxReplicas: 10
    targetCPUUtilization: 70
    targetMemoryUtilization: 80
```

Worker autoscaling:

```yaml
worker:
  autoscaling:
    enabled: true
    minReplicas: 5
    maxReplicas: 20
    targetCPUUtilization: 70
```

### Ingress Configuration

```yaml
ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - host: forge.example.com
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
        - forge.example.com
```

### Resource Limits

Adjust resources for your workload:

```yaml
api:
  resources:
    requests:
      cpu: 500m
      memory: 512Mi
    limits:
      cpu: 2000m
      memory: 1Gi

worker:
  resources:
    requests:
      cpu: 1000m
      memory: 1Gi
    limits:
      cpu: 4000m
      memory: 4Gi
```

## Values

See [values.yaml](values.yaml) for all configurable parameters.

### Key Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `image.registry` | Container registry | `cgr.dev/chainguard-private` |
| `api.replicas` | Number of API pods | `2` |
| `api.autoscaling.enabled` | Enable API autoscaling | `false` |
| `worker.replicas` | Number of worker pods | `3` |
| `worker.autoscaling.enabled` | Enable worker autoscaling | `true` |
| `redis.external.enabled` | Use external Redis | `false` |
| `ingress.enabled` | Enable ingress | `true` |
| `ingress.hosts` | Ingress hostnames | `forge.internal.chainguard.dev` |

## Upgrading

```bash
# Upgrade to new version
helm upgrade forge ./deploy/helm/forge \
  --set api.image.tag=v1.2.3 \
  --set worker.image.tag=v1.2.3 \
  --set ui.image.tag=v1.2.3
```

## Uninstallation

```bash
helm uninstall forge --namespace forge
```

## Health Checks

All pods have liveness and readiness probes:

- **API**: `GET /healthz` (liveness), `GET /readyz` (readiness)
- **UI**: `GET /healthz`
- **Worker**: Python module import check
- **Redis**: `redis-cli ping`

## Security

### Non-Root Containers

All containers run as non-root (UID 65532) by default.

### Read-Only Root Filesystem

Container security context enforces read-only root filesystem with specific writable mounts.

### Network Policies

To enable network policies:

```yaml
networkPolicy:
  enabled: true
```

### Pod Security Standards

Pods comply with restricted Pod Security Standards:
- `runAsNonRoot: true`
- `allowPrivilegeEscalation: false`
- `seccompProfile: RuntimeDefault`
- `capabilities: drop ALL`

## Monitoring

### Metrics

Expose Prometheus metrics by adding annotations:

```yaml
podAnnotations:
  prometheus.io/scrape: "true"
  prometheus.io/port: "8080"
  prometheus.io/path: "/metrics"
```

### Logging

Logs are written to stdout/stderr and can be collected by any Kubernetes logging solution (Fluentd, Loki, etc.).

## Troubleshooting

### Pods not starting

Check image pull secrets:
```bash
kubectl get pods -n forge
kubectl describe pod <pod-name> -n forge
```

### API not accessible

Check ingress configuration:
```bash
kubectl get ingress -n forge
kubectl describe ingress forge -n forge
```

### Worker not processing jobs

Check Redis connectivity:
```bash
kubectl logs -n forge deployment/forge-worker
```

### Database connection issues

Verify Redis service:
```bash
kubectl get svc -n forge
kubectl exec -it deployment/forge-redis -n forge -- redis-cli ping
```

## Support

For issues and questions:
- GitHub Issues: https://github.com/chainguard/forge/issues
- Documentation: https://github.com/chainguard/forge
