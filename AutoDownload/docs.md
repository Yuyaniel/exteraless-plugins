# Auto Download — 开发文档

> 改代码前先读这份文件。`.plugin` 是源码，没有构建步骤。

## 文件后缀：源码 `.plugin`，设备 `.py`

同一个 Python 文件，两处后缀不同，别弄混：

| 场景 | 文件名 | 说明 |
|---|---|---|
| 仓库 / 本地源码 | `auto_download.plugin` | 就是 Python，只是换了个后缀；**没有构建步骤**，直接改它 |
| 设备上 | `auto_download.py` | 加载器只认 `.py`；文件名必须等于 `__id__` |

Ruff 直接跑在 `.plugin` 上（`ruff check auto_download.plugin`）。

探针同理：源码 `tools/autodl_probe.plugin` → 设备 `autodl_probe.py`（id `autodl_probe`）。

## 元数据

| 字段 | 值 |
|---|---|
| id | `auto_download` |
| 版本 | 1.0.0 |
| 最低应用 | exteraGram `>=12.5.1` |
| 最低 SDK | `>=1.4.5.0`（用到 `hook_all_methods`、`find_class`） |
| 文件 | `auto_download.plugin`（源码）、`tools/autodl_probe.plugin`（探针，独立插件） |
| 依赖 | 无（不用 `__requirements__`） |

## 它到底怎么工作的

不是自己去调下载接口，而是**改写宿主已有的判断结果**。

Telegram 自己在 `org.telegram.messenger.DownloadController` 里决定"这条媒体要不要自动下载"。
本插件挂住 `canDownloadMedia(...)`，在它返回之后按本插件的规则改写返回值：

- 我们的规则说"要下" → 回写成宿主的**允许**值
- 我们的规则说"不许下" → 回写成宿主的**禁止**值
- 我们的规则说"不管" → 原样放行，应用自己说了算

**"允许/禁止"回写成什么，由被钩方法的真实返回类型在运行时决定**，不写死：

| 返回类型 | 允许 | 抑制 |
|---|---|---|
| `boolean` | `True` | `False` |
| `int` | `AUTODOWNLOAD_WIFI` / `AUTODOWNLOAD_MOBILE`（按 `allow_value_mode`） | `AUTODOWNLOAD_DISABLED` |
| 其它 | 不干预，只记诊断 | 同左 |

返回类型用 `param.method.getReturnType()` 读一次后按方法缓存，不是每条消息都反射。

好处是下载的排队、分组、续传、通知全由 Telegram 自己的管线做，插件只改一个决策位。
风险是这个方法名/签名会随版本变——所以插件**不硬编码任何常量值**，全部运行时读取。

## 架构三层

```
决策层   build_config() / decide()        纯函数，零 SDK 依赖，可本地单测
            ↑ 输入 get(key, default)  →  输出 True / False / None
适配层   _resolve_host_api()              读宿主常量、挂钩
        _classify()                      MessageObject → 媒体类型桶
        _network()                       wifi / mobile
UI 层    create_settings()               设置页
        _on_chat_menu()                  会话菜单入口
```

`decide()` 的三态语义是整个插件的核心，所有分支都在这个函数里：

| 返回 | 含义 | 对宿主返回值的影响 |
|---|---|---|
| `True` | 允许下载 | 改成允许常量 |
| `False` | 明确抑制 | 改成 `AUTODOWNLOAD_DISABLED` |
| `None` | 不干预 | 原样保留 |

### 决策优先级（自上而下，命中即返回）

| # | 条件 | 结果 |
|---|---|---|
| 1 | 插件总开关关闭 | `None` |
| 2 | 媒体类型不在 `KINDS` 里 | `None` |
| 3 | 会话有自定义配置，且被显式禁用 | `False` |
| 4 | 会话有自定义配置，已启用 | 用**该会话**的规则 |
| 5 | 无自定义配置，`scope_mode = 所有会话` | 用**默认**规则 |
| 6 | 无自定义配置，`scope_mode = 仅已添加的会话` | `None` |

未知网络类型（以太网 / VPN 等）按**移动数据**处理——保守优先，避免意外消耗流量。

## 媒体类型分类

走 TL 结构而不是 `MessageObject.isVideo()` 这类内部辅助方法。TL 是线协议的一部分，跨版本稳定得多。

