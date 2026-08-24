import unittest
import sqlite3
import tempfile
import os
from tierbridge.memory_reinforcer import MemoryReinforcer


class TestMemoryReinforcer(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_memory.db")
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE nodes (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                embedding BLOB NOT NULL,
                timestamp TEXT NOT NULL
            );
        """)
        c.execute("INSERT INTO nodes VALUES ('node_1', 'User: Q1\nAssistant: A1', X'00', '2026-08-24T10:00:00');")
        c.execute("INSERT INTO nodes VALUES ('node_2', 'User: Q2\nAssistant: A2', X'00', '2026-08-24T10:01:00');")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_compute_reinforce_weight(self):
        # 1. BRONZE low cost
        w1 = MemoryReinforcer.compute_reinforce_weight(cost_usd=0.01, decision="BRONZE", loc=0)
        self.assertAlmostEqual(w1, 1.10, places=2)

        # 2. GOLD high cost & loc
        w2 = MemoryReinforcer.compute_reinforce_weight(cost_usd=0.20, decision="GOLD", loc=50)
        # base=2.0 * (1.0 + 2.0 + 1.0) = 8.0
        self.assertGreaterEqual(w2, 8.0)

        # 3. CHALLENGER max cap
        w3 = MemoryReinforcer.compute_reinforce_weight(cost_usd=0.50, decision="CHALLENGER", loc=100)
        self.assertEqual(w3, 10.0)

    def test_reinforce_node_sqlite_edges(self):
        success = MemoryReinforcer.reinforce_node(
            node_id="node_2",
            cost_usd=0.15,
            decision="PLATINUM",
            loc=30,
            db_path=self.db_path
        )
        self.assertTrue(success)

        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT source_id, target_id, weight FROM edges;")
        edges = c.fetchall()
        conn.close()

        self.assertGreaterEqual(len(edges), 1)
        self.assertEqual(edges[0][0], "node_2")
        self.assertEqual(edges[0][1], "node_1")
        self.assertGreaterEqual(edges[0][2], 5.0)


if __name__ == "__main__":
    unittest.main()
