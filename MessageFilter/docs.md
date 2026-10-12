# Message Filter — 开发文档

> 改代码前先读这份文件。`.plugin` 是源码，没有构建步骤。

## 文件后缀：源码 `.plugin`，设备 `.py`

| 场景 | 文件名 | 说明 |
|---|---|---|
| 仓库 / 本地源码 | `message_filter.plugin` | 就是 Python，只是换了个后缀；**没有构建步骤**，直接改它 |
| 设备上 | `message_filter.py` | 加载器只认 `.py`；文件名必须等于 `__id__` |

## 元数据

| 字段 | 值 |
|---|---|
| id | `message_filter` |
| 版本 | 1.1.0 |
| 最低应用 | exteraGram `>=12.5.1` |
| 最低 SDK | `>=1.4.5.0` |
| 依赖 | 无（不用 `__requirements__`） |

## 它到底怎么工作的

不拦请求、不取消操作，只改 **TL 对象上的两个字段**：

| 字段 | 用途 |
|---|---|
| `TLRPC.Message.message` | 消息正文（媒体消息的**字幕**也存在这里） |
| `TLRPC.Message.entities` | 加粗 / 链接 / 代码块等格式实体 |

流程：

```
update / updates 容器            （新消息）
    ┐
    ├─ _iter_messages()  取出所有带正文的对象
    ├─ _process()        应用规则 → 决定最终文本与实体处置
    │     ├─ _entity_containers() 找到 entities 挂在哪
    │     ├─ remap_entities()     真删 + 重排 offset/length（失败回滚）
    │     └─ blank_deleted()      拿不到 entities 时等长隐身删除
    ├─ _write_field()    写回正文（属性访问优先，反射兜底）
    └─ sync_text_to_owner()  同步包装对象里的另一份副本
post_request_hook(response)      （打开会话 / 翻历史 / 搜索）
    └─ 同上，遍历 response.messages
on_send_message_hook(params)     （外发）
    └─ 改 params.message；外发没有现成 entities，宿主会重新解析
```

### v1.1.0 对齐真机实测的四处加固

宿主：exteraless 12.10.6 / SDK 1.4.5.7（与参考插件 tg_regex_filter v0.9.3 同环境）。
下面每条都是"本地测试全绿、真机上不工作"的典型坑，已逐条修掉：

| # | 症状 | 根因 | 修法 |
|---|---|---|---|
| 1 | **加了规则却什么都不删** | 菜单上下文给的 `dialog_id` 与从消息 `peer_id` 推出来的值可能分别是 `-100xxx` 和 `-xxx` 两种写法；`chatId`/`userId` 是正数却没还原符号 | 会话键改成**候选集合**，两种写法互通；`chatId` 取负、`userId` 取正 |
| 2 | 读不到正文 / 实体 | 真机上属性访问对这些 TL 对象不可靠（参考插件实测：必须走原始 Java 反射） | `_read_field` / `_write_field`：属性访问优先 + `java.lang.Class` 反射兜底，带缓存 |
| 3 | 历史消息不过滤 | 只挂了 update 钩子；打开会话时消息是从响应里回来的 | 补挂 `getHistory` / `getMessages` / `search` 等请求钩子 + `post_request_hook` |
| 4 | **删了字但链接串位** | 真机上这份 `TLRPC.Message` 的 `entities` 是空的，可跳转链接挂在宿主自己的 `MessageObject` 上，插件碰不到 | 拿不到 entities 时走**等长隐身删除**（见下） |

### 正文与消息发现

- 正文按 `message` → `text` → `messageText` → `caption` → `captionText` 依次尝试，
  并对非 `str` 的 Java String 做强制转换（只认 `isinstance(x, str)` 会整条漏掉）。
