"""Markdown 语料解析与切块。

切块策略：每个 `##` 二级标题及其正文 = 一个 chunk。
问答型语料里二级标题就是问题本身，因此该策略等价于"一问一答一个 chunk"，
检索粒度最细、引用溯源能精确到问题级。

chunk 携带来源元数据（doc_path / section_title / category），
是第2步"带引用生成"的基础，也是评测时判断"出处是否命中"的依据。
"""

import re
import uuid
from dataclasses import dataclass
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CORPUS_DIR = PROJECT_ROOT / "data" / "corpus"

# 稳定命名空间：保证同一 (doc_path, section) 在多次建索引时生成同一 id，
# upsert 幂等，语料更新后重建索引不会产生重复点
_CHUNK_NS = uuid.uuid5(uuid.NAMESPACE_URL, "fitpilot/chunk/v1")

_FRONT_MATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass
class Chunk:
    chunk_id: str  # uuid5(doc_path#section)，Qdrant point id
    doc_path: str  # 相对 corpus 的路径，如 training/01-训练频率与时长.md
    doc_title: str  # front matter 里的 title（无则取一级标题）
    category: str  # 类目（front matter 或父目录名）
    section_title: str  # ## 标题文本（问答语料里即问题）
    text: str  # chunk 完整文本（含标题 + 正文）

    @property
    def source(self) -> str:
        """引用溯源用的可读出处。"""
        return f"{self.doc_path} § {self.section_title}"


def _parse_front_matter(text: str) -> tuple[dict, str]:
    match = _FRONT_MATTER_RE.match(text)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, text[match.end():]


def parse_markdown(path: Path, corpus_root: Path) -> list[Chunk]:
    meta, body = _parse_front_matter(path.read_text(encoding="utf-8"))
    rel_path = path.relative_to(corpus_root).as_posix()

    # 按 ## 切段；### 及更深层级归入当前 ## 段落
    sections: list[tuple[str, list[str]]] = []
    current_title = ""
    current_lines: list[str] = []
    for line in body.splitlines():
        if line.startswith("## "):
            # 收尾上一段：无标题但有正文（整篇没有 ## 的文档）也保留为 chunk
            if current_title or any(l.strip() for l in current_lines):
                sections.append((current_title, current_lines))
            # 标题行本身放进 chunk 文本：问答语料里标题即问题，
            # 是 embedding 语义匹配和 BM25 关键词匹配的最强信号，不能只存正文
            current_title, current_lines = line[3:].strip(), [line, ""]
        elif line.startswith("# ") and not current_title:
            # 一级标题作为文档标题候选，正文归入"概述"段
            current_title, current_lines = "概述", []
        else:
            if current_title:
                current_lines.append(line)
    if current_title:
        sections.append((current_title, current_lines))

    doc_title = str(meta.get("title") or rel_path)
    category = str(meta.get("category") or path.parent.name)

    chunks = []
    for title, lines in sections:
        section_text = "\n".join(lines).strip()
        if not section_text:
            continue
        chunk_id = str(uuid.uuid5(_CHUNK_NS, f"{rel_path}#{title}"))
        chunks.append(
            Chunk(
                chunk_id=chunk_id,
                doc_path=rel_path,
                doc_title=doc_title,
                category=category,
                section_title=title,
                text=section_text,
            )
        )
    return chunks


def load_corpus(corpus_dir: Path = CORPUS_DIR) -> list[Chunk]:
    """加载全部语料，按路径排序保证顺序稳定。"""
    chunks: list[Chunk] = []
    for path in sorted(corpus_dir.rglob("*.md")):
        chunks.extend(parse_markdown(path, corpus_dir))
    return chunks


if __name__ == "__main__":
    all_chunks = load_corpus()
    print(f"共 {len(all_chunks)} 个 chunk，来自 {len({c.doc_path for c in all_chunks})} 篇文档")
    for c in all_chunks[:3]:
        print(f"  [{c.category}] {c.source} ({len(c.text)}字)")
