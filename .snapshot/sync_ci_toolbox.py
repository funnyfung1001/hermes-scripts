#!/usr/bin/env python3
"""sync_ci_toolbox.py — C&I 工具箱同步

由 cron_runner.sh sync-toolbox 调度（每天5:00）。
从飞书 Bitable 拉取 5 张表的数据，写入本地。
"""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config_shared import setup_logger, HERMES, lark_cli_user

logger = setup_logger("sync_ci", "sync_ci_toolbox.log")

CI_BASE_TOKEN = "Py5Gb5LC1arDxKsy5JucqlBwn1e"
CI_TABLES = {
    "products": "tblSxaEPudUA1fLy",
    "supporting": "tblDBaZzmqtehkDQ",
    "market": "tblSxpN1fGjiveWU",
    "technical": "tblelSWa9KXUprT5",
    "change_log": "tblQoNUzmHVENCJ4",
}

def sync_table(name, table_id):
    """同步单张 Bitable 表"""
    path = f"open-apis/bitable/v1/apps/{CI_BASE_TOKEN}/tables/{table_id}/records"
    result = lark_cli_user("GET", path, timeout=60)
    if isinstance(result, dict) and "error" in result:
        logger.error(f"Table {name} failed: {result['error']}")
        return False
    
    # 存本地
    data_dir = HERMES / "data" / "ci_knowledge"
    data_dir.mkdir(parents=True, exist_ok=True)
    out = data_dir / f"{name}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    logger.info(f"Synced {name}: {out}")
    return True

def main():
    logger.info("C&I toolbox sync start")
    ok = 0
    for name, tid in CI_TABLES.items():
        if sync_table(name, tid):
            ok += 1
    logger.info(f"Synced {ok}/{len(CI_TABLES)} tables")
    return 0 if ok > 0 else 1

if __name__ == "__main__":
    sys.exit(main())