| TL 结构 | 归类 |
|---|---|
| `TL_messageMediaPhoto` | `photo` |
| `TL_messageMediaDocument` + `TL_documentAttributeVideo` | `video` |
| `TL_messageMediaDocument` + `TL_documentAttributeAnimated` | `gif` |
| `TL_messageMediaDocument` + `TL_documentAttributeAudio` | `audio`（语音与音乐同一桶） |
| `TL_messageMediaDocument` + `TL_documentAttributeSticker` | 不干预（贴纸很小，交给应用） |
| `TL_messageMediaDocument` + `TL_documentAttributeImageSize` | `photo`（以文件形式发送的无压缩图片） |
| `TL_messageMediaDocument` + 无上述属性 | `file` |
| 其它 media（geo / venue / contact / poll / webpage / empty） | 不干预 |

顺序重要：Video 属性优先于 Animated 属性。

## 网络类型判定

两条路径，先成功后缓存 5 秒：

1. `ConnectionsManager.isConnectedToWiFi()`——宿主自己的判断，语义一致，优先
2. Android `ConnectivityManager.getActiveNetworkInfo()`——退路
3. 都失败 → 按移动数据

路径 1 先试 Chaquopy 的静态直读，失败再走 `Class.forName` 反射。

## 设置键

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `enabled` | bool | `True` | 插件总开关 |
| `scope_mode` | int | `0` | `0`=所有会话，`1`=仅已添加的会话 |
| `default_{wifi\|mobile}_{kind}` | bool | 见下 | 默认规则 |
| `peer_index` | JSON 字符串数组 | `[]` | 已配置会话的有序列表 |
| `peer_title_{peer}` | str | — | 会话显示名（设置页用） |
| `peer_{peer}_enabled` | bool | `True` | 该会话是否启用 |
| `peer_{peer}_{wifi\|mobile}_{kind}` | bool | 继承默认 | 该会话的规则 |
| `log_decisions` | bool | `False` | **每条消息**的决策日志。实测一分钟能刷近两千行，平时保持关闭；「钩子触发」「常量缺失」这类结构性信息不受它影响 |
| `quiet` | bool | `False` | 完全静默：连结构性诊断也不输出，**只剩一行加载标记和错误信息**。打开后日志量归零，但出问题也没有线索可查 |
| `allow_value_mode` | int | `0` | `0`=自动，`1`=始终 WIFI 常量，`2`=始终 MOBILE 常量 |

`kind` ∈ `photo` `video` `gif` `audio` `file`。

默认规则初值：

| | 图片 | 视频 | GIF | 语音/音频 | 文件 |
|---|---|---|---|---|---|
| WiFi | ✔ | ✔ | ✔ | ✔ | ✘ |
| 移动数据 | ✔ | ✘ | ✘ | ✘ | ✘ |

会话键是 `dialog_id` 的字符串形式（频道/群组为负数）。首次加入会话时会把当时
的默认规则固化成该会话的起点，之后两者独立演进。

## 菜单项

| 类型 | 文本 | 行为 |
|---|---|---|
| `MenuItemType.CHAT_ACTION_MENU` | 自动下载设置 | 弹出三选一对话框 |
| `MenuItemType.PROFILE_ACTION_MENU` | 自动下载设置 | 同上 |

拿不到 `Activity` 时退化成循环切换：未配置 → 启用 → 禁用 → 移除。

菜单 `context` 是 `java.util.HashMap`，**不能用 `.keys()`**，只能 `get()`。
`dialog_id` 优先从 `dialog_id` 取，退路是 `chatId` / `userId` / `chat.id` / `user.id`。

## 已知风险与假设

1. **挂点是运行时枚举的**：不硬编码 `canDownloadMedia`，而是把 `DownloadController`
   里名字含 `candownload` / `autodownload` 的方法全列出来逐个尝试挂载
   （枚举失败才退回 `canDownloadMedia`；编译器生成的 `lambda$…` 内部方法会跳过）。
   这样版本改名也不会整个失效。
2. **"允许"常量只在返回类型是 `int` 时才用**。宿主若返回 `boolean`，直接回写
   `True` / `False`，不再依赖 `AUTODOWNLOAD_*` 常量存在。
   若 `int` 版本的语义与假设相反（该下的没下 / 不该下的下了），
   把 `allow_value_mode` 调成固定值。