- 宿主给的**不一定是裸的 `TLRPC.Message`**：套了 `MessageObject` 时正文在
  `messageText`、实体在 `messageOwner.entities`。所以：
  - `_iter_messages` 认三种形态（裸消息 / update / 包装器），并递归进 `updates`、`update`；
  - `_entity_containers` 广度优先在 `messageOwner` / `owner` / … 里找实体列表；
  - `sync_text_to_owner` 把新正文同步回 owner 的那份副本，避免两份不一致。

### 三层架构

```
规则引擎   find_matches / filter_message / map_pos / shift_entities
           纯函数，零 SDK 依赖，可本地单测
会话键     dialog_candidates / peer_candidates / scope_allows
           纯函数，把 -100xxx / -xxx 两种写法展开成候选集合
Java 互操作 _read_field / _write_field / _iter_java_list / _to_python_str
           属性访问优先 + 原始反射兜底，全部 try/except 降级
适配层     _iter_messages / _process / _decide_output
UI 层      create_settings / _page_rule / _page_log
菜单层     _register_menu_items / _show_peer_dialog / _show_add_rule_dialog
           群组·频道·资料页右上角菜单入口，加出来的规则自动绑定当前会话
```

### 菜单入口的交互层级

```
右上角菜单「消息过滤规则」
  ├─ 一级 AlertDialogBuilder：本会话规则列表
  │    ├─ ＋ 添加规则（仅本会话） → 二级：EditText 输入 → 创建 scope=本会话 的规则
  │    └─ 点某条规则            → 二级：启用/禁用 · 删除
  └─ 拿不到 Activity 时降级为 Bulletin 提示，不弹窗
```

菜单 `context` 是 `java.util.HashMap`，**只能用 `get()`**；`dialog_id` 依次从
`dialog_id` / `chatId` / `userId` / `chat.id` / `user.id` 里取。

## 规则模型

| 字段 | 取值 | 说明 |
|---|---|---|
| `mode` | 0 词组 / 1 字符集合 / 2 正则 | 匹配方式 |
| `pattern` | str | 匹配内容 |
| `replacement` | str | 替换文本，留空 = 直接删掉 |
| `case_sensitive` | bool | 区分大小写 |
| `target` | 0 仅收 / 1 仅发 / 2 收发 | 作用方向 |
| `scope` | `""` 全局 / `"<dialog_id>"` 仅某会话 | 作用范围 |
| `enabled` | bool | 单条开关 |

### 作用范围：全局 vs 仅某个会话

需求是「在某个群/频道里加规则，**只在那里生效**」。两条路径：

| 从哪加 | scope | 效果 |
|---|---|---|
| 插件设置 → 添加规则 | `""` | 所有会话 |
| 群组/频道右上角菜单 → 消息过滤规则 → ＋ 添加规则 | 该会话的 `dialog_id` | 只在这个会话 |

几个设计决定：

- **不做"存下标"**：作用范围存的是 `dialog_id` 字符串，不是 `peer_index` 下标。
  同一批设置散在多处、各自过时是常见事故源；存下标在增删会话后必然错位。
- **会话键按候选集合比较**（v1.1.0）。同一个频道在不同层里的 id 写法不一样：
  菜单上下文可能是 `-1001612089540`，从消息 `peer_id` 推出来可能是 `-1612089540`。
  只认一种写法，就会"群里加的规则永不命中"。`dialog_candidates()` / `peer_candidates()`
  把等价写法全部展开，`scope_allows()` 命中任意一个即生效。
- **`chatId` / `userId` 的符号必须还原**：它们都是**正数**，聊天要取负、用户保持正数。
  旧版直接返回正数，是"会话规则不生效"的另一个来源。
- **全局规则排在会话规则之前**。`_create_rule()` 会把新的全局规则插到
  第一条会话规则之前，保证"先跑通用清理，再跑专属规则"。
- **拿不到会话就不生效**。`scope_allows()` 对空 `peer_key` 只放行全局规则——
  宁可漏过滤，也不要把某个群的专用规则误伤到别的聊天。
- **外发消息**：`on_send_message_hook` 从 `params.dialog_id` 取会话；
  宿主没带这个字段时只应用全局规则（不是猜一个会话出来）。

