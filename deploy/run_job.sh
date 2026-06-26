#!/usr/bin/env bash
# QQuant 定时任务统一入口，由 cron 调用。
# 用法: run_job.sh <download|validate|daily_report>
#
# 退出码: 0 成功 / 非0 失败（cron 会记录到 syslog）

set -uo pipefail

JOB="${1:-}"
DIR="/opt/qquant"
PY="${DIR}/.venv/bin/python"
LOG_DIR="${DIR}/logs"
TS=$(date +%Y%m%d_%H%M)
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
echo "=== ${JOB} 开始 $(date '+%F %T') ===" | tee "${LOG}"

# 关键：cd 到 /opt/qquant —— config.py 的 db_path 与 daily_report.py 的
# reports/daily/ 均锚定仓库根目录。
cd "${DIR}"
${PY} ${CMD} >> "${LOG}" 2>&1
CODE=$?

if [ ${CODE} -eq 0 ]; then
  echo "=== SUCCESS $(date '+%F %T') ===" | tee -a "${LOG}"
else
  echo "=== FAILURE 退出码 ${CODE} $(date '+%F %T') ===" | tee -a "${LOG}"
  # 可选告警：取消注释，并在 .env 配置 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
  # set -a; source "${DIR}/.env"; set +a
  # curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  #   -d "chat_id=${TELEGRAM_CHAT_ID}" \
  #   -d "text=QQuant ${JOB} 失败 (退出码 ${CODE}) $(date '+%F %T')"
fi

exit ${CODE}