3. **★ 位掩码模型（已实测确认）**：exteraGram 12.10.6 一系没有
   `AUTODOWNLOAD_DISABLED / WIFI / MOBILE` 三态常量，宿主用的是**类型位掩码**。
   实测字段表：

   | 字段 | 值 |
   |---|---|
   | `AUTODOWNLOAD_TYPE_PHOTO` | `1` |
   | `AUTODOWNLOAD_TYPE_AUDIO` | `2` |
   | `AUTODOWNLOAD_TYPE_VIDEO` | `4` |
   | `AUTODOWNLOAD_TYPE_DOCUMENT` | `8` |

   （没有 `MUSIC` / `GIF`；`loadingAutoDownloadConfig` 是 boolean，被名字子串捞进来的）

   **`getAutodownloadMask()` 实测返回 `83886080`**，而
   `83886080 = 0x5000000 = 5 << 24`，`5 = PHOTO(1) | VIDEO(4)` —— 即
   **低 24 位另有用途，24 位以上才是"允许哪些类型"**。

   当前状态与缺口：

   | 重载 | 返回 | 现状 |
   |---|---|---|
   | `canDownloadMedia(MessageObject)` | `boolean` | ✅ 按 boolean 回写，工作正常 |
   | `canDownloadMediaInternal(MessageObject)` | `int` | ❌ 缺常量 → 决定不落地 |
   | `canDownloadMediaType(MessageObject)` | `int` | ❌ 同上 |

   **int 语义还没解开**，缺的是"允许"情况下的原返回值 —— 目前只采到"拒绝"
   （三个方法首次调用都是 `0` / `False`，见上面那条注意事项）。
   新版本的 `int 返回值样本` 段会自动按「方法 + 媒体 + 网络 + 决策」去重采集，
   凑齐两侧取值后才能定"允许"该回写什么。**在那之前不要动 int 分支**：
   猜错的表现是"该下的没下"，比现状更糟。
4. **方法名会随版本变**。挂不上时插件不崩，只是不生效，并在日志里写明原因。
3. **应用自身的全局自动下载设置仍然参与**。本插件只改"这条媒体此刻要不要下"，
   不改用户存储偏好。若宿主在别处还做了前置判断（例如全局开关关闭后根本不调用
   `canDownloadMedia`），本插件就无从介入——这时需要先在应用里打开自动下载总开关。
4. **贴纸与联系人/位置等不干预**，交给应用。

## 真机验证步骤

1. **主插件自己会落盘自检报告**：加载时和每次点「运行自检」都会把
   `auto_download_report.txt` 写到插件目录。抓不到 logcat（设备不在手边、
   或启动日志时间窗已过）时，用任意 root 文件管理器看这个文件即可。
   里面有：`AUTODOWNLOAD_*` 常量、挂了几个重载、实际返回类型、最近诊断记录。
2. 需要更细的数据时再装 `tools/autodl_probe.plugin`，启用，重启应用
3. `adb pull /data/data/com.exteragram.messenger/files/plugins/autodl_probe_report.txt`
4. 看报告第 3、4 节：确认 `AUTODOWNLOAD_*` 常量值、确认哪个重载真的被调用
5. 在 WiFi 和移动数据下各收一条媒体，再看
   `autodl_probe_samples.txt` 里的"原返回值"
6. 用返回值反推"允许值"是否与插件假设一致；不一致就调 `allow_value_mode`
   （返回 `boolean` 时该设置项不参与，见上表）

装主插件：

```bash
adb push auto_download.plugin /data/local/tmp/auto_download.py
adb shell "su -c 'cp /data/local/tmp/auto_download.py /data/data/com.exteragram.messenger/files/plugins/auto_download.py'"
adb shell "su -c 'chown <uid>:<uid> /data/data/com.exteragram.messenger/files/plugins/auto_download.py'"
adb shell "su -c 'chmod 600 /data/data/com.exteragram.messenger/files/plugins/auto_download.py'"
adb shell "am force-stop com.exteragram.messenger"
```

日志过滤：`adb logcat -s plugin.auto_download`。

## 日志怎么读

诊断分两类，由**两个开关**分别控制：

