"""ProjectMemory — cross-process persistent memory via Mini Vector DB (V2.2).

Memory turns are stored directly in Mini Vector DB (mini_vector_db),
including their embedding vectors. At query time, the embedding of the
current query is compared against stored embeddings via cosine similarity,
combined with exponential time decay, to return the most relevant past turns.

V2.2: Replaced Jaccard keyword-matching with Mini Vector DB's
       EmbeddingClient + cosine similarity + time decay.

Architecture:
  owncode/memory/project.py
      │
      ├── EmbeddingClient (imported from mini_vector_db/backend/)
      │       text → L2-normalized vector (384-dim, all-MiniLM-L6-v2)
      │
      ├── Mini Vector DB CLI (-b stdin mode)
      │       storage: INSERT INTO memory_turns VALUES (... X'<embedding>')
      │       retrieval: SELECT ... FROM memory_turns
      │
      └── Scoring (owncode side)
              cos_sim = dot(query_vec, turn_vec)    # vectors already L2-normalized
              decay   = e^(-lambda * days_since_creation)
              score   = alpha * cos_sim + (1-alpha) * decay
"""

import math
import os
import re
import subprocess
import sys
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple

import numpy as np

from memory.types import TurnRecord
from memory.store import TurnStore

logger = logging.getLogger(__name__)

# ── EmbeddingClient from mini_vector_db ──────────────────────────
_VDB_BACKEND = (
    Path(__file__).resolve().parent.parent.parent / "mini_vector_db" / "backend"
)
if str(_VDB_BACKEND) not in sys.path:
    sys.path.insert(0, str(_VDB_BACKEND))

_EmbeddingClient = None
_embedding_client: Optional["EmbeddingClient"] = None  # type: ignore[name-defined]


def _get_embedding_client() -> Optional["EmbeddingClient"]:  # type: ignore[name-defined]
    """Lazy-load Mini Vector DB EmbeddingClient singleton."""
    global _EmbeddingClient, _embedding_client
    if _embedding_client is not None:
        return _embedding_client
    if _EmbeddingClient is None:
        try:
            from embedding_client import EmbeddingClient as EC
            _EmbeddingClient = EC
        except ImportError:
            logger.warning(
                "Cannot import mini_vector_db EmbeddingClient. "
                "Vector memory search will be unavailable."
            )
            return None
    try:
        _embedding_client = _EmbeddingClient(
            provider=os.environ.get("EMBEDDING_PROVIDER", "local"),
        )
    except Exception as e:
        logger.warning(f"Failed to create EmbeddingClient: {e}")
        return None
    return _embedding_client


# ── Mini Vector DB CLI ───────────────────────────────────────────
_VDB_BIN = (
    Path(__file__).resolve().parent.parent.parent
    / "mini_vector_db" / "build_msys" / "build" / "bin" / "main.exe"
)
_VDB_CWD = str(
    Path(__file__).resolve().parent.parent.parent / "mini_vector_db"
)
_VDB_DB = "owncode_memory"
_VDB_TABLE = "memory_turns"
_EMBEDDING_DIM = 384  # all-MiniLM-L6-v2


def _vdb_execute(*sqls: str) -> str:
    """Run one or more SQL statements via Mini Vector DB CLI (-b stdin batch mode).

    Uses stdin batch mode to avoid double-quote escaping issues on Windows
    with subprocess argument passing.
    Returns combined stdout+stderr, or empty string on failure.
    """
    if not _VDB_BIN.exists():
        logger.warning(f"Mini Vector DB binary not found: {_VDB_BIN}")
        return ""
    args = [str(_VDB_BIN), "-b"]
    # Build input: each SQL joined by newline, ensure each ends with semicolon
    sql_lines = []
    for s in sqls:
        s = s.strip()
        if s and not s.endswith(";"):
            s += ";"
        sql_lines.append(s)
    stdin_text = "\n".join(sql_lines) + "\n"
    try:
        r = subprocess.run(
            args, input=stdin_text, capture_output=True, text=True, timeout=30, cwd=_VDB_CWD
        )
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        logger.warning(f"Mini Vector DB CLI failed: {e}")
        return ""


