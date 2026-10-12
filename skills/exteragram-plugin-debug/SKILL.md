---
name: exteragram-plugin-debug
description: 诊断 exteraGram 插件不生效 / 翻译失败 / 网络请求异常 / 插件加载后静默失效 / 插件钩子性能问题。包含 adb 推插件、logcat 抓插件日志（三条 TAG 通道）、反编译宿主取证、设备侧绕开插件直连 API、import 探针定位、Java 反射与 Chaquopy 互操作陷阱、跨插件调用、控件坐标定位、手机 UI 自动化（截图取坐标 / 并发抓启动日志）的完整流程。当用户提到 exteraGram 插件装了没反应、插件启用后被自动禁用、翻译不能用、插件卡顿/掉帧、手机截图点击时使用。
---

# exteraGram 插件调试

面向 **exteraGram 插件（Python / BasePlugin SDK）** 的排障方法论。

> 所有结论都标注了**判据**而非"经验之谈"：能复现的写命令，能验证的写对照表。
> 涉及具体宿主版本时，请以**你自己设备上的实测**为准 —— 宿主类名、方法名、混淆情况会随版本变化。

---

## 环境准备

```bash
export MSYS_NO_PATHCONV=1          # Git Bash 下防止路径被改写
ADB=/e/platform-tools/adb.exe      # 换成你的 adb 路径
DEV=$($ADB devices | awk 'NR==2{print $1}')   # 设备序列号
D=/data/data/com.exteragram.messenger/files/plugins
X=/data/data/com.exteragram.messenger/shared_prefs/plugin_settings.xml
P=/data/data/com.exteragram.messenger/files/plugins/plugin_settings.json
```

**坑**：每条 Bash 调用都是新 shell，adb 服务会重启，直接带 `-s` 可能报 `device not found`。
**稳妥做法**：每条命令开头都 `$ADB start-server && $ADB -s $DEV wait-for-device`。

**前置条件**：设备已 root（读写 `/data/data/` 需要）、应用已开启「插件引擎 + 开发者模式」。

---

## 零、离线改造插件的标准管线（不需要真机）

改功能 / 修 bug 时**不要直接手改 `.plugin`**，用「生成脚本 + 校验脚本」两段式管线：
原文件只读不写，产出新版本文件，跑完校验才算改完。

### ① 生成脚本 `patch_XXX.py`

```python
src = io.open(SRC, encoding="utf-8").read()

def sub(old, new, label):
    global src, n_ok
    assert src.count(old) == 1, "锚点[{}]命中 {} 次".format(label, src.count(old))
    src = src.replace(old, new); n_ok += 1

io.open(DST, "w", encoding="utf-8").write(src)
```

- **原文件只读不写**，交付新版本文件；改完复算一次基线 md5，确认没被误改。
- **CRLF 往返无损**：`io.open(..., encoding="utf-8").read()` 读时把 CRLF 归一为 `\n`
  （所以锚点里写 `\n`），Windows 上写回时自动还原 `\r\n`。纯 CRLF 的插件可安全往返。
- **⚠️ 别把含反斜杠转义的代码写成精确锚点**。源码里 `\n`（真换行）与 `\\n`（字面反斜杠）
  混用时，补丁脚本的转义层级极易错位，症状是 `AssertionError: 锚点[...]命中 0 次`。
  改用**起止标记切片**：

  ```python
  assert src.count("    def method_a(self) -> str:") == 1
  assert src.count("    def method_b(self) -> Optional[str]:") == 1
  i = src.index("    def method_a(self) -> str:")
  j = src.index("    def method_b(self) -> Optional[str]:")
  assert i < j
  src = src[:i] + src[j:]        # 删除中间整段
  ```

  效果等价于精确匹配，且完全不用写转义。

### ② 校验脚本 `check_XXX.py` —— 只有跑绿了才算改完

这五类判据最能抓真问题：

**1. i18n 键存在性（正反两向）**
正则抽 `self.t("X")` 的字面量，逐个比对 `STRINGS` 的键；**再反向**列出
「定义了但没被字面量引用」的键 —— 反向检查常能直接报出遗留的死键。

**2. 死代码扫描**
对类里每个 `_` 开头的私有方法统计引用次数，`< 2`（只有定义）即零调用。

```python
hits = len(re.findall(r"(?:self\.|def\s+)" + re.escape(name) + r"\b", src))
```

- **不能要求名字后面跟 `(`**：很多方法是当**回调**传出去的
  （`target=self._xxx,` / `on_change=self._xxx,`），后面跟的是逗号，
  用 `(` 判断会把它们全部误报成死代码。
- **不能用 `(?<![\w.])` 做前置断言**：`self.` 里的那个点会把所有正常调用都排除掉。
- 用 `\b` 结尾，避免 `_ai_model` 误匹配 `_ai_model_endpoints`。

**3. `self.*` 引用完整性**
AST 收集 `self.<attr>` 与「已定义集合」（方法名 + `Store` 上下文的属性），差集即漏定义。
`base_api` 白名单要包含 SDK 基类提供的成员：
`log / get_setting / set_setting / export_settings / import_settings /
add_on_send_message_hook / add_menu_item / remove_menu_item / java / this`。

**4. 纯函数实测**
用 `textwrap.dedent` 按 `node.lineno` / `node.end_lineno` 抽出方法源码、去掉 `@staticmethod`、
整体反缩进后 `exec`，再用真实样本跑多种输入（含空值/异常形状）。
**注意** `ast.get_source_segment` 抽方法时**不会**去掉 `@staticmethod`，
静态方法要先剥装饰器再当普通函数调用。

**5. 悬挂引用扫描（删常量 / 重构时必用）**
收集全文用到的大写常量名，减去模块级已定义的名字，差集就是「用了但没定义」：

```python
used = set(re.findall(r"(?<!\.)\b([A-Z][A-Z0-9_]{2,})\b", src))
suspects = {u for u in used if u.startswith(("SOURCE_", "PROVIDER_", "STAT_"))}
dangling = sorted(suspects - defined_names)
```

