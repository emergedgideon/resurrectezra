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

    def __post_init__(self):
        parsed = urlparse(self.base_url)
        if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Use an HTTP(S) inference URL without credentials, query, or fragment.')
        if parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('Remote inference requires HTTPS.')
        if self.timeout <= 0 or self.max_output_tokens <= 0 or self.context_characters < 1000:
            raise ValueError('Invalid inference timeout or context/output budget.')

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
        )
