import os
import yaml
from pathlib import Path

_ROOT = Path(__file__).parent.parent


def load_config(path: str | None = None) -> dict:
    cfg_path = Path(path) if path else _ROOT / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # Token 优先从环境变量读取
    token = os.environ.get("TUSHARE_TOKEN", "")
    if token:
        cfg["tushare"]["token"] = token

    # db_path 转为绝对路径
    cfg["data"]["db_path"] = str(_ROOT / cfg["data"]["db_path"])

    return cfg


def get_tushare_token(cfg: dict) -> str:
    token = cfg["tushare"].get("token", "")
    if not token:
        raise ValueError(
            "Tushare token 未配置。请设置环境变量 TUSHARE_TOKEN=your_token"
        )
    return token