**前置 `(?<!\.)` 必须有**：`MenuItemType.CHAT_ACTION_MENU` 这类**枚举属性**
会被误判成本文件的模块级常量。

### ⚠️ 校验脚本自身最容易写错的三个判据

1. **`ast.literal_eval` 遇到含常量引用的赋值会静默返回 `None`**，不报错。
   `LABELS = [(SOURCE_AI, "AI")]` 就是这种 —— 断言会变成「实际 None」。
   修法：在种子命名空间里把这类赋值再 `exec` 一遍补上。
2. **「文案里不能出现 X」只能扫 `STRINGS` 的值**，不能扫全文 ——
   解释性注释里写「不要竞速」是正确的，扫全文必然误报。
   匹配英文单词要加词边界（`\brace\b`），否则 `trace` / `space` 会被误伤。
3. **删私有方法后要复跑死代码扫描**，确认没留下孤儿函数
   （删了 `_race` 但 `_race_pool` 还在，就是这类事故）。

### ③ 写设置页的两条 UI 约束

- `Selector` **没有 `subtext` 参数**（只有 `key/text/default/items/on_change`）。
  想给选择器加说明，只能写在相邻行的 `Divider(text=...)` 里。
- 长说明只有 `Custom(factory=SimpleSettingFactory(...))` 自建 View 能换行；
  `Text.subtext` 与 `Selector` 的选项文字都是**单行 + 省略号**，无接口可改。

### ④ 换配置 / 换语言后要「立刻看到新状态」

宿主设置页是**静态构建**的，`create_settings()` 只在打开时跑一次。
页内控件变化不会让它自己重跑，必须靠：

```python
self.set_setting("key", value, reload_settings=True)
```

**同一个坑会重复出现**：给 `Selector` 加了 `on_change` 才能让切换生效 ——
**每加一个 Selector，都检查一遍要不要绑 `on_change`**（漏绑的表现是"改了没反应"）。

### ⑤ 增删「设置项下标」必须配一次性迁移

设置里存**下标**的项（如 `provider`、`active_profile`、各种 `*_KEYS` 选择器），
一旦增删选项，**所有老设置都会静默指向错的项**。两条硬要求：

1. **新增项只能追加在最后**，绝不插中间（插中间 = 全部错位）。
2. **删项 / 重排必须写一次性迁移，且不能用「值是否越界」判断** ——
   删掉下标 0 之后，旧的 `0` 和 `1` 都落在新范围内但含义全变，范围判断无法察觉。
   必须用独立标记位：

   ```python
   if self.get_setting("provider_mapped_v2", False):
       return
   new = PROVIDER_A if old == 5 else PROVIDER_B
   self.set_setting("provider", new, reload_settings=False)
   self.set_setting("provider_mapped_v2", True, reload_settings=False)
   ```

   迁移函数要**用桩对象把每一种旧值都跑一遍**，并验**幂等**
   （迁移过一次后用户再手动改选，不能被二次覆盖）。

### ⑥ 自动刷新类功能的节流闸（不写就是死循环）

模式：**拉取成功 → `reload_settings=True` 重建设置页 → `create_settings()` 再跑
→ 再次触发拉取**。必须在拉取入口加节流：

```python
if reason != "manual" and last_target == target and now - last_ts < THROTTLE:
    return
```

且**只对同一目标设限**（换了配置/目标必须放行，否则切过去拉不到数据）。

---

## 一、装 / 更新插件

设备侧文件名是 **`.py`**（不是 `.plugin`）。装完必须 chown + chmod + 删 pyc：

```bash
$ADB -s $DEV push "<本地.plugin>" /data/local/tmp/x.py
$ADB -s $DEV shell "su -c 'cp /data/local/tmp/x.py $D/<id>.py'"
$ADB -s $DEV shell "su -c 'chown <app_uid>:<app_uid> $D/<id>.py'"   # 属主必须是应用 uid
$ADB -s $DEV shell "su -c 'chmod 600 $D/<id>.py'"
$ADB -s $DEV shell "su -c 'rm -f $D/__pycache__/<id>.cpython-311.pyc'"
```

- `<app_uid>` 用 `su -c 'stat -c %u $D'` 取（通常是 `u0_a<NNN>` 形式）。
- **不 chown 应用就无权限读取**；**不删 pyc 可能加载旧字节码**。
- 启用开关在 `shared_prefs/plugin_settings.xml`：
  `<boolean name="plugin_enabled_<id>" value="true" />`
- **⚠️ `adb push` 的源路径必须是纯 ASCII** —— 含中文的路径会让 push **静默挂起**
  （无报错、无进度，只是卡住）。先把文件复制到纯英文路径再 push。

---

## 二、抓插件日志

### 三条输出通道（都要覆盖）

| 调用 | logcat TAG | 行形态 |
|---|---|---|
| `self.log(...)` | `[PyObject]` | `D [PyObject]: [callAttrThrows] [<id>] 消息` |
| `android_utils.log(...)` | `[Python]` | `D [Python]: [getModule] 消息` |
| **`self.logger.info(...)`** | **`plugin.<id>`** | `I plugin.<id>: [file.py:function:line] 消息` |

`self.logger` 是新式日志器（`log_utils` 模块）：条目自带**位置前缀**，且
`adb logcat -s plugin.<id>` 能**只抓单个插件**。`self.log()` 是 legacy，固定 debug 级别、
无法按插件过滤。**新代码优先用 `self.logger`**（注意：旧 SDK 可能没有该模块，
可用 `_sdk_version.__version__` 判断）。

```bash
$ADB -s $DEV shell "am force-stop com.exteragram.messenger"
$ADB -s $DEV logcat -c
$ADB -s $DEV shell "am start -n com.exteragram.messenger/org.telegram.ui.LaunchActivity"
sleep 14
$ADB -s $DEV logcat -d | grep -aiE "<id>"
```

