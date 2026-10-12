"""适配层集成测试。

纯函数测试覆盖不到的部分全在这里：钩子注册、设置键读写、规则增删改、
TL 对象识别、实体重建、设置页构建。用假对象替换 SDK 后直接跑真插件类。

跑法：
    python tests/test_plugin_adapter.py
"""

import os
import sys
import tempfile
import types

PLUGIN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "message_filter.plugin"
)


# --------------------------------------------------------------------------
# 假 SDK
# --------------------------------------------------------------------------


class FakeHookStrategy:
    DEFAULT = 0
    CANCEL = 1
    MODIFY = 2
    MODIFY_FINAL = 3


class FakeHookResult:
    def __init__(self, strategy=None, request=None, response=None, update=None,
                 updates=None, params=None):
        self.strategy = strategy
        self.request = request
        self.response = response
        self.update = update
        self.updates = updates
        self.params = params


class FakeBasePlugin:
    """够用的 BasePlugin 替身：设置存字典，钩子登记下来。"""

    def __init__(self):
        self.version = "1.0.0"
        self.settings = {}
        self.reloads = []
        self.hooks = []
        self.send_hook = False
        self.logs = []
        self.menu_items = []

    # --- 设置 ---
    def get_setting(self, key, default=None):
        return self.settings.get(key, default)

    def set_setting(self, key, value, reload_settings=False):
        self.settings[key] = value
        self.reloads.append((key, reload_settings))

    # --- 钩子 ---
    def add_hook(self, name, *args, **kwargs):
        self.hooks.append(name)

    def add_on_send_message_hook(self):
        self.send_hook = True

    # --- 菜单 ---
    def add_menu_item(self, data):
        self.menu_items.append(data)
        return "menu-{}".format(len(self.menu_items))

    def remove_menu_item(self, item_id):
        return True

    # --- 日志（故意不提供 logger，验证回退路径）---
    def log(self, message):
        self.logs.append(message)


class FakeBulletin:
    def __init__(self):
        self.calls = []

    def show_info(self, message, *args, **kwargs):
        self.calls.append(("info", message))
        return self

    def show_error(self, message, *args, **kwargs):
        self.calls.append(("error", message))
        return self

    def show_success(self, message, *args, **kwargs):
        self.calls.append(("success", message))
        return self

    @property
    def last(self):
        return self.calls[-1] if self.calls else None


class FakeSetting:
    """记录构造参数，用来断言设置页结构。"""

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __repr__(self):
        return "{}({})".format(type(self).__name__, self.kwargs.get("key"))


class FakeArrayList:
    def __init__(self):
        self.items = []

    def add(self, item):
        self.items.append(item)


class FakeEntity:
    def __init__(self, offset, length):
        self.offset = offset
        self.length = length


class ReadOnlyEntity:
    """offset / length 写不进去的实体 —— 用来模拟"实体重排失败"。"""

    def __init__(self, offset, length):
        self._offset = offset
        self._length = length

    @property
    def offset(self):
        return self._offset

    @property
    def length(self):
        return self._length


class FakeEntityList:
    def __init__(self, items):
        self._items = list(items)

    def size(self):
        return len(self._items)

    def get(self, index):
        return self._items[index]


class FakeMessage:
    def __init__(self, text, entities=None, dialog_id=0):
        self.message = text
        self.entities = entities
        self.dialog_id = dialog_id


class FakePeerChannel:
    """TL_peerChannel 风格：内部 id 是裸 channel_id（不带 -100 前缀）。"""

    def __init__(self, channel_id):
        self.channel_id = channel_id


class FakePeerUser:
    def __init__(self, user_id):
        self.user_id = user_id


class FakeTLMessage:
    """更接近真机的消息：正文在 message，会话靠 peer_id，没有 dialog_id 字段。"""

    def __init__(self, text, channel_id=0, user_id=0):
        self.message = text
        self.entities = None
        if channel_id:
            self.peer_id = FakePeerChannel(channel_id)
        elif user_id:
            self.peer_id = FakePeerUser(user_id)


class FakeOwner:
    """MessageObject.messageOwner 风格：正文与 entities 都在这里。"""

    def __init__(self, text, entities=None):
        self.message = text
        self.entities = entities


class FakeWrapper:
    """MessageObject 风格：正文在 messageText，实体在 messageOwner 里。"""

    def __init__(self, text, entities=None):
        self.messageText = text
        self.messageOwner = FakeOwner(text, entities)


