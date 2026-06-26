#!/usr/bin/env bash
# QQuant 服务器一键初始化脚本
# 在全新的阿里云 ECS / 腾讯云 CVM（Ubuntu 22.04）上以 root 运行。
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
REPO_URL="https://github.com/klifish/QQuant.git"

echo "=== [1/6] 设置时区为 Asia/Shanghai ==="
timedatectl set-timezone Asia/Shanghai || true

echo "=== [2/6] 安装 Python 3.11 与编译依赖 ==="
apt-get update -y
apt-get install -y --no-install-recommends software-properties-common
add-apt-repository -y ppa:deadsnakes/ppa
apt-get update -y
apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3.11-dev gcc git curl

echo "=== [3/6] 克隆仓库 ==="
if [ -d "${INSTALL_DIR}/.git" ]; then
    echo "仓库已存在，拉取最新代码..."
    git -C "${INSTALL_DIR}" pull --ff-only
else
    git clone "${REPO_URL}" "${INSTALL_DIR}"
fi

echo "=== [4/6] 创建虚拟环境并安装依赖 ==="
cd "${INSTALL_DIR}"
if [ ! -d ".venv" ]; then
    python3.11 -m venv .venv
fi
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

echo "=== [5/6] 创建运行时目录 ==="
mkdir -p data logs reports/daily reports/backtests

echo "=== [6/6] 生成 .env 模板 ==="
if [ ! -f .env ]; then
    echo "TUSHARE_TOKEN=REPLACE_WITH_YOUR_TOKEN" > .env
    chmod 600 .env
    echo ">>> 已创建 ${INSTALL_DIR}/.env —— 请编辑填入真实 token"
else
    echo ">>> .env 已存在，跳过"
fi

chmod +x "${INSTALL_DIR}"/deploy/*.sh

echo ""
echo "================================================================"
echo " 初始化完成！下一步："
echo "================================================================"
echo " 1. 填入 token:   nano ${INSTALL_DIR}/.env"
echo " 2. 准备数据库（二选一）："
echo "    A) 本地上传:  scp data/database.sqlite root@<本机IP>:${INSTALL_DIR}/data/"
echo "    B) 全量下载:  cd ${INSTALL_DIR} && .venv/bin/python scripts/download_data.py"
echo " 3. 验证数据:     cd ${INSTALL_DIR} && .venv/bin/python scripts/validate_data.py"
echo " 4. 安装定时任务: crontab ${INSTALL_DIR}/deploy/crontab.template"
echo " 5. 手动测试:     ${INSTALL_DIR}/deploy/run_job.sh daily_report"
echo "================================================================"