**启动日志有时间窗**：实测启动后十几秒内还有插件日志，到 18 秒左右就**归零**。
慢一步就会误判「插件没加载」。要长时间观察就用后台
`logcat -v time > file`，别反复 `-d`。

> 若用手机 UI 自动化工具抓日志，注意它通常是**流式**的（只抓调用之后的日志），
> 必须「**先开日志流、再启动应用**」并发执行才能拿到启动那批 —— 见最后一节。

### ★ 插件日志只走 logcat，**不落盘**

- 日志行里 `[callThrows] [<id>]` 是宿主/Chaquopy 包装层加的，插件自己的输出从 `[<id>]` 之后开始。
  这个 tag 字面量在 APK 里**搜不到**（运行时拼出来的），别试图反推实现。
- 想只看插件日志：`$ADB -s $DEV logcat -s "[PyObject]"`。
- **没有任何文件日志**：`/sdcard/Android/data/com.exteragram.messenger/files/logs/`
  是宿主 `FileLog` 的目录，**插件 `log()` 不会写进去**。要落盘只能插件自己写文件。
- **应用内没有日志查看器**。
- 自带调试输出的插件通常有独立的「调试日志」开关，不开就只有 `loaded, ...` 这类加载日志。

### ★★ 探针插件：结果要写文件，不要只打日志

调试插件自身（尤其是加载阶段）时，**把结果追加写入文件**：

```python
import sys
OUT = "/data/data/com.exteragram.messenger/files/_probe_out.txt"

def emit(s):
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(str(s) + "\n")

def probe(label, fn):
    try:
        emit("%-40s => %r" % (label, fn()))
    except Exception as e:                 # 必须 except Exception
        emit("%-40s !! %s: %s" % (label, type(e).__name__, e))

# 在 import base_plugin 之前先 emit 一条，保证 import 阶段失败也留痕
emit("probe start python=%s" % sys.version)
```

理由：日志会被静默吞掉、且启动窗口很短；文件不会。**这是排查"插件装了没反应"的首选手段。**

---

## 三、看插件设置

设置文件：`$P`（`plugin_settings.json`）

**坑**：`adb shell "su -c 'cat <file>'" > out` 和 `adb exec-out` 都可能返回 **0 字节**。
**可靠做法**：把脚本 push 到 `/data/local/tmp/` 再 `su -c 'sh ...'` 执行，
由脚本内部 grep 出需要的字段。

### ★ 设置是按 `__id__` 分命名空间的（别误判成键冲突）

真实结构是**嵌套**的，不是扁平字典：

```json
{
  "<plugin_a>": { "provider": 1, "base_url": "...", "p1_url": "..." },
  "<plugin_b>": { "p1_url": "...", "preset": 1 }
}
```

**踩过的坑**：用 `tr ',' '\n'` 扁平化 dump 时，看到 `provider` 和 `p1_url`
排在一起，误判成「两个插件键名冲突」。拉下真 JSON 才发现各自有命名空间，
`p{N}_*` 在不同插件之间**不会互相覆盖**。
⇒ **判断键冲突必须看 JSON 真实嵌套结构，不能看扁平化输出。**

### 读设置的三个坑

1. **`grep -A40` 会把长命名空间截断** —— 曾据此误判「刚写的键没落盘」，实际它排在 40 行之后。
   **改用 awk 按命名空间起止提取**：

   ```bash
   $ADB -s $DEV shell "su -c 'sh /data/local/tmp/dump_settings.sh'" \
     | awk '/"<plugin_id>"/{f=1} f&&/^  },?$/{exit} f'
   ```

2. **拉 root 文件别直接 `adb pull`**：先
   `su -c 'cp <src> /data/local/tmp/x && chmod 644 /data/local/tmp/x'`，再 pull。
3. **要改设置文件，必须先 `am force-stop` 再拉**。因为 `on_plugin_unload`
   可能**写盘**（flush 统计/缓存）；不停应用就拉，拿到的是中间态，改完推回去会被覆盖。

   ```bash
   $ADB -s $DEV shell "am force-stop com.exteragram.messenger"; sleep 3
   $ADB -s $DEV shell "su -c 'cp $P /data/local/tmp/ps.json && chmod 644 /data/local/tmp/ps.json'"
   $ADB -s $DEV pull /data/local/tmp/ps.json /tmp/ps.json
   # 本地用 Python 改 json（d['<plugin_id>'][key] = value）
   $ADB -s $DEV push /tmp/ps.json /data/local/tmp/ps_new.json
   $ADB -s $DEV shell "su -c 'cp /data/local/tmp/ps_new.json $P && chown <app_uid>:<app_uid> $P && chmod 600 $P'"
   ```

   **UI 里点不准时这是唯一确定性做法**（见坐标漂移那节）。

> 设置里可能含 API Key。**打印/截图/外发前一律脱敏**。

---

## 四、宿主反编译取证

需要确认宿主真实类名 / 方法签名 / 字段名时，用 dex 级取证。可用工具类型：

| 能力 | 说明 |
|---|---|
| 按类描述找类 | 用类名子串定位 |
| 列方法 + **access flag** | 判断能否覆写 |
| 列字段 | 确认字段名与类型 |
| 搜字符串池 | 找常量、错误文案、类名 |
| 单方法指令级 dump | 看调用链 |
| **反向引用**（谁调用了它） | 排查「谁触发了 X」必用；正向查做不到 |

**判断方法可否覆写**：看 access flag。`public` 可覆写；`public final` **不可**。
例：某宿主类的 `isLanguageSupported()` 是 final，`getClient()` 是 public 可覆写。

**要读常量字面量**（如超时值）：指令级 dump 往往不显示字面量，
需自己解 `const-wide/16` / `const/16` / `const/4`。

> 有 jadx / apktool 时优先用它们；没有时用纯 Python 的 dex 解析脚本也能拿到上述信息。

