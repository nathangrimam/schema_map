import math
import os
import sys
import unittest
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import import_adapter
import layout as L
import model


SQL = """
CREATE TABLE tenants (id INT PRIMARY KEY, name TEXT);
CREATE TABLE users (id INT PRIMARY KEY, tenant_id INT REFERENCES tenants(id));
CREATE TABLE posts (id INT PRIMARY KEY, author_id INT REFERENCES users(id));
"""


def project_with_layout():
    """Projeto com posição salva para toda tabela e um bloco cobrindo todas."""
    project = import_adapter.import_sql(SQL, "blog.sql", "postgres")
    diagram = model.build_project(project)
    names = {table["name"]: table["id"] for table in project["tables"]}
    project["layout"]["tables"] = {names[t["name"]]: {"x": t["x"], "y": t["y"]}
                                   for t in diagram["tables"]}
    project["layout"]["blocks"] = [dict(block, table_ids=list(names.values()))
                                   for block in diagram["blocks"]]
    return project


class LayoutFastPathTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        original = L.build

        def spy(*args, **kwargs):
            self.calls.append(args)
            return original(*args, **kwargs)

        L.build = spy
        self.addCleanup(setattr, L, "build", original)

    def project(self):
        """Projeto pronto, sem contar as chamadas feitas para montá-lo."""
        project = project_with_layout()
        self.calls.clear()
        return project

    def test_complete_saved_layout_skips_the_auto_layout(self):
        # o auto-layout custa segundos em schemas grandes e seria descartado
        project = self.project()

        diagram = model.build_project(project)

        self.assertEqual(self.calls, [])
        self.assertTrue(diagram["saved"])
        saved = project["layout"]["tables"]
        names = {table["id"]: table["name"] for table in project["tables"]}
        placed = {t["name"]: (t["x"], t["y"]) for t in diagram["tables"]}
        for table_id, point in saved.items():
            self.assertEqual(placed[names[table_id]], (point["x"], point["y"]))

    def test_new_table_falls_back_to_the_auto_layout(self):
        project = self.project()
        project = import_adapter.import_sql(
            SQL + "CREATE TABLE tags (id INT PRIMARY KEY);", "blog.sql", "postgres",
            previous=project)

        model.build_project(project)

        self.assertEqual(len(self.calls), 1)

    def test_forced_relayout_still_runs_the_auto_layout(self):
        project = self.project()

        model.build_project(project, force_relayout=True)

        self.assertEqual(len(self.calls), 1)


class AnnealingTest(unittest.TestCase):
    def test_swap_delta_matches_a_full_recount(self):
        # order_blocks avalia trocas pelo delta; ele precisa bater com o custo
        # recalculado do zero, senão o recozimento otimiza a métrica errada
        names = ["a", "b", "c", "d", "e", "f"]
        coupling = {("a", "b"): 3, ("a", "d"): 1, ("b", "e"): 2,
                    ("c", "f"): 5, ("d", "e"): 1, ("a", "f"): 2}
        order, cost = L.order_blocks(names, coupling, 3, 2)

        self.assertEqual(sorted(order), sorted(names))
        cells = [(c * 1.0, r * 1.8) for r in range(2) for c in range(3)]
        expected = 0.0
        for i, left in enumerate(order):
            for j in range(i + 1, len(order)):
                right = order[j]
                w = coupling.get((left, right), 0) or coupling.get((right, left), 0)
                if w:
                    expected += w * math.hypot(cells[i][0] - cells[j][0],
                                               cells[i][1] - cells[j][1])
        self.assertAlmostEqual(cost, expected, places=6)

    def test_ordering_is_deterministic(self):
        names = ["a", "b", "c", "d"]
        coupling = {("a", "c"): 4, ("b", "d"): 2}

        first, _ = L.order_blocks(names, coupling, 2, 2)
        second, _ = L.order_blocks(names, coupling, 2, 2)

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
