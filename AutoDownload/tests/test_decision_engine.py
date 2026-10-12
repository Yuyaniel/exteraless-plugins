"""决策引擎本地单元测试。

插件源码顶部的 build_config / decide 是纯函数，唯一外部依赖是
`get(key, default)`。本测试把 SDK 模块（base_plugin / ui.* / hook_utils /
client_utils）替换成桩模块后直接 exec 插件源码，因此测的是**真代码**，
不是复制品。

跑法：
    python tests/test_decision_engine.py
"""

import os
import sys
import types

PLUGIN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "auto_download.plugin"
)


# --------------------------------------------------------------------------
# SDK 桩：让插件源码能在桌面上被 exec
# --------------------------------------------------------------------------


class _Stub:
    """任意属性都能取到东西的万能桩对象。"""

    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return _Stub()

    def __call__(self, *args, **kwargs):
        return _Stub()


def _module(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


def install_stubs():
    base_plugin = _module(
        "base_plugin",
        BasePlugin=_Stub,
        HookResult=_Stub,
        HookStrategy=_Stub,
        MenuItemData=_Stub,
        MenuItemType=_Stub,
        MethodHook=_Stub,
        MethodReplacement=_Stub,
        HookFilter=_Stub,
    )
    hook_utils = _module("hook_utils", find_class=lambda name: None)
    client_utils = _module("client_utils", get_last_fragment=lambda *a, **k: None)

    ui = _module("ui")
    ui.__path__ = []  # 声明为包
    _module("ui.alert", AlertDialogBuilder=_Stub)
    _module("ui.bulletin", BulletinHelper=_Stub)
    _module("ui.settings", Header=_Stub, Divider=_Stub, Switch=_Stub,
            Selector=_Stub, Text=_Stub)
    ui.alert = sys.modules["ui.alert"]
    ui.bulletin = sys.modules["ui.bulletin"]
    ui.settings = sys.modules["ui.settings"]

    return base_plugin


def load_plugin_namespace():
    """exec 插件源码，返回其模块级命名空间。"""
    with open(PLUGIN_PATH, "r", encoding="utf-8") as handle:
        source = handle.read()
    namespace = {
        "__name__": "auto_download_under_test",
        "__file__": PLUGIN_PATH,
    }
    exec(compile(source, PLUGIN_PATH, "exec"), namespace)  # noqa: S102
    return namespace


# --------------------------------------------------------------------------
# 极简断言框架
# --------------------------------------------------------------------------

PASSED = []
FAILED = []


def check(label, actual, expected):
    if actual == expected:
        PASSED.append(label)
    else:
        FAILED.append(
            "{}\n      期望: {!r}\n      实际: {!r}".format(label, expected, actual)
        )


def section(title):
    print("\n== {} ==".format(title))


# --------------------------------------------------------------------------
# 测试
# --------------------------------------------------------------------------


def run():
    install_stubs()
    ns = load_plugin_namespace()

    build_config = ns["build_config"]
    decide = ns["decide"]
    parse_peer_index = ns["parse_peer_index"]
    SCOPE_ALL = ns["SCOPE_ALL"]
    SCOPE_MANUAL = ns["SCOPE_MANUAL"]

    def make_get(overrides=None):
        store = dict(overrides or {})
        return lambda key, default=None: store.get(key, default)

    def cfg(overrides=None):
        return build_config(make_get(overrides))

    # ---------- 日志开关 ----------
    section("日志开关的默认值")

    c = cfg()
    check("默认不记录每条消息的决策", c["log_decisions"], False)
    check("默认不完全静默", c["quiet"], False)
    check("显式打开决策日志", cfg({"log_decisions": True})["log_decisions"], True)
    check("显式打开完全静默", cfg({"quiet": True})["quiet"], True)

    # ---------- 默认规则 ----------
    section("默认规则（未单独配置的会话）")

    c = cfg()
    check("默认 scope_mode == SCOPE_ALL", c["scope_mode"], SCOPE_ALL)
    check("默认 WiFi 图片 = 开", c["defaults"]["wifi"]["photo"], True)
    check("默认 WiFi 视频 = 开", c["defaults"]["wifi"]["video"], True)
    check("默认 WiFi 文件 = 关", c["defaults"]["wifi"]["file"], False)
    check("默认 移动 图片 = 开", c["defaults"]["mobile"]["photo"], True)
    check("默认 移动 视频 = 关", c["defaults"]["mobile"]["video"], False)

    check("默认+全部会话+WiFi+图片 -> 下载", decide(c, "-1001", "wifi", "photo"), True)
    check("默认+全部会话+WiFi+视频 -> 下载", decide(c, "-1001", "wifi", "video"), True)
    check("默认+全部会话+WiFi+文件 -> 不下载", decide(c, "-1001", "wifi", "file"), False)
    check("默认+全部会话+移动+图片 -> 下载", decide(c, "-1001", "mobile", "photo"), True)
    check("默认+全部会话+移动+视频 -> 不下载", decide(c, "-1001", "mobile", "video"), False)

    # ---------- 作用范围 ----------
    section("作用范围 = 仅已添加的会话")

    c_manual = cfg({"scope_mode": SCOPE_MANUAL})
    check("未配置会话 -> 不干预(None)", decide(c_manual, "-1001", "wifi", "photo"), None)

    # ---------- 自定义优先于默认 ----------
    section("自定义配置优先于默认规则")

    c_custom = cfg(
        {
            "peer_index": '["-1001"]',
            "peer_-1001_enabled": True,
            # 默认 WiFi 视频是开的，这里显式关掉
            "peer_-1001_wifi_video": False,
            # 默认 WiFi 文件是关的，这里显式打开
            "peer_-1001_wifi_file": True,
        }
    )
    check("自定义+WiFi+图片 -> 下载", decide(c_custom, "-1001", "wifi", "photo"), True)
    check("自定义+WiFi+视频 -> 不下载（覆盖默认）",
          decide(c_custom, "-1001", "wifi", "video"), False)
    check("自定义+WiFi+文件 -> 下载（覆盖默认）",
          decide(c_custom, "-1001", "wifi", "file"), True)
    check("未覆盖的项继承默认：WiFi+音频 -> 下载",
          decide(c_custom, "-1001", "wifi", "audio"), True)
    check("未覆盖的项继承默认：移动+视频 -> 不下载",
          decide(c_custom, "-1001", "mobile", "video"), False)
    check("其它会话仍走默认：-2002 WiFi 视频 -> 下载",
          decide(c_custom, "-2002", "wifi", "video"), True)

    # ---------- 会话级禁用 ----------
    section("会话被显式禁用 -> 明确抑制")

    c_off = cfg({"peer_index": '["-1001"]', "peer_-1001_enabled": False})
    for kind in ("photo", "video", "gif", "audio", "file"):
        check(
            "禁用会话 {} -> False".format(kind),
            decide(c_off, "-1001", "wifi", kind),
            False,
        )
    check("禁用只影响该会话", decide(c_off, "-2002", "wifi", "photo"), True)

    # ---------- 总开关 ----------
    section("插件总开关")

    c_master_off = cfg({"enabled": False, "peer_index": '["-1001"]'})
    check("总开关关闭 -> 不干预(None)", decide(c_master_off, "-1001", "wifi", "photo"), None)
    check("总开关关闭 -> 不干预(None)，未配置会话",
          decide(c_master_off, "-2002", "wifi", "photo"), None)

    # ---------- 边界 ----------
    section("边界与健壮性")

    c = cfg()
    check("未知媒体类型 -> 不干预", decide(c, "-1001", "wifi", "sticker"), None)
    check("空媒体类型 -> 不干预", decide(c, "-1001", "wifi", ""), None)
    check("未知网络按移动数据", decide(c, "-1001", "ethernet", "video"), False)
    check("未知网络按移动数据（图片）", decide(c, "-1001", "ethernet", "photo"), True)

    empty_peer = cfg({"peer_index": '[""]'})
    check("空会话键被忽略", empty_peer["peers"], {})

    dup = cfg({"peer_index": '["-1","-1","-2"]'})
    check("会话键去重", sorted(dup["peers"].keys()), ["-1", "-2"])

    bad = cfg({"peer_index": "not json at all"})
    check("坏 JSON 索引 -> 空", bad["peers"], {})

    none_idx = cfg({"peer_index": None})
    check("None 索引 -> 空", none_idx["peers"], {})

    check("parse_peer_index 处理 list 输入", parse_peer_index(["-1", "-1", 2]), ["-1", "2"])

    # cfg 不被 decide 修改
    snapshot = repr(sorted(c_custom["peers"]["-1001"]["wifi"].items()))
    decide(c_custom, "-1001", "wifi", "video")
    after = repr(sorted(c_custom["peers"]["-1001"]["wifi"].items()))
    check("decide 不修改配置", after, snapshot)

    # ---------- 元数据静态性 ----------
    section("元数据与结构约束")

    check("__id__ 合法", ns["__id__"], "auto_download")
    check("__id__ 只含合法字符",
          all(ch.isalnum() or ch in "_-" for ch in ns["__id__"]), True)
    check("__id__ 长度 2-32", 2 <= len(ns["__id__"]) <= 32, True)
    check("声明了 sdk_version", ns["__sdk_version__"], ">=1.4.5.0")
    check("插件类存在", "AutoDownloadPlugin" in ns, True)
    check("插件类继承 BasePlugin",
          issubclass(ns["AutoDownloadPlugin"], ns["BasePlugin"]), True)
    check("媒体类型桶数量", len(ns["KIND_IDS"]), 5)


def main():
    run()
    print("\n" + "=" * 60)
    print("通过 {} 项，失败 {} 项".format(len(PASSED), len(FAILED)))
    if FAILED:
        print("\n失败明细：")
        for item in FAILED:
            print("  ✗ " + item)
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