---

## 五、排查顺序（别一上来就怀疑插件）

1. **确认哪套配置在生效**。多配置插件的 `active_profile` 是 **0 基**
   （0→配置1、1→配置2…），用户口述的编号常常和实际槽位对不上。
2. **绕开插件、用设备上的真实凭据直连 API**（PC 的网络环境和手机不同，**别用 PC 测**）。
   一次验完 Key / 地址 / 模型 / 协议四件事。
3. **量延迟**。宿主 HTTP 客户端超时可能**硬编码**（如 10 秒），超过必然失败。
4. **验协议**。第三方中转可能按 TLS 指纹拦客户端（换 UA 无效）；
   自有协议（如某些翻译服务）的认证/请求体/响应结构都与 OpenAI 式不同，必须单独适配。
5. **最后才看插件代码。**

---

## 六、设置页：刷新与长文本

### 主动重建设置页 —— 别再找 `reload_settings` 方法

```python
self.set_setting("key", value, reload_settings=True)   # 整页原地重建
self.import_settings(dict, reload_settings=True)       # 同理，默认就是 True
```

机制：它 post `NotificationCenter.pluginSettingsRegistered`，
设置 Activity 收到且 pluginId 匹配后重新取设置列表并刷新 adapter。

> **曾经踩过的坑**：`base_plugin.so` 字符串池里有 `reload_settings`，
> 但 `self.reload_settings(...)` 报 `AttributeError`，于是得出错误结论「SDK 没有刷新接口」。
> 实际它是 `set_setting` 的**关键字参数**。
> **教训：`.so` 里出现某个名字 ≠ 它是方法名，也可能是参数名/局部名。
> 必须用「符号 + 官方文档 + 真机实调」三方交叉验证。**

### 长说明文字想换行 —— 只有自建 View 可行

宿主把 `TextSetting.subtext` 渲染成**单行 + 省略号**控件：

| 写法 | 结果 |
|---|---|
| `Text(text=..., subtext=长文本)` | 截断 |
| `Custom(item=UItem.asButton(...))` + `item.multiline = True` | 截断（multiline 对 asButton 无效）|
| `Custom(factory=SimpleSettingFactory(create_view, bind_view).instance.java)` | **完整换行** ✓ |

```python
def _create_view(context, list_view, current_account, class_guid, resources_provider):
    from android.widget import LinearLayout, TextView
    from org.telegram.ui.ActionBar import Theme
    lay = LinearLayout(context); lay.setOrientation(LinearLayout.VERTICAL)
    tv = TextView(context); tv.setText(body); tv.setTextSize(13)
    tv.setTextColor(Theme.getColor(Theme.key_windowBackgroundWhiteGrayText2))
    lay.addView(tv); return lay

def _bind_view(view, item, divider, adapter, list_view):
    pass

FACTORY = SimpleSettingFactory(_create_view, _bind_view)   # 按 key 缓存！
row = Custom(factory=FACTORY.instance.java)
```

- **factory 必须缓存**（模块级 dict 按 key）：`SimpleSettingFactory` 内部用 class proxy
  生成真正的 Java 类，每次重建都新建会不断产生新类、持续占用内存。
- 取色用 `Theme.getColor(Theme.key_windowBackgroundWhiteBlackText / ...GrayText2)`，
  自动跟随深浅色主题。
- `Selector` 的**选项文字**同样是单行截断，无接口可改。

### 动态设置页（只显示「当前那一个」）

`create_settings()` 每次构建时读状态、用它拼字段键即可。配合
`on_change` + `reload_settings=True`，切换后整页带着新状态重跑：

```python
Selector(key="active_profile", items=labels,
         on_change=lambda i: self.set_setting("active_profile", i, reload_settings=True))
# 下面用 f"p{idx}_url" 之类的键拼出「只属于当前项」的字段
```

---

## 七、UI 导航与坐标

### 进插件设置页的路径

主界面右上角 **⋮ → 插件** → 插件卡片右下角**齿轮** → 该插件的设置页。

**`am start` 直接起插件管理 Activity 不行** —— 它们通常**未导出**，
会报 `Activity class ... does not exist`（且构造函数需要 `Plugin` 对象）。

### ⚠️ 软键盘会顶起输入行 —— 复用旧坐标必然点错

聊天页输入行（含发送键）的位置**取决于软键盘是否弹出**：
键盘未弹出时贴屏幕底部，弹出后被顶到中部（位移可达屏幕高度的 1/3）。

用「键盘没弹时」的坐标去点，会落到**消息区**（表现为什么也没发生）。
同理，`input text` 之后键盘一定是弹起的。

**对策**：每次点击前重新截图算坐标。另外 `input keyevent KEYCODE_BACK`
在聊天页会**直接退出会话回列表**（不是只收键盘），草稿会保留。

### ⚠️ 插件自建的弹窗行位置会漂移 —— 每次点击前重新截图

若插件的弹窗**每点一项就重建**，而某些行**只在特定状态下出现**，
弹窗又是垂直居中的 ⇒ **多一行 / 少一行，所有行的 y 坐标整体平移**。
用上一次截图的坐标去点会点错行（曾因此误触**全局开关**）。

对策：

1. **每次点击前重新截图**，按最新截图算坐标，不要复用。
2. 点完**再截一张**确认生效（别连续盲点两个不同行）。
3. 一旦点错且改的是**全局开关**，别继续用 UI 折腾 ——
   直接走「`am force-stop` → 改 settings.json → 重启」，确定性更高。

### ★ 零外发的端到端测试（推荐做法）

想验证「发送钩子 → 处理 → 预览」整条链路，又不想真的把消息发出去：
给插件设一个**预览模式**开关，然后

```
输入测试文本 → 点发送 → 弹窗出现【原文】/【结果】→ 点「取消」
```

`HookResult.CANCEL` 拦在发送之前，**取消后消息不会发出**，原文可回填输入框。
整条链路（含真实网络请求）都跑到了，零副作用。

