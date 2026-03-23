# ZOLT — Free Cloud Deployment Guide

Complete step-by-step instructions for deploying ZOLT to **Oracle Cloud Always Free Tier** with **K3s** (lightweight Kubernetes) and activating the **GitHub Actions CI/CD** pipeline.

> **Cost: $0/month.** Everything in this guide uses permanently free tiers.

---

## Table of Contents

1. [Oracle Cloud Account Setup](#1-oracle-cloud-account-setup)
2. [Provision the ARM Compute Instance](#2-provision-the-arm-compute-instance)
3. [Server Initial Setup](#3-server-initial-setup)
4. [Install K3s](#4-install-k3s)
5. [Install Docker](#5-install-docker)
6. [Push Docker Images to Docker Hub](#6-push-docker-images-to-docker-hub)
7. [Deploy ZOLT to K3s](#7-deploy-zolt-to-k3s)
8. [Configure GitHub Actions CI/CD](#8-configure-github-actions-cicd)
9. [Set Up Domain & HTTPS (Optional)](#9-set-up-domain--https-optional)
10. [Install Grafana](#10-install-grafana)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Oracle Cloud Account Setup

### 1.1 — Create a Free Account

1. Go to [cloud.oracle.com/free](https://cloud.oracle.com/free)
2. Click **"Start for free"**
3. Fill in your details — a credit card is required for verification but **you will NOT be charged**
4. Select your **Home Region** (choose the closest to you — this cannot be changed later)
5. Wait for the account to be provisioned (~5 minutes)

> ⚠️ **Important:** Oracle gives you **Always Free** resources that never expire. The free tier includes:
> - **4 ARM Ampere A1 cores** (can be split across instances)
> - **24 GB RAM** total
> - **200 GB block storage**
> - **10 TB/month outbound data**

---

## 2. Provision the ARM Compute Instance

### 2.1 — Create the VM

1. Log into the **OCI Console** → **Compute** → **Instances** → **Create Instance**

2. **Name:** `zolt-server`

3. **Image:** Click **"Edit"** → **"Change image"** → Select **Canonical Ubuntu 22.04** (ARM build)

4. **Shape:** Click **"Change shape"** →
   - Shape series: **Ampere**
   - Shape: **VM.Standard.A1.Flex**
   - OCPUs: **4** (or fewer — 4 is the free max)
   - Memory: **24 GB** (or fewer — 24 is the free max)

5. **Networking:**
   - Use the default VCN or create a new one
   - Ensure **"Assign a public IPv4 address"** is selected

6. **SSH Key:**
   - Select **"Generate a key pair"** and **download both keys**, OR
   - Select **"Upload public key"** if you already have an SSH key:
     ```bash
     # Generate one if you don't have it
     ssh-keygen -t ed25519 -C "zolt-server" -f ~/.ssh/zolt_oci
     ```

7. **Boot volume:** Leave default (46.6 GB is fine, you can expand up to 200 GB free)

8. Click **"Create"** and wait for the instance to be **RUNNING**

9. **Copy the Public IP** from the instance details page

### 2.2 — Open Firewall Ports (Security List)

1. Go to **Networking** → **Virtual Cloud Networks** → Click your VCN
2. Click the **public subnet** → Click the **Security List**
3. **Add Ingress Rules:**

| Source CIDR    | Protocol | Dest Port | Description        |
|---------------|----------|-----------|-------------------|
| `0.0.0.0/0`  | TCP      | 80        | HTTP              |
| `0.0.0.0/0`  | TCP      | 443       | HTTPS             |
| `0.0.0.0/0`  | TCP      | 6443      | K3s API (kubectl) |
| `0.0.0.0/0`  | TCP      | 8000      | Backend (temp)    |
| `0.0.0.0/0`  | TCP      | 3001      | Grafana (temp)    |

---

## 3. Server Initial Setup

### 3.1 — SSH Into the Server

```bash
ssh -i ~/.ssh/zolt_oci ubuntu@<YOUR_PUBLIC_IP>
```

### 3.2 — Update and Install Essentials

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y curl git ufw

# Open firewall ports on the OS level (OCI also has its own)
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 6443 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 3001 -j ACCEPT

# Persist iptables rules across reboots
sudo apt install -y iptables-persistent
sudo netfilter-persistent save
```

---

## 4. Install K3s

K3s is a production-ready, lightweight Kubernetes distribution perfect for this setup.

### 4.1 — Install K3s (Single Node)

```bash
curl -sfL https://get.k3s.io | sh -
```

That's it. K3s is installed and running. Verify:

```bash
# Check the node is ready
sudo kubectl get nodes

# Expected output:
# NAME          STATUS   ROLES                  AGE   VERSION
# zolt-server   Ready    control-plane,master   1m    v1.30.x+k3s1
```

### 4.2 — Set Up kubectl for Your User

```bash
# Copy the kubeconfig so you don't need sudo
mkdir -p ~/.kube
sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config
sudo chown $(id -u):$(id -g) ~/.kube/config
export KUBECONFIG=~/.kube/config

# Add to bashrc so it persists
echo 'export KUBECONFIG=~/.kube/config' >> ~/.bashrc
```

### 4.3 — Extract Kubeconfig for CI/CD (You'll Need This Later)

```bash
# Display the kubeconfig — you'll paste this into GitHub Secrets
sudo cat /etc/rancher/k3s/k3s.yaml
```

**Important:** In the output, replace `server: https://127.0.0.1:6443` with:
```
server: https://<YOUR_PUBLIC_IP>:6443
```

Save this modified YAML — you'll paste it into GitHub Secrets in Step 8.

---

## 5. Install Docker

Docker is needed on the server to build images (optional if using CI/CD only):

```bash
# Install Docker
curl -fsSL https://get.docker.com | sh

# Add your user to the docker group
sudo usermod -aG docker $USER

# Log out and back in for group changes to take effect
exit
ssh -i ~/.ssh/zolt_oci ubuntu@<YOUR_PUBLIC_IP>

# Verify
docker --version
```

---

## 6. Push Docker Images to Docker Hub

### 6.1 — Create Docker Hub Account (Free)

1. Go to [hub.docker.com](https://hub.docker.com)
2. Sign up for a free account
3. Create two repositories:
   - `yourusername/zolt-backend`
   - `yourusername/zolt-frontend`

### 6.2 — Build and Push (From Your Local Machine)

```bash
cd /path/to/ZOLT

# Log in to Docker Hub
docker login

# Build and push backend
docker build -t yourusername/zolt-backend:latest -f backend/Dockerfile .
docker push yourusername/zolt-backend:latest

# Build and push frontend
docker build -t yourusername/zolt-frontend:latest -f frontend/Dockerfile frontend/
docker push yourusername/zolt-frontend:latest
```

---

## 7. Deploy ZOLT to K3s

### 7.1 — Create Kubernetes Secrets (On the Server)

SSH into the server and create secrets for your API keys:

```bash
kubectl create secret generic zolt-secrets \
  --from-literal=DEEPSEEK_API_KEY='your_deepseek_key_here' \
  --from-literal=GITHUB_TOKEN='your_github_pat_here' \
  --from-literal=DEEPSEEK_MODEL='deepseek-chat' \
  --from-literal=ZOLT_DB_PATH='data/zolt_evals.db'
```

### 7.2 — Update Image Names in K8s Manifests

On your local machine, edit the K8s manifests to use your Docker Hub username:

```bash
# In k8s/backend-deployment.yaml, change:
#   image: yourdockerhub/zolt-backend:latest
# To:
#   image: youractualusername/zolt-backend:latest

# Same for k8s/frontend-deployment.yaml
```

### 7.3 — Copy Manifests to Server and Apply

```bash
# From your local machine
scp -i ~/.ssh/zolt_oci -r k8s/ ubuntu@<YOUR_PUBLIC_IP>:~/zolt-k8s/

# On the server
ssh -i ~/.ssh/zolt_oci ubuntu@<YOUR_PUBLIC_IP>
kubectl apply -f ~/zolt-k8s/

# Watch the pods come up
kubectl get pods -w

# Expected output (after ~1-2 minutes):
# NAME                              READY   STATUS    RESTARTS   AGE
# zolt-backend-xxx-yyy              1/1     Running   0          60s
# zolt-frontend-xxx-yyy             1/1     Running   0          55s
# prometheus-xxx-yyy                1/1     Running   0          55s
```

### 7.4 — Verify the Deployment

```bash
# Check services
kubectl get svc

# Test backend health (from the server)
curl http://localhost:8000/api/health

# Expected: {"status":"healthy","version":"1.0.0","mcp_servers":[...]}
```

From your browser, visit:
- **Frontend:** `http://<YOUR_PUBLIC_IP>`
- **Backend API:** `http://<YOUR_PUBLIC_IP>/api/health`

---

## 8. Configure GitHub Actions CI/CD

This makes every push to `main` automatically build, push, and deploy.

### 8.1 — Add GitHub Repository Secrets

Go to your GitHub repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Secret Name            | Value                                                   |
|------------------------|---------------------------------------------------------|
| `DOCKER_HUB_USERNAME`  | Your Docker Hub username                               |
| `DOCKER_HUB_TOKEN`     | Docker Hub access token (Hub → Account Settings → Security → New Access Token) |
| `K3S_KUBECONFIG`       | The full kubeconfig YAML from Step 4.3 (with public IP) |

### 8.2 — Test the Pipeline

```bash
# Make any change and push
git add .
git commit -m "feat: initial ZOLT platform scaffold"
git push origin main
```

Go to your repo → **Actions** tab → Watch the pipeline:
1. ✅ **test** — Lint + build
2. ✅ **build** — Docker images pushed to Hub
3. ✅ **deploy** — `kubectl apply` to your K3s cluster

From now on, **every push to `main` auto-deploys** to your Oracle Cloud server.

---

## 9. Set Up Domain & HTTPS (Optional)

### 9.1 — Free Domain Options

- **Freenom:** `.tk`, `.ml`, `.cf` domains (free)
- **DuckDNS:** Free dynamic DNS subdomains `yourname.duckdns.org`
- **No-IP:** Free hostnames

### 9.2 — Point DNS to Your Server

Create an **A record** pointing to your Oracle Cloud public IP:
```
zolt.yourdomain.com → <YOUR_PUBLIC_IP>
```

### 9.3 — Install cert-manager for HTTPS

```bash
# Install cert-manager
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.15.0/cert-manager.yaml

# Wait for it to be ready
kubectl -n cert-manager wait --for=condition=ready pod -l app.kubernetes.io/instance=cert-manager --timeout=120s
```

Create a Let's Encrypt ClusterIssuer:

```bash
cat <<EOF | kubectl apply -f -
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: your-email@example.com
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
      - http01:
          ingress:
            class: traefik
EOF
```

Update `k8s/ingress.yaml` to use TLS:

```yaml
metadata:
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
spec:
  tls:
    - hosts:
        - zolt.yourdomain.com
      secretName: zolt-tls
```

Apply and you'll have free auto-renewing HTTPS.

---

## 10. Install Grafana

Grafana is already defined in `docker-compose.yml` for local dev. For K3s:

```bash
cat <<'EOF' | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: grafana
spec:
  replicas: 1
  selector:
    matchLabels:
      app: grafana
  template:
    metadata:
      labels:
        app: grafana
    spec:
      containers:
        - name: grafana
          image: grafana/grafana:11.0.0
          ports:
            - containerPort: 3000
          env:
            - name: GF_SECURITY_ADMIN_PASSWORD
              value: "admin"
            - name: GF_AUTH_ANONYMOUS_ENABLED
              value: "true"
---
apiVersion: v1
kind: Service
metadata:
  name: grafana
spec:
  selector:
    app: grafana
  ports:
    - port: 3001
      targetPort: 3000
  type: ClusterIP
EOF
```

Then add a Prometheus data source in Grafana:
1. Open Grafana (`http://<YOUR_PUBLIC_IP>:3001`, login: `admin`/`admin`)
2. **Configuration** → **Data Sources** → **Add data source** → **Prometheus**
3. URL: `http://prometheus:9090`
4. Click **Save & Test**

---

## 11. Troubleshooting

### Pods stuck in `ImagePullBackOff`

```bash
# Check what's wrong
kubectl describe pod <pod-name>

# Usually means Docker Hub image name is wrong, or the repo is private
# Fix: make sure your Docker Hub repos are PUBLIC
```

### Pod crash loops

```bash
# Check logs
kubectl logs <pod-name> --tail=50

# Common: missing API key in secrets
kubectl get secret zolt-secrets -o yaml
```

### Can't access from browser

```bash
# 1. Check OCI security list has the port open
# 2. Check OS-level iptables
sudo iptables -L INPUT -n --line-numbers

# 3. Check the K3s ingress controller (Traefik)
kubectl get svc -n kube-system
```

### K3s kubectl not working

```bash
# Make sure KUBECONFIG is set
export KUBECONFIG=~/.kube/config

# Check K3s service status
sudo systemctl status k3s
```

### Re-deploy after changes

```bash
# If you made changes and pushed to Docker Hub manually:
kubectl rollout restart deployment/zolt-backend
kubectl rollout restart deployment/zolt-frontend
```

---

## Quick Reference

| What                 | URL / Command                              |
|---------------------|--------------------------------------------|
| SSH into server     | `ssh -i ~/.ssh/zolt_oci ubuntu@<IP>`       |
| Frontend            | `http://<IP>`                              |
| Backend API         | `http://<IP>/api/health`                    |
| Prometheus          | `http://<IP>:9090`                          |
| Grafana             | `http://<IP>:3001`                          |
| Check pods          | `kubectl get pods`                          |
| View logs           | `kubectl logs deploy/zolt-backend -f`       |
| Restart backend     | `kubectl rollout restart deploy/zolt-backend` |
| CI/CD status        | GitHub repo → Actions tab                   |