- **词组**：整段子串匹配（`str.find` 循环），不支持通配符
- **字符集合**：把 `pattern` 当字符集，**逐字符**删除/替换其中出现过的每一个
- **正则**：Python `re` 语法；`case_sensitive=False` 时加 `re.IGNORECASE`

非法正则不会让插件崩：`validate_pattern()` 先校验，不合法的规则**直接跳过**，
并在设置页该规则的副标题上显示错误原因。

### 优先级语义

列表顺序即优先级，**越靠前越先执行**。

关键设计：所有规则的匹配都在**原文坐标**里算，后面的规则会**跳过已被前面的规则
删掉的区间**。这样有两个好处：

1. `removals` 始终处于同一坐标系，实体偏移才能正确换算（否则多规则串联后
   坐标会错位）
2. 不会出现"两条规则抢同一段文字"的重复替换

副作用：后面规则**不会**匹配到前面规则替换出来的新文本。这是个取舍，
替换文本一般很短，实际影响极小。

## 实体偏移换算与链接安全

文本变短后，`entities` 里的 `offset/length` 会失效。宿主渲染时可能越界，
所以改写文本后必须同步修正——`map_pos()` 做坐标映射：

| 点的位置 | 映射结果 |
|---|---|
| 在被删区间之前 | 不动 |
| 在被删区间**内部** | 塌缩到该区间替换文本的末尾 |
| 在被删区间之后 | 按前面所有区间的长度变化平移 |

`shift_entities()` 再加两条规则：

- 实体被完全删掉 → 丢弃
- 实体部分重叠 → 缩短
- 加了前缀标记 → 所有实体整体右移 `len(marker)`

回写时构造一个新的 `java.util.ArrayList`，只保留存活的实体。
**任何一步失败都降级为"不动实体"，绝不抛出去。**

### 两条策略：能摸到 entities 就重排，摸不到就等长隐身

真机实测（参考插件 v0.9.1 的诊断日志）：

```
msg类=TL_message 正文取自=message
TL_message: entities=0 caption_entities=None
```

也就是**插件能改的这份 `TLRPC.Message` 上 `entities` 是空的**，
用户看到的可跳转链接挂在宿主自己的 `MessageObject` 上，插件碰不到。
于是 v1.0.0 的重排引擎一次都没跑起来 —— 文字照删、offset 原地不动 →
**链接串位**（"第一行的链接跑到第二行"）。

v1.1.0 的两条策略：

| 情况 | 做法 | 效果 |
|---|---|---|
| 找得到非空 entities | 真删 + 重排 offset/length，失败整体回滚 | 文本真的变短，格式跟着走 |
| 找不到 entities，且开着「链接安全」 | **等长隐身删除** | 被删字符原地换成等宽零宽空格，总长度一字不差 ⇒ offset 全部有效 |

等长隐身的关键细节：**emoji（非 BMP）占 2 个 UTF-16 单元**，
只补 1 个零宽字符会让总长度变短，offset 照样错 —— 必须按宽度补。
落地前还会硬校验 `_u16_len(结果) == _u16_len(原文)`，不等就退回真删。

副作用：等长隐身下正文长度不变，所以**标记只能加在末尾**（加开头会整体平移 offset）。
设置页可关掉「链接安全（等长隐身删除）」，关掉就回到"真删文字"。

## 设置键

全局：