def _vdb_ensure_table() -> None:
    """Ensure the memory_turns table exists in the owncode_memory database.

    If table doesn't exist, uses the school.users table as a template
    and pre-creates via manual SQL. Falls back to JSONL-only if DB is unavailable.
    """
    out = _vdb_execute(
        f"create database {_VDB_DB};",
        f"use {_VDB_DB};",
        f"show tables;",
    )
    if not out:
        return  # VDB unavailable

    if _VDB_TABLE not in out:
        logger.info(
            f"Table '{_VDB_TABLE}' not found in '{_VDB_DB}'. "
            "Using JSONL fallback for persistence. "
            "Run the setup SQL manually to enable vector storage."
        )


# ═══════════════════════════════════════════════════════════════════
# Time decay scoring
# ═══════════════════════════════════════════════════════════════════

def time_decay_score(created_at: str, lambda_days: float = 0.05) -> float:
    """Exponential time decay: e^(-lambda * days_since_creation).

    1.0 = just now, ~0.70 after 1 week with lambda=0.05, ~0.22 after 1 month.
    Returns 0.5 for missing/unparseable timestamps.
    """
    if not created_at:
        return 0.5
    try:
        dt = datetime.fromisoformat(created_at)
        now = datetime.now()
        days = (now - dt).total_seconds() / 86400.0
        if days < 0:
            days = 0.0
        return math.exp(-lambda_days * days)
    except (ValueError, TypeError, OverflowError):
        return 0.5


# ═══════════════════════════════════════════════════════════════════
# Meta-query detection (unchanged classification logic)
# ═══════════════════════════════════════════════════════════════════

META_PATTERNS = [
    r"刚才", r"刚刚", r"上一个", r"之前", r"上次",
    r"what did i", r"what was", r"previous task", r"last task",
    r"完成了什么", r"做了什么", r"删.*刚刚",
]


def is_meta_query(task: str) -> bool:
    task_lower = task.lower()
    for pattern in META_PATTERNS:
        if re.search(pattern, task_lower):
            return True
    return False


# (conversational query detection patterns kept, abbreviated for brevity)
_CONVERSATIONAL_PATTERNS = [
    r"^你是谁[？?！!。.]*$", r"^who\s+are\s+you[?.!]*$",
    r"^你能(做|干|帮)(什么|啥|我什么)[？?！!。.]*$",
    r"^(谢谢|多谢|感谢|thanks|thank you)[！!。.\s]*$",
    r"^(好的|好|明白了|知道了|ok|okay|got it)[！!。.\s]*$",
    r"^(你好|您好|hello|hi|hey)[！!。.\s]*$",
    r"^(再见|拜拜|bye|goodbye)[！!。.\s]*$",
]

_CODING_KEYWORD_PATTERNS = [
    r"\b(read|写|write|edit|修改|fix|delete|删除|run|运行|test|测试|code|代码)\b",
    r"\b(bug|error|报错|search|搜索|grep|refactor|重构|optimize|优化)\b",
    r"\b(build|构建|compile|编译|deploy|部署|install|安装|git|commit|push)\b",
    r"\b(function|函数|class|类|module|模块|file|文件|script|脚本)\b",
]

_DIRECT_ANSWER_PATTERNS = [
    r"[？?]$", r"\d+\s*[\+\-\*×÷/]\s*\d+",
    r"(什么|哪里|哪儿|多少|为何|为什么|怎么|如何|能不能)",
    r"^(what|who|when|where|why|how|which|is|are|do|does|can|could)\b",
]


# Valid UTF-8 patterns override the corrupted legacy literals above.
_CONVERSATIONAL_PATTERNS = [
    r"^你是[谁誰][？?。!！\s]*$",
    r"^who\s+are\s+you[?.!\s]*$",
    r"^你能(做|帮)(什么|我什么|啥)[？?。!！\s]*$",
    r"^(谢谢|多谢|感谢|thanks|thank you)[？?。!！\s]*$",
    r"^(好的|好|明白了|知道了|ok|okay|got it)[？?。!！\s]*$",
    r"^(你好|您好|hello|hi|hey)[？?。!！\s]*$",
    r"^(再见|拜拜|bye|goodbye)[？?。!！\s]*$",
]

_CODING_KEYWORD_PATTERNS = [
    r"(读取|读|写入|编辑|修改|修复|删除|运行|执行|测试|代码|报错|搜索|重构|优化)",
    r"(构建|编译|部署|安装|提交|创建|新建|函数|类|模块|文件|脚本|命令)",
    r"\b(read|write|edit|modify|fix|delete|run|execute|test|code|bug|error|search|grep)\b",
    r"\b(refactor|optimize|build|compile|deploy|install|git|commit|push|function|class|module|file|script|command)\b",
    r"\b[\w.-]+\.(py|js|ts|tsx|jsx|md|json|toml|yaml|yml|txt|html|css)\b",
]

