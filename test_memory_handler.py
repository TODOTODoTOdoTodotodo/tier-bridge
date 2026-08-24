import os
import sys
import tempfile
import sqlite3
import unittest
from unittest.mock import patch, MagicMock

# Auto-inject src
_script_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.join(_script_dir, "src")
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from tierbridge.memory_handler import MemoryHandler
from tierbridge.memory_ingestion_worker import MemoryIngestionWorker


class TestMemoryHandler(unittest.TestCase):

    def setUp(self):
        self.sample_episode = (
            "[Session: 019ffec0-eef3-7692-801c-60dae4e386bd] [Decision: GOLD] [LOC: 45] [Cost: $0.1520]\n"
            "- 📌 문제 및 요구사항: Lombok @Getter/@Setter 호환성 오류 해결 및 DTO 리팩토링\n"
            "- 💡 적용 등급 및 라우팅: GOLD (Complex code edit)\n"
            "- 🏷️ 지식 태그: #019ffec0-eef3-7692-801c-60dae4e386bd, #GOLD, #tierbridge_auto_ingest, #code_modified"
        )

    def test_parse_memory_content(self):
        parsed = MemoryHandler.parse_memory_content(self.sample_episode)
        self.assertEqual(parsed["session_id"], "019ffec0-eef3-7692-801c-60dae4e386bd")
        self.assertEqual(parsed["decision"], "GOLD")
        self.assertEqual(parsed["loc"], 45)
        self.assertAlmostEqual(parsed["cost"], 0.1520)
        self.assertIn("Lombok @Getter/@Setter", parsed["problem"])
        self.assertIn("GOLD", parsed["solution"])

    def test_parse_empty_content(self):
        parsed = MemoryHandler.parse_memory_content("")
        self.assertEqual(parsed["session_id"], "sess_default")
        self.assertEqual(parsed["decision"], "UNKNOWN")
        self.assertEqual(parsed["loc"], 0)

    def test_parse_giyeok_node_format_with_session(self):
        content = (
            "[Session: 01a01873-7be7-7063-8540-a4f83a4fbe29] [Decision: SILVER] [LOC: 20] [Cost: $0.0500]\n"
            "User: 결제완료 화면에서 예약취소 버튼 위치를 찾아줘.\n"
            "Assistant: 결제완료 컴포넌트(payment-complete.vue) 내에 CancelModal.vue 를 호출하도록 구현되어 있습니다."
        )
        parsed = MemoryHandler.parse_memory_content(content)
        self.assertEqual(parsed["session_id"], "01a01873-7be7-7063-8540-a4f83a4fbe29")
        self.assertEqual(parsed["decision"], "SILVER")
        self.assertEqual(parsed["loc"], 20)
        self.assertIn("결제완료 화면에서 예약취소 버튼 위치", parsed["problem"])
        self.assertIn("CancelModal.vue", parsed["solution"])

    def test_sqlite_get_and_search_memories(self):
        # 임시 SQLite DB 생성 및 테스트
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            db_path = tf.name

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT,
                    tags TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cursor.execute(
                "INSERT INTO memories (content, tags) VALUES (?, ?)",
                (self.sample_episode, '["019ffec0-eef3", "GOLD", "code_modified"]')
            )
            cursor.execute(
                "INSERT INTO memories (content, tags) VALUES (?, ?)",
                ("Simple Question without code", '["sess_abc", "BRONZE"]')
            )
            conn.commit()
            conn.close()

            with patch.object(MemoryHandler, "get_db_path", return_value=db_path):
                # 1. get_recent_memories 테스트
                mems = MemoryHandler.get_recent_memories(limit=10)
                self.assertEqual(len(mems), 2)
                self.assertIn(mems[0]["decision"], ("BRONZE", "GOLD", "UNKNOWN"))

                # 2. search_associated_memories 테스트
                search_res = MemoryHandler.search_associated_memories(query="Lombok", limit=5)
                self.assertEqual(len(search_res), 1)
                self.assertIn("Lombok", search_res[0]["problem"])

                # 3. get_memory_stats 테스트
                stats = MemoryHandler.get_memory_stats()
                self.assertEqual(stats["total_memories"], 2)
                self.assertGreaterEqual(stats["total_tags"], 3)
                self.assertEqual(stats["code_modified_count"], 1)

        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    def test_get_graph_data_and_top_edges(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            db_path = tf.name

        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE nodes (
                    id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    timestamp TEXT NOT NULL
                );
            """)
            cursor.execute("""
                CREATE TABLE edges (
                    source_id TEXT,
                    target_id TEXT,
                    weight REAL DEFAULT 1.0,
                    PRIMARY KEY (source_id, target_id)
                );
            """)
            cursor.execute("INSERT INTO nodes VALUES ('node_a', 'User: Q1\nAssistant: A1', X'00', '2026-08-24T10:00:00');")
            cursor.execute("INSERT INTO nodes VALUES ('node_b', 'User: Q2\nAssistant: A2', X'00', '2026-08-24T10:05:00');")
            cursor.execute("INSERT INTO edges VALUES ('node_b', 'node_a', 5.5);")
            conn.commit()
            conn.close()

            with patch.object(MemoryHandler, "get_db_path", return_value=db_path):
                graph = MemoryHandler.get_graph_data(limit_nodes=10)
                self.assertEqual(len(graph["nodes"]), 2)
                self.assertEqual(len(graph["edges"]), 1)
                self.assertEqual(graph["edges"][0]["from"], "node_b")
                self.assertEqual(graph["edges"][0]["to"], "node_a")
                self.assertEqual(graph["edges"][0]["value"], 5.5)

                top_edges = MemoryHandler.get_top_weighted_edges(limit=5)
                self.assertEqual(len(top_edges), 1)
                self.assertEqual(top_edges[0]["source_id"], "node_b")
                self.assertEqual(top_edges[0]["weight"], 5.5)

        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    def test_fallback_when_db_missing(self):
        with patch.object(MemoryHandler, "get_db_path", return_value=None):
            mems = MemoryHandler.get_recent_memories()
            self.assertEqual(mems, [])
            search_res = MemoryHandler.search_associated_memories("non_existent")
            self.assertEqual(search_res, [])
            stats = MemoryHandler.get_memory_stats()
            self.assertEqual(stats["total_memories"], 0)


if __name__ == "__main__":
    unittest.main()