收尾记得清空输入框（`input keyevent 123` 移到行尾，再连发 `KEYCODE_DEL`）：

```bash
$ADB -s $DEV shell "input tap <输入框x> <输入框y>"
$ADB -s $DEV shell "input keyevent 123"                      # MOVE_END
DELS=$(printf '67 %.0s' $(seq 1 30))
$ADB -s $DEV shell "input keyevent $DELS"                    # 连删 30 次
```

**注意**：`input text` 不能直接输中文（用英文测即可）；空格要写成 `%s`：
`input text 'hello%sthis%sis%sa%stest'`。

### ⚠️ 改 `plugin_settings.xml` 别用整行删除

后追加的 `<boolean name="plugin_enabled_xxx" .../>` 常常和 **`</map>` 在同一行**。
`sed -i "/xxx/d"` 会连 `</map>` 一起删掉 → XML 非法 → **所有插件开关全部失效**
（表现为插件一个都不加载、logcat 里毫无插件日志）。

```bash
$ADB -s $DEV shell "su -c 'sed -i \"/plugin_enabled_xxx/d\" $X'"
$ADB -s $DEV shell "su -c 'grep -q \"</map>\" $X || echo \"</map>\" >> $X'"   # 关键补丁
$ADB -s $DEV shell "su -c 'chown <app_uid>:<app_uid> $X; chmod 600 $X'"
```

> 更稳的做法：pull 出 XML → 本地用脚本增删行 → push 回去（见第八节）。

---

## 八、部署生效机制

### ★★ 装完 ≠ 生效：新插件必须「启用 + 重启」两步

**实测时间线**：

| 时刻 | 动作 | 结果 |
|---|---|---|
| T+0 | 文件放入插件目录 + 重启应用 | ❌ 零日志、零痕迹 |
| T+4min | 在应用内启用（XML 出现 `plugin_enabled_<id>`） | ❌ 仍无日志 |
| T+6min | **再次重启应用** | ✅ 加载成功 |

**关键**：`shared_prefs/plugin_settings.xml` 的修改时间会**早于**最近一次应用重启
—— 证明**应用启动时不扫描新增插件文件**，启用状态表只在用户操作插件页面时才更新。

### ⚠️ 但只有「首次注册」需要重启

| 场景 | 是否需要重启 |
|---|---|
| 新插件首次注册 | ✅ 需要（启用 + 重启） |
| 已注册插件的启用/禁用切换 | ❌ 不需要，立即生效 |

### 直接写 prefs 启用（可全自动，无需 UI）

```
force-stop → pull XML → 在 </map> 前插入一行 → push 回
（chown <app_uid>、chmod 600）→ am start
```

**顺序不可颠倒**：`force-stop` → 改文件 → 启动。应用运行中改 prefs 会被内存副本覆盖。

**风险**：改 `shared_prefs` 属敏感操作（**改前备份**）；XML 格式错误会让**所有**插件开关失效；
若文件里存在 `had_crash` / `crashed_plugin_id`，需一并清理（见下一节）。

### 判据：插件是否曾被加载过

看 `plugin_settings.json` 里**是否存在该插件 ID 的命名空间**。
不存在 ⇒ 从未成功加载过（不是"设置是空的"，而是**根本没建命名空间**）。

### 卸载验证的可靠判据

`remove_menu_item` 是否真的生效，看**重新注册后的 id 是否变化**：

```
on_plugin_unload  ->  菜单项已移除 id='<uuid-A>'
on_plugin_load    ->  菜单项已注册 id='<uuid-B>'   ← id 变了 = 旧实例已彻底清理
```

---

## 九、Chaquopy Java 对象互操作

### ★ Java 集合不实现 Python 迭代协议

菜单回调的 `context` 是 **`java.util.HashMap`**，不是 Python dict：

| 写法 | 结果 |
|---|---|
| `context.keys()` | ❌ `AttributeError: 'HashMap' object has no attribute 'keys'` |
| `list(context.keySet())` | ❌ `TypeError: 'HashMap$KeySet' object is not iterable` |
| `len(context)` | ❌ `TypeError: object of type 'HashMap' has no len()` |
| `context.size()` | ✅ |
| `context.isEmpty()` / `containsKey()` / `get()` | ✅ |
| **`context.keySet().toArray()`** | ✅ **可迭代 —— 正确的取键路径** |
| `context.entrySet().toArray()` | ✅ 元素为 `HashMap$Node`，`toString()` 形如 `'key=value'` |
| `java.util.ArrayList(context.keySet())` | ❌ `module 'java' has no attribute 'util'`（`import java` **不**引入子模块） |

**正确写法**：

```python
keys = [str(k) for k in context.keySet().toArray()]   # Java 数组可迭代
for k in keys:
    value = context.get(k)                            # Java Map 取值用 get()
```

**通用判据**：Chaquopy 暴露的是**Java 方法**，不是 Python 协议。
遇到"Python 写法报错"时，先试 Java 同名方法（`size()` 而不是 `len()`、`get()` 而不是 `[]`）。

> 不同菜单类型（主菜单 / 消息上下文菜单 / 聊天操作菜单…）的 context 键集合**各不相同**，
> 需各自实测。别把一个菜单的键表套用到另一个。

### ★★ 诊断法：Java 对象行为未知时不要猜，用 probe + dir

```python
def probe(label, fn):
    try:
        emit("%s -> %r" % (label, fn()))
    except Exception as e:
        emit("%s 失败: %s: %s" % (label, type(e).__name__, e))

probe("type", lambda: f"{type(obj).__module__}.{type(obj).__name__}")
probe("dir",  lambda: [a for a in dir(obj) if not a.startswith('_')])
```

- **每个探测独立 `try` + `except Exception`**（不要只捕获 `AttributeError`）
- `dir(obj)` 一次列出 Java 对象暴露的**全部方法**
- 拿到清单后**只测语义最接近的 2~3 条**，不做穷举

