import sys
from pathlib import Path
from unittest.mock import MagicMock
from unittest.mock import AsyncMock

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

# Mock asyncpg globally for tests — it requires a C extension that
# may not be available in the local dev environment. Tests that need
# asyncpg behavior mock it further in their own test files.
if "asyncpg" not in sys.modules:
    _mock_asyncpg = MagicMock()
    _mock_asyncpg.Pool = MagicMock
    _mock_asyncpg.create_pool = AsyncMock()
    sys.modules["asyncpg"] = _mock_asyncpg