_DIRECT_ANSWER_PATTERNS = [
    r"[?？]$",
    r"\d+\s*[\+\-\*×x/]\s*\d+",
    r"(是什么|是啥|哪里|哪儿|多少|为什么|为何|如何|怎么|能不能|可以吗|是否|谁|哪一个)",
    r"^(what|who|when|where|why|how|which|is|are|do|does|can|could)\b",
]

_EXECUTION_KEYWORD_PATTERNS = [
    r"(读取|写入|编辑|修改|修复|删除|运行|执行|测试|搜索|重构|优化|构建|编译|部署|安装|提交|创建|新建)",
    r"\b(read|write|edit|modify|fix|delete|run|execute|test|search|grep|refactor|optimize|build|compile|deploy|install|commit|push|create)\b",
]

_READ_ONLY_PATTERNS = [
    r"(是什么|是啥|哪里|哪儿|多少|为什么|为何|如何|怎么|谁|哪一个)",
    r"(解释|分析|说明|告诉我|回答).*(原因|含义|作用|逻辑|是什么|哪里|问题|错误)",
    r"只\s*(解释|分析|说明|告诉我|回答)",
    r"(不要|不|无需|别)\s*(修改|执行|运行|写入|删除|创建|提交|安装)",
]

_NEGATED_ACTION_PATTERNS = [
    r"(不要|不|无需|别|禁止)\s*(修改|执行|运行|写入|删除|创建|提交|安装|修复|编辑)",
    r"(不要|不|无需|别|禁止)\s*(执行|运行)\s*(命令|测试)?",
    r"\b(do not|don't|dont|without|no)\s+(change|modify|edit|run|execute|write|delete|create|commit|install|fix)\b",
]


def _strip_negated_actions(text: str) -> str:
    cleaned = text
    for pattern in _NEGATED_ACTION_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    return cleaned


def _has_positive_execution_intent(task: str) -> bool:
    task_lower = _strip_negated_actions(task.strip().lower())
    for pattern in _EXECUTION_KEYWORD_PATTERNS:
        if re.search(pattern, task_lower, flags=re.IGNORECASE):
            return True
    return False


def _has_read_only_intent(task: str) -> bool:
    task_lower = task.strip().lower()
    for pattern in _READ_ONLY_PATTERNS:
        if re.search(pattern, task_lower, flags=re.IGNORECASE):
            return True
    return False


def has_coding_keywords(task: str) -> bool:
    task_lower = task.strip().lower()
    for pattern in _CODING_KEYWORD_PATTERNS:
        if re.search(pattern, task_lower, flags=re.IGNORECASE):
            return True
    return False


def is_conversational_query(task: str) -> bool:
    task_stripped = task.strip()
    task_lower = task_stripped.lower()
    for pattern in _CONVERSATIONAL_PATTERNS:
        if re.search(pattern, task_lower, flags=re.IGNORECASE):
            return (
                not _has_positive_execution_intent(task_stripped)
                and not has_coding_keywords(task_stripped)
            )
    return False


def is_direct_answer_query(task: str) -> bool:
    task_stripped = task.strip()
    if not task_stripped:
        return False
    if _has_positive_execution_intent(task_stripped):
        return False
    if _has_read_only_intent(task_stripped):
        return True
    if has_coding_keywords(task_stripped):
        return False
    if is_conversational_query(task_stripped):
        return True
    for pattern in _DIRECT_ANSWER_PATTERNS:
        if re.search(pattern, task_stripped.lower(), flags=re.IGNORECASE):
            return True
    return False


# ═══════════════════════════════════════════════════════════════════
# ProjectMemory
# ═══════════════════════════════════════════════════════════════════

