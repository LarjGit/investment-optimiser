from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from importlib import resources
import json
from typing import Any


DEFAULT_POLICY_PACK_VERSION = "v1"

_POLICY_PACK_DATA_FILES: dict[str, str] = {
    DEFAULT_POLICY_PACK_VERSION: "policy_pack_v1.json",
}


@lru_cache(maxsize=None)
def _load_policy_pack_once(version: str) -> dict[str, Any]:
    data_file = _POLICY_PACK_DATA_FILES.get(version)
    if data_file is None:
        raise ValueError(f"Unsupported policy pack version: {version}")

    raw_policy_pack = (
        resources.files("investment_optimiser")
        .joinpath(data_file)
        .read_text(encoding="utf-8")
    )
    policy_pack = json.loads(raw_policy_pack)

    if policy_pack.get("policy_version") != version:
        raise ValueError(
            "Policy pack contents do not match the requested version: "
            f"{version}"
        )

    return policy_pack


def load_policy_pack(version: str = "v1") -> dict[str, Any]:
    return deepcopy(_load_policy_pack_once(version))


def dump_policy_pack_json(version: str = "v1") -> str:
    policy_pack = _load_policy_pack_once(version)
    return json.dumps(policy_pack, indent=2, sort_keys=True) + "\n"
