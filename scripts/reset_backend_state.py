from __future__ import annotations

import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PIPELINE_ROOT = ROOT / "pipelineIQ"
if str(PIPELINE_ROOT) not in sys.path:
    sys.path.insert(0, str(PIPELINE_ROOT))

from services.state_reset import clear_backend_state, clear_runtime_state


async def main() -> None:
    await clear_backend_state()
    clear_runtime_state()
    print("Backend state cleared.")


if __name__ == "__main__":
    asyncio.run(main())