### ⚠️⚠️ 未捕获异常会被宿主静默吞掉

**最大的坑**：用 `except AttributeError` 捕获，但实际抛出的是 `TypeError`
→ 异常逃逸 → **日志里完全看不到任何痕迹**（既无输出，也无错误信息）。

**推论**：插件回调里的任何未捕获异常都不会出现在 logcat 中。
⇒ **排查时一律用 `except Exception`**，并**在每个分支都打日志**，
否则会陷入"代码明明执行了但什么都没发生"的死胡同。

### 反射：`find_class` 与 `Class.forName` 分工不同

| 写法 | 返回 | 能做什么 |
|---|---|---|
| `find_class("...")` | Chaquopy `JavaClass` | 只能作 `@java_subclass` 基类、传给 `hook_all_methods` 等；**没有反射方法**（`getName()` / `getDeclaredMethod()` 都不可用） |
| `Class.forName("...")` | 真 `java.lang.Class` | **可以反射**：`getDeclaredMethod(...)` / `getDeclaredConstructor(...)` |

```python
from java.lang import Class

cls = Class.forName("org.telegram.messenger.FileLog")          # 真 Class
method = cls.getDeclaredMethod("d", Class.forName("java.lang.String"))
method.setAccessible(True)
self.hook_method(method, MyHook())
```

> 方法名可能被混淆：写 hook 前先确认目标方法在**当前构建**里确实存在
> （`getDeclaredMethod` 会抛 `NoSuchMethodException`）。

---

## 十、metadata 陷阱

### metadata 必须是**单个字面量**，不能用括号拼接

```python
# ❌ 错误：AST 中是 BinOp 而非 Constant，loader 无法解析
__description__ = (
    "第一段。"
    "第二段。"
)

# ✅ 正确：单个字符串字面量
__description__ = "第一段。第二段。"
```

**实测**：用括号拼接写 `__description__` 的插件**完全不被扫描注册**
（XML 无条目、日志零痕迹），改为单行字面量后立即正常加载。

其余 metadata（`__id__` / `__name__` / `__version__` 等）同样规则。
**校验方法**：`ast.parse` 后检查每个 metadata 赋值节点的 `value` 是否为 `ast.Constant`。

---

## 十一、Windows 侧自动化脚本（PowerShell）

### 1. ⚠️ 脚本文件必须带 UTF-8 BOM（编辑后务必复查）

PowerShell 5.1 默认按 **ANSI/GBK** 读取脚本。无 BOM 的 UTF-8 中文会乱码
（`清理缓存` → `娓呯悊缂撳瓨`），并**破坏语法解析**，报出大量莫名其妙的
`表达式或语句中包含意外的标记`。

**Write / edit 类工具写出的文件都不带 BOM** —— 改完 .ps1 必须补：

```python
import pathlib
BOM = b'\xef\xbb\xbf'
p = pathlib.Path("tools/xxx.ps1")
data = p.read_bytes()
if not data.startswith(BOM):
    p.write_bytes(BOM + data)
```

**复查命令**：

```powershell
Get-ChildItem tools\*.ps1 | ForEach-Object {
  $b = [System.IO.File]::ReadAllBytes($_.FullName)
  "{0} BOM={1}" -f $_.Name, ($b[0] -eq 239 -and $b[1] -eq 187 -and $b[2] -eq 191)
}
```

**改完跑一次语法自检**（能立刻发现 BOM 丢失与括号错误）：

```powershell
$errs = $null
[System.Management.Automation.Language.Parser]::ParseFile("tools\xxx.ps1", [ref]$null, [ref]$errs) | Out-Null
if ($errs) { $errs | ForEach-Object { $_.Message } } else { "OK" }
```

### 2. `$ErrorActionPreference = 'Stop'` 会与 adb 冲突

adb 把进度/警告写入 **stderr**，`Stop` 语义会将其误判为终止性异常：

```
EXCEPTION: ...: 1 file pushed, 0 skipped. 4.1 MB/s (5308 bytes in 0.001s)
```

**修法**：脚本统一用 `'Continue'`，关键失败点用显式 `exit` 判断。

### 3. 不支持 `& $数组` 调用

```powershell
# ❌ 会把整个数组当成单个命令名
$args = @($adb, '-s', $Serial)
& $args logcat -d

# ✅ 用 splatting
$adbArgs = @('-s', $Serial, 'logcat', '-d')
& $adb @adbArgs
```

### 4. 多设备必须 `-Serial` 显式指定

同时存在真机与模拟器时，不指定会报 `more than one device/emulator`。
脚本应：唯一在线设备时自动选用，多个时**报错并要求指定**，不要静默挑一个。

### 5. 删除到回收站（受限环境）

若环境禁用 `Add-Type`，`Microsoft.VisualBasic.FileIO.FileSystem` 路线走不通，
可用 Python ctypes 直调 Win32：

```python
import ctypes
from ctypes import wintypes
class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                ("fFlags", ctypes.c_uint16), ("fAnyOperationsAborted", wintypes.BOOL),
                ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
op = SHFILEOPSTRUCTW()
op.wFunc  = 3                            # FO_DELETE
op.pFrom  = r"<绝对路径>" + "\0\0"        # 双 NUL 结尾
op.fFlags = 0x0004 | 0x0010 | 0x0040     # SILENT | NOCONFIRMATION | ALLOWUNDO
ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
```

---

## 十二、插件开发的高危陷阱

### ★★★ Chaquopy 不允许继承 Java 接口 —— 表现为「插件完全没反应」

```python
from java.lang import Runnable
class X(Runnable):            # ← 模块 import 阶段就抛
    def run(self): ...
# TypeError: Java classes can only be inherited using static_proxy or dynamic_proxy
```

