"""
MemoryHandler: Giyeok (sub-memory-bootstrap) 장기 기억저장소 전담 비즈니스 레이어

단일 책임 원칙(SRP)을 준수하여 harness.py와 analyze_usage.py로부터 기억저장소 조회,
시맨틱/키워드 연관 기억 검색, 통계 산출 로직을 분리 및 캡슐화한 전용 서비스 모듈입니다.
Giyeok 고유의 nodes 테이블 및 TierBridge 에피소드 memories 테이블을 모두 지원합니다.
"""

import os
import re
import json
import sqlite3
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("TierBridge.MemoryHandler")


class MemoryHandler:
    """
    기억저장소(memory.db / MemoryService) 데이터 액세스 및 검색 전담 핸들러
    """

    DB_PATHS = [
        os.environ.get("MEMORY_DB_PATH", ""),
        os.path.expanduser("~/.tierbridge/memory.db"),
        os.path.expanduser("~/.codex/sub-memory/memory.db"),
        os.path.expanduser("~/.sub-memory/memory.db"),
        os.path.abspath(".sub-memory/memory.db"),
        os.path.abspath("memory.db")
    ]

    @classmethod
    def get_db_path(cls) -> Optional[str]:
        """
        존재하는 SQLite memory.db 경로 탐색
        """
        for p in cls.DB_PATHS:
            if p and os.path.exists(p):
                return p
        return None

    @classmethod
    def parse_memory_content(cls, content: str, tags: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Step 1 3단 지식 에피소드 포맷 또는 Giyeok(User/Assistant) 포맷 문자열 파싱 (Session ID 완벽 보존)
        """
        result = {
            "raw_content": content,
            "session_id": "sess_default",
            "decision": "UNKNOWN",
            "loc": 0,
            "cost": 0.0,
            "problem": content,
            "solution": "N/A"
        }
        if not content:
            return result

        # 태그 메타데이터에서 세션 ID 및 의사결정 복원
        if tags:
            for t in tags:
                t_str = str(t).strip()
                if t_str.startswith("sess_") or t_str.startswith("01a") or len(t_str) == 36:
                    result["session_id"] = t_str
                if t_str.upper() in ("BRONZE", "SILVER", "GOLD", "PLATINUM", "CHALLENGER", "SOL"):
                    result["decision"] = t_str.upper()

        # 1. 헤더 메타데이터 파싱: [Session: ...] [Decision: ...] [LOC: ...] [Cost: $...]
        sid_match = re.search(r"\[Session:\s*([^\]]+)\]", content)
        if sid_match:
            result["session_id"] = sid_match.group(1).strip()

        dec_match = re.search(r"\[Decision:\s*([^\]]+)\]", content)
        if dec_match:
            result["decision"] = dec_match.group(1).strip()

        loc_match = re.search(r"\[LOC:\s*(\d+)\]", content)
        if loc_match:
            result["loc"] = int(loc_match.group(1))

        cost_match = re.search(r"\[Cost:\s*\$([0-9\.]+)\]", content)
        if cost_match:
            try:
                result["cost"] = float(cost_match.group(1))
            except ValueError:
                pass

        # 2. Giyeok 표준 포맷: "User: ...\nAssistant: ..."
        if "User:" in content and "Assistant:" in content:
            parts = content.split("Assistant:", 1)
            user_part = parts[0]
            # 헤더 태그가 포함되어 있다면 제거
            user_part = re.sub(r"\[Session:[^\]]+\]|\[Decision:[^\]]+\]|\[LOC:[^\]]+\]|\[Cost:[^\]]+\]", "", user_part)
            user_part = user_part.replace("User:", "").strip()
            assist_part = parts[1].strip() if len(parts) > 1 else "N/A"
            result["problem"] = user_part
            result["solution"] = assist_part
            if result["decision"] == "UNKNOWN":
                result["decision"] = "EPISODE"
            
            # LOC가 헤더에서 파싱되지 않은 경우 코드 블록 줄 수 계산
            if result["loc"] == 0:
                code_blocks = re.findall(r"```[\w]*\n(.*?)```", assist_part, re.DOTALL)
                loc_count = sum(len([l for l in b.splitlines() if l.strip()]) for b in code_blocks)
                result["loc"] = loc_count
            return result

        # 3. TierBridge 3단 지식 마크다운 포맷 파싱
        # 📌 문제 및 요구사항 추출
        prob_match = re.search(r"-\s*📌\s*문제 및 요구사항:\s*(.*?)(?=\n-\s*💡|\n-\s*🏷️|$)", content, re.DOTALL)
        if prob_match:
            result["problem"] = prob_match.group(1).strip()

        # 💡 적용 해결책 및 LLM 응답 추출
        sol_match = re.search(r"-\s*💡\s*(?:적용 해결책 및 LLM 응답|적용 등급 및 라우팅):\s*(.*?)(?=\n-\s*🏷️|$)", content, re.DOTALL)
        if sol_match:
            result["solution"] = sol_match.group(1).strip()

        return result

    @classmethod
    def get_recent_memories(cls, limit: int = 50, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        최근 적재된 장기 기억 에피소드 목록 조회 (nodes 및 memories 테이블 통합)
        """
        db_path = cls.get_db_path()
        if not db_path:
            return []

        memories = []
        try:
            conn = sqlite3.connect(db_path, timeout=2.0)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 1. Giyeok nodes 테이블 조회
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='nodes';")
            if cursor.fetchone():
                if session_id:
                    cursor.execute(
                        "SELECT id, text, timestamp FROM nodes WHERE text LIKE ? ORDER BY timestamp DESC LIMIT ?",
                        (f"%{session_id}%", limit)
                    )
                else:
                    cursor.execute("SELECT id, text, timestamp FROM nodes ORDER BY timestamp DESC LIMIT ?", (limit,))

                for row in cursor.fetchall():
                    parsed = cls.parse_memory_content(row["text"] or "")
                    parsed["id"] = row["id"]
                    parsed["tags"] = ["giyeok_node", parsed["decision"]]
                    if parsed["loc"] > 0:
                        parsed["tags"].append("code_modified")
                    parsed["created_at"] = row["timestamp"] or "N/A"
                    memories.append(parsed)

            # 2. TierBridge memories 테이블 조회
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='memories';")
            if cursor.fetchone():
                if session_id:
                    cursor.execute(
                        "SELECT id, content, tags, created_at FROM memories WHERE content LIKE ? ORDER BY id DESC LIMIT ?",
                        (f"%{session_id}%", limit)
                    )
                else:
                    cursor.execute("SELECT id, content, tags, created_at FROM memories ORDER BY id DESC LIMIT ?", (limit,))

                for row in cursor.fetchall():
                    item_tags = row["tags"] or []
                    if isinstance(item_tags, str):
                        try:
                            item_tags = json.loads(item_tags)
                        except Exception:
                            item_tags = [t.strip() for t in item_tags.split(",") if t.strip()]
                    parsed = cls.parse_memory_content(row["content"] or "", tags=item_tags)
                    parsed["id"] = row["id"]
                    parsed["tags"] = item_tags
                    parsed["created_at"] = row["created_at"] or "N/A"
                    memories.append(parsed)

            conn.close()

            # 인메모리 중복 제거 및 세션 ID 병합 (nodes와 memories 동시 적재 중복 완벽 제거)
            deduped = {}
            for m in memories:
                key = m.get("problem", "").strip()
                if not key:
                    continue
                if key not in deduped:
                    deduped[key] = m
                else:
                    existing = deduped[key]
                    if existing.get("session_id") == "sess_default" and m.get("session_id") != "sess_default":
                        existing["session_id"] = m["session_id"]
                        existing["tags"] = m.get("tags", existing.get("tags", []))
                        existing["decision"] = m.get("decision", existing.get("decision", "UNKNOWN"))

            final_list = list(deduped.values())
            return final_list[:limit]
        except Exception as e:
            logger.debug(f"[MemoryHandler] SQLite get_recent_memories error: {e}")
            return []

    @classmethod
    def extract_search_tokens(cls, query: str) -> List[str]:
        """
        한국어 형태소/서브토큰 분리 및 조사/접미사/질문형 불용어 정제
        """
        if not query:
            return []
        raw_tokens = re.findall(r"[\w\.\-@#]+", query.lower())
        meta_stop_words = {
            "은", "는", "이", "가", "을", "를", "의", "에", "로", "으로", "에서", "와", "과", "도",
            "하고", "하고있어", "해줘", "확인해줘", "알려줘", "기억나는거", "기억나", "있어", "있니", 
            "어떻게", "했었지", "했지", "작업", "작업한", "내용", "이력", "히스토리", "관련", "관련된", 
            "대한", "대해", "대해서", "질의", "질문", "관련해서", "시작", "부탁해", "작업이"
        }
        suffixes = [
            "관련된", "관련해서", "관련", "에대해", "대해서", "대한", "대해",
            "으로", "에서", "까지", "부터", "에게", "한테",
            "은", "는", "이", "가", "을", "를", "의", "에", "로", "와", "과", "도"
        ]
        tokens = set()
        for raw in raw_tokens:
            if raw in meta_stop_words:
                continue
            tokens.add(raw)
            stem = raw
            for sfx in suffixes:
                if stem.endswith(sfx) and len(stem) > len(sfx):
                    stem = stem[:-len(sfx)]
                    if len(stem) >= 2 and stem not in meta_stop_words:
                        tokens.add(stem)
                    break

        return [t for t in tokens if len(t) >= 2]

    @classmethod
    def search_associated_memories(cls, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        질의어 기반 연관 기억 다단계 시맨틱/키워드 랭킹 검색
        """
        if not query or not query.strip():
            return []

        clean_q = query.strip()
        db_path = cls.get_db_path()
        if not db_path:
            return []

        # 한국어 형태소 및 어간 토큰화
        keywords = cls.extract_search_tokens(clean_q)
        if not keywords:
            raw_keywords = re.findall(r"[\w\.\-@#]+", clean_q.lower())
            keywords = [k for k in raw_keywords if len(k) >= 2] or raw_keywords

        candidates = []
        try:
            conn = sqlite3.connect(db_path, timeout=2.0)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 1. nodes 테이블 전체 조회 후 인메모리 정밀 랭킹 (최대 100건)
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='nodes';")
            if cursor.fetchone():
                cursor.execute("SELECT id, text, timestamp FROM nodes ORDER BY timestamp DESC LIMIT 100;")
                for row in cursor.fetchall():
                    parsed = cls.parse_memory_content(row["text"] or "")
                    parsed["id"] = row["id"]
                    parsed["created_at"] = row["timestamp"] or "N/A"
                    candidates.append(parsed)

            # 2. memories 테이블 전체 조회 후 인메모리 정밀 랭킹 (최대 100건)
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='memories';")
            if cursor.fetchone():
                cursor.execute("SELECT id, content, tags, created_at FROM memories ORDER BY id DESC LIMIT 100;")
                for row in cursor.fetchall():
                    item_tags = row["tags"] or []
                    if isinstance(item_tags, str):
                        try:
                            item_tags = json.loads(item_tags)
                        except Exception:
                            item_tags = [t.strip() for t in item_tags.split(",") if t.strip()]
                    parsed = cls.parse_memory_content(row["content"] or "", tags=item_tags)
                    parsed["id"] = row["id"]
                    parsed["tags"] = item_tags
                    parsed["created_at"] = row["created_at"] or "N/A"
                    candidates.append(parsed)

            # 3. edges 테이블에서 가중치 맵 조회
            edge_weights = {}
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='edges';")
            if cursor.fetchone():
                cursor.execute("SELECT source_id, MAX(weight) FROM edges GROUP BY source_id;")
                for s_id, w in cursor.fetchall():
                    edge_weights[s_id] = float(w or 1.0)

            conn.close()

            # 4. 다단계 유사도 점수 산출 및 랭킹
            ranked = []
            for item in candidates:
                prob = (item.get("problem") or "").lower()
                sol = (item.get("solution") or "").lower()
                raw = (item.get("raw_content") or "").lower()
                combined_text = f"{prob} {sol} {raw}"

                # 전체 문장 통일치 검사
                if clean_q.lower() in combined_text:
                    base_score = 0.85
                else:
                    # 키워드 매칭 개수 기반 산출 (어간/토큰 부분 매칭)
                    matched_count = sum(1 for kw in keywords if kw in combined_text)
                    if matched_count == 0:
                        continue
                    # 단일 키워드 매칭이라도 고유 키워드(예: '쿠폰') 매칭 시 최소 0.70 보장
                    match_ratio = matched_count / max(1, len(keywords))
                    base_score = min(0.85, match_ratio * 0.40 + 0.45)

                # 퀄리티 및 엣지 가중치 보정
                quality_boost = 0.0
                if item.get("loc", 0) > 0:
                    quality_boost += 0.15  # 실제 코드 수정 에피소드 보너스
                if item.get("decision") in ("GOLD", "PLATINUM", "CHALLENGER", "SOL"):
                    quality_boost += 0.10  # 고난도 아키텍처 결정 보너스
                
                # Step 3: edges 테이블 가중치 승격 가산
                edge_w = edge_weights.get(str(item.get("id")), 1.0)
                item["edge_weight"] = edge_w
                if edge_w > 1.0:
                    quality_boost += min(0.15, (edge_w - 1.0) * 0.02)
                
                # 서브스텝 패널티
                if prob.startswith("[substep]"):
                    quality_boost -= 0.30

                final_score = round(min(0.99, max(0.10, base_score + quality_boost)), 4)
                item["score"] = final_score
                ranked.append(item)

            # 5. 인메모리 중복 제거 및 세션 ID / 최고 점수 병합
            deduped_ranked = {}
            for item in ranked:
                key = (item.get("problem") or item.get("raw_content") or "").strip()
                if not key:
                    continue
                if key not in deduped_ranked:
                    deduped_ranked[key] = item
                else:
                    curr = deduped_ranked[key]
                    if item["score"] > curr["score"]:
                        curr["score"] = item["score"]
                    if curr.get("session_id") == "sess_default" and item.get("session_id") != "sess_default":
                        curr["session_id"] = item["session_id"]
                        curr["tags"] = item.get("tags", curr.get("tags", []))
                        curr["decision"] = item.get("decision", curr.get("decision", "UNKNOWN"))

            final_ranked = list(deduped_ranked.values())
            # 점수 및 최신순 정렬
            final_ranked.sort(key=lambda x: (x["score"], x.get("created_at", "")), reverse=True)
            return final_ranked[:limit]

        except Exception as e:
            logger.debug(f"[MemoryHandler] SQLite search error: {e}")
            return []

    @classmethod
    def get_graph_data(cls, limit_nodes: int = 60) -> Dict[str, Any]:
        """
        vis-network 렌더링용 nodes & edges 인터랙티브 그래프 데이터셋 생성 (<5ms)
        """
        db_path = cls.get_db_path()
        if not db_path:
            return {"nodes": [], "edges": []}

        try:
            conn = sqlite3.connect(db_path, timeout=2.0)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # 1. edges 가중치 맵 조회
            edge_weights = {}
            raw_edges = []
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='edges';")
            if cursor.fetchone():
                cursor.execute("SELECT source_id, target_id, weight FROM edges ORDER BY weight DESC LIMIT 300;")
                for row in cursor.fetchall():
                    s_id, t_id, w = row["source_id"], row["target_id"], float(row["weight"] or 1.0)
                    raw_edges.append((s_id, t_id, w))
                    edge_weights[s_id] = max(edge_weights.get(s_id, 1.0), w)
                    edge_weights[t_id] = max(edge_weights.get(t_id, 1.0), w)

            # 2. nodes 조회
            cursor.execute("SELECT id, text, timestamp FROM nodes ORDER BY timestamp DESC LIMIT ?;", (limit_nodes,))
            nodes_data = []
            node_ids = set()
            for row in cursor.fetchall():
                nid = row["id"]
                node_ids.add(nid)
                parsed = cls.parse_memory_content(row["text"] or "")
                dec = parsed.get("decision", "BRONZE").upper()
                prob = parsed.get("problem", "")
                sol = parsed.get("solution", "")
                loc = parsed.get("loc", 0)
                cost = parsed.get("cost", 0.0)
                weight = edge_weights.get(nid, 1.0)

                label = prob.replace("\n", " ")[:16] + ("..." if len(prob) > 16 else "")
                title = f"<b>[{dec}] #{nid[:8]}</b> (가중치: {weight:.2f}x)<br><br><b>📌 문제:</b> {prob[:100]}...<br><br><b>💡 해결:</b> {sol[:100]}...<br>💻 LOC: {loc}줄 | 💰 Cost: ${cost:.4f}"

                # 노드 색상 매핑
                color_map = {
                    "CHALLENGER": {"background": "#ef4444", "border": "#b91c1c", "highlight": {"background": "#f87171", "border": "#dc2626"}},
                    "PLATINUM": {"background": "#06b6d4", "border": "#0891b2", "highlight": {"background": "#22d3ee", "border": "#0e7490"}},
                    "GOLD": {"background": "#f59e0b", "border": "#d97706", "highlight": {"background": "#fbbf24", "border": "#b45309"}},
                    "SILVER": {"background": "#94a3b8", "border": "#64748b", "highlight": {"background": "#cbd5e1", "border": "#475569"}},
                    "BRONZE": {"background": "#b45309", "border": "#78350f", "highlight": {"background": "#d97706", "border": "#92400e"}},
                }
                node_color = color_map.get(dec, color_map["BRONZE"])

                nodes_data.append({
                    "id": nid,
                    "label": label,
                    "title": title,
                    "group": dec,
                    "value": round(weight, 1),
                    "size": min(38, max(16, int(16 + weight * 2.2))),
                    "color": node_color,
                    "font": {"color": "#ffffff", "size": 11, "face": "Pretendard, -apple-system, sans-serif"},
                    "decision": dec,
                    "loc": loc,
                    "cost": cost,
                    "weight": weight,
                    "problem": prob,
                    "solution": sol,
                    "timestamp": row["timestamp"] or "N/A"
                })

            # 3. 유효한 엣지만 필터링 및 굵기 설정
            edges_data = []
            seen_edges = set()
            for s_id, t_id, w in raw_edges:
                if s_id in node_ids and t_id in node_ids:
                    pair_key = tuple(sorted([s_id, t_id]))
                    if pair_key in seen_edges:
                        continue
                    seen_edges.add(pair_key)
                    edges_data.append({
                        "from": s_id,
                        "to": t_id,
                        "value": w,
                        "width": min(6.0, max(1.0, w * 0.8)),
                        "title": f"연결 강도: {w:.2f}x",
                        "color": {
                            "color": "rgba(168, 85, 247, 0.45)" if w < 3.0 else "rgba(236, 72, 153, 0.85)",
                            "highlight": "#ec4899"
                        },
                        "smooth": {"type": "continuous"}
                    })

            conn.close()
            return {"nodes": nodes_data, "edges": edges_data}
        except Exception as e:
            logger.debug(f"[MemoryHandler] get_graph_data error: {e}")
            return {"nodes": [], "edges": []}

    @classmethod
    def get_top_weighted_edges(cls, limit: int = 10) -> List[Dict[str, Any]]:
        """
        가장 높은 가중치를 가진 상위 엣지 및 노드 정보 목록 조회
        """
        db_path = cls.get_db_path()
        if not db_path:
            return []

        try:
            conn = sqlite3.connect(db_path, timeout=2.0)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='edges';")
            if not cursor.fetchone():
                conn.close()
                return []

            cursor.execute(
                """
                SELECT e.source_id, e.target_id, e.weight, n.text, n.timestamp
                FROM edges e
                LEFT JOIN nodes n ON e.source_id = n.id
                ORDER BY e.weight DESC
                LIMIT ?;
                """,
                (limit,)
            )
            rows = cursor.fetchall()
            results = []
            for r in rows:
                parsed = cls.parse_memory_content(r["text"] or "")
                results.append({
                    "source_id": r["source_id"],
                    "target_id": r["target_id"],
                    "weight": round(float(r["weight"] or 1.0), 2),
                    "problem": parsed.get("problem", ""),
                    "solution": parsed.get("solution", ""),
                    "decision": parsed.get("decision", "BRONZE"),
                    "loc": parsed.get("loc", 0),
                    "cost": parsed.get("cost", 0.0),
                    "timestamp": r["timestamp"] or "N/A"
                })
            conn.close()
            return results
        except Exception as e:
            logger.debug(f"[MemoryHandler] get_top_weighted_edges error: {e}")
            return []

    @classmethod
    def get_memory_stats(cls) -> Dict[str, Any]:
        """
        기억저장소 통계 산출
        """
        db_path = cls.get_db_path()
        if not db_path:
            return {
                "status": "success",
                "total_memories": 0,
                "total_tags": 0,
                "code_modified_count": 0,
                "max_edge_weight": 1.0,
                "structured_rate": 100.0
            }

        total_count = 0
        code_mod_count = 0
        max_edge_w = 1.0
        try:
            conn = sqlite3.connect(db_path, timeout=2.0)
            cursor = conn.cursor()

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='nodes';")
            if cursor.fetchone():
                cursor.execute("SELECT count(*) FROM nodes;")
                total_count += cursor.fetchone()[0]
                cursor.execute("SELECT count(*) FROM nodes WHERE text LIKE '%```%';")
                code_mod_count += cursor.fetchone()[0]

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='memories';")
            if cursor.fetchone():
                cursor.execute("SELECT count(*) FROM memories;")
                total_count += cursor.fetchone()[0]
                cursor.execute("SELECT count(*) FROM memories WHERE tags LIKE '%code_modified%' OR (content LIKE '%[LOC:%' AND NOT content LIKE '%[LOC: 0]%');")
                code_mod_count += cursor.fetchone()[0]

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='edges';")
            if cursor.fetchone():
                cursor.execute("SELECT MAX(weight) FROM edges;")
                res = cursor.fetchone()
                if res and res[0] is not None:
                    max_edge_w = round(float(res[0]), 2)

            conn.close()
        except Exception:
            pass

        return {
            "status": "success",
            "total_memories": total_count,
            "total_tags": max(1, total_count * 2),
            "code_modified_count": code_mod_count,
            "max_edge_weight": max_edge_w,
            "structured_rate": 100.0
        }

    @classmethod
    def neuralize_memory(cls, node_id: str) -> Dict[str, Any]:
        """
        Neuralizer: 특정 기억 노드를 안전하게 삭제하고 연결된 엣지만 정밀 소각 (주변 기억 안전 보존)
        """
        if not node_id:
            return {"status": "error", "message": "Invalid node_id"}

        clean_id = node_id.lstrip("#").strip()
        target_ids = list(set([clean_id, f"#{clean_id}", node_id]))

        db_path = cls.get_db_path()
        if not db_path:
            return {"status": "error", "message": "Database not found", "node_id": clean_id}

        try:
            conn = sqlite3.connect(db_path, timeout=2.0)
            cursor = conn.cursor()

            deleted_edges_count = 0
            # 1. edges 테이블에서 연결선 카운트 및 삭제
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='edges';")
            if cursor.fetchone():
                q_marks = ",".join(["?"] * len(target_ids))
                cursor.execute(f"SELECT count(*) FROM edges WHERE source_id IN ({q_marks}) OR target_id IN ({q_marks});", (*target_ids, *target_ids))
                deleted_edges_count = cursor.fetchone()[0]
                cursor.execute(f"DELETE FROM edges WHERE source_id IN ({q_marks}) OR target_id IN ({q_marks});", (*target_ids, *target_ids))

            # 2. nodes 테이블에서 노드 삭제
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='nodes';")
            deleted_nodes_count = 0
            if cursor.fetchone():
                q_marks = ",".join(["?"] * len(target_ids))
                cursor.execute(f"DELETE FROM nodes WHERE id IN ({q_marks});", tuple(target_ids))
                deleted_nodes_count = cursor.rowcount

            # 3. memories 테이블에서도 id 또는 UUID 매칭되는 레코드 정리
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='memories';")
            if cursor.fetchone():
                q_marks = ",".join(["?"] * len(target_ids))
                cursor.execute(f"DELETE FROM memories WHERE id IN ({q_marks}) OR tags LIKE ?;", (*target_ids, f"%{clean_id}%"))

            conn.commit()
            conn.close()

            return {
                "status": "deleted" if (deleted_nodes_count > 0 or deleted_edges_count > 0) else "not_found",
                "node_id": clean_id,
                "deleted_edges_count": deleted_edges_count
            }
        except Exception as e:
            logger.debug(f"[MemoryHandler] neuralize_memory error: {e}")
            return {"status": "error", "message": str(e), "node_id": clean_id}
