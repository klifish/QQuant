# 通过 GitHub Actions 间接操作部署服务器

本文记录一种**不直接持有服务器凭据**、仅借助 GitHub Actions 远程驱动部署服务器的方法。
适用场景：开发环境（如 codespace、本地）拿不到服务器 SSH 私钥，但需要在服务器上
查看数据、跑批处理任务、临时验证修复版代码。

## 背景与前提

- 服务器连接信息存在 GitHub 仓库的 **Environment（名为 `server`）** 里：
  - `vars.SERVER_HOST` / `vars.SERVER_USER` / `vars.SERVER_PORT`（Environment variables）
  - `secrets.SERVER_SSH_KEY`（Environment secret，SSH 私钥）
- 这些只有 Actions runner 在运行时能读到，**开发环境读不到**，因此无法本地直连。
- 仓库已有 `deploy.yml` / `verify-server.yml` 用 `appleboy/ssh-action` 走这套机制，
  本方法只是复用同一套凭据。

## 整体链路

```
开发环境(codespace)                GitHub                         部署服务器
       │  gh push / 触发              │                                │
       ├────────────────────────────▶│  Actions runner                │
       │                             │  ── SSH(用 server secrets) ──▶ │ docker compose run ...
       │                             │                                │ （读真实数据/产出文件）
       │  gh run view --log          │  ◀── 收集服务器 stdout ────────┤
       ◀─────────────────────────────┤                                │
```

要点：**我方不接触服务器凭据**；所有操作都体现为一次可审计的 workflow run，日志可回溯。

## 步骤

### 1. 写一个 workflow，用 ssh-action 在服务器上执行命令

```yaml
name: Run Server Jobs
on:
  workflow_dispatch:        # 手动触发（要求文件在默认分支）
  push:
    branches: [chore/inspect-server]   # 推到该分支即自动触发（见下方“触发坑”）

jobs:
  run:
    runs-on: ubuntu-latest
    environment: server      # 关键：声明用 server 环境，才能读到其 vars/secrets
    steps:
      - uses: appleboy/ssh-action@v1.0.3
        with:
          host: ${{ vars.SERVER_HOST }}
          username: ${{ vars.SERVER_USER }}
          key: ${{ secrets.SERVER_SSH_KEY }}
          port: ${{ vars.SERVER_PORT }}
          command_timeout: "120m"   # 长任务务必加大，默认会过早杀进程
          script: |
            set -uo pipefail
            DIR="/opt/qquant"
            cd "$DIR"
            docker compose -f "$DIR/docker-compose.yml" run --rm -T qquant \
              python scripts/run_backtest.py --start 20160101 --end 20260626
```

### 2. 触发它（注意默认分支的坑）

`workflow_dispatch` 通过 `gh workflow run` 触发时，要求该 workflow **已存在于默认分支**，
否则报 `HTTP 404: workflow not found on the default branch`。若不想/不能直接推 main，
改用 **`on: push` 触发某个专用分支**，往该分支 push 即自动跑：

```bash
git checkout -b chore/inspect-server
git add .github/workflows/run-server-jobs.yml
git commit -m "..."
git push -u origin chore/inspect-server      # push 即触发
```

### 3. 拉回结果并轮询状态

服务器的 stdout 被 runner 收进 Actions 日志：

```bash
# 找到最近一次 run 的 id
run_id=$(gh run list --workflow=run-server-jobs.yml --limit 1 --json databaseId -q '.[0].databaseId')

# 轮询状态（长任务）
gh run view "$run_id" --json status,conclusion -q '{s:.status,c:.conclusion}'

# 跑完后取日志
gh run view "$run_id" --log
```

> 提示：`gh run watch` 会一直阻塞到结束，对超长任务不友好；用一个 `sleep`+`gh run view --json status`
> 的轮询循环更可控。

### 4. 关键技巧：不重建镜像就跑“改过的代码”

服务器上的源码是**打进 Docker 镜像**的（通常落后于 main），而在国内重建镜像又慢又易失败。
若只想临时验证某个修复版文件，不必重建镜像、也不要改动服务器上部署的代码——
用 `git show` 把目标文件写到服务器临时目录，再用 `docker compose run -v` **bind mount 覆盖**进容器：

```bash
BR=chore/inspect-server
git -C "$DIR" fetch origin "$BR"
git -C "$DIR" show "origin/$BR:src/backtester.py"      > /tmp/backtester_fixed.py
git -C "$DIR" show "origin/$BR:scripts/run_backtest.py" > /tmp/run_backtest_fixed.py

docker compose -f "$DIR/docker-compose.yml" run --rm -T \
  -v /tmp/backtester_fixed.py:/app/src/backtester.py \
  -v /tmp/run_backtest_fixed.py:/app/scripts/run_backtest.py \
  qquant python scripts/run_backtest.py --start 20160101 --end 20260626
```

容器跑完即弃，**镜像、部署代码、git 工作区都不受影响**。验证通过后再走正常 PR → tag → 部署流程把修复落地。

## 安全与边界

- 凭据始终留在 GitHub Environment 里，开发侧零接触；每次操作 = 一次可审计的 run。
- 只读诊断 workflow 不写任何数据；跑批处理时注意区分：哪些会写 bind mount（如 `reports/`），
  哪些会动数据库——按需控制。
- 临时分支 + 临时 workflow 属于“脚手架”，用完应清理：保留有用的代码修复（走 PR 合 main），
  删除临时分支与临时 workflow，避免 `on: push` 触发器留在仓库里误触发。

## 本仓库里的实例

- `inspect-server.yml`（只读诊断：dump 数据库/报告/cron/日志状态）
- `run-server-jobs.yml`（跑回测 + 生成日报，bind mount 覆盖修复版代码）

> 上述两个为一次性脚手架 workflow，验证完成后已随临时分支一并清理；此处仅作示例留档。