class _FakeField:
    """java.lang.reflect.Field 替身：值存在对象自己的 _values 里。"""

    def __init__(self, name):
        self.name = name

    def setAccessible(self, flag):
        return None

    def get(self, obj):
        return obj._values[self.name]

    def set(self, obj, value):
        obj._values[self.name] = value


class _FakeClass:
    """getDeclaredField 只认 message —— 用来模拟"只能靠反射读字段"的宿主。"""

    NAMES = ("message",)

    def getDeclaredField(self, name):
        if name in self.NAMES:
            return _FakeField(name)
        raise AttributeError(name)

    def getSuperclass(self):
        return None


class ReflectedMessage:
    """字段读不到、必须走反射的对象。

    对应参考插件在真机上的结论：hook_utils / 属性访问对这些 TL 对象不工作，
    只能 `obj.getClass().getDeclaredField(...)`。
    """

    def __init__(self, text):
        object.__setattr__(self, "_values", {"message": text})

    def getClass(self):
        return _FakeClass()

    def __getattr__(self, name):
        raise AttributeError(name)

    def __setattr__(self, name, value):
        raise AttributeError(name)


class FakeChat:
    def __init__(self, title):
        self.title = title


class FakeActivity:
    pass


class FakeFragment:
    def __init__(self, activity):
        self._activity = activity

    def getParentActivity(self):
        return self._activity


class FakeHashMap:
    """java.util.HashMap 替身：只有 get()/size()，没有 keys()/len()。"""

    def __init__(self, data=None):
        self._data = dict(data or {})

    def get(self, key, default=None):
        return self._data.get(key, default)

    def size(self):
        return len(self._data)


class FakeUpdate:
    def __init__(self, message):
        self.message = message


class FakeContainer:
    def __init__(self, updates):
        self.updates = FakeEntityList(updates)


class FakeParams:
    def __init__(self, message):
        self.message = message


