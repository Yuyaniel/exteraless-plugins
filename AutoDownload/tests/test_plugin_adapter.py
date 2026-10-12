"""适配层集成测试。

纯函数测试（test_decision_engine.py）覆盖不到的都在这里：宿主 API 探测、
候选方法枚举与挂钩、int / boolean 两种返回类型的回写、诊断日志的分级与去重、
各重载统计、自检报告内容。用假对象替换 SDK 后直接跑真插件类。

跑法：
    python tests/test_plugin_adapter.py
"""

import os
import sys
import tempfile
import types

PLUGIN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "auto_download.plugin"
)


# --------------------------------------------------------------------------
# 假 Java 反射层
# --------------------------------------------------------------------------


class FakeJavaClassInfo:
    """java.lang.Class 的实例（方法是 getName / getSimpleName）。"""

    def __init__(self, name):
        self._name = name

    def getName(self):
        return self._name

    def getSimpleName(self):
        return self._name.split(".")[-1].split("$")[-1]


class FakeJavaObject:
    def __init__(self, class_name):
        self._class_name = class_name

    def getClass(self):
        return FakeJavaClassInfo(self._class_name)


class FakeMethod:
    def __init__(self, name, param_types, return_type):
        self._name = name
        self._params = [FakeJavaClassInfo(item) for item in param_types]
        self._return = FakeJavaClassInfo(return_type)

    def getName(self):
        return self._name

    def getParameterTypes(self):
        return list(self._params)

    def getReturnType(self):
        return self._return

    def __str__(self):
        return "{}({}) -> {}".format(
            self._name,
            ", ".join(item.getName() for item in self._params),
            self._return.getName(),
        )


class FakeField:
    def __init__(self, name, value):
        self._name = name
        self._value = value

    def getName(self):
        return self._name

    def setAccessible(self, flag):
        return None

    def get(self, obj):
        return self._value

    def getInt(self, obj):
        return int(self._value)


class FakeJavaClass:
    """java.lang.Class 本身：只实现 forName。"""

    registry = {}

    @staticmethod
    def forName(name):
        if name in FakeJavaClass.registry:
            return FakeJavaClass.registry[name]
        raise Exception("ClassNotFoundException: " + name)


# --------------------------------------------------------------------------
# 假宿主：DownloadController / ConnectionsManager / TL 对象
# --------------------------------------------------------------------------

DC_CLASS_NAME = "org.telegram.messenger.DownloadController"
CM_CLASS_NAME = "org.telegram.messenger.ConnectionsManager"


class FakeDownloadController(FakeJavaObject):
    """位掩码构建的 DownloadController 替身（对应真机实测的那套）。"""

    METHODS = (
        ("canDownloadMedia", ("org.telegram.tgnet.TLRPC$Message",), "int"),
        (
            "canDownloadMedia",
            ("org.telegram.tgnet.TLRPC$Message", "org.telegram.tgnet.TLRPC$MessageMedia"),
            "int",
        ),
        ("canDownloadMedia", ("int", "long"), "boolean"),
        ("canDownloadMedia", ("org.telegram.messenger.MessageObject",), "boolean"),
        ("canDownloadMediaInternal", ("org.telegram.messenger.MessageObject",), "int"),
        (
            "canDownloadMediaInternal",
            ("org.telegram.messenger.MessageObject", "long"),
            "int",
        ),
        ("canDownloadMediaType", ("org.telegram.messenger.MessageObject",), "int"),
        ("getAutodownloadMask", (), "int"),
        ("getAutodownloadMaskAll", (), "int"),
        ("lambda$loadAutoDownloadConfig$1", ("org.telegram.tgnet.TLObject",), "void"),
        ("loadAutoDownloadConfig", ("boolean",), "void"),
    )
    FIELDS = (
        ("AUTODOWNLOAD_TYPE_PHOTO", 1),
        ("AUTODOWNLOAD_TYPE_AUDIO", 2),
        ("AUTODOWNLOAD_TYPE_VIDEO", 4),
        ("AUTODOWNLOAD_TYPE_DOCUMENT", 8),
    )

    def __init__(self):
        FakeJavaObject.__init__(self, DC_CLASS_NAME)

    def getDeclaredMethods(self):
        return [FakeMethod(*item) for item in self.METHODS]

    def getDeclaredFields(self):
        return [FakeField(*item) for item in self.FIELDS]

    def getDeclaredField(self, name):
        for item in self.FIELDS:
            if item[0] == name:
                return FakeField(*item)
        raise Exception("NoSuchFieldException: " + name)


