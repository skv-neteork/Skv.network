with open('/root/skv-core/src/app/multi_tenant_store.py', 'r') as f:
    content = f.read()

old = 'conn.execute("CREATE INDEX IF NOT EXISTS idx_event_id ON event_metadata(event_id)")'
new = 'conn.execute("CREATE INDEX IF NOT EXISTS idx_event_id ON event_metadata(event_id)")\n            conn.execute("CREATE INDEX IF NOT EXISTS idx_time ON event_metadata(time_str)")\n            conn.execute("CREATE INDEX IF NOT EXISTS idx_metric ON event_metadata(metric_value)")\n            conn.execute("CREATE INDEX IF NOT EXISTS idx_topics ON event_metadata(topics_json)")'

content = content.replace(old, new)

with open('/root/skv-core/src/app/multi_tenant_store.py', 'w') as f:
    f.write(content)
print('OK')
