from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path('data')
    api_key: str = field(default='', repr=False)
    model: str = ''
    base_url: str = 'https://api.featherless.ai/v1'
    access_token: str = field(default='', repr=False)
    timeout: float = 120
    max_output_tokens: int = 2048
    context_characters: int = 24000
    database_url: str = field(default='', repr=False)
    database_password: str = field(default='', repr=False)
    supabase_url: str = ''
    supabase_key: str = field(default='', repr=False)
    storage_bucket: str = 'ezra-private'

    def __post_init__(self):
        parsed = urlparse(self.base_url)
        if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Use an HTTP(S) inference URL without credentials, query, or fragment.')
        if parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('Remote inference requires HTTPS.')
        if self.timeout <= 0 or self.max_output_tokens <= 0 or self.context_characters < 1000:
            raise ValueError('Invalid inference timeout or context/output budget.')
        if self.database_url:
            database = urlparse(self.database_url.replace('[YOUR-PASSWORD]', '').replace('[YOUR_PASSWORD]', ''))
            if database.scheme not in ('postgres', 'postgresql') or not database.hostname:
                raise ValueError('EZRA_DATABASE_URL must be a PostgreSQL connection URL.')
            if database.hostname.endswith('.pooler.supabase.com') and database.port == 6543:
                raise ValueError('Use Supabase Session pooler on port 5432, not Transaction pooler on 6543.')
            storage = urlparse(self.supabase_url)
            if storage.scheme != 'https' or not storage.hostname or storage.username or storage.password or storage.query or storage.fragment or storage.path not in ('', '/') or not self.supabase_key:
                raise ValueError('Cloud database mode also requires HTTPS SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY.')
            if len(self.access_token) < 24:
                raise ValueError('Cloud mode requires EZRA_ACCESS_TOKEN of at least 24 characters.')
        elif self.supabase_url or self.supabase_key or self.database_password:
            raise ValueError('Supabase storage requires EZRA_DATABASE_URL; partial cloud configuration is refused.')
        import re
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', self.storage_bucket):
            raise ValueError('Use a simple private storage bucket name.')

    @classmethod
    def from_env(cls):
        return cls(
            data_dir=Path(os.getenv('EZRA_DATA_DIR', 'data')).expanduser().resolve(),
            api_key=os.getenv('FEATHERLESS_API_KEY', ''),
            model=os.getenv('FEATHERLESS_MODEL', ''),
            base_url=os.getenv('FEATHERLESS_BASE_URL', 'https://api.featherless.ai/v1'),
            access_token=os.getenv('EZRA_ACCESS_TOKEN', ''),
            timeout=float(os.getenv('EZRA_INFERENCE_TIMEOUT', '120')),
            max_output_tokens=int(os.getenv('EZRA_MAX_OUTPUT_TOKENS', '2048')),
            context_characters=int(os.getenv('EZRA_CONTEXT_CHARACTERS', '24000')),
            database_url=os.getenv('EZRA_DATABASE_URL', ''),
            database_password=os.getenv('EZRA_DATABASE_PASSWORD', ''),
            supabase_url=os.getenv('SUPABASE_URL', ''),
            supabase_key=os.getenv('SUPABASE_SERVICE_ROLE_KEY', ''),
            storage_bucket=os.getenv('SUPABASE_STORAGE_BUCKET', 'ezra-private'),
        )
