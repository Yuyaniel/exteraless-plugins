"""过滤规则引擎本地单元测试。

插件源码顶部的 find_matches / filter_message / shift_entities 等是纯函数，
零 SDK 依赖。本测试把 SDK 模块替换成桩模块后直接 exec 插件源码，
因此测的是**真代码**，不是复制品。

跑法：
    python tests/test_filter_engine.py
"""

import ast
import os
import re
import sys
import types

PLUGIN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "message_filter.plugin"
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


class _MenuTypeStub:
    """MenuItemType 的替身：插件在模块级就用到了它的枚举属性。"""

    MESSAGE_CONTEXT_MENU = "MESSAGE_CONTEXT_MENU"
    DRAWER_MENU = "DRAWER_MENU"
    MAIN_MENU = "MAIN_MENU"
    CHAT_ACTION_MENU = "CHAT_ACTION_MENU"
    PROFILE_ACTION_MENU = "PROFILE_ACTION_MENU"


def _module(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


def install_stubs():
    _module(
        "base_plugin",
        BasePlugin=_Stub,
        HookResult=_Stub,
        HookStrategy=_Stub,
        MenuItemData=_Stub,
        # 纯函数测试也要能 exec 整个文件，菜单枚举得是真类属性
        MenuItemType=_MenuTypeStub,
        MethodHook=_Stub,
        HookFilter=_Stub,
    )
    _module("client_utils", get_last_fragment=lambda *args, **kwargs: None)
    ui = _module("ui")
    ui.__path__ = []  # 声明为包
    _module("ui.alert", AlertDialogBuilder=_Stub, ALERT_TYPE_MESSAGE=0)
    _module("ui.bulletin", BulletinHelper=_Stub)
    _module(
        "ui.settings",
        Header=_Stub,
        Divider=_Stub,
        Switch=_Stub,
        Selector=_Stub,
        Input=_Stub,
        EditText=_Stub,
        Text=_Stub,
    )
    ui.alert = sys.modules["ui.alert"]
    ui.bulletin = sys.modules["ui.bulletin"]
    ui.settings = sys.modules["ui.settings"]


def load_plugin_namespace():
    """exec 插件源码，返回其模块级命名空间。"""
    with open(PLUGIN_PATH, "r", encoding="utf-8") as handle:
        source = handle.read()
    namespace = {"__name__": "message_filter_under_test", "__file__": PLUGIN_PATH}
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


def rule(rid="r1", mode=0, pattern="", replacement="", case_sensitive=True, target=0):
    return {
        "id": rid,
        "mode": mode,
        "pattern": pattern,
        "replacement": replacement,
        "case_sensitive": case_sensitive,
        "target": target,
    }


def run():
    install_stubs()
    ns = load_plugin_namespace()

    parse_index = ns["parse_index"]
    validate_pattern = ns["validate_pattern"]
    find_matches = ns["find_matches"]
    apply_matches = ns["apply_matches"]
    filter_message = ns["filter_message"]
    map_pos = ns["map_pos"]
    shift_entities = ns["shift_entities"]
    target_allows = ns["target_allows"]
    MODE_CHARS = ns["MODE_CHARS"]
    MODE_REGEX = ns["MODE_REGEX"]
    POS_SUFFIX = ns["POS_SUFFIX"]
    EMPTY_KEEP_EMPTY = ns["EMPTY_KEEP_EMPTY"]
    EMPTY_ABORT = ns["EMPTY_ABORT"]
    TARGET_OUT = ns["TARGET_OUT"]
    TARGET_BOTH = ns["TARGET_BOTH"]

    section("索引解析")
    check("合法 JSON 数组", parse_index('["r1","r2"]'), ["r1", "r2"])
    check("去重", parse_index('["r1","r1"]'), ["r1"])
    check("非法输入", parse_index("not json"), [])
    check("非数组", parse_index('{"a":1}'), [])
    check("空串元素被丢弃", parse_index('["r1","  "]'), ["r1"])

    section("规则校验")
    check("空内容报错", validate_pattern(0, "") is not None, True)
    check("词组合法", validate_pattern(0, "abc"), None)
    check("正则合法", validate_pattern(MODE_REGEX, r"\d+"), None)
    check("正则非法", validate_pattern(MODE_REGEX, "([") is not None, True)

    section("匹配：词组")
    check("基本", find_matches("hello world", 0, "world", True), [(6, 11)])
    check("多处", find_matches("ab ab", 0, "ab", True), [(0, 2), (3, 5)])
    check("区分大小写时不匹配", find_matches("ABC", 0, "abc", True), [])
    check("忽略大小写时匹配", find_matches("ABC", 0, "abc", False), [(0, 3)])
    check("空文本", find_matches("", 0, "a", True), [])
    check("空模式", find_matches("abc", 0, "", True), [])

    section("匹配：字符集合")
    check("逐字符", find_matches("a1b2", MODE_CHARS, "12", True), [(1, 2), (3, 4)])
    check("无命中", find_matches("abc", MODE_CHARS, "xyz", True), [])

    section("匹配：正则")
    check("数字", find_matches("a12b345", MODE_REGEX, r"\d+", True), [(1, 3), (4, 7)])
    check("非法正则返回空", find_matches("abc", MODE_REGEX, "([", True), [])
    check(
        "忽略大小写",
        find_matches("AbC", MODE_REGEX, "abc", False),
        [(0, 3)],
    )

    section("应用匹配")
    check("删除", apply_matches("hello world", [(5, 11, "")]), "hello")
    check("替换", apply_matches("hello world", [(6, 11, "***")]), "hello ***")
    check("空列表原样返回", apply_matches("abc", []), "abc")

    section("过滤：单条规则")
    check(
        "删掉词组",
        filter_message("前面 广告 后面", [rule(pattern="广告")])[0],
        "前面  后面",
    )
    check(
        "替换为指定文本",
        filter_message("密码是 12345", [rule(pattern="12345", replacement="****")])[0],
        "密码是 ****",
    )
    check("未命中原样返回", filter_message("正常消息", [rule(pattern="广告")])[0], "正常消息")
    check("未命中时 removals 为空", filter_message("正常消息", [rule(pattern="广告")])[1], [])
    check("空规则列表原样返回", filter_message("abc", [])[0], "abc")

    section("过滤：多规则与优先级")
    rules = [rule("r1", pattern="bad"), rule("r2", pattern="worse")]
    text, removals, _prefix, matched = filter_message("a bad b worse c", rules)
    check("两条都生效", text, "a  b  c")
    check("命中顺序", matched, ["r1", "r2"])
    check("removals 都是原文坐标", removals, [(2, 5, ""), (8, 13, "")])

    # 后面的规则不能重复处理已被前面删掉的区间
    overlap = [rule("r1", MODE_REGEX, pattern=r"\d+"), rule("r2", pattern="123")]
    check(
        "重叠区间只被处理一次",
        filter_message("x123y", overlap)[0],
        "xy",
    )
    check("第二条规则不再命中", filter_message("x123y", overlap)[3], ["r1"])

    section("过滤：标记")
    check(
        "前缀标记",
        filter_message("a删我b", [rule(pattern="删我")], marker="🚫")[0],
        "🚫ab",
    )
    check(
        "整条删空时占位文本也带标记",
        filter_message("删我", [rule(pattern="删我")], marker="🚫")[0],
        "🚫（已过滤）",
    )
    check(
        "前缀标记会返回 prefix_len",
        filter_message("a删我b", [rule(pattern="删我")], marker=">>")[2],
        2,
    )
    check(
        "后缀标记",
        filter_message("a删我b", [rule(pattern="删我")], marker="!", marker_position=POS_SUFFIX)[0],
        "ab!",
    )
    check(
        "未改动时不加标记",
        filter_message("正常", [rule(pattern="广告")], marker="🚫")[0],
        "正常",
    )

    section("过滤：清空后的处置")
    full = [rule("r1", MODE_REGEX, pattern=r".+")]
    check("占位文本（默认）", filter_message("abc", full)[0], "（已过滤）")
    check("留空", filter_message("abc", full, on_empty=EMPTY_KEEP_EMPTY)[0], "")
    check("放弃修改", filter_message("abc", full, on_empty=EMPTY_ABORT)[0], "abc")
    check("放弃修改时不算改动", filter_message("abc", full, on_empty=EMPTY_ABORT)[1], [])

    section("坐标换算 map_pos")
    removals = [(2, 5, "")]  # 原文 [2,5) 被删
    check("区间前的点不动", map_pos(0, removals), 0)
    check("区间起点", map_pos(2, removals), 2)
    check("区间内的点塌缩", map_pos(3, removals), 2)
    check("区间后的点左移", map_pos(5, removals), 2)
    check("远处的点左移 3", map_pos(10, removals), 7)
    check("替换为更长文本时右移", map_pos(10, [(2, 5, "*****")]), 12)

    section("实体偏移换算")
    # 原文: "hello bold world"，bold 在 [6,10)
    ents = [(6, 4)]
    check("删除在实体之后，实体不动", shift_entities(ents, [(11, 16, "")]), [(0, 6, 4)])
    check("删除在实体之前，实体左移", shift_entities(ents, [(0, 6, "")]), [(0, 0, 4)])
    check("实体被完全删掉则丢弃", shift_entities(ents, [(5, 11, "")]), [])
    check("部分重叠则缩短", shift_entities(ents, [(8, 12, "")]), [(0, 6, 2)])
    check("前缀标记使实体右移", shift_entities(ents, [], 2), [(0, 8, 4)])
    check("多实体", shift_entities([(0, 3), (6, 4)], [(3, 6, "")]), [(0, 0, 3), (1, 3, 4)])

    section("作用方向")
    check("仅收 作用于 in", target_allows(0, "in"), True)
    check("仅收 不作用于 out", target_allows(0, "out"), False)
    check("仅发 作用于 out", target_allows(TARGET_OUT, "out"), True)
    check("仅发 不作用于 in", target_allows(TARGET_OUT, "in"), False)
    check("收发 都作用", (target_allows(TARGET_BOTH, "in"), target_allows(TARGET_BOTH, "out")), (True, True))

    scope_allows = ns["scope_allows"]
    parse_peer_key = ns["parse_peer_key"]

    section("规则作用范围")
    check("空 scope 是全局", scope_allows("", "-100123"), True)
    check("星号也是全局", scope_allows("*", "-100123"), True)
    check("会话规则命中本会话", scope_allows("-100123", "-100123"), True)
    check("会话规则不命中别的会话", scope_allows("-100123", "-100456"), False)
    check("拿不到会话时不生效", scope_allows("-100123", ""), False)
    check("拿不到会话时全局仍生效", scope_allows("", ""), True)

    section("会话键解析")
    check("正常值", parse_peer_key(-100123), "-100123")
    check("字符串值", parse_peer_key("42"), "42")
    check("零表示取不到", parse_peer_key(0), "")
    check("None 表示取不到", parse_peer_key(None), "")
    check("脏值表示取不到", parse_peer_key("abc"), "")

    section("元数据与结构约束")
    with open(PLUGIN_PATH, "r", encoding="utf-8") as handle:
        source = handle.read()
    tree = ast.parse(source)
    meta = {
        node.targets[0].id: node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id.startswith("__")
    }
    check("id 存在", "__id__" in meta, True)
    check("name 存在", "__name__" in meta, True)
    check("id 与文件名一致", meta["__id__"].value, "message_filter")
    for key, node in meta.items():
        check("{} 是单个字面量".format(key), isinstance(node, ast.Constant), True)

    # Selector 不接受 subtext（SDK 实测），传了会让设置页整体抛异常
    bad_selector = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Selector"
        for kw in node.keywords
        if kw.arg == "subtext"
    ]
    check("没有给 Selector 传 subtext", bad_selector, [])

    # 死代码：模块级常量是否真的被引用（出现次数 < 2 = 只有定义）
    mod_consts = [
        node.targets[0].id
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id.isupper()
    ]
    unused = [
        name
        for name in mod_consts
        if len(re.findall(r"(?<![\.\w])" + re.escape(name) + r"\b", source)) < 2
    ]
    check("没有未使用的模块级常量", sorted(unused), [])


def main():
    run()
    print("\n" + "=" * 60)
    print("通过 {} 项，失败 {} 项".format(len(PASSED), len(FAILED)))
    if FAILED:
        for item in FAILED:
            print("  ✗ {}".format(item))
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
