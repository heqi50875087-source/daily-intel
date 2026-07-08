#!/usr/bin/env python3
"""原子写 JSON:先写同目录 .tmp 再 os.replace,进程中断不再留半截损坏文件。
守护回退:原子路径任何异常时退回旧的直写行为(与历史行为一致),绝不让定时任务因此崩掉。"""
import json, os, sys


def save_json(obj, path):
    path = str(path)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        print(f"⚠ 原子写失败({type(e).__name__}),回退直写: {path}", file=sys.stderr)
        try:
            os.remove(tmp)
        except OSError:
            pass
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    import tempfile
    d = tempfile.mkdtemp()
    p = os.path.join(d, "t.json")
    save_json({"中": 1}, p)
    assert json.load(open(p, encoding="utf-8")) == {"中": 1}
    assert not os.path.exists(p + ".tmp")
    print("jsonio selfcheck ok")
