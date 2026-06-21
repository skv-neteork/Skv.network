import json
import sys
sys.path.insert(0, '/root/skv-core/src/app')
from multi_tenant_store import MultiTenantMetadataStore

store = MultiTenantMetadataStore(base_dir='/data/skv/metadata_store')

with open('/tmp/const_cubes.txt', 'r') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        parts = line.split('|')
        if len(parts) >= 3:
            cube_id = parts[0]
            title = parts[1]
            content = parts[2]
            try:
                data = json.loads(content)
                text = data.get('text', content)
            except:
                text = content
            store.write_metadata(
                user_id='shared_master',
                event_id=cube_id,
                time_str='constitutional',
                essence=title,
                messages_count=0,
                topics=['constitutional'],
                links=[],
                raw_dialogue=text,
                is_shared=True
            )
            print(f'Done: {cube_id}')

print('All constitutional cubes saved')