def _module(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


class FakeMenuType:
    MESSAGE_CONTEXT_MENU = "MESSAGE_CONTEXT_MENU"
    DRAWER_MENU = "DRAWER_MENU"
    MAIN_MENU = "MAIN_MENU"
    CHAT_ACTION_MENU = "CHAT_ACTION_MENU"
    PROFILE_ACTION_MENU = "PROFILE_ACTION_MENU"


class FakeMenuItemData:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeAlertBuilder:
    """记录弹窗调用，并可手动触发已注册的监听。"""

    instances = []

    def __init__(self, activity, *args, **kwargs):
        self.activity = activity
        self.title = None
        self.items = None
        self.item_listener = None
        self.view = None
        self.buttons = {}
        self.shown = False
        self.dismissed = False
        FakeAlertBuilder.instances.append(self)

    def set_title(self, title):
        self.title = title
        return self

    def set_items(self, items, listener=None, icons=None):
        self.items = list(items)
        self.item_listener = listener
        return self

    def set_view(self, view, height=-2):
        self.view = view
        return self

    def set_positive_button(self, text, listener=None):
        self.buttons["positive"] = (text, listener)
        return self

    def set_negative_button(self, text, listener=None):
        self.buttons["negative"] = (text, listener)
        return self

    def set_neutral_button(self, text, listener=None):
        self.buttons["neutral"] = (text, listener)
        return self

    def show(self):
        self.shown = True
        return self

    def dismiss(self):
        self.dismissed = True
        return self

    def click_item(self, which):
        if self.item_listener is not None:
            self.item_listener(self, which)

    def click_button(self, name):
        text, listener = self.buttons[name]
        if listener is not None:
            listener(self, -1)


class FakeEditText:
    def __init__(self, context):
        self.context = context
        self.hint = None
        self.text = ""

    def setHint(self, hint):
        self.hint = hint

    def setText(self, text):
        self.text = text

    def getText(self):
        return self.text


def install_stubs():
    _module(
        "base_plugin",
        BasePlugin=FakeBasePlugin,
        HookResult=FakeHookResult,
        HookStrategy=FakeHookStrategy,
        MenuItemData=FakeMenuItemData,
        MenuItemType=FakeMenuType,
    )
    _module("client_utils", get_last_fragment=lambda *args, **kwargs: None)
    bulletin = FakeBulletin()
    ui = _module("ui")
    ui.__path__ = []
    _module("ui.alert", AlertDialogBuilder=FakeAlertBuilder)
    _module("ui.bulletin", BulletinHelper=bulletin)
    _module(
        "ui.settings",
        Header=FakeSetting,
        Divider=FakeSetting,
        Switch=FakeSetting,
        Selector=FakeSetting,
        Input=FakeSetting,
        EditText=FakeSetting,
        Text=FakeSetting,
    )
    ui.alert = sys.modules["ui.alert"]
    ui.bulletin = sys.modules["ui.bulletin"]
    ui.settings = sys.modules["ui.settings"]

    android = _module("android")
    android.__path__ = []
    _module("android.widget", EditText=FakeEditText)
    android.widget = sys.modules["android.widget"]

    java = _module("java")
    java.__path__ = []
    _module("java.util", ArrayList=FakeArrayList)
    java.util = sys.modules["java.util"]

    return bulletin


def load_plugin():
    """exec 插件源码并注册成 message_filter 模块，返回插件实例。"""
    with open(PLUGIN_PATH, "r", encoding="utf-8") as handle:
        source = handle.read()
    namespace = {
        "__name__": "message_filter",
        # 报告写进临时目录，别污染仓库
        "__file__": os.path.join(tempfile.mkdtemp(), "message_filter.plugin"),
    }
    exec(compile(source, PLUGIN_PATH, "exec"), namespace)  # noqa: S102

    module = types.ModuleType("message_filter")
    module.__dict__.update(namespace)
    sys.modules["message_filter"] = module

    plugin = namespace["MessageFilterPlugin"]()
    plugin.on_plugin_load()
    return namespace, plugin


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


def entities_of(message):
    """读实体偏移，兼容"原列表"和"重建后的 Java 列表"两种形态。"""
    entities = message.entities
    if isinstance(entities, FakeArrayList):
        return [(entity.offset, entity.length) for entity in entities.items]
    return [
        (entities.get(index).offset, entities.get(index).length)
        for index in range(entities.size())
    ]


def add_rule(plugin, pattern, mode=0, target=0, replacement="", case_sensitive=True):
    plugin.settings["new_rule_pattern"] = pattern
    plugin.settings["new_rule_mode"] = mode
    plugin._on_add_rule()
    rule_id = plugin._rule_ids()[-1]
    plugin.settings["rule_{}_target".format(rule_id)] = target
    plugin.settings["rule_{}_replacement".format(rule_id)] = replacement
    plugin.settings["rule_{}_case_sensitive".format(rule_id)] = case_sensitive
    plugin._invalidate()
    return rule_id


def run():
    bulletin = install_stubs()
    ns, plugin = load_plugin()

    # 基线：关掉「等长隐身删除」，这样断言能直接比对纯文本；
    # 隐身删除本身的行为单独在后面一节验证。
    plugin.settings["blank_fallback"] = False
    plugin._invalidate()

    TARGET_OUT = ns["TARGET_OUT"]
    TARGET_BOTH = ns["TARGET_BOTH"]
    MODE_REGEX = ns["MODE_REGEX"]
    EMPTY_KEEP_EMPTY = ns["EMPTY_KEEP_EMPTY"]

    section("加载与钩子注册")
    check("注册了发送钩子", plugin.send_hook, True)
    check(
        "注册了全部 update 钩子",
        all(name in plugin.hooks for name in ns["UPDATE_NAMES"]),
        True,
    )
    check(
        "注册了容器钩子",
        all(name in plugin.hooks for name in ns["CONTAINER_NAMES"]),
        True,
    )
    check(
        "注册了请求钩子（历史消息）",
        all(name in plugin.hooks for name in ns["REQUEST_NAMES"]),
        True,
    )
    check("加载日志走的是 log 回退路径", bool(plugin.logs), True)

    section("添加规则")
    plugin.settings["marker_enabled"] = False
    plugin._invalidate()
    plugin.settings["new_rule_pattern"] = "  "
    plugin._on_add_rule()
    check("空内容被拒绝", plugin._rule_ids(), [])
    check("空内容提示", bulletin.last[0], "error")

    rule_id = add_rule(plugin, "广告")
    check("规则已加入索引", plugin._rule_ids(), ["r1"])
    check("规则内容落盘", plugin.settings["rule_r1_pattern"], "广告")
    check("输入框被清空", plugin.settings["new_rule_pattern"], "")
    check("添加成功提示", bulletin.last[0], "success")

    plugin.settings["new_rule_pattern"] = "(["
    plugin.settings["new_rule_mode"] = MODE_REGEX
    plugin._on_add_rule()
    check("非法正则被拒绝", plugin._rule_ids(), ["r1"])
    check("非法正则提示", bulletin.last[0], "error")

    section("处理收到的消息")
    message = FakeMessage("今天促销 广告 速来")
    check("返回已修改", plugin._process(message, "in"), True)
    check("只删匹配部分", message.message, "今天促销  速来")
    check("未命中的消息不动", plugin._process(FakeMessage("正常消息"), "in"), False)
    check("空文本不动", plugin._process(FakeMessage(""), "in"), False)
    check("非字符串文本不动", plugin._process(FakeMessage(None), "in"), False)
    check("没有 message 字段的对象不动", plugin._process(object(), "in"), False)

    section("方向过滤")
    plugin.settings["rule_r1_target"] = TARGET_OUT
    plugin._invalidate()
    check("仅发出的规则不动收到的消息", plugin._process(FakeMessage("广告"), "in"), False)
    plugin.settings["rule_r1_target"] = 0
    plugin._invalidate()

    section("TL 对象识别（_iter_messages）")
    inner = FakeMessage("广告")
    extracted = plugin._iter_messages(FakeUpdate(inner))
    check("从 update 里取出 Message 而不是 update 本身", extracted, [inner])
    check("单个 Message 直接返回自身", plugin._iter_messages(inner), [inner])
    container = FakeContainer([FakeUpdate(FakeMessage("a")), FakeUpdate(FakeMessage("b"))])
    check("从容器里递归取出两条", len(plugin._iter_messages(container)), 2)
    check("None 返回空", plugin._iter_messages(None), [])

    section("实体偏移重建")
    plugin.settings["rule_r1_pattern"] = "广告"
    plugin._invalidate()

    # 实体完全落在被删区间里 -> 丢弃，且回写成 Java 列表
    message = FakeMessage("aaa 广告 bbb", FakeEntityList([FakeEntity(4, 2)]))
    plugin._process(message, "in")
    check("文本已改", message.message, "aaa  bbb")
    check("实体列表被换掉", isinstance(message.entities, FakeArrayList), True)
    check("被删掉的实体不再保留", entities_of(message), [])

    # 实体在被删区间之后 -> 左移
    message = FakeMessage("aaa 广告 bbb", FakeEntityList([FakeEntity(7, 3)]))
    plugin._process(message, "in")
    check("实体左移", entities_of(message), [(5, 3)])

    # 加前缀标记 -> 实体整体右移
    plugin.settings["marker_enabled"] = True
    plugin.settings["marker_text"] = ">>"
    plugin._invalidate()
    message = FakeMessage("aaa 广告 bbb", FakeEntityList([FakeEntity(0, 3)]))
    plugin._process(message, "in")
    check("带标记时文本", message.message, ">>aaa  bbb")
    check("带标记时实体右移", entities_of(message), [(2, 3)])

    # 删掉的 2 字 + 前缀 2 字 = 净位移 0 -> 不该白重建一遍列表
    message = FakeMessage("aaa 广告 bbb", FakeEntityList([FakeEntity(7, 3)]))
    original_list = message.entities
    plugin._process(message, "in")
    check("净位置不变时实体不动", message.entities is original_list, True)
    check("净位置不变时偏移也不变", entities_of(message), [(7, 3)])

    # 关掉实体修正 -> 不动实体
    plugin.settings["fix_entities"] = False
    plugin._invalidate()
    original = FakeEntityList([FakeEntity(7, 3)])
    message = FakeMessage("aaa 广告 bbb", original)
    plugin._process(message, "in")
    check("关掉修正后实体原样保留", message.entities is original, True)

    plugin.settings["marker_enabled"] = False
    plugin.settings["fix_entities"] = True
    plugin._invalidate()

    section("整条被删空")
    plugin.settings["rule_r1_pattern"] = "广告"
    plugin._invalidate()
    plugin.settings["on_empty"] = EMPTY_KEEP_EMPTY
    plugin._invalidate()
    message = FakeMessage("广告")
    plugin._process(message, "in")
    check("留空策略", message.message, "")

    section("update 钩子")
    plugin.settings["on_empty"] = 1
    plugin._invalidate()
    update = FakeUpdate(FakeMessage("hello 广告 world"))
    result = plugin.on_update_hook("TL_updateNewMessage", 0, update)
    check("返回 MODIFY", result.strategy, FakeHookStrategy.MODIFY)
    check("回带了 update 对象", result.update is update, True)
    check("消息已被改", update.message.message, "hello  world")

    untouched = FakeUpdate(FakeMessage("没有命中"))
    result = plugin.on_update_hook("TL_updateNewMessage", 0, untouched)
    check("未命中时策略为空", result.strategy, None)
    check("未命中时不动文本", untouched.message.message, "没有命中")

    section("容器钩子")
    container = FakeContainer([FakeUpdate(FakeMessage("x 广告")), FakeUpdate(FakeMessage("y 广告"))])
    result = plugin.on_updates_hook("TL_updates", 0, container)
    check("容器钩子返回 MODIFY", result.strategy, FakeHookStrategy.MODIFY)
    check("回带了容器对象", result.updates is container, True)
    check(
        "容器里两条都被处理",
        [u.message.message for u in container.updates._items],
        ["x ", "y "],
    )

    section("发送钩子")
    plugin.settings["rule_r1_target"] = TARGET_BOTH
    plugin._invalidate()
    params = FakeParams("发出去 广告 内容")
    result = plugin.on_send_message_hook(0, params)
    check("发送钩子返回 MODIFY", result.strategy, FakeHookStrategy.MODIFY)
    check("回带了 params", result.params is params, True)
    check("外发文本已改", params.message, "发出去  内容")

    result = plugin.on_send_message_hook(0, FakeParams(None))
    check("纯媒体发送不炸", result.strategy, None)
    result = plugin.on_send_message_hook(0, FakeParams(123))
    check("非字符串发送不炸", result.strategy, None)

    plugin.settings["rule_r1_target"] = 0
    plugin._invalidate()
    params = FakeParams("发出去 广告 内容")
    check("仅收的规则不动外发", plugin.on_send_message_hook(0, params).strategy, None)
    check("外发文本保持原样", params.message, "发出去 广告 内容")

    section("总开关")
    plugin.settings["enabled"] = False
    plugin._invalidate()
    message = FakeMessage("广告")
    check("关闭后不处理消息", plugin._process(message, "in"), False)
    check("关闭后 update 钩子直通", plugin.on_update_hook("x", 0, FakeUpdate(FakeMessage("广告"))).strategy, None)
    check("关闭后发送钩子直通", plugin.on_send_message_hook(0, FakeParams("广告")).strategy, None)
    plugin.settings["enabled"] = True
    plugin._invalidate()

    section("规则优先级与增删改")
    second = add_rule(plugin, "更坏")
    check("两条规则", plugin._rule_ids(), ["r1", "r2"])
    plugin._on_move("r1", 1)
    check("下移后顺序", plugin._rule_ids(), ["r2", "r1"])
    plugin._on_move("r1", 1)
    check("到底后再下移无变化", plugin._rule_ids(), ["r2", "r1"])
    plugin._on_move("r2", -1)
    check("到顶后再上移无变化", plugin._rule_ids(), ["r2", "r1"])
    plugin._on_delete(second)
    check("删除后只剩一条", plugin._rule_ids(), ["r1"])

    section("设置页构建")
    rows = plugin.create_settings()
    check("返回列表", isinstance(rows, list), True)
    check("有内容", len(rows) > 10, True)
    page = plugin._page_rule("r1")
    check("规则子页返回列表", isinstance(page, list), True)
    check("规则子页有内容", len(page) > 5, True)
    check("日志子页返回列表", isinstance(plugin._page_log(), list), True)
    plugin._on_self_check()
    check("自检不抛异常", True, True)
    plugin._on_clear_log()

    # 设置页里用到的 key 必须都能在 _config / _load_rules 里被读到，
    # 拼错一个 key 就是"改了设置没反应"这类难查的 bug
    known_prefixes = ("rule_",)
    known_keys = {
        "enabled", "new_rule_pattern", "new_rule_mode",
        "marker_enabled", "marker_text", "marker_position",
        "on_empty", "empty_placeholder", "fix_entities", "log_filtered",
        "blank_fallback", "capture_mode",
    }
    setting_keys = [
        row.kwargs["key"]
        for row in rows
        if isinstance(row, FakeSetting) and "key" in row.kwargs
    ]
    unknown = [
        key
        for key in setting_keys
        if key not in known_keys and not key.startswith(known_prefixes)
    ]
    check("设置页没有拼错的 key", unknown, [])
    check("设置页确实有控件", len(setting_keys) > 5, True)

    # 每条规则页的 key 必须是该规则的，不能串到别的规则上
    rule_keys = [
        row.kwargs["key"]
        for row in page
        if isinstance(row, FakeSetting) and "key" in row.kwargs
    ]
    check(
        "规则子页的 key 都带自己的 id",
        [key for key in rule_keys if not key.startswith("rule_r1_")],
        [],
    )

    section("配置缓存")
    plugin.settings["rule_r1_pattern"] = "缓存"
    plugin._invalidate()
    check("失效后立刻读到新规则", plugin._process(FakeMessage("缓存"), "in"), True)
    check("命中标记", plugin._config()["rules"][0]["pattern"], "缓存")

    # ----------------------------------------------------------------------
    # 群组 / 频道右上角菜单入口
    # ----------------------------------------------------------------------

    section("菜单注册")
    check("注册了两个菜单项", len(plugin.menu_items), 2)
    check(
        "菜单位置是聊天菜单与资料页菜单",
        [item.kwargs["menu_type"] for item in plugin.menu_items],
        ["CHAT_ACTION_MENU", "PROFILE_ACTION_MENU"],
    )

    activity = FakeActivity()
    context = FakeHashMap(
        {
            "dialog_id": -1001234,
            "chat": FakeChat("测试群"),
            "fragment": FakeFragment(activity),
        }
    )

    section("菜单里快捷添加规则")
    FakeAlertBuilder.instances.clear()
    plugin._on_chat_menu(context)
    dialog = FakeAlertBuilder.instances[-1]
    check("弹出了对话框", dialog.shown, True)
    check("标题带会话名", dialog.title, "消息过滤 · 测试群")
    check("首项是添加规则", dialog.items[0], "＋ 添加规则（仅本会话）")
    check("还没专属规则时给出提示", dialog.items[1], "（这个会话还没有专属规则）")

    dialog.click_item(0)
    add_dialog = FakeAlertBuilder.instances[-1]
    check("添加对话框带输入框", isinstance(add_dialog.view, FakeEditText), True)
    check("输入框有提示文字", bool(add_dialog.view.hint), True)
    add_dialog.view.setText("广告")
    add_dialog.click_button("positive")

    scoped_id = plugin._rule_ids()[-1]
    check("规则已创建", plugin.settings["rule_{}_pattern".format(scoped_id)], "广告")
    check(
        "作用范围绑定到该会话而不是全局",
        plugin.settings["rule_{}_scope".format(scoped_id)],
        "-1001234",
    )
    check("会话名被记住", plugin.settings["peer_title_-1001234"], "测试群")
    check("提示添加成功", bulletin.last[0], "success")

    section("会话规则只在那个会话生效")
    check("本会话命中", plugin._process(FakeMessage("广告", dialog_id=-1001234), "in"), True)
    check("别的会话不命中", plugin._process(FakeMessage("广告", dialog_id=-1009999), "in"), False)
    check("拿不到会话时不命中", plugin._process(FakeMessage("广告"), "in"), False)
    check("发送钩子拿不到会话也不命中", plugin.on_send_message_hook(0, FakeParams("广告")).strategy, None)

    section("菜单里管理规则")
    plugin._show_peer_dialog("-1001234", "测试群", activity)
    dialog = FakeAlertBuilder.instances[-1]
    check("只列出本会话的规则", len(dialog.items), 2)
    check("规则前有启用标记", dialog.items[1].startswith("✓"), True)

    dialog.click_item(1)
    actions = FakeAlertBuilder.instances[-1]
    check("二级操作项", actions.items, ["禁用这条规则", "删除这条规则"])
    actions.click_item(0)
    check("规则已禁用", plugin.settings["rule_{}_enabled".format(scoped_id)], False)
    check(
        "禁用后不再过滤",
        plugin._process(FakeMessage("广告", dialog_id=-1001234), "in"),
        False,
    )

    plugin.settings["rule_{}_enabled".format(scoped_id)] = True
    plugin._invalidate()
    plugin._show_peer_dialog("-1001234", "测试群", activity)
    FakeAlertBuilder.instances[-1].click_item(1)
    FakeAlertBuilder.instances[-1].click_item(1)  # 删除
    check("从菜单删除了规则", scoped_id in plugin._rule_ids(), False)
    check("删除后不再过滤", plugin._process(FakeMessage("广告", dialog_id=-1001234), "in"), False)

    section("会话规则与全局规则的顺序")
    moved = plugin._create_rule("临时词", 0, scope="-1001234", reload_settings=False)
    check("新建的是会话规则", plugin.settings["rule_{}_scope".format(moved)], "-1001234")
    check(
        "全局规则排在最前",
        plugin.settings["rule_{}_scope".format(plugin._rule_ids()[0])],
        "",
    )
    check("会话规则排在最后", plugin._rule_ids()[-1], moved)

    plugin._on_make_global(moved)
    check("改成全局", plugin.settings["rule_{}_scope".format(moved)], "")
    check(
        "改成全局后任何会话都命中",
        plugin._process(FakeMessage("临时词", dialog_id=-1009999), "in"),
        True,
    )

    section("拿不到界面时优雅降级")
    FakeAlertBuilder.instances.clear()
    plugin._on_chat_menu(FakeHashMap({"dialog_id": -1005555}))
    check("没有 Activity 时不弹窗", FakeAlertBuilder.instances, [])
    check("给了错误提示", bulletin.last[0], "error")
    check(
        "取不到会话名时用 id 兜底",
        plugin.settings.get("peer_title_-1005555"),
        "-1005555",
    )

    # ----------------------------------------------------------------------
    # v1.1.0 修复点：会话键候选、反射兜底、包装对象、链接安全、请求路径
    # ----------------------------------------------------------------------

    def reset_rules(*patterns):
        """清空规则，重建若干条全局规则，返回它们的 id。"""
        plugin.settings["rule_index"] = "[]"
        plugin.settings["rule_seq"] = 0
        plugin._invalidate()
        ids = []
        for pattern in patterns:
            plugin.settings["new_rule_pattern"] = pattern
            plugin.settings["new_rule_mode"] = 0
            plugin._on_add_rule()
            ids.append(plugin._rule_ids()[-1])
        return ids

    section("会话键：-100xxx 与裸 id 两种写法必须互通")
    plugin.settings["marker_enabled"] = False
    plugin.settings["blank_fallback"] = False
    plugin.settings["rule_index"] = "[]"
    plugin.settings["rule_seq"] = 0
    plugin._invalidate()
    plugin._create_rule("广告", 0, scope="-1001234", reload_settings=False)
    plugin._invalidate()
    check(
        "带 -100 前缀的会话规则命中裸 channel_id 的消息",
        plugin._process(FakeTLMessage("广告", channel_id=1234), "in"),
        True,
    )
    check(
        "别的频道不受影响",
        plugin._process(FakeTLMessage("广告", channel_id=9999), "in"),
        False,
    )
    check(
        "拿不到会话时不命中",
        plugin._process(FakeTLMessage("广告"), "in"),
        False,
    )

    plugin.settings["rule_index"] = "[]"
    plugin.settings["rule_seq"] = 0
    plugin._invalidate()
    plugin._create_rule("广告", 0, scope="-1234", reload_settings=False)
    plugin._invalidate()
    check(
        "裸写法的会话规则同样能命中",
        plugin._process(FakeTLMessage("广告", channel_id=1234), "in"),
        True,
    )

    section("菜单上下文里的 chatId / userId 符号")
    check(
        "chatId 是正数，会话键要取负",
        plugin._dialog_id_from_context(FakeHashMap({"chatId": 1234})),
        -1234,
    )
    check(
        "userId 保持正数",
        plugin._dialog_id_from_context(FakeHashMap({"userId": 55})),
        55,
    )
    check(
        "dialog_id 优先于 chatId",
        plugin._dialog_id_from_context(FakeHashMap({"dialog_id": -100777, "chatId": 1})),
        -100777,
    )
    check(
        "chat.id 取负",
        plugin._dialog_id_from_context(FakeHashMap({"chat": FakeChat("群")})),
        0,
    )

    section("从菜单给「只有 chatId 的频道」加规则，端到端生效")
    plugin.settings["rule_index"] = "[]"
    plugin.settings["rule_seq"] = 0
    plugin._invalidate()
    FakeAlertBuilder.instances.clear()
    plugin._on_chat_menu(
        FakeHashMap(
            {"chatId": 4321, "chat": FakeChat("某频道"), "fragment": FakeFragment(activity)}
        )
    )
    dialog = FakeAlertBuilder.instances[-1]
    check("只有 chatId 也能识别会话", dialog.shown, True)
    check("标题带会话名", dialog.title, "消息过滤 · 某频道")
    dialog.click_item(0)
    add_dialog = FakeAlertBuilder.instances[-1]
    add_dialog.view.setText("广告")
    add_dialog.click_button("positive")
    menu_rule = plugin._rule_ids()[-1]
    check("规则绑定到负数会话键", plugin.settings["rule_{}_scope".format(menu_rule)], "-4321")
    check(
        "该频道的新消息被过滤",
        plugin._process(FakeTLMessage("广告", channel_id=4321), "in"),
        True,
    )
    check(
        "别的频道不被误伤",
        plugin._process(FakeTLMessage("广告", channel_id=4322), "in"),
        False,
    )

    section("反射兜底：属性读不到时走 java.lang.Class")
    reset_rules("广告")
    reflected = ReflectedMessage("x 广告 y")
    check("反射路径能读到正文并改写", plugin._process(reflected, "in"), True)
    check("反射写回生效", reflected._values["message"], "x  y")

    section("包装对象：正文在 messageText，实体在 messageOwner")
    reset_rules("广告")
    wrapper = FakeWrapper("hello 广告 world", FakeEntityList([FakeEntity(6, 2)]))
    check("包装对象被识别为消息", plugin._iter_messages(wrapper), [wrapper])
    check("改写成功", plugin._process(wrapper, "in"), True)
    check("写回 messageText", wrapper.messageText, "hello  world")
    check("同步回 owner.message", wrapper.messageOwner.message, "hello  world")
    check("owner.entities 已重排（整段被删则丢弃）", entities_of(wrapper.messageOwner), [])

    section("请求路径：历史消息")
    reset_rules("广告")
    response = types.SimpleNamespace(
        messages=FakeEntityList([FakeMessage("历史 广告"), FakeMessage("正常")])
    )
    result = plugin.post_request_hook("TL_messages_getHistory", 0, response, None)
    check("历史消息也被过滤", result.strategy, FakeHookStrategy.MODIFY)
    check("回带了 response", result.response is response, True)
    check("历史消息文本已改", response.messages.get(0).message, "历史 ")
    check(
        "无关请求直通",
        plugin.post_request_hook("TL_users_getFullUser", 0, response, None).strategy,
        None,
    )
    check(
        "有 error 时直通",
        plugin.post_request_hook("TL_messages_getHistory", 0, response, "boom").strategy,
        None,
    )

    section("链接安全：等长隐身删除")
    reset_rules("广告")
    plugin.settings["blank_fallback"] = True
    plugin.settings["marker_enabled"] = False
    plugin._invalidate()
    message = FakeMessage("今天促销 广告 速来")
    check("命中", plugin._process(message, "in"), True)
    check("总长度守恒（字符数）", len(message.message), len("今天促销 广告 速来"))
    check(
        "可见文本等于真删结果",
        message.message.replace("\u200b", ""),
        "今天促销  速来",
    )
    check("被删位置换成零宽空格", "\u200b" in message.message, True)

    emoji_text = "a🥇b 广告 c"
    message = FakeMessage(emoji_text)
    plugin._process(message, "in")
    check(
        "emoji 处按 UTF-16 宽度补零宽（总长守恒）",
        sum(2 if ord(char) > 0xFFFF else 1 for char in message.message),
        sum(2 if ord(char) > 0xFFFF else 1 for char in emoji_text),
    )

    message = FakeMessage("aaa 广告 bbb", FakeEntityList([FakeEntity(7, 3)]))
    plugin._process(message, "in")
    check("拿得到 entities 时仍走真删", message.message, "aaa  bbb")
    check("真删时不残留零宽空格", "\u200b" in message.message, False)

    section("实体重排失败 → 宁可不动，也不让链接串位")
    reset_rules("广告")
    plugin.settings["blank_fallback"] = False
    plugin.settings["marker_enabled"] = False
    plugin._invalidate()
    message = FakeMessage("aaa 广告 bbb", FakeEntityList([ReadOnlyEntity(7, 3)]))
    check("重排失败时不修改消息", plugin._process(message, "in"), False)
    check("原文保持不变", message.message, "aaa 广告 bbb")

    section("只观察不改（样本捕获）")
    reset_rules("广告")
    plugin.settings["blank_fallback"] = False
    plugin.settings["capture_mode"] = True
    plugin._invalidate()
    message = FakeMessage("x 广告 y")
    check("捕获模式下不修改消息", plugin._process(message, "in"), False)
    check("原文保持不变", message.message, "x 广告 y")
    check(
        "样本写进了日志",
        any("[样本#" in str(line) for line in plugin.logs),
        True,
    )
    plugin.settings["capture_mode"] = False
    plugin._invalidate()

    section("自检与最近处理")
    plugin._on_self_check()
    check("自检报告已落盘到设置", bool(plugin.settings.get("_self_check")), True)
    check("自检弹了提示", bulletin.last[0], "info")
    check("最近处理有记录", len(plugin._activity) > 0, True)
    plugin._on_clear_log()
    check("清空后无记录", plugin._activity, [])


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
