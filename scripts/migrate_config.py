# -*- coding: utf-8 -*-
"""一次性迁移：把 ~/.matlens/config.yaml 的内容并入权威 config.yaml。

背景（2026-10-15）：修复 settings_store 与 matlens_cli 的路径不一致后，
权威路径成为唯一写入目标。老配置留在 ~/.matlens/config.yaml（5045 字节 / 26 段），
若不迁移，load_settings 读权威路径时会「看不到」那些段 —— 对用户表现为
**设置全部被重置**。

迁移原则（保守，不丢数据）：
  1. 权威文件不存在 → 直接把旧文件复制过去（最干净的情况）
  2. 权威文件已存在 → 逐段深合并：**权威已有值不被旧文件覆盖**，
     只补权威缺失的键。因为 AppData 那份目前只含 agent/onboarding/network，
     而旧文件有完整 26 段，所以旧文件的内容会大量被采纳 —— 这正是期望行为。

执行前会自动备份。幂等：重复运行不会重复写入。
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, r"D:\MatLens")

import yaml  # noqa: E402

from matlens_cli.config import get_matlens_home  # noqa: E402


def backup(p: Path, tag: str) -> Path | None:
    if not p.exists():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    d = Path(r"D:\MatLens\_backup_config")
    d.mkdir(parents=True, exist_ok=True)
    dst = d / f"{tag}-{p.name}.{stamp}"
    shutil.copy2(p, dst)
    return dst


def deep_merge(dst: dict, src: dict) -> dict:
    """把 src 合进 dst：dst 已有值不被覆盖。"""
    for k, v in src.items():
        if k not in dst:
            dst[k] = v
        elif isinstance(dst[k], dict) and isinstance(v, dict):
            deep_merge(dst[k], v)
    return dst


def main() -> None:
    primary = get_matlens_home() / "config.yaml"
    legacy = Path.home() / ".matlens" / "config.yaml"

    print(f"权威路径: {primary}  exists={primary.exists()}")
    print(f"旧路径  : {legacy}  exists={legacy.exists()}")

    if not legacy.exists():
        print("\n无旧配置，无需迁移。")
        return

    b1 = backup(primary, "pre-migrate-primary")
    b2 = backup(legacy, "pre-migrate-legacy")
    for b in (b1, b2):
        if b:
            print(f"已备份: {b}")

    old = yaml.safe_load(legacy.read_text(encoding="utf-8")) or {}
    if not isinstance(old, dict):
        print("旧配置解析异常，中止。")
        return
    print(f"\n旧配置 {len(old)} 段: {sorted(old.keys())[:8]} ...")

    if not primary.exists():
        shutil.copy2(legacy, primary)
        print(f"权威文件不存在 → 已整份复制（{len(old)} 段全部就位）")
    else:
        cur = yaml.safe_load(primary.read_text(encoding="utf-8")) or {}
        before_keys = set(cur.keys()) if isinstance(cur, dict) else set()
        before_count = len(before_keys)
        merged = deep_merge(dict(cur), old)
        added = set(merged.keys()) - before_keys
        primary.write_text(
            yaml.safe_dump(merged, allow_unicode=True, sort_keys=True, default_flow_style=False),
            encoding="utf-8")
        print(f"权威文件已存在 → 深合并完成")
        print(f"  迁移前 {before_count} 段 → 迁移后 {len(merged)} 段")
        print(f"  新增段: {sorted(added) if added else '（无）'}")

    # 校验
    final = yaml.safe_load(primary.read_text(encoding="utf-8")) or {}
    print(f"\n校验：权威文件现有 {len(final)} 段")
    lost = set(old.keys()) - set(final.keys())
    print(f"  丢失的段: {sorted(lost) if lost else '无 ✓'}")


if __name__ == "__main__":
    main()