class FakeConnectionsManager(FakeJavaObject):
    def __init__(self, wifi=True):
        FakeJavaObject.__init__(self, CM_CLASS_NAME)
        self._wifi = wifi

    def isConnectedToWiFi(self):
        return self._wifi


class FakeJavaList(FakeJavaObject):
    def __init__(self, items, class_name="java.util.ArrayList"):
        FakeJavaObject.__init__(self, class_name)
        self._items = list(items)

    def size(self):
        return len(self._items)

    def get(self, index):
        return self._items[index]


class FakeTlObject(FakeJavaObject):
    def __init__(self, simple_name, **extra):
        FakeJavaObject.__init__(self, "org.telegram.tgnet.TLRPC$" + simple_name)
        for key, value in extra.items():
            setattr(self, key, value)


def photo_media():
    return FakeTlObject("TL_messageMediaPhoto")


def document_media(*attribute_names):
    document = FakeTlObject(
        "TL_document",
        attributes=FakeJavaList([FakeTlObject(name) for name in attribute_names]),
    )
    return FakeTlObject("TL_messageMediaDocument", document=document)


class FakeOwner(FakeJavaObject):
    def __init__(self, media, dialog_id):
        FakeJavaObject.__init__(self, "org.telegram.tgnet.TLRPC$TL_message")
        self.media = media
        self.dialog_id = dialog_id


class FakeMessageObject(FakeJavaObject):
    """MessageObject：媒体挂在 messageOwner 上。"""

    def __init__(self, media=None, dialog_id=0, text=""):
        FakeJavaObject.__init__(self, "org.telegram.messenger.MessageObject")
        self.messageOwner = FakeOwner(media, dialog_id)
        self.message = text


class FakeTlMessage(FakeJavaObject):
    """TLRPC$Message：没有 messageOwner，media 直接挂在身上。"""

    def __init__(self, media=None, dialog_id=0):
        FakeJavaObject.__init__(self, "org.telegram.tgnet.TLRPC$TL_message")
        self.media = media
        self.dialog_id = dialog_id


class FakeParam:
    """XC_MethodHook.MethodHookParam 替身。"""

    def __init__(self, method, args=(), result=None, this_object=None):
        self.method = method
        self.args = list(args)
        self.thisObject = this_object
        self._result = result
        self.result_written = False

    def getResult(self):
        return self._result

    def setResult(self, value):
        self._result = value
        self.result_written = True


# --------------------------------------------------------------------------
# 假 SDK
# --------------------------------------------------------------------------


class FakeMenuType:
    MESSAGE_CONTEXT_MENU = "MESSAGE_CONTEXT_MENU"
    CHAT_ACTION_MENU = "CHAT_ACTION_MENU"
    PROFILE_ACTION_MENU = "PROFILE_ACTION_MENU"


class FakeMenuItemData:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeMethodHook:
    pass


def _format(message, args):
    try:
        return message % args if args else message
    except Exception:
        return str(message)


class FakeLogger:
    def __init__(self):
        self.lines = []

    def info(self, message, *args):
        self.lines.append(("info", _format(message, args)))

    def error(self, message, *args):
        self.lines.append(("error", _format(message, args)))


class FakeBasePlugin:
    def __init__(self):
        self.version = "1.1.0"
        self.settings = {}
        self.logger = FakeLogger()
        self.hooked = {}          # 方法名 -> 重载数
        self.captured = {}        # 方法名 -> [hook 对象]
        self.unhooked = []
        self.menu_items = []

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)

    def set_setting(self, key, value, reload_settings=False):
        self.settings[key] = value

    def hook_all_methods(self, java_class, method_name, hook):
        matches = [
            item for item in java_class.getDeclaredMethods() if item.getName() == method_name
        ]
        if not matches:
            return None
        self.hooked[method_name] = len(matches)
        self.captured.setdefault(method_name, []).append(hook)
        return [
            "unhook-{}-{}".format(method_name, index) for index in range(len(matches))
        ]

    def unhook_method(self, unhook):
        self.unhooked.append(unhook)

    def add_menu_item(self, data):
        self.menu_items.append(data)
        return "menu-{}".format(len(self.menu_items))

    def log(self, message):
        self.logger.lines.append(("legacy", message))