| 类别 | 何时输出 | `log_decisions` | `quiet` |
|---|---|---|---|
| **结构性**（候选方法、钩子首次触发、常量缺失、int 样本） | 每个方法/每类问题**各一条**，有界（≤ ~60 行/会话） | ❌ 不受影响 | ✅ 也被拦掉 |
| **决策细节**（每条消息的媒体/会话/网络/决策） | 每次调用（实测 2000 行/分钟） | ✅ 默认关 | ✅ 也被拦掉 |

即：`log_decisions` 开 → 全量；两个都关 → 只剩结构性；`quiet` 开 → **只剩一行加载标记 + 错误信息**。

错误信息（`_error`）**不受任何开关影响** —— 出错必须看得见。

### 结构性信息（排查先看这些）

加载时**一行**列出 `DownloadController` 里所有候选方法连同签名：

```
候选方法 10 个: canDownloadMedia: canDownloadMedia(org.telegram.tgnet.TLRPC$Message) -> int | ... ;;  getAutodownloadMask: getAutodownloadMask() -> int ← 全为无参重载，拿不到消息，无法干预
```

跟随一行列出宿主上**真实存在**的 `AUTODOWNLOAD*` 字段：

```
AUTODOWNLOAD 字段（N 个）: AUTODOWNLOAD_TYPE_PHOTO=1, ...
宿主类上没有任何 AUTODOWNLOAD* 静态字段 —— 这个构建用的是位掩码模型
```

> **这一行是判断模型的关键**：固定名 `AUTODOWNLOAD_DISABLED/WIFI/MOBILE`
> 读不到时，插件会把真实字段全枚举出来。若一个字段都没有，说明该构建走的是
> `getAutodownloadMask() -> int` 的**位掩码模型**，而不是三态模型。

每个被钩方法**第一次**触发时记一条（之后静默）：

```
钩子触发 #1: canDownloadMedia(org.telegram.messenger.MessageObject) -> boolean @ ...DownloadController | 参数类型=空 —— 该方法无参数 | 原返回值=-1
```

- **`原返回值=`** 是反推宿主 int 语义的关键。⚠️ **但它只是该方法的第一次调用**
  （`_note_call` 每个方法只记一条），第一次碰上的消息未必有代表性。
  要看**多种组合**的原返回值，得用报告里的「int 返回值样本」段 ——
  那一段按「方法 + 媒体 + 网络 + 决策」去重，最多 40 条。
- `参数类型=空 —— 该方法无参数` 等价于旧版那条
  `args=jarray('Ljava/lang/Object;')([])`（Chaquopy 对空 `Object[]` 的 repr）

### 「不干预」的原因也要能区分

`媒体=?` 这一个记号同时代表两种完全不同的情况，光看它分不出来：

| 真实情况 | 危害 |
|---|---|
| 纯文本 / 服务消息（`media` 为 `None`） | 无，本来就没媒体可下 |
| media 类名不在收录表里（webpage / geo / poll…） | 无，按设计不干预 |
| **某个本该处理的类型没被收录** | **有** —— 这类消息永远不自动下载 |

所以 `_classify` 每次返回 `None` 时都会记一条**带实际类名**的提示，每类只记一次：

```
不干预: 纯文本/服务消息（media 为 None）
不干预: 未收录的 media 类名: TL_messageMediaWebPage
不干预: 贴纸（TL_documentAttributeSticker），交给应用
```

看到 `未收录的 media 类名: xxx` 就是个明确信号：要么把它加进分类表，
要么确认它确实不该下载。**别只看 `媒体=?`。**

### ⚠️ 决策日志必须带方法名

同一条消息会被**三个**方法各查一次：

| 方法 | 返回 | 能否改写 |
|---|---|---|
| `canDownloadMedia(MessageObject)` | `boolean` | ✅ 能 |
| `canDownloadMediaInternal(MessageObject)` | `int` | ❌ 缺常量时不能 |
| `canDownloadMediaType(MessageObject)` | `int` | ❌ 缺常量时不能 |

早期版本的诊断文本把方法名**写死**成 `canDownloadMedia(MessageObject)`，
于是这三条打出来是同一句话，日志看着像"重复刷屏"，实际是三个不同方法。
现在每条决策日志都带真实签名，别再把它们当成重复日志。

### 自检报告里的汇总表

