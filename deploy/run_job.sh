#!/usr/bin/env bash
# QQuant 定时任务统一入口，由 cron 调用（Docker 版）。
# 用法: run_job.sh <download|validate|daily_report>
#
# 每次启动一个临时容器跑完即退。退出码: 0 成功 / 非0 失败。

set -uo pipefail

JOB="${1:-}"
DIR="/opt/qquant"
LOG_DIR="${DIR}/logs"
TS=$(TZ=Asia/Shanghai date +%Y%m%d_%H%M)
mkdir -p "${LOG_DIR}"

case "${JOB}" in
  download)     CMD="scripts/download_data.py --incremental" ;;
  validate)     CMD="scripts/validate_data.py" ;;
  daily_report) CMD="scripts/daily_report.py" ;;
  *)
    echo "用法: run_job.sh download|validate|daily_report" >&2
    exit 1
    ;;
esac

LOG="${LOG_DIR}/${JOB}_${TS}.log"
NOW() { TZ=Asia/Shanghai date '+%F %T'; }
echo "=== ${JOB} 开始 $(NOW) ===" | tee "${LOG}"

# -f 指定 compose 文件，使 cron 无论 cwd 在哪都能正确解析 bind mount 相对路径
docker compose -f "${DIR}/docker-compose.yml" run --rm qquant \
    python ${CMD} >> "${LOG}" 2>&1
CODE=$?

if [ ${CODE} -eq 0 ]; then
  echo "=== SUCCESS $(NOW) ===" | tee -a "${LOG}"
else
  echo "=== FAILURE 退出码 ${CODE} $(NOW) ===" | tee -a "${LOG}"
  # 可选告警：取消注释，并在 .env 配置 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
  # set -a; source "${DIR}/.env"; set +a
  # curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  #   -d "chat_id=${TELEGRAM_CHAT_ID}" \
  #   -d "text=QQuant ${JOB} 失败 (退出码 ${CODE}) $(NOW)"
fi

exit ${CODE}
