import os
import zipfile
import tempfile
import json
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

class ProjectGenerator:
    def __init__(self):
        self.base_dir = Path(__file__).parent.parent

    def generate_zip(self, entry_data: Dict[str, Any]) -> str:
        user_fields = entry_data.get('user_fields', {})
        meta = entry_data.get('meta', {})
        project_name = user_fields.get('project_name', 'skv_project')
        files_structure = user_fields.get('files', {})
        
        if not files_structure:
            raise ValueError("Нет файлов")

        temp_dir = tempfile.mkdtemp(prefix=f"skv_{project_name}_")
        
        try:
            for file_path, file_content in files_structure.items():
                full_path = Path(temp_dir) / file_path
                full_path.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(file_content, str):
                    with open(full_path, 'w', encoding='utf-8') as f: f.write(file_content)
                elif isinstance(file_content, dict):
                    with open(full_path, 'w', encoding='utf-8') as f: json.dump(file_content, f, indent=2, ensure_ascii=False)

            if meta:
                meta_path = Path(temp_dir) / "meta.json"
                with open(meta_path, 'w', encoding='utf-8') as f:
                    json.dump({"submission_info": meta, "generated_at": datetime.utcnow().isoformat()}, f, indent=2, ensure_ascii=False)

            zip_path = self.base_dir / "storage" / f"{project_name}.zip"
            zip_path.parent.mkdir(exist_ok=True)
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        file_path = Path(root) / file
                        arcname = file_path.relative_to(temp_dir)
                        zipf.write(file_path, arcname)
            
            return str(zip_path)
        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

    def generate_txt_export(self, user_fields: Dict[str, Any]) -> str:
        project_name = user_fields.get('project_name', 'Project')
        files_structure = user_fields.get('files', {})
        insights = user_fields.get('insights', {})
        content = [f"# {project_name}", "="*60, ""]
        if 'summary' in insights: content.append(f"**Summary:** {insights['summary']}")
        if 'tags' in insights: content.append(f"**Tags:** {', '.join(insights['tags'])}")
        if 'domain' in insights: content.append(f"**Domain:** {', '.join(insights['domain'])}")
        content.extend(["", "="*60, ""])
        for file_path, file_content in files_structure.items():
            content.append(f"--- Файл: {file_path} ---")
            content.append("")
            if isinstance(file_content, str): content.append(file_content)
            elif isinstance(file_content, dict): content.append(json.dumps(file_content, indent=2, ensure_ascii=False))
            content.extend(["", ""])
        return "\n".join(content)

generator = ProjectGenerator()