**为什么难查**：异常发生在**模块 import 阶段**，插件进不到 `on_plugin_load`，
**一行日志都打不出来**（release 版 `FileLog.d` 可能被直接 return），
只表现为「插件装了没反应」。

**解法**：延迟执行改用 `threading.Thread` + `android_utils.run_on_ui_thread`；
确实需要 Java 接口时用 `java.dynamic_proxy` / `static_proxy`。

**定位手法**：写「import 探针」插件 —— 把每条 import 放进 `try/except`，
结果写进文件（**在 import `base_plugin` 之前就落盘**，这样即使加载失败文件也已写出）。

### ★★ 插件加载失败会被自动禁用 —— 出现「怎么启用都会被关掉」的假象

插件引擎加载失败时，id 会被记进 `crashed_plugin_id`；下次启动读到
`had_crash` + `crashed_plugin_id`，就执行 `plugin_enabled_<id> = false`。

- 遇到「启用了、重启了，还是 disabled」→ **先怀疑 import 阶段异常**，别怀疑 prefs
- `am force-stop` 会留下 `had_crash`。**手动写 `plugin_settings.xml` 启用插件时，
  必须以「不含 `had_crash` / `crashed_plugin_id` 的干净文件」为基础覆盖**，
  否则会把上一次的崩溃标记带进去，插件被立刻禁用

### ★★ `get_private_field` 是高频钩子里的性能杀手

`hook_utils.get_private_field(obj, name)` 每次都要**按名字在类里重新查找字段**。
放进会被反复调用的钩子里，单次可达毫秒级。

**解法：缓存 `java.lang.reflect.Field`**，之后只做 `field.get(obj)`（可快约 1000×）。

```python
def field_of(self, obj, name):
    key = (obj.getClass().getName(), name)
    f = self._field_cache.get(key)
    if f is None:
        cls, depth = obj.getClass(), 0
        while cls is not None and depth < 8:      # getDeclaredField 只查本类
            try:
                f = cls.getDeclaredField(name); break
            except Exception:
                cls = cls.getSuperclass(); depth += 1
        if f is None:
            self._field_cache[key] = False; return None
        try:
            f.setAccessible(True)                 # ⚠️ 必须单独 try
        except Exception:
            pass
        self._field_cache[key] = f
    if f is False:
        return None
    return f.get(obj)
```

**两个必踩的坑**：

1. `setAccessible` 若和外层共用一个 try，异常会被吞掉后**缓存成「字段不存在」**，
   后续全部返回 None。
2. `getDeclaredField` **只查本类**，继承字段必须向上遍历父类。

### ★ `self.get_setting()` 在高频钩子里也很慢

跨语言读 SharedPreferences。**加 TTL 缓存**（如 20s）即可。

### ★ 反直觉：先测再优化，别猜热点

看起来"一定很高频"的方法，实测可能**在目标操作下调用 0 次**（只在特定界面出现时才调）。
**埋点实测**才知道真相：

```python
_p("STAT %-18s calls=%-5d avg=%7.1fus max=%8.1fus" % (k, n, avg, mx))   # 每 15s 汇总
```

### ★ 跨插件调用：`sys.modules` 里能拿到别的插件

插件引擎用 `python.getModule(pluginId)` 加载
⇒ **插件模块以 `__id__` 为名注册进 `sys.modules`**。

```python
import sys
mod  = sys.modules["<other_plugin_id>"]                # 另一个插件的模块
inst = getattr(mod, "_ACTIVE_INSTANCE", None)          # 它的实例（如果它导出了）
inst.bridge.do_something(...)                          # 调它的能力
```

注意：**Elyx 编译插件（`.eaf`）走独立命名空间**（`ElyxPlugins.<id>...`），
**不在 `sys.modules["<id>"]`**；用 `find_class` 找其 DEX 里的类也会返回 `None`
（由 `InMemoryDexClassLoader` 加载，不在应用 ClassLoader）。

### ★ 往宿主容器注入 View：触摸会被 `onInterceptTouchEvent` 拦掉

向宿主的匿名子容器 `addView` 自己的控件时，若该容器 **override 了
`onInterceptTouchEvent`**，事件**不会分发给子视图**，
子视图的 `OnClickListener` **不会触发**；实际走的是容器的 `onTouchEvent`。

⇒ **两条路径都要接管**：hook 容器的 `onTouchEvent`（用 `container.getClass()` 运行时取类），
同时保留子视图的 `OnClickListener` 作双保险。

### ★★ 定位控件坐标：用 `getLocationOnScreen()`，不要目测截图

从缩放过的截图估算 `input tap` 坐标**极不可靠**（曾偏出数百像素，白折腾两轮）。
让插件自己上报：

```python
loc = [0, 0]
container.getLocationOnScreen(loc)
_p("at screen (%d,%d) size %dx%d" % (loc[0], loc[1], w, h))
```

`uiautomator dump` 对 Telegram 界面**可能返回空**，不可依赖。

### ★ Java int 是 32 位有符号 —— 颜色值会溢出

```python
Theme.getColor(...)                  # 0xFF3390EC = 4281544940
PorterDuffColorFilter(0xFFFFFFFF, …) # 4294967295
# OverflowError: value too large to convert to int32_t
```

```python
def _signed32(v):
    v = int(v) & 0xFFFFFFFF
    return v - 0x100000000 if v > 0x7FFFFFFF else v
```

### ⚠️ `/data/local/tmp` 是多会话共享区 —— 清理前必须查最近写入时间

设备可能**同时有多个会话**在跑不同插件任务。清理前先：

```bash
adb shell "su -c 'ls -lat /data/local/tmp/ | head -20'"
```

若看到**几分钟前刚写入**的文件，说明别的会话正在用，**不要动**。

### ★★ 隐藏宿主按钮前，先确认「有几个同类控件、显示条件是否互斥」

**翻车案例**：需求是「隐藏输入框里的机器人命令斜杠」，
把两个都带 "bot" 的按钮**一起**隐藏 —— 结果**bot 聊天的左下角菜单按钮也消失**。

