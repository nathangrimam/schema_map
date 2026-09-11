import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import generate_sql
import import_adapter
import parse_sql

POSTGRES = """
CREATE TABLE customers (
    id UUID PRIMARY KEY,
    email CITEXT NOT NULL UNIQUE,
    active BOOLEAN NOT NULL DEFAULT true,
    score NUMERIC(10,2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (score >= 0)
);

CREATE TABLE orders (
    id BIGSERIAL PRIMARY KEY,
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL CHECK (status IN ('NEW','PAID')),
    payload JSONB
);
"""

MYSQL = """
CREATE TABLE `users` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `flag` tinyint(1) NOT NULL DEFAULT 0,
  `body` longtext,
  `seen_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB;
"""


def project_from(sql, dialect=None):
    return import_adapter.import_sql(sql, 'teste.sql', dialect)


class GenerateSqlTest(unittest.TestCase):
    def setUp(self):
        self.project = project_from(POSTGRES)

    def test_round_trip_preserves_tables_columns_and_fks(self):
        for dialect in ('postgres', 'mysql'):
            with self.subTest(dialect=dialect):
                back = parse_sql.parse(generate_sql.generate(self.project, dialect),
                                       is_sql=True)
                self.assertEqual(sorted(back['tables']), ['customers', 'orders'])
                self.assertEqual(len(back['fks']), 1)
                self.assertEqual(len(back['tables']['customers']['cols']), 5)

    def test_postgres_types_are_translated_to_mysql(self):
        sql = generate_sql.generate(self.project, 'mysql')
        self.assertIn('CHAR(36)', sql)          # UUID
        self.assertIn('JSON', sql)              # JSONB
        self.assertIn('DATETIME', sql)          # TIMESTAMPTZ
        self.assertIn('TINYINT(1)', sql)        # BOOLEAN
        self.assertIn('DECIMAL(10,2)', sql)     # NUMERIC
        self.assertIn('CURRENT_TIMESTAMP', sql)  # NOW()
        self.assertIn('`customers`', sql)       # aspas do dialeto
        self.assertNotIn('JSONB', sql)

    def test_mysql_types_are_translated_to_postgres(self):
        sql = generate_sql.generate(project_from(MYSQL), 'postgres')
        self.assertIn('BOOLEAN', sql)           # tinyint(1)
        self.assertIn('TEXT', sql)              # longtext
        self.assertIn('TIMESTAMP', sql)         # datetime
        self.assertIn('"users"', sql)
        self.assertNotIn('`', sql)

    def test_same_dialect_keeps_the_original_spelling(self):
        sql = generate_sql.generate(project_from('CREATE TABLE t (a INT);'), 'postgres')
        self.assertIn('INT', sql)
        self.assertNotIn('INTEGER', sql)

    def test_check_constraints_survive(self):
        for dialect in ('postgres', 'mysql'):
            with self.subTest(dialect=dialect):
                sql = generate_sql.generate(self.project, dialect)
                self.assertIn('CHECK (score >= 0)', sql)
                self.assertIn("status IN ('NEW','PAID')", sql)

    def test_foreign_keys_come_after_every_table(self):
        sql = generate_sql.generate(self.project, 'postgres')
        last_create = sql.rindex('CREATE TABLE')
        self.assertGreater(sql.index('ADD CONSTRAINT'), last_create)
        self.assertIn('ON DELETE CASCADE', sql)

    def test_invalid_dialect_is_refused(self):
        with self.assertRaises(ValueError):
            generate_sql.generate(self.project, 'oracle')

    def test_map_type_keeps_unknown_types_untouched(self):
        self.assertEqual(generate_sql.map_type('GEOMETRY', 'mysql'), 'GEOMETRY')
        self.assertEqual(generate_sql.map_type('VARCHAR(150)', 'mysql'), 'VARCHAR(150)')

    def test_identifiers_with_quotes_are_escaped(self):
        self.assertEqual(generate_sql.quote('a"b', 'postgres'), '"a""b"')
        self.assertEqual(generate_sql.quote('a`b', 'mysql'), '`a``b`')


class CheckConstraintParsingTest(unittest.TestCase):
    def test_parser_keeps_nested_parentheses_in_check(self):
        parsed = parse_sql.parse(POSTGRES, is_sql=True)
        checks = parsed['tables']['orders']['checks']
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]['expression'], "status IN ('NEW','PAID')")

    def test_column_named_like_a_keyword_is_not_dropped(self):
        parsed = parse_sql.parse(
            'CREATE TABLE t (checked_by TEXT, key_hash TEXT, uniquely TEXT);', is_sql=True)
        self.assertEqual([c['name'] for c in parsed['tables']['t']['cols']],
                         ['checked_by', 'key_hash', 'uniquely'])



class StatementSplitTest(unittest.TestCase):
    """Dumps do mysqldump escapam aspas com barra invertida. Sem tratar isso, o
    estado de aspas inverte no meio dos dados e os CREATE TABLE seguintes somem."""

    DUMP = r"""
CREATE TABLE `a` (`id` INT NOT NULL, PRIMARY KEY (`id`));
INSERT INTO `a` VALUES (1,'erro: \'status\' truncado'),(2,'caminho C:\\tmp');
CREATE TABLE `b` (`id` INT NOT NULL, `a_id` INT,
  CONSTRAINT `fk_b_a` FOREIGN KEY (`a_id`) REFERENCES `a` (`id`));
"""

    def test_data_with_escaped_quotes_does_not_hide_later_tables(self):
        parsed = parse_sql.parse(self.DUMP, is_sql=True)
        self.assertEqual(sorted(parsed['tables']), ['a', 'b'])
        self.assertEqual(len(parsed['fks']), 1)

    def test_statements_after_escaped_backslash_are_still_split(self):
        statements = parse_sql.split_statements(self.DUMP)
        creates = [s for s in statements if s.lstrip().upper().startswith('CREATE')]
        self.assertEqual(len(creates), 2)

if __name__ == '__main__':
    unittest.main()
