"""Persistent dedup store: story hashes survive within a Cloud Run instance by
being mirrored to Firestore (local seen.json alone is wiped on restart)."""

import importlib.util
import os
import sys
from pathlib import Path

import pytest


def _load_monitor_module():
    spec = importlib.util.spec_from_file_location(
        "monitor_tested", str(Path(__file__).resolve().parent.parent / "agents" / "monitor" / "monitor.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["monitor_tested"] = module
    spec.loader.exec_module(module)
    return module


class _FakeBatch:
    def __init__(self, store):
        self.store = store
        self.pending = {}

    def set(self, ref, data, merge=True):
        self.pending[ref._path] = data

    def commit(self):
        for path, data in self.pending.items():
            self.store[path] = data
        self.pending = {}


class _FakeCollection:
    def __init__(self, store, prefix):
        self.store = store
        self.prefix = prefix

    def document(self, story_id):
        return _FakeRef(f"{self.prefix}/{story_id}", self.store)

    def list_documents(self):
        return [_FakeRef(p, self.store) for p in self.store if p.startswith(self.prefix + "/")]


class _FakeRef:
    def __init__(self, path, store):
        self._path = path
        self._store = store

    @property
    def id(self):
        return self._path.rsplit("/", 1)[-1]


class _FakeDb:
    def __init__(self):
        self.store = {}

    def collection(self, name):
        return _FakeCollection(self.store, name)

    def batch(self):
        return _FakeBatch(self.store)


@pytest.fixture
def cloud_enabled(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-proj")
    fake = _FakeDb()
    monkeypatch.setattr("google.cloud.firestore.Client", lambda project=None: fake)
    return fake


def test_seen_docs_reuse_set_across_loads(monkeypatch, cloud_enabled):
    module = _load_monitor_module()
    # First run marks two stories seen in the cloud.
    module.cloud_mark_seen_ids({"aaaa1111aaaa1111", "bbbb2222bbbb2222"})
    # A later run loads those same ids back and they are now in the set.
    seen = module.cloud_seen_ids()
    assert "aaaa1111aaaa1111" in seen
    assert "bbbb2222bbbb2222" in seen


def test_mark_seen_is_idempotent(monkeypatch, cloud_enabled):
    module = _load_monitor_module()
    module.cloud_mark_seen_ids({"cccc3333cccc3333"})
    module.cloud_mark_seen_ids({"cccc3333cccc3333"})
    assert module.cloud_seen_ids() == {"cccc3333cccc3333"}


def test_no_project_skips_cloud(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    module = _load_monitor_module()
    assert module.cloud_seen_ids() == set()
    module.cloud_mark_seen_ids({"dddd4444dddd4444"})  # must not raise