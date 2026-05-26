import re

# Patterns to detect and replace PII
PII_PATTERNS = [
    # API keys, tokens, passwords
    (r'[a-zA-Z0-9_\-\.]{20,}', '[TOKEN]'),  # Long alphanumeric strings
    (r'(?i)(api[_-]?key|token|secret|password|passwd)\s*[:=]\s*[\'"]?[^\'"\s]+[\'"]?', r'\1=[SECRET]'),
    
    # Emails
    (r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[EMAIL]'),
    
    # IP addresses
    (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '[IP]'),
    
    # Phone numbers (various formats)
    (r'\+?\d[\d\s\-\(\)]{7,}\d', '[PHONE]'),
    
    # File paths with usernames
    (r'(/home/|/Users/|C:\\Users\\)[a-zA-Z0-9_\-]+', r'\1[USER]'),
    
    # Credit card numbers (Luhn not implemented, simple pattern)
    (r'\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b', '[CARD]'),
    
    # Social security numbers (US format)
    (r'\b\d{3}-\d{2}-\d{4}\b', '[SSN]'),
    
    # URLs with credentials
    (r'https?://[^:]+:[^@]+@', '[URL_WITH_CREDS]://'),
]

def sanitize_code(code: str) -> str:
    """Replace PII patterns with placeholders."""
    sanitized = code
    for pattern, replacement in PII_PATTERNS:
        sanitized = re.sub(pattern, replacement, sanitized)
    return sanitized

def has_pii(code: str) -> bool:
    """Check if code contains potential PII."""
    return sanitize_code(code) != code