| 键 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `enabled` | bool | `True` | 插件总开关 |
| `rule_index` | JSON 字符串数组 | `[]` | 规则 id 的有序列表（= 优先级） |
| `rule_seq` | int | `0` | id 自增计数 |
| `peer_index` | JSON 字符串数组 | `[]` | 出现过会话规则的会话 id（用于显示名字） |
| `peer_title_<dialog_id>` | str | — | 会话显示名（菜单点击时记下来） |
| `new_rule_pattern` / `new_rule_mode` | str / int | `""` / `0` | 添加规则的输入框 |
| `marker_enabled` | bool | `True` | 是否加标记 |
| `marker_text` | str | `🚫` | 标记内容 |
| `marker_position` | int | `0` | 0 开头 / 1 末尾 |
| `on_empty` | int | `1` | 0 留空 / 1 占位文本 / 2 放弃修改 |
| `empty_placeholder` | str | `（已过滤）` | 占位文本 |
| `fix_entities` | bool | `True` | 同步修正实体偏移 |
| `blank_fallback` | bool | `True` | 链接安全：拿不到 entities 时等长隐身删除 |
| `capture_mode` | bool | `False` | 只观察不改（样本捕获，排查用） |
| `log_filtered` | bool | `False` | 记录过滤记录 |
| `_filtered_log` | list | `[]` | 最近记录（内部） |
| `_self_check` | str | — | 上次自检报告（内部，避免写文件要 `files` 权限） |

每条规则一组 `rule_<id>_*`：`enabled` / `mode` / `pattern` /
`replacement` / `case_sensitive` / `target` / `scope`。

> 规则索引存的是 **id 字符串**，不是下标 —— 增删规则不会让其它规则错位，
> 不需要迁移逻辑。删除规则后 `rule_<id>_*` 会残留，不影响使用。

## 兼容性设计（第 6 条需求）

| 措施 | 说明 |
|---|---|
| 只碰 2 个字段 | 不改 message id / date / from_id / media / 请求流程 |
| 从不 `CANCEL` | 只在真的改了文本时才返回 `MODIFY`，否则返回空 `HookResult` |
| 写回失败即放弃 | `_write_field` 失败 → 保留原文 |
| 实体修正失败即回滚 | offset/length 与列表全部恢复原样，最坏情况是"这次不删"，不会串位 |
| 钩子里全部 `except Exception` | 未捕获异常会被宿主静默吞掉，排查时无从下手 |
| 模块级 import 全部降级 | `MenuItemData` / `ui.settings` / `ui.alert` / `ui.bulletin` / `client_utils` 缺失也不影响加载 |
| 钩子逐个注册并回报 | `已注册 N/M 个钩子`，一次就能看出哪个名字没挂上 |
| TTL 缓存配置 | 收消息是热路径，3 秒 TTL，避免每条消息全量读设置 |
| 记录写入有封顶 | `LOG_WRITE_LIMIT = 60` 次/会话，`CAPTURE_LIMIT = 30` 条样本 |
| 不写文件 | 自检报告存进设置键，绕开 `files` 权限（真机上写文件会报 permission 错误） |

## 已知限制

1. **"颜色"标记没实现**。需求里的"图标或颜色"目前只做了**文本/emoji 标记**。
   染色需要 hook 消息渲染层（`ChatMessageCell` 之类），风险高、且类名随版本变，
   没有真机验证前不写。
2. **「替换为」是纯文本**：不支持 `\1` 反向引用，也插不进换行
   （该输入框是单行）。"保留一个字符删掉其余"这类需求做不到，
   只能整段删或整体换成一个固定字符串。SKILL.md 里已把这条列为硬规矩。
3. **修改 update 里的 TL 对象能不能反映到界面**，取决于宿主是否在插件钩子之后
   才把 update 交给 `MessagesController`。参考插件（同宿主）已实测成立：
   它用同一套"改对象 + 返回 MODIFY"的做法能正常过滤，所以本插件沿用。
   真机上若仍不动，用「只观察不改」+「最近处理」两步定位（见 README）。
4. **已读消息的界面不会回溯刷新**。过滤发生在消息到达那一刻，已经显示在
   屏幕上的气泡不会因为改设置而重算。
5. **媒体消息的字幕**也是 `message` 字段，所以同样会被过滤；文件名不受影响。
6. 后面规则不匹配前面规则替换出来的文本（见「优先级语义」）。
7. **会话规则对"发出的消息"是否生效取决于宿主**：`on_send_message_hook` 的
   `params` 里有没有 `dialog_id`。没有就只应用全局规则，不会猜一个会话出来。