宿主里这两个控件是**互斥显示**的（一个显示时另一个为 `null`）：

```java
boolean z = botMenuButtonType != BotMenuButtonType.NO_BUTTON && dialog_id > 0;
// z == true  → 显示 botCommandsMenuButton（命令菜单入口，文本「菜单 / Menu」）
// z == false → 显示 botButton（48×48 ImageView，图标 input_bot1 / input_bot2）
```

**三条教训**：

1. **名字相近不等于同一个控件** —— 必须回宿主源码确认 `addView` 的
   **父容器与 Gravity**，别靠命名猜
2. **非目标场景测不出来**：普通聊天里某个控件为 `null`，隐藏分支根本不执行
   ⇒ 这类缺陷**必须在真实触发场景里验证**
3. **字段名用常量集中管理**，避免同一名字散落在多个钩子里导致同类误伤

### 特定类型插件的额外经验（外部 API / 翻译类）

- **「切一下 / 重开一下就恢复正常」⇒ 优先怀疑队列积压或节流**，不是逻辑错。
  典型：滚动不再处理，是因为批次间被 `minIntervalMs` 限速、并发数受限。
  吞吐 ≈ `每批条数 / max(最小间隔, 网络耗时)`。
- **档位要按服务商分**：有「每天 N 次」硬上限的免费层要放宽间隔、降并发；
  按字符/token 计费的可以压到几百毫秒 + 多并发。
- **限速参数必须按当前设置实时算**。若只在插件加载时构建一次并缓存，
  用户改设置就**必须重启应用**才生效 —— 很容易漏的 bug。
- **抓请求时间戳判断是否被限速**：间隔 ≈ `minIntervalMs` 就说明队列正被它限速。
- **验协议时先分清"用的是哪一套"**：同一服务的官方 API 与网页端私有接口，
  认证方式、请求体编码、响应结构、计费口径**完全不同**。
  域名/环境选错的症状可能是 **403 而不是 401**，别去查 Key 有效性。
- **语言/区域码的大小写与格式**要按服务方要求（有的要大写、有的要求带地区后缀）；
  与宿主的小写 Locale 比较时**两边都要归一化**，否则会「没处理但也不报错」。

---

## 十三、手机 UI 自动化工具（可选增强）

有些环境提供 **MCP 形态的手机控制工具**（截图 / 点击 / 滑动 / 输入 / 起停应用 / 抓日志）。

**能力边界（重要）**：这类工具通常**没有任何通用 shell 能力** ⇒
装插件、读写设置、dex 反编译**仍然只能走前面的 adb 管线**。

### 一、截图取坐标 —— 替代「目测估算」（最有用）

截图工具通常**直接把画面作为图像返回给模型**，不需要自己 `screencap` 再缩放读图，
并且会**自动给出坐标换算系数**（因为返回图被缩放过），这正是「目测坐标偏几百像素」的解药：

```
Screenshot is 465x1024. Screen coordinates are 1440x3168.
To tap something you see in this screenshot, multiply its x by 3.097 and y by 3.094.
```

- 要落盘用「保存截图」类工具。
- **坑**：返回的常是 **JPEG**，写文件时**扩展名必须 `.jpg`**；存成 `.png`
  会让读图工具报 `extension declares image/png, but the bytes use a different image format`。

### 二、元素树在 Telegram 类界面上通常**不可用**

```
list_elements_on_screen → isError=true
failed to get view tree dump: no XML content found in uiautomator dump
```

这与「`uiautomator dump` 被 Killed / 返回空」是同一回事 —— **换后端也一样**，
底层仍是 uiautomator。⇒ 这类界面**只能靠截图 + 坐标点击**，别指望无障碍树那条路。

### 三、抓插件日志：**必须并发**，且 filter 要带方括号

流式日志工具**只抓调用开始之后**的日志（无新日志若干秒后停止并返回）。

**① filter 必须带方括号**：

| filter | 结果 |
|---|---|
| `tag=PyObject` | ❌ 0 条 |
| **`tag=[PyObject]`** | ✅ 命中 |
| `message=PyObject` | ❌ 0 条 |

logcat 里的 tag 字面量就是 `[PyObject]`（含方括号）—— 这点和
`adb logcat \| grep` 的直觉不同，写错就是静默 0 条。

**⚠️ 多个 filter 是 AND 不是 OR**，所以**没法一次覆盖三条日志通道**
（`[PyObject]` / `plugin.<id>` / `[Python]`）。要全覆盖只能：按 tag 分别调用三次，
或**不加 filter** 抓一大段再自己筛。

**② 必须「先开日志流、再启动应用」**。顺序调用抓不到（日志先于调用产生）；
这类工具通常支持并发请求：

```
发 get_device_logs {limit:40, filter:["tag=[PyObject]"]}   ← 流已开
发 launch_app                                             ← 此时才启动
   → 捕获启动阶段全部插件日志（含各插件 hook 日志）
```

⇒ 这正好解决第二节「启动十几秒后日志归零、慢一步就误判插件没加载」的痛点。

**返回通常是结构化 JSON**，比原始 logcat 好筛：

```json
{"timestamp":"...","message":"[callThrows] [<id>] hooked ...","level":"Debug","pid":12345,"process":"com.exteragram.messenger","tag":"[PyObject]"}
```

### 四、注意事项

1. **截图会把整屏送进模型上下文** —— 若要求「设置里的 Key 一律脱敏」，
   **别停在插件设置页截图**。
2. 手机自动化 daemon 可能占用设备**唯一的 UiAutomation 连接**，与 Appium 等互斥；
   一般可手动 stop（空闲一段时间也会自动退出）。
3. 「批量命令」类工具能把「点击+输入+点击」合成一次调用，但**与
   「每次点击前重新截图」的约束冲突** —— 弹窗行会漂移时别用。
4. 首次连接可能需要下载辅助二进制；有缓存后无需联网。