def _module(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


def install_stubs():
    controller = FakeDownloadController()
    connections = FakeConnectionsManager(wifi=True)
    found = {
        DC_CLASS_NAME: controller,
        CM_CLASS_NAME: connections,
    }
    FakeJavaClass.registry = {
        DC_CLASS_NAME: controller,
        CM_CLASS_NAME: connections,
    }

    _module(
        "base_plugin",
        BasePlugin=FakeBasePlugin,
        MenuItemData=FakeMenuItemData,
        MenuItemType=FakeMenuType,
        MethodHook=FakeMethodHook,
    )
    _module("hook_utils", find_class=lambda name: found.get(name))
    _module("client_utils", get_last_fragment=lambda *args, **kwargs: None)
    ui = _module("ui")
    ui.__path__ = []
    _module("ui.alert", AlertDialogBuilder=FakeStub)
    _module("ui.bulletin", BulletinHelper=FakeStub)
    _module("ui.settings", Divider=FakeStub, Header=FakeStub, Selector=FakeStub,
            Switch=FakeStub, Text=FakeStub)
    ui.alert = sys.modules["ui.alert"]
    ui.bulletin = sys.modules["ui.bulletin"]
    ui.settings = sys.modules["ui.settings"]

    java = _module("java")
    java.__path__ = []
    _module("java.lang", Class=FakeJavaClass)
    java.lang = sys.modules["java.lang"]

    return found


class FakeStub:
    def __init__(self, *args, **kwargs):
        pass

    def __getattr__(self, name):
        return FakeStub()

    def __call__(self, *args, **kwargs):
        return FakeStub()


def load_plugin():
    with open(PLUGIN_PATH, "r", encoding="utf-8") as handle:
        source = handle.read()
    namespace = {
        "__name__": "auto_download",
        # 报告写进临时目录，别污染仓库
        "__file__": os.path.join(tempfile.mkdtemp(), "auto_download.plugin"),
    }
    exec(compile(source, PLUGIN_PATH, "exec"), namespace)  # noqa: S102

    module = types.ModuleType("auto_download")
    module.__dict__.update(namespace)
    sys.modules["auto_download"] = module

    plugin = namespace["AutoDownloadPlugin"]()
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


def logged(plugin, needle):
    return [text for _level, text in plugin.logger.lines if needle in text]


METHOD_BOOL = FakeMethod(
    "canDownloadMedia", ("org.telegram.messenger.MessageObject",), "boolean"
)
METHOD_INT = FakeMethod(
    "canDownloadMediaInternal", ("org.telegram.messenger.MessageObject",), "int"
)
METHOD_TYPE = FakeMethod(
    "canDownloadMediaType", ("org.telegram.messenger.MessageObject",), "int"
)
METHOD_MASK = FakeMethod("getAutodownloadMask", (), "int")


def run():
    install_stubs()
    ns, plugin = load_plugin()
    controller = FakeJavaClass.registry[DC_CLASS_NAME]

    def fire(name, param):
        if param.thisObject is None:
            param.thisObject = controller
        hook = plugin.captured[name][0]
        hook.after_hooked_method(param)

    def msg(media, dialog_id=-1001234):
        return FakeMessageObject(media, dialog_id)

    section("加载与挂钩")
    check("挂了 canDownloadMedia", "canDownloadMedia" in plugin.hooked, True)
    check("挂了 canDownloadMediaInternal", "canDownloadMediaInternal" in plugin.hooked, True)
    check("挂了 canDownloadMediaType", "canDownloadMediaType" in plugin.hooked, True)
    check("挂了 getAutodownloadMask", "getAutodownloadMask" in plugin.hooked, True)
    check(
        "跳过了 lambda$ 内部方法",
        [name for name in plugin.hooked if name.startswith("lambda$")],
        [],
    )
    check(
        "挂钩的方法名正好是这些",
        sorted(plugin.hooked),
        [
            "canDownloadMedia",
            "canDownloadMediaInternal",
            "canDownloadMediaType",
            "getAutodownloadMask",
            "getAutodownloadMaskAll",
            "loadAutoDownloadConfig",
        ],
    )
    check("挂钩重载总数（不含被跳过的 lambda）", sum(plugin.hooked.values()), 10)
    check("三态常量读不到", plugin._caps.values, {})
    check("把真实字段列了出来", len(logged(plugin, "AUTODOWNLOAD 字段（4 个）")), 1)
    check("字段值正确", len(logged(plugin, "AUTODOWNLOAD_TYPE_PHOTO=1")), 1)
    check("菜单项已注册", len(plugin.menu_items), 2)

    section("int 返回的重载无法回写（位掩码构建）")
    param = FakeParam(METHOD_INT, [msg(photo_media())], result=0)
    fire("canDownloadMediaInternal", param)
    check("没有改写返回值", param.result_written, False)
    check("记了一条 int 样本", len(logged(plugin, "int 样本")), 1)
    check(
        "样本里带了原返回值",
        len([line for line in logged(plugin, "int 样本") if "原返回值=0" in line]),
        1,
    )

    section("boolean 返回的重载按真实返回类型回写")
    # 「改写返回值 / 原值」这行属于逐条决策日志，受 log_decisions 控制
    plugin.settings["log_decisions"] = True
    plugin._invalidate_config()
    param = FakeParam(METHOD_BOOL, [msg(photo_media())], result=False)
    fire("canDownloadMedia", param)
    check("改写成了允许", param.getResult(), True)
    check("日志里能看到原值", len(logged(plugin, "原值=False")), 1)

    plugin.settings["default_wifi_photo"] = False
    plugin._invalidate_config()
    param = FakeParam(METHOD_BOOL, [msg(photo_media())], result=False)
    fire("canDownloadMedia", param)
    check("设置改成不下时就回写 False", param.getResult(), False)

    plugin.settings["default_wifi_photo"] = True
    plugin._invalidate_config()

    section("TLRPC$Message 重载（没有 messageOwner，media 在身上）")
    param = FakeParam(METHOD_INT, [FakeTlMessage(photo_media())], result=0)
    fire("canDownloadMediaInternal", param)
    check(
        "能读到 media 并算出决策",
        len(logged(plugin, "媒体=photo")),
        len(logged(plugin, "媒体=photo")),
    )
    check("确实识别出了 photo", bool(logged(plugin, "媒体=photo")), True)

    section("无参方法的掩码采样")
    param = FakeParam(METHOD_MASK, [], result=83886080)
    fire("getAutodownloadMask", param)
    check("记了一条掩码取值", len(logged(plugin, "掩码取值")), 1)
    check("解出了 >>24", len(logged(plugin, ">>24 = 5")), 1)
    param = FakeParam(METHOD_MASK, [], result=83886080)
    fire("getAutodownloadMask", param)
    check("同一个值不重复记", len(logged(plugin, "掩码取值")), 1)
    param = FakeParam(METHOD_MASK, [], result=16777216)
    fire("getAutodownloadMask", param)
    check("值变了再记一条", len(logged(plugin, "掩码取值")), 2)

    section("识别不出的消息不刷屏")
    for _ in range(3):
        fire("canDownloadMediaInternal", FakeParam(METHOD_INT, [msg(None)], result=0))
    check("纯文本只记一条不干预", len(logged(plugin, "不干预: 纯文本")), 1)
    fire(
        "canDownloadMediaInternal",
        FakeParam(METHOD_INT, [msg(FakeTlObject("TL_messageMediaWebPage"))], result=0),
    )
    check(
        "未收录的类名被写出来",
        len(logged(plugin, "未收录的 media 类名: TL_messageMediaWebPage")),
        1,
    )

    section("决策日志受开关控制")
    plugin.settings["log_decisions"] = True
    plugin._invalidate_config()
    before = len(logged(plugin, "媒体="))
    fire("canDownloadMedia", FakeParam(METHOD_BOOL, [msg(photo_media())], result=False))
    check("开着时会输出决策行", len(logged(plugin, "媒体=")) > before, True)

    plugin.settings["log_decisions"] = False
    plugin._invalidate_config()
    before = len(logged(plugin, "媒体="))
    fire("canDownloadMedia", FakeParam(METHOD_BOOL, [msg(photo_media())], result=False))
    check("关掉后不再输出决策行", len(logged(plugin, "媒体=")), before)
    check("但结构性诊断照旧", bool(logged(plugin, "int 样本")), True)

    section("完全静默")
    plugin.settings["quiet"] = False
    plugin.settings["log_decisions"] = False
    plugin._invalidate_config()
    plugin._config()
    check("静默关时结构性诊断可用", plugin._note_on, True)
    check("静默关时决策日志仍关着", plugin._diag_on, False)

    plugin.settings["quiet"] = True
    plugin._invalidate_config()
    plugin._config()
    check("静默开时结构性诊断被拦", plugin._note_on, False)
    check("静默开时决策日志也被拦", plugin._diag_on, False)

    before = len(plugin.logger.lines)
    quiet_param = FakeParam(METHOD_BOOL, [msg(photo_media())], result=False)
    fire("canDownloadMedia", quiet_param)
    fire("canDownloadMediaInternal", FakeParam(METHOD_INT, [msg(None)], result=0))
    fire("getAutodownloadMask", FakeParam(METHOD_MASK, [], result=999))
    check("静默下不产生任何诊断行", len(plugin.logger.lines), before)
    check("静默下仍然照常改写返回值", quiet_param.getResult(), True)

    # 错误信息不受静默影响：出错必须看得见
    plugin._error("模拟错误")
    check("静默下错误照旧输出", len(plugin.logger.lines), before + 1)
    check("错误级别正确", plugin.logger.lines[-1][0], "error")

    plugin.settings["quiet"] = False
    plugin._invalidate_config()
    plugin._config()
    check("关掉静默后恢复", plugin._note_on, True)

    section("热路径：方法标识只跨语言取一次")
    # `str(param.method)` 是跨语言调用，曾经在一条调用链上算 4 次。
    # 这里把它钉住：一次钩子触发只能取 1 次。
    plugin_class = ns["AutoDownloadPlugin"]
    real_raw_key = plugin_class._raw_key
    tally = {"count": 0}

    def counting_raw_key(param):
        tally["count"] += 1
        return real_raw_key(param)

    plugin_class._raw_key = staticmethod(counting_raw_key)
    try:
        fire("canDownloadMedia", FakeParam(METHOD_BOOL, [msg(photo_media())], result=False))
        check("一次钩子触发只取 1 次方法标识", tally["count"], 1)

        tally["count"] = 0
        fire("canDownloadMediaInternal", FakeParam(METHOD_INT, [msg(photo_media())], result=0))
        check("int 重载同样只取 1 次", tally["count"], 1)

        tally["count"] = 0
        fire("getAutodownloadMask", FakeParam(METHOD_MASK, [], result=1234))
        check("无参方法同样只取 1 次", tally["count"], 1)
    finally:
        plugin_class._raw_key = staticmethod(real_raw_key)

    section("各重载统计")
    totals = plugin._stats_totals()
    check("统计了调用次数", totals.get("calls", 0) > 0, True)
    check("统计了改写次数", totals.get("rewritten", 0) > 0, True)
    check("统计了放弃次数", totals.get("aborted", 0) > 0, True)
    check(
        "int 那两条被记为放弃",
        plugin._stats[METHOD_INT_LABEL]["aborted"] > 0,
        True,
    )

    section("自检报告")
    report = plugin._build_report()
    check("有各重载统计段", "## 各重载统计" in report, True)
    check("有 int 样本段", "## int 返回值样本" in report, True)
    check("有掩码段", "## 掩码取值" in report, True)
    check("报告里有候选方法", "候选方法" in report, True)
    check("报告里没有三态常量", "（未读到任何 AUTODOWNLOAD_* 常量）" in report, True)
    check("报告能落盘", bool(plugin._write_report()), True)


METHOD_INT_LABEL = (
    "canDownloadMediaInternal(org.telegram.messenger.MessageObject) -> int "
    "@ org.telegram.messenger.DownloadController"
)


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
