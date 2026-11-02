"""Immutable, private Supabase Storage objects; local files are disposable cache."""
import hashlib
from pathlib import Path
import re
import tempfile

import httpx

from .database import PersistenceError


class SupabaseStorage:
    def __init__(self, url, key, bucket, transport=None):
        self.url = url.rstrip('/')
        self.key = key
        self.bucket = bucket
        self.transport = transport

    def request(self, method, path, **kwargs):
        try:
            with httpx.Client(timeout=60, transport=self.transport) as client:
                headers = {'apikey': self.key}
                if not self.key.startswith('sb_secret_'):
                    headers['Authorization'] = 'Bearer ' + self.key
                return client.request(method, self.url + '/storage/v1/' + path,
                                      headers={**headers, **kwargs.pop('headers', {})}, **kwargs)
        except httpx.HTTPError:
            raise PersistenceError('Cloud file storage could not be reached. No upload was acknowledged as complete.') from None

    def validate_bucket(self):
        response = self.request('GET', 'bucket/' + self.bucket)
        if response.status_code != 200:
            raise PersistenceError('Create the configured private Supabase Storage bucket and check the server storage key.')
        if response.json().get('public') is not False:
            raise PersistenceError('The archive bucket must be PRIVATE. Startup refused to expose personal files.')

    def object_path(self, sha):
        if not re.fullmatch(r'[a-f0-9]{64}', sha):
            raise ValueError('Invalid original digest.')
        return self.bucket + '/originals/' + sha

    def put(self, sha, path):
        raw = Path(path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha:
            raise PersistenceError('Original checksum mismatch before cloud upload.')
        response = self.request('POST', 'object/' + self.object_path(sha), content=raw,
                                headers={'Content-Type': 'application/octet-stream', 'x-upsert': 'false'})
        if response.status_code in (200, 201):
            return
        # Supabase versions can report existing objects using 400 or 409. Verify
        # existing bytes instead of overwriting, regardless of response body wording.
        if response.status_code in (400, 409):
            if self.get(sha) == raw:
                return
        raise PersistenceError('Cloud original upload failed. No database import was acknowledged; retry after checking storage.')

    def get(self, sha):
        response = self.request('GET', 'object/authenticated/' + self.object_path(sha))
        if response.status_code != 200:
            raise PersistenceError('Original unavailable in private cloud storage. Restore from backup or check access.')
        raw = response.content
        if hashlib.sha256(raw).hexdigest() != sha:
            raise PersistenceError('Cloud original failed checksum verification. It was not used.')
        return raw

    def cache(self, sha, path):
        path = Path(path)
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == sha:
            return path
        raw = self.get(sha)
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
            temp = Path(output.name)
            try:
                output.write(raw)
                output.flush()
                temp.replace(path)
            finally:
                temp.unlink(missing_ok=True)
        return path