`auto_download_report.txt` 的「各重载统计」把上表压成几行，比翻日志快：

```
## 各重载统计
  调用 764    改写 335    放弃 429    放过 184    canDownloadMedia(MessageObject) -> boolean @ ...
  调用 429    改写 0      放弃 429    放过 0      canDownloadMediaInternal(MessageObject) -> int @ ...
```

判读：**「改写」为 0 而「放弃」不为 0 ⇒ 这条重载返回 int，决定没落地。**

以上全部会写进 `auto_download_report.txt`，点「运行自检」可刷新（弹窗也会直接显示
「调用 N 次 · 改写 M 次 · 放弃 K 次」）。

## 性能

**挂着钩子就一定有开销**，只是大小问题。关掉决策日志（`log_decisions`）消掉的
是最大的一块，但不是全部。

### 关掉日志消掉了什么

`_diag()` 与 `_note()` 在关闭时**第一行就 `return`**，所以 **字符串格式化**、
**跨语言调 Java Logger**、**写 logcat** 全都不执行。实测开着时约 **44 行/秒**
（浏览一个频道）。

这两个判断读的是 `_diag_on` / `_note_on` 两个**普通属性**（在 `_config()` 里
刷新），不是 `_config()` 调用 —— 所以关掉日志时热路径上只是「读属性 + 判断」，
连函数调用和 TTL 缓存检查都省了。

### 仍然存在的开销

每次判定大约 **15 次跨语言调用**，主要来自：

| 位置 | 说明 |
|---|---|
| `_on_can_download` | 读 `param.args` / `len` / 取 `args[0]`；`hasattr` 探 messageOwner、media |
| `_classify` | 读 `messageOwner.media`；`getClass().getSimpleName()` |
| `_classify_document` | 遍历 document attributes，**每个属性 3 次跨语言调用** |
| `_peer_key_of` | 读 `dialog_id` |
| 回写 | `param.getResult()` + `param.setResult()` |

`_network()` 与 `_config()` 有 TTL 缓存（5s / 3s），这两处不花钱；
`decide()` 是纯 Python。

### 已做的一处优化

`str(param.method)` 是跨语言调用，**曾经在一条调用链上被算 4 次**
（`_call_key` / `_note_call` / `_handle_message_object_hook` 里再取 / `_return_kind_of`）。
现在在 `_on_can_download` 里取一次（`_raw_key`），沿调用链传下去。

`tests/test_plugin_adapter.py` 里有一条**运行时计数**的回归断言把这件事钉住了：
一次钩子触发只允许 1 次。改坏了测试会红。

### 还要不要继续优化

**先测再优化，别猜热点。** 判据是自检报告里的「各重载统计」：

- 每秒几十次调用 → 不用管
- 每秒上千次（批量收消息、快速滚动） → 才值得动手

真正可能被感知的是**滚动时的瞬时卡顿**，那需要埋点计时才能确认。

## 本地测试

```bash
python tests/test_decision_engine.py    # 纯函数：43 项
python tests/test_plugin_adapter.py     # 适配层：41 项
```

两套都用桩模块替换 SDK 后 **exec 插件源码本身**，所以测的是真代码，不是副本。

| 文件 | 覆盖 |
|---|---|
| `test_decision_engine.py` | 默认规则、作用域、自定义覆盖、会话禁用、总开关、日志开关默认值、边界与健壮性 |
| `test_plugin_adapter.py` | 宿主 API 探测与候选方法枚举（含跳过 `lambda$`）、真实字段表、int/boolean 两种返回类型的回写、`TLRPC$Message` 重载、掩码采样去重、"不干预"原因只记一次、决策日志开关、完全静默（含"静默下仍照常改写"与"错误不受静默影响"）、各重载统计、自检报告内容、**热路径跨语言调用次数** |

第二套里那个假宿主是照**位掩码构建**做的（只有 `AUTODOWNLOAD_TYPE_*`，没有三态常量），
和真机实测的那套一致。

## 提交前检查

```
[ ] ruff check auto_download.plugin
[ ] python tests/test_decision_engine.py
[ ] python tests/test_plugin_adapter.py
[ ] docs.md 更新（改了设置键 / 钩子 / 架构时）
[ ] README.md 更新（改了用法时）
[ ] releases/vX.Y.Z/ 只在发版时创建
```
