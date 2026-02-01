import os, sys, sqlite3

db_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join("test_data", "test.db")
print("DB PATH:", os.path.abspath(db_path))

c = sqlite3.connect(db_path)

print("sqlite_version =", c.execute("SELECT sqlite_version();").fetchone())

# Проверка, что FTS5 вообще собран в SQLite
opts = [r[0] for r in c.execute("PRAGMA compile_options;").fetchall()]
print("FTS5 compiled =", any("ENABLE_FTS5" in o for o in opts))

print("journal_mode (before) =", c.execute("PRAGMA journal_mode;").fetchone())

# foreign_keys — per connection
print("foreign_keys (before) =", c.execute("PRAGMA foreign_keys;").fetchone())
c.execute("PRAGMA foreign_keys = ON;")
print("foreign_keys (after)  =", c.execute("PRAGMA foreign_keys;").fetchone())

# Проверка наличия ключевых таблиц/FTS
tables = c.execute("""
SELECT name, type
FROM sqlite_master
WHERE name IN ('library','dict_project','source_corpus','source_document','lemma','ngram','document_sentence','sentence_fts','term_fts')
ORDER BY name;
""").fetchall()
print("key_objects =", tables)

# Проверка что schema_meta и версия на месте
schema = c.execute("SELECT value FROM schema_meta WHERE key='schema_version';").fetchone()
print("schema_version =", schema)

c.close()