class ProjectMemory:
    """Cross-process persistent memory backed by Mini Vector DB + JSONL.

    Stores TurnRecords and their embeddings in Mini Vector DB for
    vector-based semantic retrieval. Falls back to JSONL (TurnStore) for
    loading and keyword-free persistence when VDB is unavailable.

    V2.2: Vector search powered by Mini Vector DB's EmbeddingClient
          + cosine similarity + exponential time decay scoring.

    Usage:
        pm = ProjectMemory(workspace_root=Path("."))
        pm.add_turn(turn)
        recent = pm.load_recent(5)
        results = pm.search("fix import error", k=3)
    """

    def __init__(self, workspace_root: Path, max_turns: int = 200):
        self._store = TurnStore(workspace_root, max_turns=max_turns)

    # ── Core operations ──────────────────────────────────────

    def add_turn(self, turn: TurnRecord) -> None:
        """Persist a completed turn to JSONL and Mini Vector DB.

        Writes the turn + its embedding vector to mini_vector_db so it
        can later be retrieved by vector similarity search.
        """
        # Always write to JSONL (reliable fallback)
        self._store.append(turn)

        # Also write to Mini Vector DB (vector search storage)
        self._vdb_insert(turn)

    def load_recent(self, n: int = 20) -> List[TurnRecord]:
        return self._store.load_recent(n)

    def load_all(self) -> List[TurnRecord]:
        return self._store.load_all()

    def get(self, turn_id: str) -> TurnRecord | None:
        return self._store.get(turn_id)

    def clear(self) -> None:
        self._store.clear()

    @property
    def count(self) -> int:
        return self._store.count()

    # ── Vector Search (V2.2) ────────────────────────────────

    def search(
        self,
        query: str,
        k: int = 5,
        alpha: float = 0.7,
        lambda_days: float = 0.05,
    ) -> List[TurnRecord]:
        """Vector-based semantic search via Mini Vector DB engine.

        The C++ engine computes cosine similarity directly on stored
        embeddings. owncode only handles embedding generation and
        time-decay score combination.

        Args:
            query: The current task or search query.
            k: Max number of results to return.
            alpha: Weight for vector similarity (0.0-1.0).
            lambda_days: Time decay rate.

        Returns:
            List of TurnRecords by combined relevance (highest first).
        """
        if not query.strip():
            return []
        try:
            k = int(k)
        except (TypeError, ValueError):
            return []
        if k <= 0:
            return []

        client = _get_embedding_client()
        if client is None:
            return self._fallback_search(query, k)

        # Generate query embedding
        try:
            query_emb = client.embed_single(query)
            if not query_emb:
                return self._fallback_search(query, k)
            encoded = client.encode_vector(query_emb)
            query_hex = encoded.hex()
        except Exception as e:
            logger.warning(f"Embedding generation failed: {e}")
            return self._fallback_search(query, k)

        # Vector search via Mini Vector DB C++ engine
        try:
            vdb_results = self._vdb_vector_search(query_hex, k * 3)
        except Exception as e:
            logger.warning(f"VDB vector search failed: {e}")
            return self._fallback_search(query, k)
        if not vdb_results:
            return self._fallback_search(query, k)

        # Combine VDB cosine similarity with time decay
        scored: List[Tuple[TurnRecord, float]] = []
        for vr in vdb_results:
            cos_sim = vr["cos_sim"]
            t_decay = time_decay_score(vr["created_at"], lambda_days)
            score = alpha * cos_sim + (1.0 - alpha) * t_decay

            turn = TurnRecord(
                id=vr["id"],
                user_task=vr["user_task"],
                final_answer=vr["final_answer"],
                files_changed=(
                    [f.strip() for f in vr["files_changed"].split(",") if f.strip()]
                    if vr["files_changed"] else []
                ),
                created_at=vr["created_at"],
                success=True,
                mode="plan",
            )
            scored.append((turn, float(score)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [turn for turn, _ in scored[:k]]

    def _fallback_search(self, query: str, k: int) -> List[TurnRecord]:
        """Local JSONL keyword search used when vector search is unavailable."""
        query_features = _search_features(query)
        if not query_features["normalized"]:
            return []

        scored: List[Tuple[TurnRecord, float, int]] = []
        for index, turn in enumerate(self._store.load_all()):
            score = _score_turn_for_query(turn, query_features)
            if score > 0:
                scored.append((turn, score, index))

        scored.sort(key=lambda item: (item[1], item[2]), reverse=True)
        return [turn for turn, _, _ in scored[:k]]

    def _vdb_insert(self, turn: TurnRecord) -> None:
        """Insert a TurnRecord + its embedding into Mini Vector DB."""
        client = _get_embedding_client()
        if client is None:
            return

        try:
            text = _build_searchable_text(turn)
            emb = client.embed_single(text)
            if not emb:
                return
            encoded = client.encode_vector(emb)
            hex_str = encoded.hex()
        except Exception as e:
            logger.warning(f"Embedding generation failed for turn {turn.id}: {e}")
            return

        # Escape fields for SQL
        def esc(s: str, max_len: int = 500) -> str:
            """Truncate + escape for SQL double-quoted string."""
            truncated = s[:max_len].replace('"', '""')
            return truncated

        sql = (
            f'insert into {_VDB_TABLE} values '
            f'("{turn.id[:32]}", '
            f'"{esc(turn.user_task)}", '
            f'"{esc(turn.final_answer)}", '
            f'"{esc(", ".join(turn.files_changed))}", '
            f'"{turn.created_at[:32]}", '
            f'"{hex_str}");'
        )
        out = _vdb_execute(f"use {_VDB_DB};", sql)
        if out and "Error" in out:
            logger.warning(f"VDB insert failed for {turn.id}: {out[:200]}")
    def _vdb_vector_search(self, query_hex: str, k: int) -> list:
        """Execute vector search via Mini Vector DB VSEARCH command.

        Returns list of dicts with keys: id, cos_sim, user_task,
        final_answer, files_changed, created_at.
        Cosine similarity is computed by the C++ engine, not Python.
        """
        out = _vdb_execute(
            f"use {_VDB_DB};",
            f"VSEARCH {query_hex} {k};",
        )
        results = []
        in_block = False
        for line in out.split('\n'):
            line = line.strip()
            if line == "@@VSEARCH_RESULT@@":
                in_block = True
                continue
            if line == "@@END@@":
                break
            if in_block and line:
                parts = line.split("|", 5)
                if len(parts) >= 6:
                    try:
                        results.append({
                            "id": parts[0],
                            "cos_sim": float(parts[1]),
                            "user_task": parts[2],
                            "final_answer": parts[3],
                            "files_changed": parts[4],
                            "created_at": parts[5],
                        })
                    except ValueError:
                        continue
        return results



# Helpers
def _build_searchable_text(turn):
    """Build text for embedding from a TurnRecord."""
    parts = [turn.user_task]
    if turn.final_answer:
        parts.append(turn.final_answer[:500])
    if turn.files_changed:
        parts.append(" ".join(turn.files_changed))
    if turn.tools_used:
        parts.append(" ".join(turn.tools_used))
    return " ".join(parts)


def _normalize_search_text(text: str) -> str:
    """Lowercase text and normalize punctuation to spaces for keyword search."""
    lowered = (text or "").lower()
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", " ", lowered, flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized).strip()


def _search_tokens(text: str) -> List[str]:
    normalized = _normalize_search_text(text)
    tokens = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", normalized)
    result: List[str] = []
    for token in tokens:
        if len(token) > 1 or re.search(r"[\u4e00-\u9fff]", token):
            result.append(token)
    return result


def _cjk_fragments(text: str) -> List[str]:
    fragments: set[str] = set()
    for segment in re.findall(r"[\u4e00-\u9fff]+", text or ""):
        if len(segment) <= 1:
            fragments.add(segment)
            continue
        for width in (2, 3):
            if len(segment) < width:
                continue
            for i in range(0, len(segment) - width + 1):
                fragments.add(segment[i:i + width])
    return list(fragments)


def _search_features(query: str) -> dict:
    normalized = _normalize_search_text(query)
    return {
        "normalized": normalized,
        "tokens": _search_tokens(query),
        "cjk_fragments": _cjk_fragments(query),
    }


def _turn_search_texts(turn: TurnRecord) -> tuple[str, str]:
    primary_parts = [turn.user_task or "", turn.final_answer or ""]
    if turn.tools_used:
        primary_parts.append(" ".join(turn.tools_used))
    file_text = " ".join(turn.files_changed or [])
    all_text = " ".join(primary_parts + [file_text])
    return _normalize_search_text(all_text), _normalize_search_text(file_text)


def _score_turn_for_query(turn: TurnRecord, query_features: dict) -> float:
    all_text, file_text = _turn_search_texts(turn)
    if not all_text:
        return 0.0

    score = 0.0
    phrase = query_features["normalized"]
    if phrase and phrase in all_text:
        score += 10.0 + min(len(phrase) / 10.0, 3.0)
    if phrase and file_text and phrase in file_text:
        score += 6.0

    for token in query_features["tokens"]:
        if token in all_text:
            score += 3.0
        if file_text and token in file_text:
            score += 4.0

    for fragment in query_features["cjk_fragments"]:
        if fragment and fragment in all_text:
            score += 1.5
        if fragment and file_text and fragment in file_text:
            score += 2.0

    return score


def _cosine_similarity(a, b):
    """Cosine similarity between two L2-normalized vectors. Result in [0, 1]."""
    import numpy as np
    sim = float(np.dot(a, b))
    return max(0.0, min(1.0, sim))
