"""从健身知识库 xlsx 生成初始语料库（data/corpus/）。

- 每个输出文件是一个主题文档，含 YAML front matter（title/category/source/updated）
- 每条 QA 对应文件内一个 "## 问题" 二级标题段落，后续切分按此为单位
- 用法: .venv/Scripts/python.exe scripts/build_corpus_from_xlsx.py

扩充语料时直接编辑生成的 Markdown 即可，无需重跑本脚本（重跑会覆盖，注意）。
"""

import datetime
import re
import shutil
import sys
from pathlib import Path

from openpyxl import load_workbook

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

XLSX_PATH = Path(r"D:\Desktop\健身知识库.xlsx")
CORPUS_DIR = PROJECT_ROOT / "data" / "corpus"
UPDATED = datetime.date.today().isoformat()

# 主题文档 → xlsx 行号（1-based，含表头行，QA 数据从第 2 行开始到第 86 行）
DOC_PLAN: dict[str, list[int]] = {
    "training/01-训练频率与时长.md": [2, 3, 4, 5, 6, 9],
    "training/02-热身拉伸与酸痛.md": [7, 8, 10, 11],
    "training/03-训练原则与组次安排.md": [24, 25, 26, 27, 28, 33, 34, 68],
    "training/04-动作技术与常见误区.md": [29, 30, 35],
    "training/05-训练计划模板.md": [63, 64, 65, 66, 67],
    "training/06-器械选择.md": [32],
    "cardio/01-有氧运动热量消耗.md": [12, 13, 14, 15, 16],
    "cardio/02-减脂有氧策略与误区.md": [17, 18, 19, 20, 21, 22, 23],
    "nutrition/01-热量计算与蛋白质.md": [36, 37, 38, 39, 52, 85],
    "nutrition/02-碳水脂肪与饮食误区.md": [40, 41, 45, 46, 47],
    "nutrition/03-蛋白粉与补剂饮品.md": [42, 43, 44, 48, 49, 51],
    "fatloss/01-减脂原理与速度.md": [55, 56, 57, 58],
    "fatloss/02-减脂误区与局部减脂.md": [50, 53, 54, 77],
    "muscle/01-增肌原理与策略.md": [59, 60],
    "body/01-体脂测量与效果评估.md": [61, 62, 86],
    "recovery/01-睡眠休息与放松.md": [69, 70, 71],
    "special/01-伤病判断与不适处理.md": [72, 73, 75, 76],
    "special/02-特殊人群与健康状况.md": [31, 74, 78, 79, 81, 82],
    "special/03-生活场景与习惯.md": [80, 83, 84],
}

USED_ROWS = [r for rows in DOC_PLAN.values() for r in rows]
ALL_QA_ROWS = list(range(2, 87))


def slugify(text: str) -> str:
    return re.sub(r"[\\/:*?\"<>|#]", "", text).strip()


def main() -> None:
    ws = load_workbook(XLSX_PATH, read_only=True).worksheets[0]
    rows = list(ws.iter_rows(values_only=True))

    # 校验：映射必须不重不漏地覆盖全部 85 条
    missing = sorted(set(ALL_QA_ROWS) - set(USED_ROWS))
    duplicated = sorted({r for r in USED_ROWS if USED_ROWS.count(r) > 1})
    if missing or duplicated:
        sys.exit(f"行号映射有误 missing={missing} duplicated={duplicated}")

    if CORPUS_DIR.exists():
        backup = CORPUS_DIR.with_name("corpus_backup")
        if backup.exists():
            shutil.rmtree(backup)
        shutil.copytree(CORPUS_DIR, backup)
        print(f"已备份原语料到 {backup}")

    total_qa = 0
    for rel_path, row_nums in DOC_PLAN.items():
        title = Path(rel_path).stem.split("-", 1)[1]
        category = Path(rel_path).parent.name
        lines = [
            "---",
            f"title: {title}",
            f"category: {category}",
            "source: 健身知识库.xlsx（85条QA整理）",
            f"updated: {UPDATED}",
            "---",
            "",
            f"# {title}",
            "",
        ]
        for n in row_nums:
            q, a = rows[n - 1][0], rows[n - 1][1]
            if not q or not a:
                sys.exit(f"第 {n} 行问答内容为空")
            lines += [f"## {slugify(str(q))}", "", str(a).strip(), ""]
            total_qa += 1
        out = CORPUS_DIR / rel_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("\n".join(lines), encoding="utf-8")
        print(f"  {rel_path}  ({len(row_nums)} 条QA)")

    print(f"完成：{len(DOC_PLAN)} 个主题文档 / {total_qa} 条QA → {CORPUS_DIR}")


if __name__ == "__main__":
    main()
