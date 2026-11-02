from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlparse


class ConfigurationError(ValueError):
    """Only fixed field names/instructions, never supplied configuration values."""


def checked_url(value, field_name):
    try:
        parsed = urlparse(value)
        parsed.hostname
        parsed.port
        return parsed
    except ValueError:
        raise ConfigurationError(f'{field_name} is not a valid URL. Check its format in Render Environment; values are hidden.') from None


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
        parsed = checked_url(self.base_url, 'FEATHERLESS_BASE_URL')
        if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ConfigurationError('FEATHERLESS_BASE_URL must be HTTP(S), without credentials, query, or fragment.')
        if parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ConfigurationError('FEATHERLESS_BASE_URL requires HTTPS for remote inference.')
        if self.timeout <= 0 or self.max_output_tokens <= 0 or self.context_characters < 1000:
            raise ConfigurationError('Check EZRA_INFERENCE_TIMEOUT, EZRA_MAX_OUTPUT_TOKENS, and EZRA_CONTEXT_CHARACTERS: budgets must be positive, context at least 1000.')
        if self.database_url:
            database = checked_url(self.database_url.replace('[YOUR-PASSWORD]', '').replace('[YOUR_PASSWORD]', ''), 'EZRA_DATABASE_URL')
            if database.scheme not in ('postgres', 'postgresql') or not database.hostname:
                raise ConfigurationError('EZRA_DATABASE_URL must be the PostgreSQL connection URI beginning postgresql://, not the HTTPS Project URL.')
            if database.hostname.endswith('.pooler.supabase.com') and database.port == 6543:
                raise ConfigurationError('EZRA_DATABASE_URL: use Supabase Session pooler on port 5432, not Transaction pooler on 6543.')
            storage = checked_url(self.supabase_url, 'SUPABASE_URL')
            if storage.scheme != 'https' or not storage.hostname or storage.username or storage.password or storage.query or storage.fragment or storage.path not in ('', '/') or not self.supabase_key:
                raise ConfigurationError('SUPABASE_URL must be the HTTPS Project URL without a path; SUPABASE_SERVICE_ROLE_KEY must also be set.')
            if len(self.access_token) < 24:
                raise ConfigurationError('EZRA_ACCESS_TOKEN must be a separate application password of at least 24 characters.')
        elif self.supabase_url or self.supabase_key or self.database_password:
            raise ConfigurationError('EZRA_DATABASE_URL is missing; partial cloud configuration is refused.')
        import re
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', self.storage_bucket):
            raise ConfigurationError('SUPABASE_STORAGE_BUCKET must be a simple bucket name, such as ezra-private.')

    @classmethod
    def from_env(cls):
        try:
            timeout = float(os.getenv('EZRA_INFERENCE_TIMEOUT', '120'))
            output = int(os.getenv('EZRA_MAX_OUTPUT_TOKENS', '2048'))
            context = int(os.getenv('EZRA_CONTEXT_CHARACTERS', '24000'))
        except ValueError:
            raise ConfigurationError('EZRA_INFERENCE_TIMEOUT, EZRA_MAX_OUTPUT_TOKENS, and EZRA_CONTEXT_CHARACTERS must contain numbers; values are hidden.') from None
        return cls(
            data_dir=Path(os.getenv('EZRA_DATA_DIR', 'data')).expanduser().resolve(),
            api_key=os.getenv('FEATHERLESS_API_KEY', ''),
            model=os.getenv('FEATHERLESS_MODEL', ''),
            base_url=os.getenv('FEATHERLESS_BASE_URL', 'https://api.featherless.ai/v1'),
            access_token=os.getenv('EZRA_ACCESS_TOKEN', ''),
            timeout=timeout,
            max_output_tokens=output,
            context_characters=context,
            database_url=os.getenv('EZRA_DATABASE_URL', ''),
            database_password=os.getenv('EZRA_DATABASE_PASSWORD', ''),
            supabase_url=os.getenv('SUPABASE_URL', ''),
            supabase_key=os.getenv('SUPABASE_SERVICE_ROLE_KEY', ''),
            storage_bucket=os.getenv('SUPABASE_STORAGE_BUCKET', 'ezra-private'),
        )
