#!/usr/bin/env bash
# QQuant 服务器一键初始化脚本（Docker 版）
# 在公用服务器（Ubuntu 22.04）上以 root 运行。
#
# 用法：
#   bash deploy/setup.sh
#
# 完成后下一步：
#   1. 编辑 /opt/qquant/.env 填入真实 TUSHARE_TOKEN
#   2. 上传 database.sqlite 到 /opt/qquant/data/（或在服务器全量下载）
#   3. crontab /opt/qquant/deploy/crontab.template

set -euo pipefail

INSTALL_DIR="/opt/qquant"
# 公开仓库：https 直接拉取，无需任何认证
REPO_URL="https://github.com/klifish/QQuant.git"

# 不修改整机时区（公用服务器）。容器内时区由 docker-compose 的 TZ 控制，
# cron 触发时间由 crontab 里的 CRON_TZ 控制，均不影响宿主机其他程序。

echo "=== [1/4] 安装 Docker Engine ==="
if ! command -v docker >/dev/null 2>&1; then
    apt-get update -y
    apt-get install -y --no-install-recommends ca-certificates curl gnupg git
    install -m 0755 -d /etc/apt/keyrings
    # 用阿里云镜像源：国内服务器访问 download.docker.com 常被连接重置
    curl -fsSL https://mirrors.aliyun.com/docker-ce/linux/ubuntu/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://mirrors.aliyun.com/docker-ce/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list
    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

    # 配置镜像加速器：国内服务器从 Docker Hub 拉基础镜像（python:3.11-slim）
    # 常超时/被重置。以下为公共加速地址，时效性较强——
    # 强烈建议替换为你的阿里云专属地址（控制台→容器镜像服务→镜像加速器，每账号免费）。
    mkdir -p /etc/docker
    cat > /etc/docker/daemon.json <<'JSON'
{
  "registry-mirrors": [
    "https://lvwlpca1.mirror.aliyuncs.com",
    "https://docker.m.daocloud.io"
  ]
}
JSON
    systemctl enable docker && systemctl restart docker
else
    echo "Docker 已安装，跳过（如拉基础镜像超时，请自行在 /etc/docker/daemon.json 配置 registry-mirrors）"
fi

echo "=== [2/4] 克隆仓库 ==="
if [ -d "${INSTALL_DIR}/.git" ]; then
    echo "仓库已存在，拉取最新代码..."
    git -C "${INSTALL_DIR}" pull --ff-only
else
    git clone "${REPO_URL}" "${INSTALL_DIR}"
fi

echo "=== [3/4] 创建运行时目录（bind mount 挂载点）==="
cd "${INSTALL_DIR}"
mkdir -p data logs reports/daily reports/backtests

echo "=== [4/4] 生成 .env 模板 ==="
if [ ! -f .env ]; then
    cat > .env <<'ENVEOF'
TUSHARE_TOKEN=REPLACE_WITH_YOUR_TOKEN
# ACR 镜像完整地址（由 GitHub Actions 推送），形如：
# QQUANT_IMAGE=crpi-xxxx.cn-hangzhou.personal.cr.aliyuncs.com/<命名空间>/qquant:latest
QQUANT_IMAGE=REPLACE_WITH_ACR_IMAGE
ENVEOF
    chmod 600 .env
    echo ">>> 已创建 ${INSTALL_DIR}/.env —— 请编辑填入 TUSHARE_TOKEN 与 QQUANT_IMAGE"
else
    echo ">>> .env 已存在，跳过"
fi
chmod +x "${INSTALL_DIR}"/deploy/*.sh

echo ""
echo "================================================================"
echo " 服务器初始化完成（镜像不在此构建，由 GitHub Actions 推送到 ACR）"
echo "================================================================"
echo " 1. 填配置:       nano ${INSTALL_DIR}/.env   # TUSHARE_TOKEN + QQUANT_IMAGE"
echo " 2. 在 GitHub 触发 Build & Deploy，镜像构建后会自动推到 ACR 并在此拉取"
echo " 3. 准备数据库:   cd ${INSTALL_DIR} && docker compose run --rm qquant python scripts/download_data.py"
echo " 4. 验证数据:     docker compose run --rm qquant python scripts/validate_data.py"
echo " 5. 安装定时任务: crontab ${INSTALL_DIR}/deploy/crontab.template"
echo "================================================================"