8. **菜单里的输入框**用原生 `android.widget.EditText` + `AlertDialogBuilder.set_view`
   搭的；拿不到 Activity 时会降级成 Bulletin 提示，让用户去插件设置里加。
9. **等长隐身删除会留下零宽字符**（U+200B）。肉眼不可见、复制时可能带上，
   这是"保链接"与"文本干净"之间的取舍；设置页可以关掉。
   整条被删空时不做隐身替换（没内容就没有 offset 要保），走「过滤后为空」的处置。

## 配套技能

`skills/message-filter-rules/SKILL.md` 是给 AI 助手用的**规则编写技能**：
用户说一句"我想过滤掉 XXX"，助手直接产出可填进设置页的字段。

它的内容受 `tests/test_rule_recipes.py` 约束——那张现成规则表里的每条正则
都必须能编译，写错就红。

## 本地测试

```bash
python tests/test_filter_engine.py    # 纯函数：83 项
python tests/test_plugin_adapter.py   # 适配层：140 项
python tests/test_rule_recipes.py     # SKILL.md 规则验签：64 项
```

三套都用桩模块替换 SDK 后 **exec 插件源码本身**，所以测的是真代码，
不是副本。适配层那套还会把源码注册成 `message_filter` 模块，因此
`on_plugin_load` 里的 `import message_filter` 也能跑通。

| 文件 | 覆盖 |
|---|---|
| `test_filter_engine.py` | 索引解析、规则校验、三种匹配模式、多规则优先级、重叠区间、标记、清空处置、坐标换算、实体换算、作用方向与作用范围、元数据与结构约束 |
| `test_plugin_adapter.py` | 钩子注册（update / 容器 / 请求）、菜单注册与整条弹窗交互链、按会话加规则与作用域隔离、**会话键 -100xxx/裸 id 互通**、**chatId/userId 符号**、规则增删改与优先级、TL 对象识别、**反射兜底**、**包装对象（messageText/messageOwner）**、**等长隐身删除与 emoji 宽度**、**post_request_hook**、**样本捕获**、实体重建与"净位置不变则不重建"、三个钩子、总开关、设置页构建与 key 拼写、配置缓存失效 |
| `test_rule_recipes.py` | 把 `skills/message-filter-rules/SKILL.md` 里那张现成规则表**抽出来**逐条编译，并对 8 条验证实际效果；**「整合版奖牌推广行」单独一节（9 正例 + 8 反例）、「奖牌不在行首」两条备用规则、「搜索 bot 结果清理」用真实样本验证（含"整合规则会误删含『包养』的结果行"这条已知取舍）、「删整行不留空行（`\n?`）」验证真删与等长隐身两条路径都不留空行且长度守恒**；同时把文档声称"做不到"的 4 件事（反向引用、插入换行、字符集合不认 `\d`、词组不认 `.*`）逐条验成事实 |

值得单独说的三条：

- 适配层测试把设置页里出现的所有 `key` 收集起来，断言要么在已知集合里、
  要么以 `rule_` 开头；规则子页的 key 还必须带自己的 rule id —— 专防
  "改了设置没反应"这类难查的 bug。
- **假对象故意做成"字段读不到"**（`ReflectedMessage`）：属性访问抛异常、
  只有 `getClass().getDeclaredField()` 能读 —— 对应真机上"必须走反射"的现实，
  防止再退回只靠 `getattr` 的写法。
- 规则验签测试让**文档和实现绑在一起**：SKILL.md 里写出一条跑不通的正则，
  这套测试会直接红。

## 提交前检查

```
[ ] ruff check message_filter.plugin
[ ] python tests/test_filter_engine.py
[ ] python tests/test_plugin_adapter.py
[ ] python tests/test_rule_recipes.py     （改了 SKILL.md 的现成规则表时必须跑）
[ ] docs.md 更新（改了规则模型 / 设置键 / 架构时）
[ ] README.md 更新（改了用法时）
```
