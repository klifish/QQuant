# syntax=docker/dockerfile:1
# 用 DaoCloud 代理拉基础镜像：国内服务器访问 Docker Hub 官方源超时，
# 阿里云个人版加速器对公共镜像返回 not found；DaoCloud 代理可正常拉取。
FROM docker.m.daocloud.io/library/python:3.11-slim

# numpy/pandas 部分 C 扩展需要 gcc；vectorbt 运行期需要 libgomp1。
# 先把 Debian 源换成阿里云镜像加速 apt（兼容 deb822 新格式与传统 sources.list）。
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list 2>/dev/null || true; \
    apt-get update && apt-get install -y --no-install-recommends \
        gcc libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖：requirements.txt 不变时此层走缓存
# 用阿里云 PyPI 镜像，国内服务器构建更快、更稳
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ \
        -r requirements.txt

# 仅拷贝源码；data/ logs/ reports/ .env 由 .dockerignore 排除，运行时挂载进来
COPY src/ src/
COPY scripts/ scripts/
COPY config.yaml .

# 运行时目录（实际内容来自宿主机 bind mount）
RUN mkdir -p data logs reports/daily reports/backtests

# 批处理容器：每次 cron 启动一个临时容器跑完即退，无常驻进程，无需 CMD。
# 以 root 运行以避免 bind mount 的宿主/容器 uid 权限匹配问题——
# 容器命名空间已提供主要隔离边界，对自用批处理可接受。
