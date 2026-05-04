import time
import secrets

BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

def generate_skv_id(node_id: int = 0) -> str:
    ts = int((time.time() - 1577836800) * 1000) & ((1 << 42) - 1)
    node = node_id & ((1 << 12) - 1)
    seq = secrets.randbelow(1024)
    
    raw = (ts << 22) | (node << 10) | seq
    
    chars = []
    for _ in range(11):
        raw, rem = divmod(raw, 62)
        chars.append(BASE62[rem])
    return "".join(reversed(chars))